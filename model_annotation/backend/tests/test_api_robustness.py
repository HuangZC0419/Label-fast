import asyncio
import json
import os
import sys
import threading
import time

import pytest
from fastapi.responses import Response, StreamingResponse
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dataset_store
import main

client = TestClient(main.app)


def _upload(content: bytes, name: str = "inline.jsonl"):
    return client.post(
        "/datasets/upload",
        files={"file": (name, content, "application/x-ndjson")},
    )


# ── 导出接口 ──────────────────────────────────────────────

def test_export_rejects_non_list_rules():
    for payload in ({"rules": 5}, {"rules": None}, {"rules": "standards"}):
        response = client.post(
            "/result/any-task/export-annotations", json=payload
        )
        assert response.status_code == 400, payload
        assert "rules" in response.json()["message"]


def test_export_rejects_invalid_model_id():
    response = client.post(
        "/result/any-task/export-annotations",
        json={"rules": [], "model_id": "../../x"},
    )
    assert response.status_code == 400
    assert response.json()["message"] == "model_id 格式错误"


def test_export_valid_rules_returns_ndjson(monkeypatch):
    monkeypatch.setattr(
        main, "load_task_markdown", lambda task_id: "依据 GB/T3191-2019 执行。"
    )
    response = client.post(
        "/result/task-x/export-annotations",
        json={"rules": ["standards"]},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")

    rows = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert rows
    assert rows[0]["spans"][0]["text"] == "GB/T3191-2019"


# ── 数据集上传 ────────────────────────────────────────────

def test_upload_dataset_counts_annotation_only_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset_store, "DATASET_BASE", str(tmp_path))
    content = (
        '{"text":"依据 GB/T3191-2019 执行",'
        '"spans":[{"start":3,"end":16,"label":"标准条文"}],'
        '"annotations":[{"label":"标准条文"},{"label":"判定结论"}]}'
    ).encode("utf-8")

    response = _upload(content)
    assert response.status_code == 200
    data = response.json()
    assert data["sample_count"] == 1
    assert data["entity_count"] == 1
    assert data["label_counts"] == {"判定结论": 1, "标准条文": 1}
    assert data["label_count"] == 2


def test_upload_accepts_utf8_bom(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset_store, "DATASET_BASE", str(tmp_path))
    content = (
        chr(0xFEFF)
        + '{"text":"abc","spans":[{"start":0,"end":1,"label":"L"}]}'
    ).encode("utf-8")

    response = _upload(content)
    assert response.status_code == 200
    assert response.json()["entity_count"] == 1


def test_upload_skips_span_without_label(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset_store, "DATASET_BASE", str(tmp_path))
    content = (
        b'{"text":"abcdef","spans":['
        b'{"start":0,"end":2},'
        b'{"start":1,"end":3,"label":"L"}]}'
    )

    response = _upload(content)
    assert response.status_code == 200
    assert response.json()["entity_count"] == 1


def test_upload_rejects_oversized_file(monkeypatch):
    monkeypatch.setattr(main, "DATASET_MAX_UPLOAD_BYTES", 8)

    response = _upload(b"x" * 9)
    assert response.status_code == 413
    assert "文件过大" in response.json()["message"]


def test_upload_invalid_content_returns_400(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset_store, "DATASET_BASE", str(tmp_path))

    response = _upload(b"not json")
    assert response.status_code == 400


def test_upload_offloads_save_dataset(monkeypatch):
    seen = {}

    def fake_save(content, file_name, name):
        return {"ok": True}

    async def fake_threadpool(func, *args, **kwargs):
        seen["func"] = func
        return func(*args, **kwargs)

    monkeypatch.setattr(main, "save_dataset", fake_save)
    monkeypatch.setattr(main, "run_in_threadpool", fake_threadpool)

    response = _upload(b'{"text":"abc"}')
    assert response.status_code == 200
    assert seen["func"] is fake_save


# ── 按数据集训练 ──────────────────────────────────────────

def test_train_from_dataset_offloads_loading(monkeypatch):
    seen = {}

    def fake_load(dataset_ids):
        return [{"text": "abc", "entities": []}]

    async def fake_threadpool(func, *args, **kwargs):
        seen["func"] = func
        return func(*args, **kwargs)

    monkeypatch.setattr(main, "load_dataset_examples", fake_load)
    monkeypatch.setattr(main, "run_in_threadpool", fake_threadpool)
    monkeypatch.setattr(main, "create_training_stream", lambda run: Response("ok"))

    response = client.post(
        "/model/train-from-dataset", json={"dataset_ids": ["a" * 12]}
    )
    assert response.status_code == 200
    assert seen["func"] is fake_load


# ── 训练并发锁 ────────────────────────────────────────────

def test_training_lock_conflict_returns_409():
    assert main.TRAINING_LOCK.acquire(blocking=False)
    try:
        response = client.post(
            "/model/train",
            json={"examples": [{"text": "abc", "entities": []}]},
        )
    finally:
        main.TRAINING_LOCK.release()

    assert response.status_code == 409
    assert response.json() == {"message": "已有训练任务正在进行，请稍后再试"}


def test_create_training_stream_starts_worker_before_return():
    started = threading.Event()

    def fake_train(callback):
        started.set()
        return {"ok": True}

    async def build():
        return main.create_training_stream(fake_train)

    response = asyncio.run(build())
    try:
        assert isinstance(response, StreamingResponse)
        # 线程必须在 create_training_stream 返回前启动。
        assert started.wait(2.0)

        deadline = time.time() + 2.0
        while time.time() < deadline:
            if main.TRAINING_LOCK.acquire(blocking=False):
                main.TRAINING_LOCK.release()
                return
            time.sleep(0.01)
        pytest.fail("训练结束后应释放全局训练锁")
    finally:
        # 兜底：等待训练线程释放锁，避免污染后续测试。
        deadline = time.time() + 2.0
        while main.TRAINING_LOCK.locked() and time.time() < deadline:
            time.sleep(0.01)


# ── 数据集列表/详情健壮性 ────────────────────────────────

def test_list_datasets_endpoint_ignores_bad_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset_store, "DATASET_BASE", str(tmp_path))
    (tmp_path / "aaaaaaaaaaaa.meta.json").write_text("[]", encoding="utf-8")
    (tmp_path / "bbbbbbbbbbbb.meta.json").write_text("{bad", encoding="utf-8")

    response = client.get("/datasets")
    assert response.status_code == 200
    assert response.json() == []


def test_get_dataset_endpoint_corrupt_meta_404(tmp_path, monkeypatch):
    monkeypatch.setattr(dataset_store, "DATASET_BASE", str(tmp_path))
    dataset_id = "b" * 12
    (tmp_path / f"{dataset_id}.meta.json").write_text("{bad", encoding="utf-8")

    response = client.get(f"/datasets/{dataset_id}")
    assert response.status_code == 404

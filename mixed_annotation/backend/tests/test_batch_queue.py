"""整文件夹批量导入与夜间串行队列测试。

覆盖：
- 服务重启时 converting 文件退回 uploaded 并保留 queue_seq；
- 队列按 queue_seq 全局串行处理，同一时刻最多 1 个转换；
- uploading 状态不会被队列选中；
- 上传接口 defer_conversion=True 只入库、不触发转换；
- OCR 服务不可用时暂停队列，恢复后继续；
- Worker 连接类失败退回 uploaded，不烧掉整批文件；
- 取消时 converting 文件退回 uploaded。

所有测试都不真正调用 OCR Worker。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import httpx

import _env  # noqa: F401  # 必须在 config/storage 之前导入

import storage
from errors import NotFoundError
from routes import files as files_routes
from services import conversion_service, ocr_client, queue_service


def _new_file(project_id: str, name: str, seq: int | None = None) -> dict:
    """创建测试文件元数据；可按需求覆盖 queue_seq。"""

    meta, _ = storage.create_file(
        project_id,
        name,
        ".pdf",
        source_type="pdf",
        enable_table=True,
        enable_formula=False,
        dpi=200,
    )
    if seq is not None:
        meta = storage.update_file(meta["id"], {"queue_seq": seq})
    return meta


async def _worker_ready() -> bool:
    """测试默认认为 OCR Worker 可用。"""

    return True


async def _finish_quickly(file_id: str) -> bool:
    """模拟一次立即完成的转换；必须让出事件循环，避免忙轮询卡死。"""

    await asyncio.sleep(0)
    storage.update_file(file_id, {"status": "completed"})
    return True


class QueueRequeueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = storage.create_project("队列恢复测试", [], [])

    def tearDown(self) -> None:
        storage.delete_project(self.project["id"])

    def test_create_file_assigns_increasing_queue_seq(self) -> None:
        first = _new_file(self.project["id"], "a.pdf")
        second = _new_file(self.project["id"], "b.pdf")
        self.assertIsInstance(first["queue_seq"], int)
        self.assertIsInstance(second["queue_seq"], int)
        self.assertGreater(second["queue_seq"], first["queue_seq"])

    def test_requeue_interrupted_conversions_keeps_queue_seq(self) -> None:
        meta = _new_file(self.project["id"], "interrupted.pdf", seq=123456)
        storage.update_file(
            meta["id"],
            {
                "status": "converting",
                "progress": 42,
                "stage": "转换中",
                "task_id": "worker-task",
                "conversion_token": "token-1",
                "page_count": 9,
            },
        )

        changed = storage.requeue_interrupted_conversions()

        self.assertGreaterEqual(changed, 1)
        restored = storage.get_file(meta["id"])
        self.assertEqual(restored["status"], "uploaded")
        self.assertEqual(restored["progress"], 0)
        self.assertEqual(restored["stage"], "服务重启，重新排队")
        self.assertEqual(restored["message"], "")
        self.assertEqual(restored["error"], "")
        self.assertEqual(restored["task_id"], "")
        self.assertEqual(restored["conversion_token"], "")
        self.assertEqual(restored["page_count"], 0)
        # 重新排队不得打乱导入顺序。
        self.assertEqual(restored["queue_seq"], 123456)


class QueueSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = storage.create_project("队列筛选测试", [], [])

    def tearDown(self) -> None:
        storage.delete_project(self.project["id"])

    def test_non_uploaded_status_is_never_selected(self) -> None:
        statuses = ["converting", "failed", "completed", "uploaded"]
        ids: dict[str, str] = {}
        for index, status in enumerate(statuses):
            meta = _new_file(self.project["id"], f"{status}.pdf", seq=100 + index)
            storage.update_file(meta["id"], {"status": status})
            ids[status] = meta["id"]

        queued_ids = {item["id"] for item in storage.list_queued_files()}
        self.assertIn(ids["uploaded"], queued_ids)
        self.assertNotIn(ids["converting"], queued_ids)
        self.assertNotIn(ids["failed"], queued_ids)
        self.assertNotIn(ids["completed"], queued_ids)

    def test_uploading_file_is_not_queued_until_completed(self) -> None:
        meta, _ = storage.create_file(
            self.project["id"],
            "uploading.pdf",
            ".pdf",
            source_type="pdf",
            enable_table=True,
            enable_formula=False,
            dpi=200,
            initial_status="uploading",
        )
        self.assertEqual(meta["status"], "uploading")
        self.assertEqual(meta["stage"], "正在上传")

        queued_ids = {item["id"] for item in storage.list_queued_files()}
        self.assertNotIn(meta["id"], queued_ids)

        storage.update_file(meta["id"], {"status": "uploaded", "stage": "排队中"})
        queued_ids = {item["id"] for item in storage.list_queued_files()}
        self.assertIn(meta["id"], queued_ids)


class QueueOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = storage.create_project("队列顺序测试", [], [])

    def tearDown(self) -> None:
        storage.delete_project(self.project["id"])

    def test_processes_in_queue_seq_order_and_serially(self) -> None:
        # 显式指定 queue_seq，验证排序不依赖 created_at（秒级精度可能相同）。
        ordered_ids = [
            _new_file(self.project["id"], "second.pdf", seq=200)["id"],
            _new_file(self.project["id"], "first.pdf", seq=100)["id"],
            _new_file(self.project["id"], "third.pdf", seq=300)["id"],
        ]
        expected = [ordered_ids[1], ordered_ids[0], ordered_ids[2]]
        our_ids = set(ordered_ids)

        # 先验证存储层排序，不受其他测试残留文件影响。
        queued = storage.list_queued_files()
        our_queued = [item["id"] for item in queued if item["id"] in our_ids]
        self.assertEqual(our_queued, expected)

        calls: list[str] = []
        active = 0
        max_active = 0

        async def fake_run(file_id: str) -> bool:
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            calls.append(file_id)
            # 留出并发窗口，若队列不串行会观察到 max_active > 1。
            await asyncio.sleep(0.02)
            storage.update_file(
                file_id,
                {"status": "completed", "progress": 100, "stage": "转换完成"},
            )
            active -= 1
            return True

        async def scenario() -> None:
            with mock.patch.dict(
                os.environ,
                {
                    "MIX_CONVERSION_CONCURRENCY": "1",
                    "MIX_QUEUE_WORKER_RETRY_SECONDS": "0.05",
                },
            ), mock.patch.object(
                ocr_client, "worker_available", new=_worker_ready
            ), mock.patch.object(
                conversion_service, "run_queued_conversion", new=fake_run
            ):
                await queue_service.start()
                try:
                    deadline = time.monotonic() + 10
                    while not our_ids.issubset(set(calls)):
                        if time.monotonic() > deadline:
                            break
                        await asyncio.sleep(0.02)
                finally:
                    await queue_service.stop()

        asyncio.run(scenario())

        # 只比较本项目文件的相对顺序，避免受其他测试残留 uploaded 文件干扰。
        ours_in_call_order = [file_id for file_id in calls if file_id in our_ids]
        self.assertEqual(ours_in_call_order, expected)
        self.assertEqual(max_active, 1)

    def test_start_is_idempotent(self) -> None:
        async def scenario() -> int:
            with mock.patch.dict(
                os.environ, {"MIX_CONVERSION_CONCURRENCY": "1"}
            ), mock.patch.object(
                ocr_client, "worker_available", new=_worker_ready
            ), mock.patch.object(
                conversion_service, "run_queued_conversion", new=_finish_quickly
            ):
                await queue_service.start()
                first_state = queue_service._state
                await queue_service.start()
                same_state = queue_service._state
                worker_count = len(first_state.workers) if first_state else 0
                try:
                    self.assertIs(first_state, same_state)
                finally:
                    await queue_service.stop()
            return worker_count

        self.assertEqual(asyncio.run(scenario()), 1)


class QueuedConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = storage.create_project("排队转换入口测试", [], [])

    def tearDown(self) -> None:
        storage.delete_project(self.project["id"])

    def test_lock_is_released_before_conversion(self) -> None:
        meta = _new_file(self.project["id"], "queued.pdf")
        # 模拟上次中断留下的页码，重新排队时必须清零。
        storage.update_file(meta["id"], {"page_count": 7})
        observed: dict = {}

        async def fake_run(
            file_id: str,
            token: str,
            worker_options: dict,
            worker_filename: str,
            worker_content_type: str,
            *,
            requeue_on_cancel: bool = False,
            timeout_seconds: float | None = None,
        ) -> None:
            # 若外层仍持有 _lock_for(file_id)，这里会超时（死锁）。
            lock = conversion_service._lock_for(file_id)
            acquired = await asyncio.wait_for(lock.acquire(), timeout=0.5)
            if acquired:
                lock.release()
            current = storage.get_file(file_id)
            observed["acquired"] = acquired
            observed["status"] = current["status"]
            observed["page_count"] = current["page_count"]
            observed["requeue_on_cancel"] = requeue_on_cancel
            observed["timeout_seconds"] = timeout_seconds
            storage.update_file(file_id, {"status": "completed"})

        async def scenario() -> bool:
            with mock.patch.object(
                conversion_service, "_run_conversion", new=fake_run
            ):
                return await conversion_service.run_queued_conversion(meta["id"])

        started = asyncio.run(scenario())

        self.assertTrue(started)
        self.assertTrue(observed.get("acquired"))
        # 进入 _run_conversion 时已持久化为 converting。
        self.assertEqual(observed.get("status"), "converting")
        self.assertEqual(observed.get("page_count"), 0)
        self.assertTrue(observed.get("requeue_on_cancel"))
        self.assertEqual(storage.get_file(meta["id"])["status"], "completed")

    def test_non_uploaded_file_is_skipped(self) -> None:
        meta = _new_file(self.project["id"], "done.pdf")
        storage.update_file(meta["id"], {"status": "completed"})

        async def scenario() -> bool:
            with mock.patch.object(
                conversion_service, "_run_conversion", new=mock.AsyncMock()
            ) as run_mock:
                started = await conversion_service.run_queued_conversion(
                    meta["id"]
                )
            run_mock.assert_not_called()
            return started

        self.assertFalse(asyncio.run(scenario()))


class QueueErrorIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = storage.create_project("队列异常隔离测试", [], [])

    def tearDown(self) -> None:
        storage.delete_project(self.project["id"])

    def test_exception_in_one_file_continues_to_next(self) -> None:
        first = _new_file(self.project["id"], "first.pdf", seq=100)
        second = _new_file(self.project["id"], "second.pdf", seq=200)
        calls: list[str] = []

        async def fake_run(file_id: str) -> bool:
            calls.append(file_id)
            if file_id == first["id"]:
                raise RuntimeError("模拟转换协程异常")
            storage.update_file(file_id, {"status": "completed"})
            return True

        async def scenario() -> None:
            with mock.patch.dict(
                os.environ, {"MIX_QUEUE_WORKER_RETRY_SECONDS": "0.05"}
            ), mock.patch.object(
                ocr_client, "worker_available", new=_worker_ready
            ), mock.patch.object(
                conversion_service, "run_queued_conversion", new=fake_run
            ):
                await queue_service.start()
                try:
                    deadline = time.monotonic() + 10
                    while second["id"] not in calls:
                        if time.monotonic() > deadline:
                            break
                        await asyncio.sleep(0.02)
                finally:
                    await queue_service.stop()

        asyncio.run(scenario())

        our_order = [
            file_id
            for file_id in calls
            if file_id in {first["id"], second["id"]}
        ]
        self.assertEqual(our_order, [first["id"], second["id"]])
        self.assertEqual(storage.get_file(second["id"])["status"], "completed")
        # 抛异常的文件保持上传态，但本次启动不再重复认领。
        self.assertEqual(storage.get_file(first["id"])["status"], "uploaded")


class QueueCancelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = storage.create_project("队列取消测试", [], [])

    def tearDown(self) -> None:
        storage.delete_project(self.project["id"])

    def test_cancel_requeues_converting_file(self) -> None:
        meta = _new_file(self.project["id"], "cancel.pdf")

        async def slow_run(*args, **kwargs) -> None:
            await asyncio.sleep(10)

        async def scenario() -> None:
            with mock.patch.object(
                conversion_service, "_run_conversion", new=slow_run
            ):
                task = asyncio.create_task(
                    conversion_service.run_queued_conversion(meta["id"])
                )
                try:
                    deadline = time.monotonic() + 5
                    while storage.get_file(meta["id"])["status"] != "converting":
                        if time.monotonic() > deadline:
                            break
                        await asyncio.sleep(0.01)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                finally:
                    if not task.done():  # pragma: no cover - 防御性清理
                        task.cancel()

        asyncio.run(scenario())

        restored = storage.get_file(meta["id"])
        self.assertEqual(restored["status"], "uploaded")
        self.assertEqual(restored["progress"], 0)
        self.assertEqual(restored["stage"], "转换已暂停，等待重新排队")
        self.assertEqual(restored["message"], "")
        self.assertEqual(restored["error"], "")
        self.assertEqual(restored["task_id"], "")
        self.assertEqual(restored["conversion_token"], "")


class WorkerPauseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = storage.create_project("Worker 暂停测试", [], [])

    def tearDown(self) -> None:
        storage.delete_project(self.project["id"])

    def test_pauses_while_unavailable_then_recovers(self) -> None:
        meta = _new_file(self.project["id"], "paused.pdf")
        calls: list[str] = []
        availability = {"ready": False}

        async def fake_available() -> bool:
            return availability["ready"]

        async def fake_run(file_id: str) -> bool:
            calls.append(file_id)
            storage.update_file(file_id, {"status": "completed"})
            return True

        async def scenario() -> None:
            with mock.patch.dict(
                os.environ, {"MIX_QUEUE_WORKER_RETRY_SECONDS": "0.05"}
            ), mock.patch.object(
                ocr_client, "worker_available", new=fake_available
            ), mock.patch.object(
                conversion_service, "run_queued_conversion", new=fake_run
            ):
                await queue_service.start()
                try:
                    # 留出若干轮退避：不可用期间不得认领或改变文件状态。
                    await asyncio.sleep(0.25)
                    self.assertEqual(calls, [])
                    self.assertEqual(
                        storage.get_file(meta["id"])["status"], "uploaded"
                    )

                    availability["ready"] = True
                    deadline = time.monotonic() + 10
                    while meta["id"] not in calls:
                        if time.monotonic() > deadline:
                            break
                        await asyncio.sleep(0.02)
                finally:
                    await queue_service.stop()

        asyncio.run(scenario())

        self.assertIn(meta["id"], calls)
        self.assertEqual(storage.get_file(meta["id"])["status"], "completed")


class WorkerFailureRequeueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = storage.create_project("Worker 失败退回测试", [], [])

    def tearDown(self) -> None:
        storage.delete_project(self.project["id"])

    def test_connection_failure_is_requeued_and_retried(self) -> None:
        meta = _new_file(self.project["id"], "connection.pdf")
        attempts = {"count": 0}

        async def fake_run(file_id: str) -> bool:
            if file_id != meta["id"]:
                storage.update_file(file_id, {"status": "completed"})
                return True
            attempts["count"] += 1
            if attempts["count"] == 1:
                storage.update_file(
                    file_id,
                    {
                        "status": "failed",
                        "stage": "转换失败",
                        "message": "转换失败",
                        "error": "无法连接 OCR Worker：connection refused",
                        "conversion_token": "token-connection",
                    },
                )
            else:
                storage.update_file(
                    file_id,
                    {"status": "completed", "conversion_token": ""},
                )
            return True

        async def scenario() -> None:
            with mock.patch.dict(
                os.environ, {"MIX_QUEUE_WORKER_RETRY_SECONDS": "0.05"}
            ), mock.patch.object(
                ocr_client, "worker_available", new=_worker_ready
            ), mock.patch.object(
                conversion_service, "run_queued_conversion", new=fake_run
            ):
                await queue_service.start()
                try:
                    deadline = time.monotonic() + 10
                    while attempts["count"] < 2:
                        if time.monotonic() > deadline:
                            break
                        await asyncio.sleep(0.02)
                finally:
                    await queue_service.stop()

        asyncio.run(scenario())

        self.assertGreaterEqual(attempts["count"], 2)
        self.assertEqual(storage.get_file(meta["id"])["status"], "completed")

    def test_requeue_uses_conversion_token_and_worker_marker(self) -> None:
        meta = _new_file(self.project["id"], "failed.pdf")
        storage.update_file(
            meta["id"],
            {
                "status": "failed",
                "stage": "转换失败",
                "error": "无法连接 OCR Worker：connection refused",
                "conversion_token": "token-x",
            },
        )

        # 令牌被并发更新时，退回操作应放回 None 且不覆盖状态。
        with mock.patch.object(
            storage, "update_file_if_token", return_value=None
        ) as update_mock:
            self.assertFalse(queue_service._requeue_worker_failure(meta["id"]))
        self.assertEqual(update_mock.call_args.args[1], "token-x")

        # 正常路径：命中 Worker 连接错误标记后退回 uploaded，并累计重试次数。
        self.assertTrue(queue_service._requeue_worker_failure(meta["id"]))
        restored = storage.get_file(meta["id"])
        self.assertEqual(restored["status"], "uploaded")
        self.assertEqual(restored["stage"], "OCR 服务不可用，稍后重试")
        self.assertEqual(restored["conversion_token"], "")
        self.assertEqual(restored["queue_retry_count"], 1)

    def test_non_worker_failure_is_not_requeued(self) -> None:
        meta = _new_file(self.project["id"], "bad-file.pdf")
        storage.update_file(
            meta["id"],
            {
                "status": "failed",
                "stage": "转换失败",
                "error": "源文件不存在，请重新上传",
                "conversion_token": "token-y",
            },
        )
        self.assertFalse(queue_service._requeue_worker_failure(meta["id"]))
        self.assertEqual(storage.get_file(meta["id"])["status"], "failed")

    def test_http_400_failure_is_not_requeued_and_queue_continues(self) -> None:
        first = _new_file(self.project["id"], "bad.pdf", seq=100)
        second = _new_file(self.project["id"], "good.pdf", seq=200)
        calls: list[str] = []

        async def fake_run(file_id: str) -> bool:
            calls.append(file_id)
            if file_id == first["id"]:
                storage.update_file(
                    file_id,
                    {
                        "status": "failed",
                        "stage": "转换失败",
                        "message": "转换失败",
                        "error": "OCR Worker 拒绝任务（HTTP 400）：坏文件",
                        "conversion_token": "token-400",
                    },
                )
            else:
                storage.update_file(file_id, {"status": "completed"})
            return True

        async def scenario() -> None:
            with mock.patch.dict(
                os.environ,
                {
                    "MIX_QUEUE_WORKER_RETRY_SECONDS": "0.05",
                    "MIX_QUEUE_MAX_RETRIES": "3",
                },
            ), mock.patch.object(
                ocr_client, "worker_available", new=_worker_ready
            ), mock.patch.object(
                conversion_service, "run_queued_conversion", new=fake_run
            ):
                await queue_service.start()
                try:
                    deadline = time.monotonic() + 10
                    while second["id"] not in calls:
                        if time.monotonic() > deadline:
                            break
                        await asyncio.sleep(0.02)
                finally:
                    await queue_service.stop()

        asyncio.run(scenario())

        # 4xx 属于文件本身问题：保持 failed，不重试、不阻塞后续文件。
        failed = storage.get_file(first["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["stage"], "转换失败")
        self.assertEqual(failed["queue_retry_count"], 0)
        self.assertEqual(storage.get_file(second["id"])["status"], "completed")
        self.assertEqual(calls.count(first["id"]), 1)

    def test_retry_limit_stops_retrying_connection_failures(self) -> None:
        meta = _new_file(self.project["id"], "flaky.pdf")
        attempts = {"count": 0}

        async def fake_run(file_id: str) -> bool:
            if file_id != meta["id"]:
                storage.update_file(file_id, {"status": "completed"})
                return True
            attempts["count"] += 1
            storage.update_file(
                file_id,
                {
                    "status": "failed",
                    "stage": "转换失败",
                    "message": "转换失败",
                    "error": "无法连接 OCR Worker：connection refused",
                    "conversion_token": f"token-{attempts['count']}",
                },
            )
            return True

        async def scenario() -> None:
            with mock.patch.dict(
                os.environ,
                {
                    "MIX_QUEUE_WORKER_RETRY_SECONDS": "0.05",
                    "MIX_QUEUE_MAX_RETRIES": "2",
                },
            ), mock.patch.object(
                ocr_client, "worker_available", new=_worker_ready
            ), mock.patch.object(
                conversion_service, "run_queued_conversion", new=fake_run
            ):
                await queue_service.start()
                try:
                    deadline = time.monotonic() + 10
                    while attempts["count"] < 3:
                        if time.monotonic() > deadline:
                            break
                        await asyncio.sleep(0.02)
                    # 再等一会儿，确认达到上限后不再重试。
                    await asyncio.sleep(0.3)
                finally:
                    await queue_service.stop()

        asyncio.run(scenario())

        # 初始 1 次 + 最多重试 2 次。
        self.assertEqual(attempts["count"], 3)
        paused = storage.get_file(meta["id"])
        self.assertEqual(paused["status"], "failed")
        self.assertEqual(
            paused["stage"], "OCR 服务多次不可用，已暂停该文件，请稍后手动重试"
        )
        self.assertEqual(
            paused["message"], "OCR 服务多次不可用，已暂停该文件，请稍后手动重试"
        )
        self.assertEqual(
            paused["error"], "OCR 服务多次不可用，已暂停该文件，请稍后手动重试"
        )
        self.assertEqual(paused["queue_retry_count"], 2)


class WorkerFailureClassificationTests(unittest.TestCase):
    def test_retryability_classification(self) -> None:
        cases = {
            "无法连接 OCR Worker：connection refused": True,
            "与 OCR Worker 通信中断，正在重试…": True,
            "查询 OCR 任务失败：timed out": True,
            "下载 OCR 结果失败：reset": True,
            "OCR 任务不存在（Worker 可能已重启）": True,
            "OCR 结果不存在": True,
            "OCR Worker 返回了非 JSON 响应": True,
            "OCR Worker 拒绝任务（HTTP 500）：内部错误": True,
            "OCR Worker 拒绝任务（HTTP 503）：busy": True,
            # 即使 detail 含连接类文案，4xx 仍是文件/请求问题，不可重试。
            "OCR Worker 拒绝任务（HTTP 400）：无法连接 OCR Worker": False,
            "OCR Worker 拒绝任务（HTTP 422）：与 OCR Worker 通信中断": False,
            # 5xx 与连接文案同时出现时按服务故障重试。
            "OCR Worker 拒绝任务（HTTP 500）：无法连接 OCR Worker": True,
            "OCR Worker 拒绝任务（HTTP 400）：坏文件": False,
            "OCR Worker 拒绝任务（HTTP 401）：未授权": False,
            "OCR Worker 拒绝任务（HTTP 404）：不存在": False,
            "OCR Worker 拒绝任务（HTTP 422）：参数错误": False,
            "OCR Worker 拒绝任务：缺少状态码": False,
            "源文件不存在，请重新上传": False,
            # 查询/下载接口的非 5xx 失败：401/403 属于鉴权问题，重试无意义。
            "查询 OCR 任务失败（HTTP 401）：未授权": False,
            "查询 OCR 任务失败（HTTP 403）：禁止访问": False,
            "查询 OCR 任务失败（HTTP 500）：内部错误": True,
            "下载 OCR 结果失败（HTTP 503）：服务不可用": True,
            # 404 只有在明确表示任务/结果丢失时才可重试（Worker 重启）。
            "下载 OCR 结果失败（HTTP 404）：missing": False,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(
                    queue_service._is_worker_failure(text), expected
                )

    def test_retry_limit_marks_file_paused(self) -> None:
        project = storage.create_project("重试上限单元测试", [], [])
        try:
            meta = _new_file(project["id"], "limit.pdf")
            storage.update_file(
                meta["id"],
                {
                    "status": "failed",
                    "stage": "转换失败",
                    "error": "无法连接 OCR Worker：refused",
                    "conversion_token": "token-limit",
                    "queue_retry_count": 3,
                },
            )
            with mock.patch.dict(
                os.environ, {"MIX_QUEUE_MAX_RETRIES": "3"}
            ):
                self.assertFalse(
                    queue_service._requeue_worker_failure(meta["id"])
                )
            paused = storage.get_file(meta["id"])
            self.assertEqual(paused["status"], "failed")
            self.assertEqual(
                paused["stage"],
                "OCR 服务多次不可用，已暂停该文件，请稍后手动重试",
            )
            self.assertEqual(
                paused["message"],
                "OCR 服务多次不可用，已暂停该文件，请稍后手动重试",
            )
            self.assertEqual(paused["queue_retry_count"], 3)
        finally:
            storage.delete_project(project["id"])

    def test_invalid_max_retries_falls_back_to_default(self) -> None:
        with mock.patch.dict(
            os.environ, {"MIX_QUEUE_MAX_RETRIES": "not-a-number"}
        ):
            self.assertEqual(queue_service._queue_max_retries(), 3)
        with mock.patch.dict(os.environ, {"MIX_QUEUE_MAX_RETRIES": "0"}):
            self.assertEqual(queue_service._queue_max_retries(), 1)


class QueueRetryResetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = storage.create_project("重试计数归零测试", [], [])

    def tearDown(self) -> None:
        storage.delete_project(self.project["id"])

    def test_completed_result_resets_retry_count(self) -> None:
        meta = _new_file(self.project["id"], "success.pdf")
        token = "token-success"
        storage.update_file(
            meta["id"],
            {
                "status": "converting",
                "conversion_token": token,
                "queue_retry_count": 2,
            },
        )
        temp_dir = Path(tempfile.mkdtemp(prefix="lfm-queue-test-"))
        zip_path = temp_dir / "result.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("result.md", "# 转换完成\n")

        async def scenario() -> bool:
            return await conversion_service._install_downloaded_result(
                meta["id"], token, zip_path, 4
            )

        try:
            installed = asyncio.run(scenario())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        self.assertTrue(installed)
        stored = storage.get_file(meta["id"])
        self.assertEqual(stored["status"], "completed")
        self.assertEqual(stored["page_count"], 4)
        self.assertEqual(stored["queue_retry_count"], 0)


class StaleUploadCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = storage.create_project("残留上传清理测试", [], [])

    def tearDown(self) -> None:
        storage.delete_project(self.project["id"])

    def test_cleanup_removes_uploading_records_only(self) -> None:
        uploading, _ = storage.create_file(
            self.project["id"],
            "stale.pdf",
            ".pdf",
            source_type="pdf",
            enable_table=True,
            enable_formula=False,
            dpi=200,
            initial_status="uploading",
        )
        uploaded = _new_file(self.project["id"], "healthy.pdf")
        uploading_dir = storage.file_dir(uploading)
        uploaded_dir = storage.file_dir(uploaded)
        self.assertTrue(uploading_dir.exists())

        removed = storage.cleanup_stale_uploads()

        self.assertGreaterEqual(removed, 1)
        self.assertFalse(uploading_dir.exists())
        with self.assertRaises(NotFoundError):
            storage.get_file(uploading["id"])
        # 正常的 uploaded 文件不受影响。
        self.assertTrue(uploaded_dir.exists())
        self.assertEqual(storage.get_file(uploaded["id"])["status"], "uploaded")


class WorkerProbeExceptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = storage.create_project("Worker 探测异常测试", [], [])

    def tearDown(self) -> None:
        storage.delete_project(self.project["id"])

    def test_health_probe_never_raises(self) -> None:
        async def scenario() -> bool:
            with mock.patch.object(
                httpx.AsyncClient,
                "get",
                new=mock.AsyncMock(side_effect=httpx.InvalidURL("bad url")),
            ):
                return await ocr_client.worker_available()

        self.assertFalse(asyncio.run(scenario()))

    def test_probe_exception_keeps_worker_alive_and_pauses(self) -> None:
        meta = _new_file(self.project["id"], "probe.pdf")
        calls: list[str] = []

        async def raising_probe() -> bool:
            raise RuntimeError("probe boom")

        async def fake_run(file_id: str) -> bool:
            calls.append(file_id)
            storage.update_file(file_id, {"status": "completed"})
            return True

        async def scenario() -> None:
            with mock.patch.dict(
                os.environ, {"MIX_QUEUE_WORKER_RETRY_SECONDS": "0.05"}
            ), mock.patch.object(
                ocr_client, "worker_available", new=raising_probe
            ), mock.patch.object(
                conversion_service, "run_queued_conversion", new=fake_run
            ):
                await queue_service.start()
                try:
                    await asyncio.sleep(0.3)
                    state = queue_service._state
                    self.assertIsNotNone(state)
                    assert state is not None
                    # worker 仍存活，没有因探测异常静默退出。
                    self.assertTrue(
                        all(not task.done() for task in state.workers)
                    )
                    self.assertEqual(calls, [])
                    self.assertEqual(
                        storage.get_file(meta["id"])["status"], "uploaded"
                    )
                finally:
                    await queue_service.stop()

        asyncio.run(scenario())
        self.assertEqual(storage.get_file(meta["id"])["status"], "uploaded")


class DeferredUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = storage.create_project("延迟转换测试", [], [])

    def tearDown(self) -> None:
        storage.delete_project(self.project["id"])

    def _client(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:  # pragma: no cover - 依赖缺失时跳过
            self.skipTest("未安装 FastAPI TestClient")

        import app as app_module

        return TestClient(app_module.app)

    def test_defer_conversion_only_enqueues(self) -> None:
        client = self._client()
        queue_start = mock.AsyncMock()
        with mock.patch.object(
            queue_service, "start", new=queue_start
        ), mock.patch.object(
            queue_service, "stop", new=mock.AsyncMock()
        ), mock.patch.object(
            queue_service, "wake"
        ) as wake_mock, mock.patch.object(
            conversion_service, "start_conversion", new=mock.AsyncMock()
        ) as start_mock:
            with client:
                response = client.post(
                    f"/api/projects/{self.project['id']}/files",
                    files={
                        "file": (
                            "batch.pdf",
                            b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n",
                            "application/pdf",
                        )
                    },
                    data={"defer_conversion": "true"},
                )

        self.assertEqual(response.status_code, 201, response.text)
        payload = response.json()
        self.assertEqual(payload["status"], "uploaded")
        self.assertEqual(payload["progress"], 0)
        self.assertEqual(payload["stage"], "排队中")
        self.assertEqual(payload["message"], "")
        self.assertEqual(payload["error"], "")
        self.assertEqual(payload["task_id"], "")
        # 内部字段不暴露给前端。
        self.assertNotIn("queue_seq", payload)
        self.assertNotIn("conversion_token", payload)

        start_mock.assert_not_called()
        wake_mock.assert_called_once()
        # lifespan 必须启动队列。
        queue_start.assert_awaited_once()

        stored = storage.get_file(payload["id"])
        self.assertEqual(stored["status"], "uploaded")
        self.assertEqual(stored["stage"], "排队中")
        self.assertIsInstance(stored["queue_seq"], int)

    def test_uploading_file_is_invisible_to_queue_during_save(self) -> None:
        client = self._client()
        started = threading.Event()
        release = threading.Event()
        observed: dict = {}
        original_save = files_routes._save_upload
        response = None

        async def blocking_save(upload, destination):
            started.set()
            # 模拟慢速/阻塞上传，期间文件记录只应是 uploading。
            await asyncio.to_thread(release.wait, 10)
            return await original_save(upload, destination)

        def watcher() -> None:
            if not started.wait(10):  # pragma: no cover - 超时保护
                return
            metas = storage.list_files(self.project["id"])
            observed["statuses"] = [item["status"] for item in metas]
            observed["meta_ids"] = [item["id"] for item in metas]
            observed["queued_ids"] = [
                item["id"] for item in storage.list_queued_files()
            ]
            release.set()

        thread = threading.Thread(target=watcher)
        thread.start()
        try:
            with mock.patch.object(
                queue_service, "start", new=mock.AsyncMock()
            ), mock.patch.object(
                queue_service, "stop", new=mock.AsyncMock()
            ), mock.patch.object(
                queue_service, "wake"
            ), mock.patch.object(
                conversion_service, "start_conversion", new=mock.AsyncMock()
            ), mock.patch.object(
                files_routes, "_save_upload", new=blocking_save
            ):
                with client:
                    response = client.post(
                        f"/api/projects/{self.project['id']}/files",
                        files={
                            "file": (
                                "slow.pdf",
                                b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n",
                                "application/pdf",
                            )
                        },
                        data={"defer_conversion": "true"},
                    )
        finally:
            release.set()
            thread.join(timeout=10)

        self.assertTrue(started.is_set())
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(observed.get("statuses"), ["uploading"])
        self.assertNotIn(observed["meta_ids"][0], observed["queued_ids"])
        # 上传完成后才进入队列。
        stored = storage.get_file(response.json()["id"])
        self.assertEqual(stored["status"], "uploaded")

    def test_default_upload_still_starts_conversion(self) -> None:
        client = self._client()
        captured: dict = {}

        async def fake_start(file_id: str, **kwargs) -> dict:
            captured["file_id"] = file_id
            return storage.update_file(
                file_id,
                {"status": "converting", "stage": "正在提交 OCR 任务"},
            )

        with mock.patch.object(
            queue_service, "start", new=mock.AsyncMock()
        ), mock.patch.object(
            queue_service, "stop", new=mock.AsyncMock()
        ), mock.patch.object(
            queue_service, "wake"
        ) as wake_mock, mock.patch.object(
            conversion_service, "start_conversion", new=fake_start
        ):
            with client:
                response = client.post(
                    f"/api/projects/{self.project['id']}/files",
                    files={
                        "file": (
                            "single.pdf",
                            b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n",
                            "application/pdf",
                        )
                    },
                )

        self.assertEqual(response.status_code, 201, response.text)
        payload = response.json()
        self.assertEqual(payload["status"], "converting")
        self.assertIn("file_id", captured)
        wake_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()

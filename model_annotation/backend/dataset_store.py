"""训练数据集的落盘、统计与读取。"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Any

from model_service import parse_jsonl_training_data

DATASET_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datasets")

_DATASET_ID_PATTERN = re.compile(r"[0-9a-f]{12}")


def dataset_dir() -> str:
    os.makedirs(DATASET_BASE, exist_ok=True)
    return DATASET_BASE


def _validate_dataset_id(dataset_id: str) -> str:
    """只接受 uuid4().hex[:12]，阻断通过 dataset_id 的路径穿越。"""
    if not dataset_id or not _DATASET_ID_PATTERN.fullmatch(dataset_id):
        raise FileNotFoundError(f"数据集不存在: {dataset_id}")
    return dataset_id


def dataset_data_path(dataset_id: str) -> str:
    return os.path.join(dataset_dir(), f"{_validate_dataset_id(dataset_id)}.jsonl")


def dataset_meta_path(dataset_id: str) -> str:
    return os.path.join(dataset_dir(), f"{_validate_dataset_id(dataset_id)}.meta.json")


def analyze_examples(examples: list[dict[str, Any]]) -> dict[str, Any]:
    label_counts: dict[str, int] = {}
    entity_count = 0
    char_count = 0
    unlabeled_sample_count = 0

    for example in examples:
        text = str(example.get("text") or "")
        char_count += len(text)
        entities = example.get("entities") or []
        if not entities:
            unlabeled_sample_count += 1
        entity_count += len(entities)
        for entity in entities:
            label = str(entity.get("label", "")).strip()
            if not label:
                continue
            label_counts[label] = label_counts.get(label, 0) + 1

    sample_count = len(examples)
    ordered_labels = dict(
        sorted(label_counts.items(), key=lambda item: (-item[1], item[0]))
    )
    return {
        "sample_count": sample_count,
        "entity_count": entity_count,
        "label_count": len(ordered_labels),
        "label_counts": ordered_labels,
        "char_count": char_count,
        "avg_text_length": round(char_count / sample_count, 1) if sample_count else 0,
        "unlabeled_sample_count": unlabeled_sample_count,
    }


def _collect_raw_labels(item: dict[str, Any]) -> set[str]:
    """收集原始 JSON 行里 spans/entities/labels 出现的所有 label。"""
    labels: set[str] = set()

    def add(value: Any) -> None:
        if value is None:
            return
        text = str(value).strip()
        if text:
            labels.add(text)

    for key in ("spans", "entities"):
        raw_items = item.get(key)
        if not isinstance(raw_items, list):
            continue
        for raw in raw_items:
            if isinstance(raw, dict):
                add(raw.get("label"))

    raw_labels = item.get("labels")
    if isinstance(raw_labels, list):
        for raw in raw_labels:
            if isinstance(raw, dict):
                add(raw.get("label"))
            elif isinstance(raw, (list, tuple)) and len(raw) >= 3:
                add(raw[2])

    return labels


def analyze_dataset_content(content: str) -> dict[str, Any]:
    """统计数据集，并把仅出现在 annotations 中的类别纳入 label_counts。

    parse_jsonl_training_data 只保留可训练实体（spans/entities/labels），
    像 decisions 这种只有 annotation、没有 span 的类别会丢失。这里逐行读取
    原始 JSON 补齐这些类别；已有对应 span 的 annotation 不重复计数。
    """
    content = content.lstrip("\ufeff")
    stats = analyze_examples(parse_jsonl_training_data(content))
    label_counts = dict(stats["label_counts"])

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text:
            continue

        span_labels = _collect_raw_labels(item)
        annotations = item.get("annotations")
        if not isinstance(annotations, list):
            continue
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            label = annotation.get("label")
            candidate = str(label).strip() if label is not None else ""
            if not candidate:
                candidate = str(annotation.get("rule_id") or "").strip()
            if not candidate or candidate in span_labels:
                continue
            label_counts[candidate] = label_counts.get(candidate, 0) + 1

    ordered_labels = dict(
        sorted(label_counts.items(), key=lambda item: (-item[1], item[0]))
    )
    stats["label_counts"] = ordered_labels
    stats["label_count"] = len(ordered_labels)
    return stats


def _atomic_write_text(path: str, content: str) -> None:
    """先写 .tmp 再原子替换，异常时清理临时文件。"""
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise


def save_dataset(content: str, file_name: str, name: str = "") -> dict[str, Any]:
    stats = analyze_dataset_content(content)
    if not stats["sample_count"]:
        raise ValueError("未解析到有效训练数据，请检查 JSONL 格式")

    dataset_id = uuid.uuid4().hex[:12]
    dataset_name = (name or os.path.splitext(file_name or "")[0] or "未命名数据集").strip()
    meta = {
        "dataset_id": dataset_id,
        "name": dataset_name,
        "file_name": file_name or f"{dataset_name}.jsonl",
        "uploaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "format": "mineru-annotation-jsonl-v1",
        **stats,
    }

    data_path = dataset_data_path(dataset_id)
    meta_path = dataset_meta_path(dataset_id)
    _atomic_write_text(data_path, content)
    try:
        _atomic_write_text(meta_path, json.dumps(meta, ensure_ascii=False, indent=2))
    except Exception:
        # 元数据写失败时不留下孤立的原始数据文件。
        try:
            if os.path.exists(data_path):
                os.remove(data_path)
        except OSError:
            pass
        raise
    return meta


def list_datasets() -> list[dict[str, Any]]:
    base = dataset_dir()
    datasets: list[dict[str, Any]] = []
    for file_name in os.listdir(base):
        if not file_name.endswith(".meta.json"):
            continue
        try:
            with open(os.path.join(base, file_name), "r", encoding="utf-8") as handle:
                meta = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        # 损坏的元数据可能是 []、5、null，跳过而不是让调用方 AttributeError。
        if not isinstance(meta, dict):
            continue
        datasets.append(meta)
    datasets.sort(key=lambda item: item.get("uploaded_at", ""), reverse=True)
    return datasets


def get_dataset(dataset_id: str) -> dict[str, Any]:
    path = dataset_meta_path(dataset_id)
    if not os.path.exists(path):
        raise FileNotFoundError(f"数据集不存在: {dataset_id}")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            meta = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise FileNotFoundError(f"数据集不存在: {dataset_id}") from exc
    if not isinstance(meta, dict):
        raise FileNotFoundError(f"数据集不存在: {dataset_id}")
    return meta


def delete_dataset(dataset_id: str) -> None:
    removed = False
    for path in (dataset_data_path(dataset_id), dataset_meta_path(dataset_id)):
        if os.path.exists(path):
            os.remove(path)
            removed = True
    if not removed:
        raise FileNotFoundError(f"数据集不存在: {dataset_id}")


def load_dataset_examples(dataset_ids: list[str]) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    missing: list[str] = []
    for dataset_id in dataset_ids:
        try:
            path = dataset_data_path(dataset_id)
        except FileNotFoundError:
            missing.append(dataset_id)
            continue
        if not os.path.exists(path):
            missing.append(dataset_id)
            continue
        with open(path, "r", encoding="utf-8") as handle:
            examples.extend(parse_jsonl_training_data(handle.read()))
    if missing:
        raise FileNotFoundError(f"数据集不存在: {', '.join(missing)}")
    return examples

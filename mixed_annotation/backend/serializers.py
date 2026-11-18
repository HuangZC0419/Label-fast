"""API 输出裁剪，避免把内部并发令牌暴露给客户端。"""

from __future__ import annotations

from typing import Any

_INTERNAL_FILE_FIELDS = {
    "conversion_token",
    # 文件目录名是内部实现，API 始终以 file_id 标识文件。
    "dir_name",
    "queue_seq",
    "queue_retry_count",
}


def serialize_file(meta: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in meta.items() if key not in _INTERNAL_FILE_FIELDS}


def serialize_annotation(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": record.get("text", ""),
        "spans": record.get("spans", []),
        "relations": record.get("relations", []),
        "paragraphs": record.get("paragraphs", []),
        "figures": record.get("figures", []),
        "updated_at": record.get("updated_at", ""),
    }

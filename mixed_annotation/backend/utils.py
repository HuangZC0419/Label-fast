"""无业务依赖的通用工具函数。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def utc_now() -> str:
    """返回带 Z 后缀、秒精度的 UTC 时间。"""

    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def clean_display_filename(filename: str | None) -> str:
    """保留用户原始文件名用于展示，但去掉路径和控制字符。"""

    raw = (filename or "").replace("\\", "/").split("/")[-1]
    cleaned = _CONTROL_CHARS.sub("", raw).strip().strip(".")
    if not cleaned:
        raise ValueError("缺少文件名")
    # 避免 Windows 保留设备名导致落盘异常；显示名仅存元数据，仍做基本约束。
    if cleaned.split(".")[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *{f"COM{i}" for i in range(1, 10)},
        *{f"LPT{i}" for i in range(1, 10)},
    }:
        cleaned = f"file_{cleaned}"
    return cleaned[:255]


def normalize_extension(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if not suffix or "\x00" in suffix:
        return ""
    return suffix


def normalize_string_list(values: Iterable[str], field_name: str) -> list[str]:
    """去首尾空白、去重并保持原顺序。"""

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value).strip()
        if not item:
            continue
        if len(item) > 200:
            raise ValueError(f"{field_name}中的单条内容不能超过 200 个字符")
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def ensure_within(base: Path, target: Path) -> Path:
    """校验 target 位于 base 内，防止目录穿越。"""

    resolved_base = base.resolve()
    resolved_target = target.resolve(strict=False)
    try:
        resolved_target.relative_to(resolved_base)
    except ValueError as exc:
        raise ValueError("非法路径") from exc
    return resolved_target


def validate_magic_header(extension: str, head: bytes) -> bool:
    """轻量校验文件头，拒绝伪装扩展名；不替代完整格式解析。"""

    if extension == ".pdf":
        return b"%PDF-" in head[:1024]
    if extension == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if extension in {".jpg", ".jpeg"}:
        return head.startswith(b"\xff\xd8\xff")
    return False

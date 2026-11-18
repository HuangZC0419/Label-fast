"""Markdown 切块服务（后端权威）。

把 OCR 产出的 ``result.md`` 按顶级结构切分为块，并把字符偏移映射到
``pages.json`` 的页码。``blocks.json`` 是文件级派生数据：

- 前端通过 ``GET /api/files/{fid}/blocks`` 读取；
- 缓存以 Markdown 的 sha256 为指纹，Markdown 变化后自动重建；
- 所有写盘均为同目录临时文件 + ``os.replace`` 的原子替换。
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
from pathlib import Path
from typing import Any

from errors import BadRequestError, NotFoundError
from storage import atomic_write_json, get_file, read_markdown
from storage import blocks_path as _storage_blocks_path
from storage import pages_path as _storage_pages_path

logger = logging.getLogger(__name__)

_BUILD_LOCK = threading.RLock()

_HEADING_RE = re.compile(r"^ {0,3}#{1,6}\s+")
_IMAGE_RE = re.compile(r"^\s*!\[[^\]]*\]\([^)]*\)\s*$")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
_SECTION_NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)*|附录[A-Z]|[A-Z]\d*)")

Block = dict[str, Any]


# ---------------------------------------------------------------------------
# 基础归一化
# ---------------------------------------------------------------------------


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _normalize_pages(raw: Any) -> list[dict[str, Any]]:
    """校验并排序 pages.json：每页必须满足 start < end，page >= 1。"""

    if not isinstance(raw, list):
        return []
    pages: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        page = _to_int(item.get("page"), 0)
        start = _to_int(item.get("start"), -1)
        end = _to_int(item.get("end"), -1)
        if page < 1 or start < 0 or end <= start:
            continue
        pages.append(
            {
                "page": page,
                "start": start,
                "end": end,
                "width": _to_float(item.get("width")),
                "height": _to_float(item.get("height")),
                "continuation": bool(
                    item.get("continuation")
                    or item.get("page_continuation_flags")
                ),
            }
        )
    pages.sort(key=lambda item: (item["start"], item["page"]))
    return pages


def page_for(offset: int, pages: list[dict[str, Any]]) -> int:
    """把 Markdown 字符偏移映射为页码；无法映射时返回 0。"""

    for item in pages:
        if item["start"] <= offset < item["end"]:
            return int(item["page"])
    return 0


# ---------------------------------------------------------------------------
# 切块
# ---------------------------------------------------------------------------


def _scan_lines(markdown: str) -> list[dict[str, Any]]:
    """按行扫描并保留原始偏移（兼容 \\n 与 \\r\\n）。"""

    lines: list[dict[str, Any]] = []
    offset = 0
    for raw in markdown.splitlines(keepends=True):
        content = raw.rstrip("\r\n")
        lines.append(
            {
                "start": offset,
                "content": content,
                "end": offset + len(raw),
            }
        )
        offset += len(raw)
    return lines


def _start_type(content: str) -> str | None:
    """判断一行是否会开启一个新的顶级块；空行返回 None。"""

    if not content.strip():
        return None
    left = content.lstrip()
    if left.startswith("```"):
        return "code"
    if _HEADING_RE.match(content):
        return "heading"
    if _IMAGE_RE.match(content):
        return "image"
    if left.startswith("|"):
        return "table"
    if _LIST_RE.match(content):
        return "list"
    if left.startswith(">"):
        return "blockquote"
    if left.startswith("<"):
        return "html"
    return "paragraph"


def _heading_text(content: str) -> str:
    return _HEADING_RE.sub("", content, count=1).strip()


def _section_number(title: str) -> str:
    match = _SECTION_NUMBER_RE.match(title)
    return match.group(1) if match else ""


def _plain_text(markdown_slice: str) -> str:
    """从块原文提取可读纯文本，用于图谱节点名称与导出。"""

    text = markdown_slice.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"```[^\n]*\n?(.*?)```", r"\1", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    lines: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if re.fullmatch(r"\|?[\s:|-]+\|?", stripped) and "-" in stripped:
            continue
        stripped = re.sub(r"^#{1,6}\s*", "", stripped)
        stripped = re.sub(r"^>\s*", "", stripped)
        stripped = re.sub(r"^(?:[-*+]|\d+\.)\s+", "", stripped)
        stripped = stripped.replace("|", " ")
        stripped = re.sub(r"\*\*|__", "", stripped)
        stripped = re.sub(r"[ \t]+", " ", stripped).strip()
        if stripped:
            lines.append(stripped)
    return "\n".join(lines).strip()


def markdown_hash(markdown: str) -> str:
    return "sha256:" + hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def parse_blocks(markdown: str, pages: list[dict] | None = None) -> dict[str, Any]:
    """把 Markdown 切分为块并计算章节、页码与偏移。

    纯函数：不访问磁盘，便于单元测试与复用。
    """

    normalized_pages = _normalize_pages(pages or [])
    lines = _scan_lines(markdown)
    blocks: list[Block] = []
    sections: list[dict[str, Any]] = []
    current = {"id": "", "number": "", "title": ""}

    def emit(first: int, last: int, block_type: str) -> None:
        nonlocal current
        index = len(blocks)
        start = lines[first]["start"]
        last_line = lines[last - 1]
        if block_type == "code":
            end = last_line["start"] + len(last_line["content"])
        else:
            end = last_line["start"] + len(last_line["content"].rstrip())
        if end <= start:
            end = last_line["start"] + len(last_line["content"])
        source = markdown[start:end]
        block_number = index + 1

        if block_type == "heading":
            title = _heading_text(lines[first]["content"])
            number = _section_number(title)
            section_id = f"s{block_number:04d}"
            if sections:
                sections[-1]["end"] = start
            sections.append(
                {
                    "id": section_id,
                    "number": number,
                    "title": title,
                    "start": start,
                    "end": len(markdown),
                    "page": page_for(start, normalized_pages),
                }
            )
            current = {"id": section_id, "number": number, "title": title}

        page = page_for(start, normalized_pages)
        page_end = page_for(max(start, end - 1), normalized_pages) or page
        blocks.append(
            {
                "id": f"b{block_number:04d}",
                "index": index,
                "type": block_type,
                "markdown": source,
                "text": _plain_text(source),
                "start": start,
                "end": end,
                "lineStart": first,
                "lineEnd": last - 1,
                "page": page,
                "pageEnd": page_end,
                "sectionId": current["id"],
                "sectionNumber": current["number"],
                "sectionTitle": current["title"],
            }
        )

    i = 0
    total = len(lines)
    while i < total:
        content = lines[i]["content"]
        block_type = _start_type(content)
        if block_type is None:
            i += 1
            continue
        if block_type == "code":
            first = i
            i += 1
            while i < total:
                if lines[i]["content"].lstrip().startswith("```"):
                    i += 1
                    break
                i += 1
            emit(first, i, "code")
            continue
        if block_type in {"heading", "image"}:
            emit(i, i + 1, block_type)
            i += 1
            continue
        # 表格 / 列表 / 引用 / HTML / 段落：连续同类行合并为一个块。
        first = i
        i += 1
        while i < total and _start_type(lines[i]["content"]) == block_type:
            i += 1
        emit(first, i, block_type)

    return {
        "version": 1,
        "markdown_hash": markdown_hash(markdown),
        "pages": normalized_pages,
        "sections": sections,
        "blocks": blocks,
    }


# ---------------------------------------------------------------------------
# 存储读写
# ---------------------------------------------------------------------------


def _read_json_soft(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        logger.warning("读取 %s 失败，按缺失处理", path)
        return None


def blocks_path(file_id: str) -> Path:
    return _storage_blocks_path(get_file(file_id))


def pages_path(file_id: str) -> Path:
    # Worker 结果 ZIP 根目录的 pages.json 解压在 markdown/ 下。
    return _storage_pages_path(get_file(file_id))


def load_pages(file_id: str) -> list[dict[str, Any]]:
    path = pages_path(file_id)
    data = _read_json_soft(path)
    if isinstance(data, dict):
        return _normalize_pages(data.get("pages"))
    if isinstance(data, list):
        return _normalize_pages(data)
    return []


def save_pages(file_id: str, payload: dict) -> None:
    """写入 pages.json 并使旧 blocks 缓存失效。"""

    if not isinstance(payload, dict):
        raise BadRequestError("pages 数据格式不正确")
    pages = _normalize_pages(payload.get("pages"))
    page_count = _to_int(payload.get("page_count"), 0)
    if page_count <= 0 and pages:
        page_count = max(item["page"] for item in pages)
    record = {"version": 1, "page_count": page_count, "pages": pages}
    with _BUILD_LOCK:
        meta = get_file(file_id)
        # 先删除缓存，避免写 pages 后崩溃导致旧页码继续被返回。
        _storage_blocks_path(meta).unlink(missing_ok=True)
        atomic_write_json(_storage_pages_path(meta), record)


def delete_pages(file_id: str) -> None:
    pages_path(file_id).unlink(missing_ok=True)


def _rebuild(file_id: str, markdown: str) -> dict[str, Any]:
    meta = get_file(file_id)
    payload = parse_blocks(markdown, load_pages(file_id))
    atomic_write_json(_storage_blocks_path(meta), payload)
    return payload


def rebuild_blocks(file_id: str) -> dict[str, Any]:
    """读取 Markdown 与 pages.json，重建并写入 blocks.json。"""

    with _BUILD_LOCK:
        markdown = read_markdown(file_id)
        if markdown is None:
            raise NotFoundError("Markdown 尚未生成")
        return _rebuild(file_id, markdown)


def load_blocks(file_id: str) -> dict[str, Any]:
    """读取 blocks.json；缺失或 Markdown 指纹不匹配时懒重建。"""

    markdown = read_markdown(file_id)
    if markdown is None:
        raise NotFoundError("Markdown 尚未生成")
    expected = markdown_hash(markdown)
    with _BUILD_LOCK:
        cached = _read_json_soft(blocks_path(file_id))
        if (
            isinstance(cached, dict)
            and cached.get("markdown_hash") == expected
            and isinstance(cached.get("blocks"), list)
        ):
            return cached
        return _rebuild(file_id, markdown)


def validate_block(blocks: dict[str, Any], block_id: str) -> bool:
    if not block_id:
        return False
    entries = blocks.get("blocks")
    if not isinstance(entries, list):
        return False
    return any(
        isinstance(item, dict) and item.get("id") == block_id for item in entries
    )

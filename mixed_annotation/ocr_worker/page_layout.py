"""逐页 Markdown 拼接与页偏移映射。

本模块只包含纯函数，不导入 ``engine`` / ``paddleocr``，
便于测试与后端复用。
"""

from __future__ import annotations

PAGE_SEPARATOR = "\n\n"


def _page_number(item: dict, fallback: int) -> int:
    raw = item.get("page")
    if raw is None:
        return fallback
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback


def _dimension(item: dict, key: str) -> float:
    raw = item.get(key, 0)
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _is_continuation(flags: object) -> bool:
    """判断页面是否存在跨页延续。

    PP-StructureV3 给出 ``(是否承接上页, 是否延续到下页)``；
    任意一侧为真都视为存在跨页文本。兼容缺失与布尔值。
    """

    if flags is None:
        return False
    if isinstance(flags, (tuple, list)):
        return any(bool(flag) for flag in flags)
    return bool(flags)


def assemble_pages(pages: list[dict]) -> tuple[str, list[dict]]:
    """用 ``"\\n\\n"`` 确定性地拼接逐页 Markdown，并返回页偏移映射。

    ``pages`` 每项可含 ``page`` / ``markdown_texts`` / ``width`` /
    ``height`` / ``page_continuation_flags``。

    返回 ``(markdown, page_map)``。``page_map`` 每项包含：

    - ``page``：从 1 开始的页码（缺失时按顺序兜底）
    - ``start`` / ``end``：该页文本在整篇 Markdown 中的字符区间（左闭右开）
    - ``width`` / ``height``：页面尺寸（PDF 为 pt，图片为 px）
    - ``continuation``：是否存在跨页延续
    - ``empty``：该页是否没有文本（此时 ``start == end``）

    空页仍保留在映射中，以保证页码与区间一一对应；这样即使某页
    识别失败，后续页面的偏移也不会错位。
    """

    parts: list[str] = []
    page_map: list[dict] = []
    cursor = 0
    separator_length = len(PAGE_SEPARATOR)

    for index, item in enumerate(pages):
        text = str(item.get("markdown_texts") or "").strip()
        start = cursor + separator_length if parts else cursor
        end = start + len(text)
        page_map.append(
            {
                "page": _page_number(item, index + 1),
                "start": start,
                "end": end,
                "width": _dimension(item, "width"),
                "height": _dimension(item, "height"),
                "continuation": _is_continuation(
                    item.get("page_continuation_flags")
                ),
                "empty": not text,
            }
        )
        parts.append(text)
        cursor = end

    return PAGE_SEPARATOR.join(parts), page_map

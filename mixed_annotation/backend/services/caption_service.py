"""图表标题自动预填：从截图 OCR 行里提取「图 3 XXXX / 表 2 XXXX」。

设计原则：
- 纯函数、可单测：输入 OCR 文本行，输出建议标题，不依赖网络与文件；
- 只在有明确「图/表 + 编号 + 分隔符」时给建议，避免把正文里的 “图3所示” 当成标题；
- 识别不准确也没关系：前端只把它填进输入框，用户提交前可以改。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

# 「图3 液压系统」「表 2：A-A 方向」；编号支持 3-1 / 1.1 这类分段号。
_FULL_CAPTION = re.compile(
    r"^(图|表)\s*(\d+(?:[-\u2010-\u2015./]\d+)*)\s*(?:[:.,、;；]\s*|\s+)(.+)$"
)
# 中文规范里最常见的紧凑写法：「图1单元面积示例」（编号后没有空格/冒号）。
# 只接受紧邻中文/拉丁标题的形态；「图3所示」这类正文引用由 _REFERENCE_PREFIXES 过滤。
_ATTACHED_CAPTION = re.compile(
    r"^(图|表)\s*(\d+(?:[-\u2010-\u2015./]\d+)*)\s*([\u4e00-\u9fffA-Za-z].*)$"
)
# 只有编号没有标题：「图3」「表 2」。
_NUMBER_ONLY_CAPTION = re.compile(
    r"^(图|表)\s*(\d+(?:[-\u2010-\u2015./]\d+)*)\s*[:.,、;；]?$"
)

# 正文里对图表的引用（“图3 中……”“图3 所示……”）不应该当作标题。
_REFERENCE_PREFIXES = (
    "所示",
    "中",
    "为",
    "是",
    "表示",
    "给出",
    "可见",
    "所列",
    "见",
    "和",
    "与",
    "及",
    "的",
)

_MIN_SCORE = 0.5

# 表格表头/列名，不能当作标题后缀（OCR 有时把「表 1」和表头拆成两行）。
_HEADER_WORDS = (
    "类型",
    "名称",
    "型号",
    "序号",
    "单位",
    "数量",
    "质量",
    "重量",
    "备注",
    "项目",
    "参数",
    "符号",
    "说明",
    "规格",
    "材料",
    "尺寸",
)


def _looks_like_header(text: str) -> bool:
    if len(text) > 8:
        return False
    return any(word in text for word in _HEADER_WORDS)



def _normalize(text: str) -> str:
    # NFKC 把全角数字/标点折叠成半角，OCR 全角输出也能命中。
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(text or ""))).strip()


def _clean_title(title: str) -> str:
    cleaned = _normalize(title)
    # OCR 偶尔会在汉字之间插空格，去掉这类空格；中英文之间的空格保留。
    cleaned = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", cleaned)
    return cleaned.strip(" .:;、-—–")


def _is_reference(title: str) -> bool:
    return any(title.startswith(prefix) for prefix in _REFERENCE_PREFIXES)


def extract_caption(lines: Iterable[dict[str, Any]]) -> str:
    """从 OCR 行里提取标题建议；没有命中返回空串。

    ``lines`` 需按阅读顺序排列（上→下、左→右）。
    """

    texts: list[tuple[str, float]] = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        text = _normalize(line.get("text", ""))
        if not text:
            continue
        try:
            score = float(line.get("score", 0))
        except (TypeError, ValueError):
            score = 0.0
        texts.append((text, score))

    number_only: str = ""
    for index, (text, score) in enumerate(texts):
        if score and score < _MIN_SCORE:
            continue

        full = _FULL_CAPTION.match(text) or _ATTACHED_CAPTION.match(text)
        if full:
            kind, number, raw_title = full.groups()
            title = _clean_title(raw_title)
            if not title or _is_reference(title):
                continue
            return f"{kind}{number} {title}"

        bare = _NUMBER_ONLY_CAPTION.match(text)
        if not bare:
            continue
        kind, number = bare.group(1), bare.group(2)
        # OCR 可能把「表 1」和「软线拉力试验」拆成上下两行：向后找一行标题补上。
        following = _find_following_title(texts, index + 1)
        if following:
            return f"{kind}{number} {following}"
        if not number_only:
            number_only = f"{kind}{number}"

    return number_only


def _find_following_title(texts: list[tuple[str, float]], start: int) -> str:
    """在编号行之后最多两行内找标题；遇到表头/正文句子就放弃。"""

    for offset in range(start, min(len(texts), start + 2)):
        text, _score = texts[offset]
        if not text:
            continue
        # 下一张图的编号或正文引用：标题已经断了。
        if (
            _NUMBER_ONLY_CAPTION.match(text)
            or _FULL_CAPTION.match(text)
            or _ATTACHED_CAPTION.match(text)
        ):
            return ""
        if _looks_like_header(text):
            return ""
        title = _clean_title(text)
        if not title or _is_reference(title):
            return ""
        # 标题通常短、不以句末标点结束；长句说明这是表格正文或段落。
        if len(title) > 40 or title.endswith(("。", "；", ";", "，", ",")):
            return ""
        if not re.search(r"[\u4e00-\u9fffA-Za-z]", title):
            return ""
        return title

    return ""


def build_caption_result(payload: dict[str, Any]) -> dict[str, Any]:
    """把 Worker 的 ``{lines: [...]}`` 转成接口响应。

    ``caption`` 为建议标题；``text`` 是整张图的 OCR 文本，便于用户查看/排错；
    ``lines`` 只保留文本与置信度，不向前端暴露坐标细节。
    """

    raw_lines = payload.get("lines") if isinstance(payload, dict) else None
    lines = [line for line in raw_lines or [] if isinstance(line, dict)]
    caption = extract_caption(lines)
    return {
        "caption": caption,
        "text": "\n".join(
            str(line.get("text", "")).strip()
            for line in lines
            if str(line.get("text", "")).strip()
        ),
        "lines": [
            {
                "text": str(line.get("text", "")).strip(),
                "score": round(float(line.get("score") or 0), 4),
            }
            for line in lines
            if str(line.get("text", "")).strip()
        ],
    }

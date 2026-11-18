# -*- coding: utf-8 -*-
"""标准号、标准名称的规范化和中文分词。"""

import re
import unicodedata
from typing import Any, List, Sequence

CHINESE_RE = re.compile(r"[一-鿿]+")
DASH_RE = re.compile(r"[—–－]")

_PUNCTUATION_CLASS = r"，,。.;；、:：\-—_/\\()（）\[\]【】<>《》\"'“”‘’"
_NAME_PUNCTUATION_RE = re.compile(r"[" + _PUNCTUATION_CLASS + r"]")
_SEGMENT_SPLIT_RE = re.compile(r"[\s" + _PUNCTUATION_CLASS + r"]+")
_ALNUM_SEPARATOR_CLASS = r"\s，,。.;；、:：\\()（）\[\]【】<>《》\"'“”‘’—–－"
_ALNUM_CLAUSE_SPLIT_RE = re.compile(r"[" + _ALNUM_SEPARATOR_CLASS + r"]+")
_ALNUM_TOKEN_RE = re.compile(r"[a-z0-9]+")


def to_text(value: Any) -> str:
    """把单元格值安全转成去首尾空格的字符串。"""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def normalize_name(name: Any) -> str:
    """名称规范化：全半角统一、转小写、去空格与常见标点。"""
    text = unicodedata.normalize("NFKC", to_text(name)).lower()
    text = re.sub(r"\s+", "", text)
    return _NAME_PUNCTUATION_RE.sub("", text)


def normalize_code(code: Any) -> str:
    """标准号规范化：统一前缀写法、两位年份补全、去掉空格和连字符。"""
    text = unicodedata.normalize("NFKC", to_text(code)).upper()
    text = DASH_RE.sub("-", text)
    text = text.replace("／", "/")
    text = re.sub(r"\s+", "", text)
    text = text.replace("GJB/T", "GJBT").replace("GB/T", "GBT")

    match = re.search(r"-(\d{2})$", text)
    if match:
        year = int(match.group(1))
        full_year = 1900 + year if year >= 30 else 2000 + year
        text = text[: match.start()] + "-" + str(full_year)

    return re.sub(r"[-\s]", "", text)


def base_code(code: str) -> str:
    """去掉末尾四位年份，得到标准号主体。"""
    normalized = normalize_code(code)
    return re.sub(r"(?:19|20)\d{2}$", "", normalized)


def segments(text: Any) -> List[str]:
    """按空格和标点切分名称，保留中文子句边界。"""
    normalized = unicodedata.normalize("NFKC", to_text(text)).lower()
    return [part for part in _SEGMENT_SPLIT_RE.split(normalized) if part]


def candidate_terms(
    text: Any, min_length: int = 2, max_length: int = 6
) -> List[str]:
    """提取候选词条：中文默认 2~6 元子串 + 含字母的字母数字 token（纯数字排除）。"""
    min_length = max(1, min_length)
    max_length = max(min_length, max_length)
    terms = set()
    for segment in segments(text):
        for match in CHINESE_RE.finditer(segment):
            chunk = match.group(0)
            for length in range(min_length, min(max_length, len(chunk)) + 1):
                for start in range(len(chunk) - length + 1):
                    terms.add(chunk[start : start + length])

    normalized = unicodedata.normalize("NFKC", to_text(text)).lower()
    for clause in _ALNUM_CLAUSE_SPLIT_RE.split(normalized):
        for token in _ALNUM_TOKEN_RE.findall(normalize_name(clause)):
            if len(token) >= 2 and any(char.isalpha() for char in token):
                terms.add(token)
    return sorted(terms)


def char_ngrams(text: Any, sizes: Sequence[int] = (2, 3)) -> List[str]:
    """去掉标点和空格后的字符 n-gram，用于相似名称检索。

    normalize_name 会移除分隔符，因此跨子句窗口同样视为有效特征。
    """
    normalized = normalize_name(text)
    grams = set()
    for size in sizes:
        if size < 1 or len(normalized) < size:
            continue
        for index in range(len(normalized) - size + 1):
            grams.add(normalized[index : index + size])
    return sorted(grams)

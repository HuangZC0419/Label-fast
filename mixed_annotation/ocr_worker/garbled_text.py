"""PDF 文本层是否是「字体编码坏掉」的符号串。"""

from __future__ import annotations

import re

_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")
_LATIN_PATTERN = re.compile(r"[A-Za-z]")
# 只统计 ASCII 标点/符号；中英文正常正文里占比通常低于 10%。
_PUNCT_PATTERN = re.compile(r"""[!"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~]""")


def looks_like_garbled_text(text: str) -> bool:
    """判断 PDF 文本层是否是「字体编码坏掉」的符号串。

    典型特征（中文标准文档）：几乎没有汉字、标点/符号占比极高、字母很少且
    不成词。英文文档虽然汉字为 0，但字母占比高、标点比例低，不会命中。
    扫描件没有文本层，不在这里判断。
    """

    sample = re.sub(r"\s+", "", str(text or ""))
    if len(sample) < 200:
        return False
    total = len(sample)
    cjk = len(_CJK_PATTERN.findall(sample))
    latin = len(_LATIN_PATTERN.findall(sample))
    punct = len(_PUNCT_PATTERN.findall(sample))
    return (
        cjk / total < 0.02
        and punct / total > 0.2
        and latin / total < 0.5
    )

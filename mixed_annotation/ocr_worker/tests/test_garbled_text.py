"""PDF 文本层乱码检测与 parse_method 覆盖的纯单元测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from garbled_text import looks_like_garbled_text


class GarbledTextTests(unittest.TestCase):
    def test_detects_broken_font_encoding(self) -> None:
        # 真实老国标 PDF 文本层的形态：汉字为 0、标点/符号占比极高、字母零散。
        sample = (
            '!"#!"!"!!!##$!$!"#$%&\'\'()*%&!"$$%&!"%"\'!!(" "#!$ %%&\'!&"()\'%'
            '!"#$%&\'()*+,-()*+,-.*,/01,2.-34"!-0.*,5.6-6756/)1,-*)47164.8),-0677.54'
        ) * 4
        self.assertTrue(looks_like_garbled_text(sample))

    def test_normal_chinese_is_not_garbled(self) -> None:
        sample = (
            "本标准规定了机械制图尺寸公差与配合注法。"
            "尺寸公差应按本标准规定的符号与数值标注，"
            "未注公差应符合相应的国家标准。"
        ) * 8
        self.assertFalse(looks_like_garbled_text(sample))

    def test_english_text_is_not_garbled(self) -> None:
        sample = (
            "This standard specifies the indication of tolerances for size and "
            "fits in mechanical drawings. Tolerances shall be indicated clearly."
        ) * 5
        self.assertFalse(looks_like_garbled_text(sample))

    def test_short_text_is_ignored(self) -> None:
        self.assertFalse(looks_like_garbled_text('!"#$%&'))

    def test_parse_method_override(self) -> None:
        import mineru_engine

        data = mineru_engine.build_api_form_data(
            enable_table=True, enable_formula=False, parse_method="ocr"
        )
        self.assertEqual(data["parse_method"], "ocr")

        default = mineru_engine.build_api_form_data(
            enable_table=True, enable_formula=False
        )
        self.assertEqual(default["parse_method"], mineru_engine.config.MINERU_PARSE_METHOD)


if __name__ == "__main__":
    unittest.main()

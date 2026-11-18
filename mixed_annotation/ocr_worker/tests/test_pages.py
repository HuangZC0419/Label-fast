"""``assemble_pages`` 的页码偏移、页面尺寸与空页处理测试。

测试只导入纯函数模块，不加载 PaddleOCR / engine。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from page_layout import assemble_pages


class AssemblePagesTests(unittest.TestCase):
    def test_empty_input(self) -> None:
        self.assertEqual(assemble_pages([]), ("", []))

    def test_single_page(self) -> None:
        markdown, page_map = assemble_pages(
            [
                {
                    "page": 1,
                    "markdown_texts": "单页内容",
                    "width": 595.28,
                    "height": 841.89,
                }
            ]
        )

        self.assertEqual(markdown, "单页内容")
        self.assertEqual(len(page_map), 1)
        self.assertEqual(page_map[0]["start"], 0)
        self.assertEqual(page_map[0]["end"], 4)
        self.assertEqual(markdown[0:4], "单页内容")
        self.assertFalse(page_map[0]["empty"])

    def test_separator_offsets(self) -> None:
        markdown, page_map = assemble_pages(
            [
                {"page": 1, "markdown_texts": "A"},
                {"page": 2, "markdown_texts": "BC"},
                {"page": 3, "markdown_texts": "DEF"},
            ]
        )

        self.assertEqual(markdown, "A\n\nBC\n\nDEF")
        self.assertEqual(
            [(item["start"], item["end"]) for item in page_map],
            [(0, 1), (3, 5), (7, 10)],
        )
        for expected, item in zip(["A", "BC", "DEF"], page_map):
            self.assertEqual(markdown[item["start"] : item["end"]], expected)

    def test_three_pages_with_empty_middle_page(self) -> None:
        _, page_map = assemble_pages(
            [
                {"page": 1, "markdown_texts": "第一页"},
                {"page": 2, "markdown_texts": "   "},
                {"page": 3, "markdown_texts": "第三页"},
            ]
        )

        self.assertEqual([item["page"] for item in page_map], [1, 2, 3])
        self.assertEqual((page_map[0]["start"], page_map[0]["end"]), (0, 3))
        # 空页保留在映射中，区间退化为 start == end，且不影响后续页偏移。
        self.assertEqual((page_map[1]["start"], page_map[1]["end"]), (5, 5))
        self.assertTrue(page_map[1]["empty"])
        self.assertEqual((page_map[2]["start"], page_map[2]["end"]), (7, 10))

    def test_page_sizes_are_preserved(self) -> None:
        _, page_map = assemble_pages(
            [
                {
                    "page": 1,
                    "markdown_texts": "PDF",
                    "width": 595.28,
                    "height": 841.89,
                },
                {
                    "page": 2,
                    "markdown_texts": "IMAGE",
                    "width": 1240,
                    "height": 1754,
                },
            ]
        )

        self.assertAlmostEqual(page_map[0]["width"], 595.28)
        self.assertAlmostEqual(page_map[0]["height"], 841.89)
        self.assertEqual(page_map[1]["width"], 1240.0)
        self.assertEqual(page_map[1]["height"], 1754.0)

    def test_missing_size_defaults_to_zero(self) -> None:
        _, page_map = assemble_pages([{"page": 1, "markdown_texts": "A"}])

        self.assertEqual(page_map[0]["width"], 0.0)
        self.assertEqual(page_map[0]["height"], 0.0)

    def test_continuation_flags(self) -> None:
        _, page_map = assemble_pages(
            [
                {
                    "page": 1,
                    "markdown_texts": "A",
                    "page_continuation_flags": (False, False),
                },
                {
                    "page": 2,
                    "markdown_texts": "B",
                    "page_continuation_flags": (True, False),
                },
                {
                    "page": 3,
                    "markdown_texts": "C",
                    "page_continuation_flags": (False, True),
                },
                {"page": 4, "markdown_texts": "D"},
            ]
        )

        self.assertFalse(page_map[0]["continuation"])
        self.assertTrue(page_map[1]["continuation"])
        self.assertTrue(page_map[2]["continuation"])
        self.assertFalse(page_map[3]["continuation"])

    def test_text_is_stripped_before_offsets(self) -> None:
        markdown, page_map = assemble_pages(
            [
                {"page": 1, "markdown_texts": "  A  "},
                {"page": 2, "markdown_texts": "\n\nB\n"},
            ]
        )

        self.assertEqual(markdown, "A\n\nB")
        self.assertEqual((page_map[0]["start"], page_map[0]["end"]), (0, 1))
        self.assertEqual((page_map[1]["start"], page_map[1]["end"]), (3, 4))

    def test_page_number_fallback(self) -> None:
        _, page_map = assemble_pages(
            [{"markdown_texts": "A"}, {"markdown_texts": "B"}]
        )

        self.assertEqual([item["page"] for item in page_map], [1, 2])

    def test_no_engine_import(self) -> None:
        self.assertNotIn("engine", sys.modules)


if __name__ == "__main__":
    unittest.main()

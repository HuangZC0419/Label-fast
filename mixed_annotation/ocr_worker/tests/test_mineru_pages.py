"""MinerU content_list -> pages.json 映射测试。

只导入 ``mineru_engine``（标准库 + config），不加载 PaddleOCR / engine。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mineru_engine import build_pages_from_content_list


def _middle(page_sizes: list[list[float]]) -> dict:
    return {
        "pdf_info": [
            {"page_size": [float(width), float(height)]}
            for width, height in page_sizes
        ]
    }


class BuildPagesFromContentListTests(unittest.TestCase):
    def setUp(self) -> None:
        self.markdown = (
            "# 第一页标题\n\n"
            "第一页正文\n\n"
            "| A | B |\n"
            "|---|---|\n"
            "| 1 | 2 |\n\n"
            "![示意图](images/fig1.jpg)\n"
        )
        self.content_list = [
            {"type": "text", "text": "# 第一页标题", "page_idx": 0, "bbox": [0, 0, 1, 1]},
            {
                "type": "table",
                "table_body": "| A | B |",
                "img_path": "images/table1.jpg",
                "page_idx": 1,
                "bbox": [0, 0, 1, 1],
            },
            {
                "type": "image",
                "img_path": "images/fig1.jpg",
                "page_idx": 2,
                "bbox": [0, 0, 1, 1],
            },
        ]
        self.middle = _middle([[595.0, 842.0], [595.0, 842.0], [1240.0, 1754.0]])

    def test_three_pages_with_text_table_and_image(self) -> None:
        payload = build_pages_from_content_list(
            self.markdown, self.content_list, self.middle
        )

        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["page_count"], 3)
        pages = payload["pages"]
        self.assertEqual([page["page"] for page in pages], [1, 2, 3])

        table_pos = self.markdown.find("| A | B |")
        image_pos = self.markdown.find("images/fig1.jpg")
        self.assertEqual(pages[0]["start"], 0)
        self.assertEqual(pages[0]["end"], table_pos)
        self.assertEqual(pages[1]["start"], table_pos)
        self.assertEqual(pages[1]["end"], image_pos)
        self.assertEqual(pages[2]["start"], image_pos)
        self.assertEqual(pages[2]["end"], len(self.markdown))

        self.assertIn("第一页标题", self.markdown[pages[0]["start"] : pages[0]["end"]])
        self.assertIn("| A | B |", self.markdown[pages[1]["start"] : pages[1]["end"]])
        self.assertIn("images/fig1.jpg", self.markdown[pages[2]["start"] : pages[2]["end"]])

        self.assertAlmostEqual(pages[0]["width"], 595.0)
        self.assertAlmostEqual(pages[2]["width"], 1240.0)
        self.assertAlmostEqual(pages[2]["height"], 1754.0)
        self.assertFalse(any(page["empty"] for page in pages))
        self.assertFalse(any(page["continuation"] for page in pages))

    def test_missing_middle_uses_zero_page_sizes(self) -> None:
        payload = build_pages_from_content_list(self.markdown, self.content_list, {})

        self.assertEqual(payload["page_count"], 3)
        for page in payload["pages"]:
            self.assertEqual(page["width"], 0.0)
            self.assertEqual(page["height"], 0.0)

    def test_missing_content_list_uses_middle_page_count(self) -> None:
        payload = build_pages_from_content_list("abcdefghij", [], self.middle)

        self.assertEqual(payload["page_count"], 3)
        self.assertEqual(payload["pages"][0]["start"], 0)
        self.assertEqual(payload["pages"][-1]["end"], 10)
        # 页数均分：余数优先给前面的页（4 + 3 + 3）。
        self.assertEqual(
            [(page["start"], page["end"]) for page in payload["pages"]],
            [(0, 4), (4, 7), (7, 10)],
        )

    def test_low_hit_rate_falls_back_to_equal_split(self) -> None:
        content_list = [
            {"type": "text", "text": "完全不存在的内容 A", "page_idx": 0},
            {"type": "text", "text": "完全不存在的内容 B", "page_idx": 1},
            {"type": "text", "text": "完全不存在的内容 C", "page_idx": 2},
        ]
        payload = build_pages_from_content_list("012345678", content_list, self.middle)

        self.assertEqual(payload["page_count"], 3)
        self.assertEqual(
            [(page["start"], page["end"]) for page in payload["pages"]],
            [(0, 3), (3, 6), (6, 9)],
        )
        # 兜底仍保留 middle.json 的页面尺寸。
        self.assertAlmostEqual(payload["pages"][2]["width"], 1240.0)

    def test_single_page_document(self) -> None:
        payload = build_pages_from_content_list("唯一一页", [], {})

        self.assertEqual(payload["page_count"], 1)
        page = payload["pages"][0]
        self.assertEqual((page["start"], page["end"]), (0, 4))
        self.assertFalse(page["empty"])

    def test_empty_markdown_is_empty_page(self) -> None:
        payload = build_pages_from_content_list("", [], self.middle)

        self.assertEqual(payload["page_count"], 3)
        for page in payload["pages"]:
            self.assertTrue(page["empty"])
            self.assertEqual(page["start"], page["end"])

    def test_whitespace_collapsed_marker_fallback(self) -> None:
        markdown = "第一页标题\n\n第一页 正文 续行\n\n第二页内容"
        content_list = [
            {"type": "text", "text": "第一页\n正文\n续行", "page_idx": 0},
            {"type": "text", "text": "第二页内容", "page_idx": 1},
        ]
        payload = build_pages_from_content_list(markdown, content_list, {})

        self.assertEqual(payload["page_count"], 2)
        # 首页始终从 0 开始，确保标题等前缀内容也有页码。
        self.assertEqual(payload["pages"][0]["start"], 0)
        self.assertEqual(
            payload["pages"][0]["end"], markdown.find("第二页内容")
        )
        self.assertEqual(
            payload["pages"][1]["start"], markdown.find("第二页内容")
        )
        self.assertEqual(payload["pages"][1]["end"], len(markdown))

    def test_leading_page_without_hit_keeps_prefix(self) -> None:
        markdown = "前缀内容\n\n第二页内容\n\n第三页内容"
        content_list = [
            {"type": "text", "text": "不存在", "page_idx": 0},
            {"type": "text", "text": "第二页内容", "page_idx": 1},
            {"type": "text", "text": "第三页内容", "page_idx": 2},
        ]
        payload = build_pages_from_content_list(markdown, content_list, {})

        pages = payload["pages"]
        self.assertEqual(pages[0]["start"], 0)
        self.assertEqual(pages[0]["end"], markdown.find("第二页内容"))
        self.assertFalse(pages[0]["empty"])

    def test_repeated_text_does_not_rewind_page_start(self) -> None:
        # 封面/页眉重复出现的短文本不应把后续页拉回文档开头。
        markdown = "重复标题\n\n第一页正文\n\n重复标题\n\n第二页正文"
        content_list = [
            {"type": "text", "text": "重复标题", "page_idx": 0},
            {"type": "text", "text": "第一页正文", "page_idx": 1},
            {"type": "text", "text": "重复标题", "page_idx": 2},
            {"type": "text", "text": "第二页正文", "page_idx": 3},
        ]
        payload = build_pages_from_content_list(markdown, content_list, {})

        starts = [page["start"] for page in payload["pages"]]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(payload["pages"][2]["start"], markdown.find("重复标题", 1))

    def test_first_page_covers_leading_whitespace(self) -> None:
        # content_list 首个 marker 可能在 BOM/空行之后；首页仍必须从 0 开始，
        # 否则后端切块会把首个标题判成“无页码”。
        markdown = "﻿\n# 标题\n\n正文"
        content_list = [
            {"type": "text", "text": "标题", "page_idx": 0},
            {"type": "text", "text": "正文", "page_idx": 1},
        ]
        payload = build_pages_from_content_list(markdown, content_list, {})

        self.assertEqual(payload["pages"][0]["start"], 0)
        self.assertFalse(payload["pages"][0]["empty"])

    def test_page_size_dict_and_missing_entry(self) -> None:
        middle = {
            "pdf_info": [
                {"page_size": {"width": 100, "height": 200}},
                {},
            ]
        }
        markdown = "A\n\nB"
        content_list = [
            {"type": "text", "text": "A", "page_idx": 0},
            {"type": "text", "text": "B", "page_idx": 1},
        ]
        payload = build_pages_from_content_list(markdown, content_list, middle)

        self.assertEqual(payload["pages"][0]["width"], 100.0)
        self.assertEqual(payload["pages"][0]["height"], 200.0)
        self.assertEqual(payload["pages"][1]["width"], 0.0)

    def test_payload_is_json_serializable(self) -> None:
        payload = build_pages_from_content_list(
            self.markdown, self.content_list, self.middle
        )
        text = json.dumps(payload, ensure_ascii=False)
        self.assertIn("page_count", text)

    def test_does_not_import_paddleocr(self) -> None:
        # 该模块必须能在 CF Python 3.9 下轻量导入；PaddleOCR 只在真正
        # 转换时才加载（由 test_pages 的 engine 断言兜底）。
        self.assertNotIn("paddleocr", sys.modules)


if __name__ == "__main__":
    unittest.main()

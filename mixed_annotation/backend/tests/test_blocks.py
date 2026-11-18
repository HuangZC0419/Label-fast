"""块切分、章节号与页码映射测试。"""

from __future__ import annotations

import json
import unittest

import _env  # noqa: F401  # 必须在 config/storage 之前导入

import storage
from errors import NotFoundError
from services import block_service

MARKDOWN = (
    "\n".join(
        [
            "# 1 范围",
            "",
            "本文件规定了紧固件的尺寸要求。",
            "",
            "## 3.1 结构和尺寸",
            "",
            "- 第一条",
            "- 第二条",
            "",
            "| 名称 | 尺寸 |",
            "| --- | --- |",
            "| 端子 | 5mm |",
            "",
            "![图1 结构](images/fig1.png)",
            "",
            "```python",
            "def foo():",
            "    return 1",
            "```",
            "",
            "> 注：单位为毫米。",
            "",
            "<div>原始 HTML</div>",
            "",
            "## 3.2 材料",
            "",
            "3.2 使用 T2 铜板。",
        ]
    )
    + "\n"
)

EXPECTED_TYPES = [
    "heading",
    "paragraph",
    "heading",
    "list",
    "table",
    "image",
    "code",
    "blockquote",
    "html",
    "heading",
    "paragraph",
]

EXPECTED_SECTIONS = [
    "s0001",
    "s0001",
    "s0003",
    "s0003",
    "s0003",
    "s0003",
    "s0003",
    "s0003",
    "s0003",
    "s0010",
    "s0010",
]


class ParseBlocksTests(unittest.TestCase):
    def test_block_types_and_ids(self) -> None:
        payload = block_service.parse_blocks(MARKDOWN)
        blocks = payload["blocks"]
        self.assertEqual([item["type"] for item in blocks], EXPECTED_TYPES)
        self.assertEqual(
            [item["id"] for item in blocks],
            [f"b{index + 1:04d}" for index in range(len(blocks))],
        )
        self.assertEqual(
            [item["index"] for item in blocks], list(range(len(blocks)))
        )

    def test_markdown_slice_and_offsets(self) -> None:
        payload = block_service.parse_blocks(MARKDOWN)
        previous_end = -1
        for block in payload["blocks"]:
            self.assertGreaterEqual(block["start"], previous_end)
            self.assertLess(block["start"], block["end"])
            self.assertEqual(block["markdown"], MARKDOWN[block["start"] : block["end"]])
            previous_end = block["end"]
        self.assertEqual(payload["blocks"][0]["markdown"], "# 1 范围")
        self.assertEqual(payload["blocks"][0]["lineStart"], 0)
        self.assertEqual(payload["blocks"][0]["lineEnd"], 0)
        self.assertEqual(payload["blocks"][3]["lineStart"], 6)
        self.assertEqual(payload["blocks"][3]["lineEnd"], 7)

    def test_sections_and_numbers(self) -> None:
        payload = block_service.parse_blocks(MARKDOWN)
        self.assertEqual(
            [item["sectionId"] for item in payload["blocks"]], EXPECTED_SECTIONS
        )
        sections = payload["sections"]
        self.assertEqual(
            [item["id"] for item in sections], ["s0001", "s0003", "s0010"]
        )
        self.assertEqual([item["number"] for item in sections], ["1", "3.1", "3.2"])
        self.assertEqual(
            [item["title"] for item in sections],
            ["1 范围", "3.1 结构和尺寸", "3.2 材料"],
        )
        head31 = MARKDOWN.index("## 3.1")
        head32 = MARKDOWN.index("## 3.2")
        self.assertEqual(sections[0]["start"], 0)
        self.assertEqual(sections[0]["end"], head31)
        self.assertEqual(sections[1]["start"], head31)
        self.assertEqual(sections[1]["end"], head32)
        self.assertEqual(sections[2]["start"], head32)
        self.assertEqual(sections[2]["end"], len(MARKDOWN))

    def test_section_number_extraction(self) -> None:
        for title, expected in [
            ("3.1 结构和尺寸", "3.1"),
            ("附录A 术语", "附录A"),
            ("A1 范围", "A1"),
            ("前言", ""),
        ]:
            self.assertEqual(block_service._section_number(title), expected)

    def test_page_mapping(self) -> None:
        head31 = MARKDOWN.index("## 3.1")
        head32 = MARKDOWN.index("## 3.2")
        pages = [
            {"page": 1, "start": 0, "end": head31, "width": 595, "height": 842},
            {"page": 2, "start": head31, "end": head32, "width": 595, "height": 842},
            {"page": 3, "start": head32, "end": len(MARKDOWN), "width": 595, "height": 842},
        ]
        payload = block_service.parse_blocks(MARKDOWN, pages)
        mapping = {item["id"]: item["page"] for item in payload["blocks"]}
        self.assertEqual(mapping["b0001"], 1)
        self.assertEqual(mapping["b0002"], 1)
        self.assertEqual(mapping["b0003"], 2)
        self.assertEqual(mapping["b0009"], 2)
        self.assertEqual(mapping["b0010"], 3)
        self.assertEqual(mapping["b0011"], 3)
        self.assertEqual(payload["pages"][0]["page"], 1)
        self.assertEqual(len(payload["pages"]), 3)

    def test_pages_missing_returns_zero(self) -> None:
        payload = block_service.parse_blocks(MARKDOWN)
        self.assertTrue(all(item["page"] == 0 for item in payload["blocks"]))
        self.assertTrue(all(item["pageEnd"] == 0 for item in payload["blocks"]))

    def test_crlf_offsets(self) -> None:
        markdown = "A\r\n\r\nB"
        blocks = block_service.parse_blocks(markdown)["blocks"]
        self.assertEqual(blocks[0]["markdown"], "A")
        self.assertEqual((blocks[0]["start"], blocks[0]["end"]), (0, 1))
        self.assertEqual(blocks[1]["markdown"], "B")
        # "A\r\n" 占 0-2，空行 "\r\n" 占 3-4，B 从 5 开始。
        self.assertEqual((blocks[1]["start"], blocks[1]["end"]), (5, 6))

    def test_text_is_plain(self) -> None:
        blocks = block_service.parse_blocks(MARKDOWN)["blocks"]
        self.assertEqual(blocks[0]["text"], "1 范围")
        self.assertIn("端子", blocks[4]["text"])
        self.assertNotIn("|", blocks[4]["text"])
        self.assertNotIn("```", blocks[6]["text"])
        self.assertIn("return 1", blocks[6]["text"])
        self.assertEqual(blocks[8]["text"], "原始 HTML")

    def test_hash_and_validate(self) -> None:
        payload = block_service.parse_blocks(MARKDOWN)
        self.assertTrue(payload["markdown_hash"].startswith("sha256:"))
        self.assertEqual(len(payload["markdown_hash"]), len("sha256:") + 64)
        self.assertTrue(block_service.validate_block(payload, "b0001"))
        self.assertFalse(block_service.validate_block(payload, "b9999"))
        self.assertFalse(block_service.validate_block(payload, ""))

    def test_empty_markdown(self) -> None:
        payload = block_service.parse_blocks("")
        self.assertEqual(payload["blocks"], [])
        self.assertEqual(payload["sections"], [])


class BlockStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project = storage.create_project("块测试项目", [], [])

    def _new_file(self) -> dict:
        meta, _ = storage.create_file(
            self.project["id"],
            "doc.pdf",
            ".pdf",
            source_type="pdf",
            enable_table=True,
            enable_formula=False,
            dpi=200,
        )
        return meta

    def test_lazy_rebuild_and_markdown_change(self) -> None:
        meta = self._new_file()
        file_id = meta["id"]
        markdown = "第一段\n\n第二段"
        storage.save_markdown(file_id, markdown)

        pages_file = block_service.pages_path(file_id)
        pages_file.parent.mkdir(parents=True, exist_ok=True)
        pages_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "page_count": 2,
                    "pages": [
                        {"page": 1, "start": 0, "end": 3, "width": 600, "height": 800},
                        {"page": 2, "start": 5, "end": 8, "width": 600, "height": 800},
                    ],
                }
            ),
            encoding="utf-8",
        )

        first = block_service.load_blocks(file_id)
        self.assertEqual(len(first["blocks"]), 2)
        self.assertEqual(first["blocks"][1]["page"], 2)
        self.assertTrue(block_service.blocks_path(file_id).is_file())

        # 相同 Markdown 直接命中缓存。
        second = block_service.load_blocks(file_id)
        self.assertEqual(second["markdown_hash"], first["markdown_hash"])

        # Markdown 变化后指纹不匹配，触发重建。
        storage.save_markdown(file_id, "只有一段")
        third = block_service.load_blocks(file_id)
        self.assertEqual(len(third["blocks"]), 1)
        self.assertNotEqual(third["markdown_hash"], first["markdown_hash"])

    def test_save_pages_invalidates_cache(self) -> None:
        meta = self._new_file()
        file_id = meta["id"]
        storage.save_markdown(file_id, "正文")
        self.assertEqual(block_service.rebuild_blocks(file_id)["blocks"][0]["page"], 0)

        block_service.save_pages(
            file_id,
            {
                "page_count": 1,
                "pages": [
                    {"page": 1, "start": 0, "end": 2, "width": 600, "height": 800}
                ],
            },
        )
        rebuilt = block_service.load_blocks(file_id)
        self.assertEqual(rebuilt["blocks"][0]["page"], 1)
        self.assertEqual(
            block_service.load_pages(file_id)[0]["width"], 600.0
        )

    def test_load_blocks_without_markdown(self) -> None:
        meta = self._new_file()
        with self.assertRaises(NotFoundError):
            block_service.load_blocks(meta["id"])


if __name__ == "__main__":
    unittest.main()

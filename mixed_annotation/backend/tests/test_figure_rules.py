"""图表参数校验、id 生成与存储行为测试。"""

from __future__ import annotations

import json
import unittest
from unittest import mock

import _env  # noqa: F401  # 必须在 config/storage 之前导入

import storage
from errors import BadRequestError, NotFoundError
from pydantic import ValidationError
from routes import figures as figure_routes
from schemas import AnnotationInput, FigureCreate, FigurePatch, ParagraphAnnotation
from services import block_service

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

# 图表记录的唯一合法字段集合（不含派生字段 missing）。
FIGURE_RECORD_KEYS = {
    "id",
    "kind",
    "caption",
    "note",
    "page",
    "bbox",
    "assetPath",
    "created_at",
    "updated_at",
}

LEGACY_FIGURE_FIELDS = {"number", "label", "paragraphId"}


def _figure(**overrides):
    payload = {
        "kind": "figure",
        "page": 1,
        "bbox": [1, 2, 3, 4],
        "caption": "结构",
        "note": "",
    }
    payload.update(overrides)
    return payload


class FigureSchemaTests(unittest.TestCase):
    def test_valid_figure(self) -> None:
        item = FigureCreate.model_validate(_figure())
        self.assertEqual(item.bbox, [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(item.page, 1)

    def test_page_must_be_positive(self) -> None:
        with self.assertRaises(ValidationError):
            FigureCreate.model_validate(_figure(page=0))

    def test_bbox_must_have_four_numbers(self) -> None:
        with self.assertRaises(ValidationError):
            FigureCreate.model_validate(_figure(bbox=[1, 2, 3]))
        with self.assertRaises(ValidationError):
            FigureCreate.model_validate(_figure(bbox=[1, 2, 3, 4, 5]))

    def test_bbox_must_be_ordered_and_non_negative(self) -> None:
        for bbox in ([-1, 0, 1, 2], [2, 2, 2, 4], [1, 5, 3, 5], [1, 2, float("nan"), 4]):
            with self.assertRaises(ValidationError):
                FigureCreate.model_validate(_figure(bbox=bbox))

    def test_kind_is_literal(self) -> None:
        with self.assertRaises(ValidationError):
            FigureCreate.model_validate(_figure(kind="other"))

    def test_create_ignores_legacy_fields(self) -> None:
        item = FigureCreate.model_validate(
            _figure(number="图1", label="结构图", paragraphId="b0001")
        )
        dumped = item.model_dump()
        for field in LEGACY_FIGURE_FIELDS:
            self.assertNotIn(field, dumped)

    def test_patch_is_optional(self) -> None:
        patch = FigurePatch()
        self.assertEqual(patch.model_dump(exclude_unset=True), {})
        patch = FigurePatch(caption=" 新标题 ")
        self.assertEqual(patch.caption, "新标题")

    def test_patch_only_edits_caption_and_note(self) -> None:
        patch = FigurePatch.model_validate(
            {
                "caption": "新标题",
                "note": "新备注",
                "number": "图2",
                "label": "结构图",
                "paragraphId": "b0002",
            }
        )
        self.assertEqual(
            patch.model_dump(exclude_unset=True),
            {"caption": "新标题", "note": "新备注"},
        )


class ParagraphSchemaTests(unittest.TestCase):
    def test_block_id_must_not_be_blank(self) -> None:
        with self.assertRaises(ValidationError):
            ParagraphAnnotation(blockId="  ", label="尺寸")

    def test_duplicate_block_id_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AnnotationInput(
                text="文本",
                paragraphs=[
                    {"blockId": "b0001", "label": "尺寸"},
                    {"blockId": "b0001", "label": "材料"},
                ],
            )
        payload = AnnotationInput(
            text="文本",
            paragraphs=[
                {"blockId": "b0001", "label": "尺寸"},
                {"blockId": "b0002", "label": "材料"},
            ],
        )
        self.assertEqual(len(payload.paragraphs), 2)

    def test_span_block_id_defaults_to_empty(self) -> None:
        payload = AnnotationInput(
            text="文本",
            spans=[{"id": 1, "start": 0, "end": 2, "label": "材料"}],
        )
        self.assertEqual(payload.spans[0].blockId, "")
        tagged = AnnotationInput(
            text="文本",
            spans=[
                {
                    "id": 1,
                    "start": 0,
                    "end": 2,
                    "label": "材料",
                    "blockId": "b0003",
                }
            ],
        )
        self.assertEqual(tagged.spans[0].blockId, "b0003")


class FigureGeometryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pages = [
            {"page": 1, "start": 0, "end": 100, "width": 600, "height": 800}
        ]

    def test_accepts_bbox_inside_page(self) -> None:
        figure_routes.validate_figure_against_pages(
            1, [10, 10, 100, 100], self.pages, 1
        )

    def test_rejects_page_out_of_range(self) -> None:
        with self.assertRaises(BadRequestError):
            figure_routes.validate_figure_against_pages(
                2, [10, 10, 100, 100], self.pages, 1
            )

    def test_rejects_bbox_beyond_page(self) -> None:
        with self.assertRaises(BadRequestError):
            figure_routes.validate_figure_against_pages(
                1, [10, 10, 700, 100], self.pages, 1
            )
        with self.assertRaises(BadRequestError):
            figure_routes.validate_figure_against_pages(
                1, [10, 10, 100, 900], self.pages, 1
            )

    def test_unknown_page_entry_skips_size_check(self) -> None:
        figure_routes.validate_figure_against_pages(
            2, [10, 10, 100, 100], self.pages, 3
        )

    def test_zero_page_size_skips_size_check(self) -> None:
        pages = [{"page": 1, "start": 0, "end": 10, "width": 0, "height": 0}]
        figure_routes.validate_figure_against_pages(
            1, [10, 10, 9000, 9000], pages, 1
        )


class PngUploadTests(unittest.TestCase):
    def test_accepts_png(self) -> None:
        figure_routes.validate_png_upload(PNG)

    def test_rejects_empty_and_non_png(self) -> None:
        with self.assertRaises(BadRequestError):
            figure_routes.validate_png_upload(b"")
        with self.assertRaises(BadRequestError):
            figure_routes.validate_png_upload(b"\xff\xd8\xff" + b"\x00" * 8)

    def test_rejects_oversized(self) -> None:
        with mock.patch.object(figure_routes, "MAX_FIGURE_BYTES", 8):
            with self.assertRaises(BadRequestError):
                figure_routes.validate_png_upload(PNG)


class FigureIdTests(unittest.TestCase):
    def test_ids_start_at_one_per_kind(self) -> None:
        self.assertEqual(storage.next_figure_id([], "figure"), "fig_0001")
        self.assertEqual(storage.next_figure_id([], "table"), "tbl_0001")

    def test_ids_are_monotonic(self) -> None:
        figures = [
            {"id": "fig_0001"},
            {"id": "fig_0007"},
            {"id": "tbl_0002"},
            {"id": "bad"},
        ]
        self.assertEqual(storage.next_figure_id(figures, "figure"), "fig_0008")
        self.assertEqual(storage.next_figure_id(figures, "table"), "tbl_0003")

    def test_invalid_kind(self) -> None:
        with self.assertRaises(BadRequestError):
            storage.next_figure_id([], "other")


class FigureStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project = storage.create_project("图表测试项目", [], [])

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

    def _annotation_file(self, meta: dict):
        return storage.file_dir(meta) / "annotations.json"

    def test_crud_and_annotation_preservation(self) -> None:
        meta = self._new_file()
        file_id = meta["id"]

        figure = storage.add_figure(file_id, _figure(), PNG)
        self.assertEqual(figure["id"], "fig_0001")
        # 资产文件名取 caption；内部 id 保持不变。
        self.assertEqual(figure["assetPath"], "assets/figures/结构.png")
        self.assertEqual(set(figure), FIGURE_RECORD_KEYS)
        asset = storage.resolve_figure_asset(file_id, "结构.png")
        self.assertTrue(asset.is_file())

        table = storage.add_figure(
            file_id,
            _figure(kind="table", bbox=[5, 6, 50, 60]),
            PNG,
        )
        self.assertEqual(table["id"], "tbl_0001")

        listed = storage.list_figures(file_id)
        self.assertEqual([item["id"] for item in listed], ["fig_0001", "tbl_0001"])
        self.assertFalse(any(item["missing"] for item in listed))

        # 保存文本/段落标注必须保留图表。
        saved = storage.save_annotations(
            file_id,
            {
                "text": "正文",
                "spans": [],
                "relations": [],
                "paragraphs": [
                    {"blockId": "b0001", "label": "尺寸", "note": ""}
                ],
            },
        )
        self.assertEqual(len(saved["figures"]), 2)
        self.assertEqual(saved["paragraphs"][0]["blockId"], "b0001")

        # 历史字段即便传入更新接口也必须被忽略。
        updated = storage.update_figure(
            file_id,
            "fig_0001",
            {
                "caption": "新标题",
                "number": "图1",
                "label": "结构图",
                "paragraphId": "b0002",
            },
        )
        self.assertEqual(updated["caption"], "新标题")
        # caption 变化会同步重命名资产。
        self.assertEqual(updated["assetPath"], "assets/figures/新标题.png")
        self.assertFalse((asset.parent / "结构.png").exists())
        self.assertTrue((asset.parent / "新标题.png").is_file())
        for field in LEGACY_FIGURE_FIELDS:
            self.assertNotIn(field, updated)

        reloaded = storage.load_annotations(file_id)
        persisted = next(item for item in reloaded["figures"] if item["id"] == "fig_0001")
        self.assertEqual(persisted["caption"], "新标题")
        self.assertEqual(set(persisted), FIGURE_RECORD_KEYS)
        for field in LEGACY_FIGURE_FIELDS:
            self.assertNotIn(field, persisted)

        storage.delete_figure(file_id, "fig_0001")
        self.assertFalse((asset.parent / "新标题.png").exists())
        self.assertEqual(
            [item["id"] for item in storage.list_figures(file_id)], ["tbl_0001"]
        )
        with self.assertRaises(NotFoundError):
            storage.delete_figure(file_id, "fig_0001")

    def test_legacy_record_fields_are_stripped_on_load_and_update(self) -> None:
        meta = self._new_file()
        file_id = meta["id"]
        legacy = {
            "id": "fig_0001",
            "kind": "figure",
            "label": "结构图",
            "number": "图1",
            "caption": "旧标题",
            "note": "",
            "page": 1,
            "bbox": [1, 2, 3, 4],
            "paragraphId": "b0001",
            "assetPath": "assets/figures/fig_0001.png",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        self._annotation_file(meta).write_text(
            json.dumps(
                {
                    "text": "正文",
                    "spans": [],
                    "relations": [],
                    "paragraphs": [],
                    "figures": [legacy],
                    "updated_at": "2026-01-01T00:00:00Z",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        loaded = storage.load_annotations(file_id)
        figure = loaded["figures"][0]
        self.assertEqual(set(figure), FIGURE_RECORD_KEYS)
        self.assertEqual(figure["caption"], "旧标题")
        for field in LEGACY_FIGURE_FIELDS:
            self.assertNotIn(field, figure)

        # 更新后落盘数据同样只保留白名单字段。
        storage.update_figure(file_id, "fig_0001", {"caption": "新标题"})
        raw = json.loads(self._annotation_file(meta).read_text(encoding="utf-8"))
        stored = raw["figures"][0]
        self.assertEqual(set(stored), FIGURE_RECORD_KEYS)
        for field in LEGACY_FIGURE_FIELDS:
            self.assertNotIn(field, stored)

    def test_missing_asset_marker(self) -> None:
        meta = self._new_file()
        file_id = meta["id"]
        storage.add_figure(file_id, _figure(), PNG)
        asset = storage.resolve_figure_asset(file_id, "结构.png")
        asset.unlink()
        listed = storage.list_figures(file_id)
        self.assertTrue(listed[0]["missing"])

    def test_asset_path_rejects_traversal(self) -> None:
        meta = self._new_file()
        file_id = meta["id"]
        storage.add_figure(file_id, _figure(), PNG)
        for name in ("../meta.json", "..\\meta.json", "/etc/passwd", ".hidden.png"):
            with self.assertRaises(BadRequestError):
                storage.resolve_figure_asset(file_id, name)
        with self.assertRaises(NotFoundError):
            storage.resolve_figure_asset(file_id, "missing.png")

    def test_clear_results_keeps_figures(self) -> None:
        meta = self._new_file()
        file_id = meta["id"]
        storage.save_markdown(file_id, "正文")
        block_service.save_pages(
            file_id,
            {
                "page_count": 1,
                "pages": [
                    {"page": 1, "start": 0, "end": 2, "width": 600, "height": 800}
                ],
            },
        )
        block_service.rebuild_blocks(file_id)
        storage.save_annotations(
            file_id,
            {
                "text": "正文",
                "spans": [
                    {
                        "id": 1,
                        "start": 0,
                        "end": 2,
                        "label": "材料",
                        "text": "正文",
                        "blockId": "b0001",
                    }
                ],
                "relations": [],
                "paragraphs": [
                    {"blockId": "b0001", "label": "尺寸", "note": ""}
                ],
            },
        )
        storage.add_figure(file_id, _figure(), PNG)

        storage.clear_results(file_id, clear_annotations=True)

        record = storage.load_annotations(file_id)
        self.assertEqual(record["text"], "")
        self.assertEqual(record["spans"], [])
        self.assertEqual(record["relations"], [])
        self.assertEqual(record["paragraphs"], [])
        self.assertEqual(len(record["figures"]), 1)
        self.assertEqual(set(record["figures"][0]), FIGURE_RECORD_KEYS)
        self.assertNotIn("paragraphId", record["figures"][0])
        self.assertTrue(storage.resolve_figure_asset(file_id, "结构.png").is_file())
        self.assertFalse(storage.pages_path(meta).exists())
        self.assertFalse(storage.blocks_path(meta).exists())
        self.assertFalse(storage.markdown_path(meta).exists())

    def test_reset_annotations_keeps_figures_and_ignores_valid_ids(self) -> None:
        meta = self._new_file()
        file_id = meta["id"]
        storage.add_figure(file_id, _figure(), PNG)
        # 兼容旧调用方：参数仍可传入，但不再影响图表记录。
        storage.reset_annotations(file_id, valid_paragraph_ids={"b0002"})
        record = storage.load_annotations(file_id)
        self.assertEqual([item["id"] for item in record["figures"]], ["fig_0001"])
        self.assertEqual(set(record["figures"][0]), FIGURE_RECORD_KEYS)
        self.assertNotIn("paragraphId", record["figures"][0])

    def test_reset_without_figures_removes_annotation_file(self) -> None:
        meta = self._new_file()
        file_id = meta["id"]
        storage.save_annotations(
            file_id,
            {
                "text": "正文",
                "spans": [],
                "relations": [],
                "paragraphs": [],
            },
        )
        self.assertTrue(storage.has_annotations(file_id))
        storage.reset_annotations(file_id, valid_paragraph_ids=set())
        self.assertFalse(storage.has_annotations(file_id))


if __name__ == "__main__":
    unittest.main()

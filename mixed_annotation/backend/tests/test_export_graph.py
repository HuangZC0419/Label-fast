"""双文件导出：图谱行构造、annotations 扩展字段与导出命名测试。

纯函数断言不依赖文件系统；ZIP 命名测试使用测试隔离的临时数据目录。
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

import _env  # noqa: F401  # 必须在 config/storage 之前导入

import storage
from services import block_service
from services.export_service import (
    EXPORT_VERSION,
    _assign_export_stems,
    _file_folder,
    build_annotation_row,
    build_export_zip,
    build_graph_rows,
    extract_standard_id,
)

FILE_ID = "11111111-1111-1111-1111-111111111111"
PROJECT = {"id": "22222222-2222-2222-2222-222222222222", "name": "测试项目"}
META = {
    "id": FILE_ID,
    "project_id": PROJECT["id"],
    "name": "GBT 4423-2020 紧固件.pdf",
    "updated_at": "2026-11-04T00:00:00Z",
}

BLOCKS = {
    "version": 1,
    "markdown_hash": "sha256:test",
    "pages": [
        {"page": 1, "start": 0, "end": 20, "width": 595.0, "height": 842.0},
        {"page": 2, "start": 20, "end": 40, "width": 595.0, "height": 842.0},
    ],
    "sections": [
        {"id": "s0001", "number": "1", "title": "范围", "page": 1},
        {"id": "s0003", "number": "3.1", "title": "结构和尺寸", "page": 2},
    ],
    "blocks": [
        {
            "id": "b0001",
            "index": 0,
            "type": "heading",
            "text": "1 范围",
            "page": 1,
            "sectionId": "s0001",
            "sectionNumber": "1",
            "sectionTitle": "范围",
        },
        {
            "id": "b0002",
            "index": 1,
            "type": "paragraph",
            "text": "OD·JZ型端子应满足尺寸要求。",
            "page": 1,
            "sectionId": "s0001",
            "sectionNumber": "1",
            "sectionTitle": "范围",
        },
        {
            "id": "b0003",
            "index": 2,
            "type": "heading",
            "text": "3.1 结构和尺寸",
            "page": 2,
            "sectionId": "s0003",
            "sectionNumber": "3.1",
            "sectionTitle": "结构和尺寸",
        },
        {
            "id": "b0004",
            "index": 3,
            "type": "paragraph",
            "text": "T2铜板用于导电部件。",
            "page": 2,
            "sectionId": "s0003",
            "sectionNumber": "3.1",
            "sectionTitle": "结构和尺寸",
        },
        {
            "id": "b0005",
            "index": 4,
            "type": "paragraph",
            "text": "未标注段落。",
            "page": 2,
            "sectionId": "s0003",
            "sectionNumber": "3.1",
            "sectionTitle": "结构和尺寸",
        },
    ],
}

# 模拟旧 annotations.json：携带已废弃的 number/label/paragraphId 与内部 missing。
FIGURE_RECORD = {
    "id": "fig_0001",
    "kind": "figure",
    "number": "图1",
    "label": "结构图",
    "caption": "端子结构",
    "note": "",
    "page": 2,
    "bbox": [72, 120, 520.5, 380],
    "paragraphId": "b0004",
    "asset_path": "assets/figures/fig_0001.png",
    "missing": False,
}

LEGACY_FIGURE_FIELDS = {"number", "label", "paragraphId", "missing"}

ANNOTATIONS = {
    "text": "OD·JZ型端子应满足尺寸要求。T2铜板用于导电部件。",
    "spans": [
        {
            "id": 1,
            "start": 0,
            "end": 6,
            "label": "端子",
            "text": "OD·JZ型",
            "blockId": "b0002",
        },
        {
            "id": 2,
            "start": 16,
            "end": 20,
            "label": "材料",
            "text": "T2铜板",
            "blockId": "b0004",
        },
    ],
    "relations": [{"fromId": 1, "toId": 2, "type": "使用"}],
    "paragraphs": [
        {"blockId": "b0002", "label": "尺寸", "note": "段注"},
        {"blockId": "b0004", "label": "材料", "note": ""},
    ],
    "figures": [dict(FIGURE_RECORD)],
}

ASSET_MAP = {"fig_0001": "assets/figures/fig_0001.png"}

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_LEGACY_ID_SUFFIX = re.compile(r"__[0-9a-fA-F]{8}")


def _node_ids(rows):
    return {
        row["id"] for row in rows if row.get("record") == "node"
    }


def _edge_ids(rows):
    return {
        row["id"] for row in rows if row.get("record") == "edge"
    }


def _figure_node(rows):
    return next(
        row
        for row in rows
        if row.get("record") == "node" and row["kind"] == "figure"
    )


class StandardIdTests(unittest.TestCase):
    def test_extracts_standard_number(self) -> None:
        self.assertEqual(
            extract_standard_id("GBT 4423-2020 紧固件.pdf"), "GBT 4423-2020"
        )
        self.assertEqual(
            extract_standard_id("GB 1234—2020.pdf"), "GB 1234—2020"
        )

    def test_falls_back_to_stem(self) -> None:
        self.assertEqual(extract_standard_id("未编号文件.pdf"), "未编号文件")
        self.assertEqual(extract_standard_id(""), "")


class BuildGraphRowsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = build_graph_rows(
            PROJECT,
            META,
            BLOCKS,
            ANNOTATIONS,
            ASSET_MAP,
            exported_at="2026-11-04T01:02:03Z",
        )

    def test_meta_row_comes_first(self) -> None:
        meta = self.rows[0]
        self.assertEqual(meta["record"], "meta")
        self.assertEqual(meta["format"], EXPORT_VERSION)
        self.assertEqual(meta["file_name"], META["name"])
        self.assertEqual(meta["exported_at"], "2026-11-04T01:02:03Z")
        self.assertEqual(meta["standard_id"], "GBT 4423-2020")

    def test_record_counts(self) -> None:
        records = [row["record"] for row in self.rows]
        self.assertEqual(records.count("meta"), 1)
        # 1 document + 2 section + 2 annotated paragraph + 1 figure + 2 entity
        self.assertEqual(records.count("node"), 8)
        # 2 doc→section + 2 section→paragraph + 1 doc→figure
        # + 2 entity→paragraph + 1 entity relation（不再有 paragraph→figure）
        self.assertEqual(records.count("edge"), 8)

    def test_node_ids(self) -> None:
        expected = {
            f"doc:{FILE_ID}",
            f"sec:{FILE_ID}:s0001",
            f"sec:{FILE_ID}:s0003",
            f"par:{FILE_ID}:b0002",
            f"par:{FILE_ID}:b0004",
            f"fig:{FILE_ID}:fig_0001",
            f"ent:{FILE_ID}:1",
            f"ent:{FILE_ID}:2",
        }
        self.assertEqual(_node_ids(self.rows), expected)

    def test_unannotated_paragraph_has_no_node(self) -> None:
        self.assertNotIn(f"par:{FILE_ID}:b0005", _node_ids(self.rows))

    def test_edge_ids(self) -> None:
        expected = {
            f"e:doc:{FILE_ID}|sec:{FILE_ID}:s0001|包含",
            f"e:doc:{FILE_ID}|sec:{FILE_ID}:s0003|包含",
            f"e:sec:{FILE_ID}:s0001|par:{FILE_ID}:b0002|包含",
            f"e:sec:{FILE_ID}:s0003|par:{FILE_ID}:b0004|包含",
            f"e:doc:{FILE_ID}|fig:{FILE_ID}:fig_0001|包含",
            f"e:ent:{FILE_ID}:1|par:{FILE_ID}:b0002|出现在",
            f"e:ent:{FILE_ID}:2|par:{FILE_ID}:b0004|出现在",
            f"e:ent:{FILE_ID}:1|ent:{FILE_ID}:2|使用",
        }
        self.assertEqual(_edge_ids(self.rows), expected)

    def test_no_paragraph_to_figure_edge(self) -> None:
        for row in self.rows:
            if row.get("record") != "edge":
                continue
            self.assertNotEqual(row["relation"], "附有")
            self.assertFalse(
                row["source"].startswith("par:")
                and row["target"].startswith("fig:")
            )

    def test_edge_kind(self) -> None:
        edges = [row for row in self.rows if row.get("record") == "edge"]
        relation_edge = next(
            row for row in edges if row["relation"] == "使用"
        )
        self.assertEqual(relation_edge["kind"], "relation")
        containment = next(row for row in edges if row["relation"] == "包含")
        self.assertEqual(containment["kind"], "hierarchy")

    def test_entity_paragraph_edge_is_relation_not_hierarchy(self) -> None:
        """“出现在”是实体与段落的关联边，不能编码成父子层级。"""
        edges = [
            row
            for row in self.rows
            if row.get("record") == "edge" and row["relation"] == "出现在"
        ]
        self.assertEqual(len(edges), 2)
        for edge in edges:
            with self.subTest(edge=edge["id"]):
                self.assertEqual(edge["kind"], "relation")
                self.assertTrue(edge["source"].startswith("ent:"))
                self.assertTrue(edge["target"].startswith("par:"))

    def test_all_attributes_are_strings(self) -> None:
        for row in self.rows:
            if row.get("record") != "node":
                continue
            for key, value in row["attributes"].items():
                with self.subTest(node=row["id"], attribute=key):
                    self.assertIsInstance(value, str)

    def test_figure_node_label_name_and_attributes(self) -> None:
        figure = _figure_node(self.rows)
        self.assertEqual(figure["label"], "图")
        self.assertEqual(figure["name"], "端子结构")
        self.assertEqual(
            set(figure["attributes"]),
            {"asset_path", "page", "bbox", "caption"},
        )
        self.assertEqual(figure["attributes"]["bbox"], "72,120,520.5,380")
        self.assertEqual(figure["attributes"]["page"], "2")
        self.assertEqual(figure["attributes"]["caption"], "端子结构")
        self.assertEqual(
            figure["attributes"]["asset_path"], "assets/figures/fig_0001.png"
        )

    def test_figure_legacy_fields_are_ignored(self) -> None:
        figure = _figure_node(self.rows)
        for field in LEGACY_FIGURE_FIELDS:
            self.assertNotIn(field, figure["attributes"])
        self.assertNotEqual(figure["label"], "结构图")
        self.assertNotIn("图1 端子结构", figure["name"])

    def test_table_node_uses_table_label(self) -> None:
        annotations = {
            **ANNOTATIONS,
            "figures": [
                {
                    "id": "tbl_0001",
                    "kind": "table",
                    "caption": "",
                    "note": "",
                    "page": 2,
                    "bbox": [1, 2, 3, 4],
                    "asset_path": "assets/figures/tbl_0001.png",
                }
            ],
        }
        rows = build_graph_rows(
            PROJECT,
            META,
            BLOCKS,
            annotations,
            {"tbl_0001": "assets/figures/tbl_0001.png"},
            exported_at="2026-11-04T01:02:03Z",
        )
        table = _figure_node(rows)
        self.assertEqual(table["label"], "表")
        self.assertEqual(table["name"], "表")

    def test_entity_attributes(self) -> None:
        entity = next(
            row
            for row in self.rows
            if row.get("record") == "node" and row["id"].endswith(":1")
        )
        self.assertEqual(entity["attributes"]["block_id"], "b0002")
        self.assertEqual(entity["attributes"]["page"], "1")

    def test_paragraph_node_uses_block_text(self) -> None:
        paragraph = next(
            row
            for row in self.rows
            if row.get("record") == "node" and row["id"] == f"par:{FILE_ID}:b0002"
        )
        self.assertEqual(paragraph["name"], "OD·JZ型端子应满足尺寸要求。")
        self.assertEqual(paragraph["label"], "尺寸")
        self.assertEqual(
            paragraph["attributes"]["text"], "OD·JZ型端子应满足尺寸要求。"
        )


class BuildAnnotationRowTests(unittest.TestCase):
    def setUp(self) -> None:
        figures = [dict(item) for item in ANNOTATIONS["figures"]]
        self.row = build_annotation_row(
            PROJECT,
            META,
            text=ANNOTATIONS["text"],
            spans=ANNOTATIONS["spans"],
            relations=ANNOTATIONS["relations"],
            paragraphs=ANNOTATIONS["paragraphs"],
            figures=figures,
            pages=BLOCKS["pages"],
            blocks=BLOCKS,
            source_rel="original/GBT 4423-2020.pdf",
            markdown_rel="markdown/GBT 4423-2020.md",
            updated_at="2026-11-04T00:00:00Z",
        )

    def test_legacy_fields_are_unchanged(self) -> None:
        self.assertEqual(self.row["file_name"], META["name"])
        self.assertEqual(self.row["text"], ANNOTATIONS["text"])
        self.assertEqual(self.row["relations"], ANNOTATIONS["relations"])
        self.assertEqual(self.row["source_file"], "GBT 4423-2020.pdf")
        self.assertEqual(self.row["markdown_file"], "GBT 4423-2020.md")
        self.assertEqual(self.row["updated_at"], "2026-11-04T00:00:00Z")

    def test_spans_keep_legacy_shape(self) -> None:
        self.assertEqual(
            set(self.row["spans"][0]),
            {"id", "start", "end", "label", "text"},
        )

    def test_paragraphs_are_enriched_from_blocks(self) -> None:
        self.assertEqual(
            self.row["paragraphs"][0],
            {
                "block_id": "b0002",
                "label": "尺寸",
                "note": "段注",
                "text": "OD·JZ型端子应满足尺寸要求。",
                "page": 1,
                "section_number": "1",
                "section_title": "范围",
            },
        )
        self.assertEqual(self.row["paragraphs"][1]["block_id"], "b0004")
        self.assertEqual(self.row["paragraphs"][1]["page"], 2)

    def test_figures_use_whitelisted_fields_only(self) -> None:
        figure = self.row["figures"][0]
        self.assertEqual(
            set(figure),
            {"id", "kind", "caption", "note", "page", "bbox", "asset_path"},
        )
        self.assertEqual(figure["id"], "fig_0001")
        self.assertEqual(figure["asset_path"], "assets/figures/fig_0001.png")
        self.assertNotIn("assetPath", figure)
        for field in LEGACY_FIGURE_FIELDS:
            self.assertNotIn(field, figure)

    def test_pages_are_trimmed(self) -> None:
        self.assertEqual(
            self.row["pages"],
            [
                {"page": 1, "width": 595.0, "height": 842.0},
                {"page": 2, "width": 595.0, "height": 842.0},
            ],
        )

    def test_meta_fields(self) -> None:
        meta = self.row["meta"]
        self.assertEqual(meta["export_version"], EXPORT_VERSION)
        self.assertEqual(meta["standard_id"], "GBT 4423-2020")
        self.assertEqual(meta["block_count"], 5)
        self.assertEqual(meta["paragraph_count"], 2)
        self.assertEqual(meta["figure_count"], 1)


class ExportStemTests(unittest.TestCase):
    def test_file_folder_uses_uploaded_stem_only(self) -> None:
        self.assertEqual(
            _file_folder({"id": FILE_ID, "name": "GBT 4423-2020.pdf"}),
            "GBT 4423-2020",
        )
        self.assertEqual(
            _file_folder({"id": FILE_ID, "name": "GBT+4423-2020.PDF"}),
            "GBT+4423-2020",
        )

    def test_duplicate_names_get_numeric_suffix(self) -> None:
        files = [
            {"id": "a", "name": "同名.pdf"},
            {"id": "b", "name": "同名.pdf"},
            {"id": "c", "name": "同名.pdf"},
        ]
        stems = _assign_export_stems(files)
        self.assertEqual(
            [stems["a"], stems["b"], stems["c"]],
            ["同名", "同名_2", "同名_3"],
        )

    def test_dedupe_is_case_insensitive(self) -> None:
        files = [
            {"id": "a", "name": "ABC.pdf"},
            {"id": "b", "name": "abc.pdf"},
        ]
        stems = _assign_export_stems(files)
        self.assertEqual([stems["a"], stems["b"]], ["ABC", "abc_2"])


class ExportZipNamingTests(unittest.TestCase):
    def setUp(self) -> None:
        # 每个测试使用独立项目，避免同一测试类内文件互相污染导出。
        self.project = storage.create_project("导出命名测试", [], [])

    def _new_file(self, name: str) -> dict:
        meta, source_target = storage.create_file(
            self.project["id"],
            name,
            ".pdf",
            source_type="pdf",
            enable_table=True,
            enable_formula=False,
            dpi=200,
        )
        source_target.write_bytes(b"%PDF-1.4 test")
        storage.save_markdown(meta["id"], "正文内容。")
        return meta

    def _export(self, destination: Path):
        path, download_name = build_export_zip(self.project["id"], destination)
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            rows = []
            if f"{download_name.removesuffix('.zip')}/annotations.jsonl" in names:
                content = archive.read(
                    f"{download_name.removesuffix('.zip')}/annotations.jsonl"
                ).decode("utf-8")
                rows = [json.loads(line) for line in content.splitlines() if line]
            manifest = json.loads(
                archive.read(
                    f"{download_name.removesuffix('.zip')}/manifest.json"
                ).decode("utf-8")
            )
        return names, rows, manifest

    def test_all_paths_have_no_internal_id_suffix(self) -> None:
        meta = self._new_file("GBT+4423-2020.pdf")
        storage.add_figure(meta["id"], {"kind": "figure", "page": 1,
                                        "bbox": [1, 2, 3, 4],
                                        "caption": "结构", "note": ""}, PNG)
        with tempfile.TemporaryDirectory() as temp_dir:
            names, rows, manifest = self._export(Path(temp_dir) / "export.zip")

        self.assertTrue(names)
        for name in names:
            self.assertIsNone(_LEGACY_ID_SUFFIX.search(name), name)

        prefix = "导出命名测试"
        self.assertIn(f"{prefix}/original/GBT+4423-2020.pdf", names)
        self.assertIn(f"{prefix}/markdown/GBT+4423-2020.md", names)
        self.assertIn(f"{prefix}/blocks/GBT+4423-2020.json", names)
        self.assertIn(
            f"{prefix}/assets/GBT+4423-2020/结构.png", names
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["source_file"], "GBT+4423-2020.pdf")
        self.assertEqual(row["markdown_file"], "GBT+4423-2020.md")
        self.assertEqual(row["source_path"], "original/GBT+4423-2020.pdf")
        self.assertEqual(row["markdown_path"], "markdown/GBT+4423-2020.md")
        self.assertEqual(row["figures"][0]["asset_path"],
                         "assets/GBT+4423-2020/结构.png")
        self.assertEqual(manifest["files"][0]["blocks"],
                         "blocks/GBT+4423-2020.json")

    def test_duplicate_file_names_share_same_deduped_stem(self) -> None:
        first = self._new_file("同名标准.pdf")
        second = self._new_file("同名标准.pdf")
        storage.add_figure(
            first["id"],
            {"kind": "table", "page": 1, "bbox": [1, 2, 3, 4],
             "caption": "参数表", "note": ""},
            PNG,
        )
        storage.save_markdown(second["id"], "第二份正文。")

        with tempfile.TemporaryDirectory() as temp_dir:
            names, rows, manifest = self._export(Path(temp_dir) / "export.zip")

        for name in names:
            self.assertIsNone(_LEGACY_ID_SUFFIX.search(name), name)

        prefix = "导出命名测试"
        self.assertIn(f"{prefix}/original/同名标准.pdf", names)
        self.assertIn(f"{prefix}/original/同名标准_2.pdf", names)
        self.assertIn(f"{prefix}/markdown/同名标准/同名标准.md", names)
        self.assertIn(f"{prefix}/markdown/同名标准_2/同名标准_2.md", names)
        self.assertIn(f"{prefix}/blocks/同名标准.json", names)
        self.assertIn(f"{prefix}/blocks/同名标准_2.json", names)

        by_file = {row["file_id"]: row for row in rows}
        self.assertEqual(set(by_file), {first["id"], second["id"]})
        for row in rows:
            source_path = row["source_path"]
            stem = Path(source_path).stem
            self.assertEqual(source_path, f"original/{stem}.pdf")
            self.assertEqual(row["source_file"], f"{stem}.pdf")
            self.assertEqual(row["markdown_file"], f"{stem}.md")
            self.assertEqual(
                row["markdown_path"], f"markdown/{stem}/{stem}.md"
            )
        first_row = by_file[first["id"]]
        self.assertEqual(
            first_row["figures"][0]["asset_path"],
            f"assets/{Path(first_row['source_path']).stem}/参数表.png",
        )
        manifest_by_file = {item["file_id"]: item for item in manifest["files"]}
        for file_id, item in manifest_by_file.items():
            stem = Path(item["source"]).stem
            self.assertEqual(item["blocks"], f"blocks/{stem}.json")
            self.assertEqual(item["markdown"], f"markdown/{stem}/{stem}.md")


class GraphEndpointTests(unittest.TestCase):
    """GET /api/projects/{project_id}/graph.jsonl 契约测试。

    该端点让知识库软件直接拉取图谱，不必下载整个 ZIP；因此返回内容
    必须与 ZIP 内 ``graph.jsonl`` 等价（仅 ``exported_at`` 因请求时间
    不同而不同）。
    """

    def setUp(self) -> None:
        self.project = storage.create_project("图谱拉取测试", [], [])
        self.meta, source_target = storage.create_file(
            self.project["id"],
            "GBT 4423-2020 紧固件.pdf",
            ".pdf",
            source_type="pdf",
            enable_table=True,
            enable_formula=False,
            dpi=200,
        )
        source_target.write_bytes(b"%PDF-1.4 test")
        storage.save_markdown(
            self.meta["id"],
            "# 1 范围\n\nOD·JZ型端子应满足尺寸要求。\n\nT2铜板用于导电部件。\n",
        )
        blocks = block_service.load_blocks(self.meta["id"])
        target = next(
            item for item in blocks["blocks"] if item["type"] == "paragraph"
        )
        self.block_id = target["id"]
        self.text = target["text"]
        storage.save_annotations(
            self.meta["id"],
            {
                "text": self.text,
                "spans": [
                    {
                        "id": 1,
                        "start": 0,
                        "end": len(self.text),
                        "label": "对象",
                        "text": self.text,
                        "blockId": self.block_id,
                    }
                ],
                "relations": [],
                "paragraphs": [
                    {"blockId": self.block_id, "label": "尺寸", "note": ""}
                ],
            },
        )

    def _client(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:  # pragma: no cover - 依赖缺失时跳过
            self.skipTest("未安装 FastAPI TestClient")

        import app as app_module

        return TestClient(app_module.app)

    def _fetch(self, project_id: str):
        return self._client().get(
            f"/api/projects/{project_id}/graph.jsonl"
        )

    @staticmethod
    def _parse_rows(response) -> list[dict]:
        content = response.content.decode("utf-8")
        return [json.loads(line) for line in content.splitlines() if line]

    @staticmethod
    def _without_exported_at(rows: list[dict]) -> list[dict]:
        return [
            {key: value for key, value in row.items() if key != "exported_at"}
            for row in rows
        ]

    def test_returns_ndjson_with_expected_records(self) -> None:
        response = self._fetch(self.project["id"])

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.headers["content-type"],
            "application/x-ndjson; charset=utf-8",
        )
        self.assertTrue(response.content.endswith(b"\n"))

        rows = self._parse_rows(response)
        self.assertEqual(rows[0]["record"], "meta")
        self.assertEqual(rows[0]["format"], EXPORT_VERSION)
        self.assertEqual(
            {row["record"] for row in rows}, {"meta", "node", "edge"}
        )
        # 1 document + 1 section + 1 annotated paragraph + 1 entity
        records = [row["record"] for row in rows]
        self.assertEqual(records.count("node"), 4)
        # doc→section + section→paragraph + entity→paragraph
        self.assertEqual(records.count("edge"), 3)

        node_ids = {row["id"] for row in rows if row["record"] == "node"}
        self.assertIn(f"par:{self.meta['id']}:{self.block_id}", node_ids)
        self.assertIn(f"ent:{self.meta['id']}:1", node_ids)
        edge = next(
            row
            for row in rows
            if row["record"] == "edge" and row["relation"] == "出现在"
        )
        self.assertEqual(edge["source"], f"ent:{self.meta['id']}:1")
        self.assertEqual(edge["target"], f"par:{self.meta['id']}:{self.block_id}")
        self.assertEqual(edge["kind"], "relation")

    def test_matches_graph_jsonl_inside_zip(self) -> None:
        endpoint_rows = self._parse_rows(self._fetch(self.project["id"]))

        with tempfile.TemporaryDirectory() as temp_dir:
            path, download_name = build_export_zip(
                self.project["id"], Path(temp_dir) / "export.zip"
            )
            with zipfile.ZipFile(path) as archive:
                content = archive.read(
                    f"{download_name.removesuffix('.zip')}/graph.jsonl"
                ).decode("utf-8")
        zip_rows = [
            json.loads(line) for line in content.splitlines() if line
        ]

        self.assertTrue(zip_rows)
        self.assertEqual(
            self._without_exported_at(endpoint_rows),
            self._without_exported_at(zip_rows),
        )

    def test_empty_project_returns_empty_body(self) -> None:
        project = storage.create_project("空图谱项目", [], [])
        response = self._fetch(project["id"])

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.headers["content-type"],
            "application/x-ndjson; charset=utf-8",
        )
        self.assertEqual(response.content, b"")

    def test_unannotated_file_still_exports_document_and_sections(self) -> None:
        project = storage.create_project("无标注图谱项目", [], [])
        meta, source_target = storage.create_file(
            project["id"],
            "未标注标准.pdf",
            ".pdf",
            source_type="pdf",
            enable_table=True,
            enable_formula=False,
            dpi=200,
        )
        source_target.write_bytes(b"%PDF-1.4 test")
        storage.save_markdown(meta["id"], "# 1 范围\n\n未标注段落。\n")

        response = self._fetch(project["id"])
        self.assertEqual(response.status_code, 200, response.text)
        rows = self._parse_rows(response)

        kinds = [
            row["kind"] for row in rows if row["record"] == "node"
        ]
        self.assertEqual(kinds, ["document", "section"])
        edges = [row for row in rows if row["record"] == "edge"]
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["relation"], "包含")

    def test_missing_project_returns_404(self) -> None:
        response = self._fetch("33333333-3333-3333-3333-333333333333")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "项目不存在")


if __name__ == "__main__":
    unittest.main()

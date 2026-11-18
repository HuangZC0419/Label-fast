"""图表截图资产按 caption 命名、重命名与迁移测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _env  # noqa: F401  # 必须在 config/storage 之前导入

import storage
from errors import BadRequestError, NotFoundError

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class FigureAssetNameTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="labelfast-figure-names-")
        root = Path(self._tmp.name)
        self.projects_dir = root / "projects"
        self.index_path = root / "projects.json"
        self._patchers = [
            mock.patch.object(storage, "PROJECTS_DIR", self.projects_dir),
            mock.patch.object(storage, "PROJECTS_INDEX_PATH", self.index_path),
            mock.patch.object(storage, "_FILE_DIR_CACHE", {}),
        ]
        for patcher in self._patchers:
            patcher.start()
        self.project = storage.create_project("图表资产命名测试", [], [])
        self.meta, _ = storage.create_file(
            self.project["id"],
            "doc.pdf",
            ".pdf",
            source_type="pdf",
            enable_table=True,
            enable_formula=False,
            dpi=200,
        )

    def tearDown(self) -> None:
        for patcher in reversed(self._patchers):
            patcher.stop()
        self._tmp.cleanup()

    # -- 工具 ---------------------------------------------------------

    def add_figure(
        self, caption: str, *, kind: str = "figure", page: int = 1
    ) -> dict:
        return storage.add_figure(
            self.meta["id"],
            {
                "kind": kind,
                "page": page,
                "bbox": [1, 2, 3, 4],
                "caption": caption,
                "note": "",
            },
            PNG,
        )

    def assets_dir(self) -> Path:
        return storage.figure_assets_dir(self.meta)

    def asset_names(self) -> list[str]:
        return sorted(
            child.name for child in self.assets_dir().iterdir() if child.is_file()
        )

    def annotations_raw(self) -> dict:
        return json.loads(
            (storage.file_dir(self.meta) / "annotations.json").read_text(
                encoding="utf-8"
            )
        )

    def write_legacy_annotations(self, figures: list[dict]) -> None:
        record = {
            "text": "",
            "spans": [],
            "relations": [],
            "paragraphs": [],
            "figures": figures,
            "updated_at": "2026-01-01T00:00:00Z",
        }
        (storage.file_dir(self.meta) / "annotations.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def legacy_figure(self, figure_id: str, caption: str, filename: str) -> dict:
        return {
            "id": figure_id,
            "kind": "table" if figure_id.startswith("tbl_") else "figure",
            "caption": caption,
            "note": "",
            "page": 1,
            "bbox": [1, 2, 3, 4],
            "assetPath": f"assets/figures/{filename}",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }

    def write_asset(self, filename: str) -> Path:
        self.assets_dir().mkdir(parents=True, exist_ok=True)
        path = self.assets_dir() / filename
        path.write_bytes(PNG)
        return path


class AddFigureTests(FigureAssetNameTestBase):
    def test_caption_becomes_asset_filename(self) -> None:
        figure = self.add_figure(
            "表1 不同公称纤维直径的断裂强度要求", kind="table"
        )

        self.assertEqual(figure["id"], "tbl_0001")
        self.assertEqual(
            figure["assetPath"],
            "assets/figures/表1 不同公称纤维直径的断裂强度要求.png",
        )
        asset = storage.resolve_figure_asset(
            self.meta["id"], "表1 不同公称纤维直径的断裂强度要求.png"
        )
        self.assertTrue(asset.is_file())

    def test_empty_caption_falls_back_to_figure_id(self) -> None:
        figure = self.add_figure("")
        table = self.add_figure("", kind="table")

        self.assertEqual(figure["assetPath"], "assets/figures/fig_0001.png")
        self.assertEqual(table["assetPath"], "assets/figures/tbl_0001.png")
        self.assertTrue(storage.resolve_figure_asset(
            self.meta["id"], "fig_0001.png"
        ).is_file())

    def test_duplicate_captions_get_suffix(self) -> None:
        first = self.add_figure("表1")
        second = self.add_figure("表1")
        third = self.add_figure("表1")

        self.assertEqual(
            [first["assetPath"], second["assetPath"], third["assetPath"]],
            [
                "assets/figures/表1.png",
                "assets/figures/表1 (2).png",
                "assets/figures/表1 (3).png",
            ],
        )
        self.assertEqual(self.asset_names(), ["表1 (2).png", "表1 (3).png", "表1.png"])
        # API 侧 id 仍保持不变。
        self.assertEqual([first["id"], second["id"], third["id"]],
                         ["fig_0001", "fig_0002", "fig_0003"])

    def test_caption_is_sanitized_and_truncated(self) -> None:
        reserved = self.add_figure("CON")

        self.assertEqual(reserved["assetPath"], "assets/figures/CON_.png")

    def test_illegal_characters_in_caption_are_replaced(self) -> None:
        figure = self.add_figure("表1/参数:单位*?")
        self.assertEqual(figure["assetPath"], "assets/figures/表1_参数_单位__.png")

    def test_long_caption_stem_is_truncated_to_80(self) -> None:
        figure = self.add_figure("长" * 120)
        filename = figure["assetPath"].rsplit("/", 1)[-1]
        self.assertEqual(len(filename.removesuffix(".png")), 80)
        self.assertTrue(filename.endswith(".png"))


class UpdateFigureTests(FigureAssetNameTestBase):
    def test_caption_change_renames_asset(self) -> None:
        figure = self.add_figure("旧标题")
        old_asset = storage.figure_asset_path(self.meta, figure["assetPath"])

        updated = storage.update_figure(
            self.meta["id"], figure["id"], {"caption": "新标题"}
        )

        self.assertEqual(updated["assetPath"], "assets/figures/新标题.png")
        self.assertFalse(old_asset.exists())
        self.assertTrue(
            storage.figure_asset_path(self.meta, updated["assetPath"]).is_file()
        )
        stored = storage.load_annotations(self.meta["id"])["figures"][0]
        self.assertEqual(stored["assetPath"], "assets/figures/新标题.png")
        self.assertEqual(stored["caption"], "新标题")

    def test_clearing_caption_restores_figure_id_name(self) -> None:
        figure = self.add_figure("图1")

        updated = storage.update_figure(
            self.meta["id"], figure["id"], {"caption": ""}
        )

        self.assertEqual(updated["assetPath"], "assets/figures/fig_0001.png")
        self.assertTrue(
            storage.resolve_figure_asset(self.meta["id"], "fig_0001.png").is_file()
        )

    def test_caption_collision_gets_suffix(self) -> None:
        first = self.add_figure("标题")
        second = self.add_figure("其他")

        updated = storage.update_figure(
            self.meta["id"], second["id"], {"caption": "标题"}
        )

        self.assertEqual(first["assetPath"], "assets/figures/标题.png")
        self.assertEqual(updated["assetPath"], "assets/figures/标题 (2).png")

    def test_note_change_does_not_rename_asset(self) -> None:
        figure = self.add_figure("图1")
        updated = storage.update_figure(
            self.meta["id"], figure["id"], {"note": "备注"}
        )
        self.assertEqual(updated["assetPath"], "assets/figures/图1.png")

    def test_rename_failure_keeps_old_asset_path_and_new_caption(self) -> None:
        figure = self.add_figure("旧标题")
        old_asset = storage.figure_asset_path(self.meta, figure["assetPath"])

        with mock.patch.object(
            storage, "_rename_file", side_effect=OSError("文件被占用")
        ):
            updated = storage.update_figure(
                self.meta["id"], figure["id"], {"caption": "新标题"}
            )

        self.assertEqual(updated["caption"], "新标题")
        self.assertEqual(updated["assetPath"], "assets/figures/旧标题.png")
        self.assertTrue(old_asset.is_file())
        self.assertFalse((self.assets_dir() / "新标题.png").exists())

    def test_missing_asset_keeps_old_path_without_error(self) -> None:
        figure = self.add_figure("旧标题")
        storage.figure_asset_path(self.meta, figure["assetPath"]).unlink()

        updated = storage.update_figure(
            self.meta["id"], figure["id"], {"caption": "新标题"}
        )

        self.assertEqual(updated["caption"], "新标题")
        self.assertEqual(updated["assetPath"], "assets/figures/旧标题.png")


class FigureAssetPathSafetyTests(FigureAssetNameTestBase):
    def test_resolve_accepts_chinese_and_rejects_traversal(self) -> None:
        figure = self.add_figure("表1 参数")
        name = figure["assetPath"].rsplit("/", 1)[-1]
        self.assertTrue(storage.resolve_figure_asset(self.meta["id"], name).is_file())

        for bad in (
            "../meta.json",
            "..\\meta.json",
            "/etc/passwd",
            ".hidden.png",
            "a/b.png",
            "a:b.png",
        ):
            with self.assertRaises(BadRequestError):
                storage.resolve_figure_asset(self.meta["id"], bad)
        with self.assertRaises(NotFoundError):
            storage.resolve_figure_asset(self.meta["id"], "missing.png")

    def test_figure_asset_path_rejects_unsafe_names(self) -> None:
        self.assertIsNone(
            storage.figure_asset_path(self.meta, "assets/figures/../x.png")
        )
        self.assertIsNone(
            storage.figure_asset_path(self.meta, "assets/figures/a:b.png")
        )
        self.assertIsNone(storage.figure_asset_path(self.meta, "other/x.png"))


class MigrateFigureAssetNamesTests(FigureAssetNameTestBase):
    def test_legacy_assets_are_renamed_and_paths_updated(self) -> None:
        self.write_asset("fig_0001.png")
        self.write_asset("fig_0002.png")
        self.write_legacy_annotations(
            [
                self.legacy_figure("fig_0001", "表1", "fig_0001.png"),
                self.legacy_figure("fig_0002", "表1", "fig_0002.png"),
            ]
        )

        migrated = storage.migrate_figure_asset_names()

        self.assertEqual(migrated, 2)
        self.assertEqual(self.asset_names(), ["表1 (2).png", "表1.png"])
        stored = self.annotations_raw()["figures"]
        self.assertEqual(
            [item["assetPath"] for item in stored],
            ["assets/figures/表1.png", "assets/figures/表1 (2).png"],
        )
        # 幂等：再次运行不产生移动。
        self.assertEqual(storage.migrate_figure_asset_names(), 0)
        self.assertEqual(self.asset_names(), ["表1 (2).png", "表1.png"])

    def test_empty_caption_keeps_figure_id_name(self) -> None:
        self.write_asset("fig_0001.png")
        self.write_legacy_annotations(
            [self.legacy_figure("fig_0001", "", "fig_0001.png")]
        )

        self.assertEqual(storage.migrate_figure_asset_names(), 0)
        self.assertEqual(self.asset_names(), ["fig_0001.png"])

    def test_missing_asset_is_skipped(self) -> None:
        self.write_legacy_annotations(
            [self.legacy_figure("fig_0001", "表1", "fig_0001.png")]
        )

        self.assertEqual(storage.migrate_figure_asset_names(), 0)
        self.assertEqual(
            self.annotations_raw()["figures"][0]["assetPath"],
            "assets/figures/fig_0001.png",
        )

    def test_single_failure_is_skipped_without_blocking_others(self) -> None:
        self.write_asset("fig_0001.png")
        self.write_asset("fig_0002.png")
        self.write_legacy_annotations(
            [
                self.legacy_figure("fig_0001", "表1", "fig_0001.png"),
                self.legacy_figure("fig_0002", "表2", "fig_0002.png"),
            ]
        )

        original_rename = storage._rename_file

        def flaky_rename(source: Path, target: Path) -> None:
            if source.name == "fig_0001.png":
                raise OSError("文件被占用")
            original_rename(source, target)

        with mock.patch.object(storage, "_rename_file", side_effect=flaky_rename):
            migrated = storage.migrate_figure_asset_names()

        self.assertEqual(migrated, 1)
        self.assertEqual(self.asset_names(), ["fig_0001.png", "表2.png"])
        stored = self.annotations_raw()["figures"]
        self.assertEqual(stored[0]["assetPath"], "assets/figures/fig_0001.png")
        self.assertEqual(stored[1]["assetPath"], "assets/figures/表2.png")

    def test_migration_preserves_record_ids(self) -> None:
        self.write_asset("tbl_0001.png")
        self.write_legacy_annotations(
            [self.legacy_figure("tbl_0001", "参数表", "tbl_0001.png")]
        )

        storage.migrate_figure_asset_names()

        figure = storage.list_figures(self.meta["id"])[0]
        self.assertEqual(figure["id"], "tbl_0001")
        self.assertEqual(figure["caption"], "参数表")
        self.assertEqual(figure["assetPath"], "assets/figures/参数表.png")
        self.assertFalse(figure["missing"])


if __name__ == "__main__":
    unittest.main()

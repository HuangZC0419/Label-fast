"""文件目录按显示名命名、路径解析与迁移测试。

所有用例使用独立临时项目目录，不触碰 ``backend/data``。
"""

from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

import _env  # noqa: F401  # 必须在 config/storage 之前导入

import storage
from errors import NotFoundError
from serializers import serialize_file


def _meta(
    project_id: str,
    file_id: str,
    name: str,
    *,
    created_at: str = "2026-01-01T00:00:00Z",
) -> dict:
    """构造旧版 UUID 文件目录所需的完整元数据。"""

    return {
        "id": file_id,
        "project_id": project_id,
        "name": name,
        "source_type": "pdf",
        "source_ext": "pdf",
        "source_filename": "source.pdf",
        "status": "uploaded",
        "progress": 0,
        "stage": "等待转换",
        "message": "",
        "error": "",
        "task_id": "",
        "conversion_token": "",
        "page_count": 0,
        "enable_table": True,
        "enable_formula": False,
        "dpi": 200,
        "queue_seq": 1,
        "queue_retry_count": 0,
        "created_at": created_at,
        "updated_at": created_at,
    }


class FileDirTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="labelfast-file-dirs-")
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
        self.project = storage.create_project("文件目录测试", [], [])

    def tearDown(self) -> None:
        for patcher in reversed(self._patchers):
            patcher.stop()
        self._tmp.cleanup()

    # -- 工具 ---------------------------------------------------------

    def project_dir(self) -> Path:
        return storage._project_dir(self.project["id"])

    def create_file(self, name: str) -> dict:
        meta, _ = storage.create_file(
            self.project["id"],
            name,
            ".pdf",
            source_type="pdf",
            enable_table=True,
            enable_formula=False,
            dpi=200,
        )
        return meta

    def write_legacy_file(self, name: str, file_id: str | None = None) -> tuple[dict, Path]:
        fid = str(uuid.UUID(file_id)) if file_id else str(uuid.uuid4())
        legacy_dir = self.project_dir() / "files" / fid
        (legacy_dir / "markdown" / "images").mkdir(parents=True)
        meta = _meta(self.project["id"], fid, name)
        (legacy_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return meta, legacy_dir

    def file_dir_names(self) -> list[str]:
        files_dir = self.project_dir() / "files"
        return sorted(
            child.name for child in files_dir.iterdir() if child.is_dir()
        )


class CreateFileDirTests(FileDirTestBase):
    def test_directory_uses_display_name_without_extension(self) -> None:
        meta = self.create_file("9 GB-T 18371-2008 连续玻璃纤维纱.pdf")

        self.assertEqual(
            storage.file_dir(meta).name, "9 GB-T 18371-2008 连续玻璃纤维纱"
        )
        self.assertEqual(
            storage.file_dir(meta),
            self.project_dir() / "files" / "9 GB-T 18371-2008 连续玻璃纤维纱",
        )
        self.assertEqual(
            meta["dir_name"], "9 GB-T 18371-2008 连续玻璃纤维纱"
        )
        # 内部字段不进入 API 响应。
        self.assertNotIn("dir_name", serialize_file(meta))
        self.assertTrue(storage.source_path(meta).parent.is_dir())

    def test_illegal_characters_are_sanitized(self) -> None:
        meta = self.create_file('a<b>c:d"e|f?g* .pdf')
        self.assertEqual(storage.file_dir(meta).name, "a_b_c_d_e_f_g_")

    def test_windows_reserved_names_get_suffix(self) -> None:
        con = self.create_file("CON.pdf")
        with_extension = self.create_file("con.txt.pdf")

        self.assertEqual(storage.file_dir(con).name, "CON_")
        self.assertEqual(storage.file_dir(with_extension).name, "con.txt_")

    def test_long_name_is_truncated_to_80(self) -> None:
        meta = self.create_file("长" * 120 + ".pdf")
        self.assertEqual(len(storage.file_dir(meta).name), 80)

    def test_empty_name_falls_back_to_file_id_prefix(self) -> None:
        meta = self.create_file("")
        self.assertEqual(
            storage.file_dir(meta).name, f"文件-{meta['id'][:8]}"
        )

    def test_duplicate_names_get_numeric_suffix(self) -> None:
        first = self.create_file("同名文件.pdf")
        second = self.create_file("同名文件.pdf")
        third = self.create_file("同名文件.pdf")

        self.assertEqual(
            self.file_dir_names(), ["同名文件", "同名文件 (2)", "同名文件 (3)"]
        )
        self.assertEqual(
            {first["dir_name"], second["dir_name"], third["dir_name"]},
            {"同名文件", "同名文件 (2)", "同名文件 (3)"},
        )

    def test_duplicate_names_are_case_insensitive(self) -> None:
        first = self.create_file("Doc.pdf")
        second = self.create_file("doc.pdf")

        self.assertEqual(storage.file_dir(first).name, "Doc")
        self.assertEqual(storage.file_dir(second).name, "doc (2)")

    def test_read_and_delete_by_file_id(self) -> None:
        meta = self.create_file("可读目录.pdf")
        file_dir = storage.file_dir(meta)
        storage.save_markdown(meta["id"], "# 标题\n")

        self.assertEqual(storage.get_file(meta["id"])["name"], "可读目录.pdf")
        self.assertTrue((file_dir / "markdown" / "result.md").is_file())

        storage.delete_file(meta["id"])
        self.assertFalse(file_dir.exists())
        with self.assertRaises(NotFoundError):
            storage.get_file(meta["id"])

    def test_project_rename_keeps_file_directory_resolvable(self) -> None:
        meta = self.create_file("稳定文件.pdf")
        storage.save_markdown(meta["id"], "正文")

        storage.update_project(self.project["id"], {"name": "新项目名"})

        self.assertEqual(storage.get_file(meta["id"])["dir_name"], "稳定文件")
        self.assertEqual(storage.file_dir(meta).name, "稳定文件")
        self.assertEqual(storage.read_markdown(meta["id"]), "正文")


class LegacyFileDirTests(FileDirTestBase):
    def test_uuid_directory_still_resolves_before_migration(self) -> None:
        meta, legacy_dir = self.write_legacy_file("旧版文件.pdf")

        self.assertEqual(storage._find_meta_path(meta["id"]), legacy_dir / "meta.json")
        self.assertEqual(storage.file_dir(meta), legacy_dir)
        self.assertEqual(
            storage.source_path(meta), legacy_dir / "source.pdf"
        )

        storage.save_markdown(meta["id"], "旧目录正文")
        self.assertTrue((legacy_dir / "markdown" / "result.md").is_file())

    def test_find_meta_path_scans_named_directories_without_cache(self) -> None:
        meta = self.create_file("缓存失效.pdf")
        storage._FILE_DIR_CACHE.clear()

        path = storage._find_meta_path(meta["id"])
        self.assertEqual(path, storage.file_dir(meta) / "meta.json")
        # 扫描后回填缓存。
        self.assertIn(meta["id"], storage._FILE_DIR_CACHE)


class MigrateFileDirsTests(FileDirTestBase):
    def test_uuid_directories_migrate_to_names_and_are_idempotent(self) -> None:
        first, first_dir = self.write_legacy_file("同名标准.pdf")
        second, second_dir = self.write_legacy_file("同名标准.pdf")

        migrated = storage.migrate_file_dirs()

        self.assertEqual(migrated, 2)
        self.assertFalse(first_dir.exists())
        self.assertFalse(second_dir.exists())
        self.assertEqual(
            self.file_dir_names(), ["同名标准", "同名标准 (2)"]
        )
        self.assertEqual(
            {storage.get_file(first["id"])["dir_name"],
             storage.get_file(second["id"])["dir_name"]},
            {"同名标准", "同名标准 (2)"},
        )
        self.assertEqual(
            {storage._find_meta_path(first["id"]).parent.name,
             storage._find_meta_path(second["id"]).parent.name},
            {"同名标准", "同名标准 (2)"},
        )

        self.assertEqual(storage.migrate_file_dirs(), 0)
        self.assertEqual(storage.migrate_file_dirs(), 0)

    def test_migration_writes_dir_name_for_already_named_directory(self) -> None:
        meta, legacy_dir = self.write_legacy_file("已命名的文件.pdf")
        named_dir = legacy_dir.parent / "已命名的文件"
        legacy_dir.rename(named_dir)

        self.assertEqual(storage.migrate_file_dirs(), 0)

        stored = json.loads(
            (named_dir / "meta.json").read_text(encoding="utf-8")
        )
        self.assertEqual(stored["dir_name"], "已命名的文件")
        self.assertEqual(storage._find_meta_path(meta["id"]), named_dir / "meta.json")

    def test_single_failure_is_skipped_without_blocking_others(self) -> None:
        failing, failing_dir = self.write_legacy_file("占用文件.pdf")
        healthy, _ = self.write_legacy_file("正常文件.pdf")

        original_rename = storage._rename_dir

        def flaky_rename(source: Path, target: Path) -> None:
            if source.name == failing["id"]:
                raise PermissionError("目录被占用")
            original_rename(source, target)

        with mock.patch.object(storage, "_rename_dir", side_effect=flaky_rename):
            migrated = storage.migrate_file_dirs()

        self.assertEqual(migrated, 1)
        self.assertTrue(failing_dir.is_dir())
        self.assertFalse((failing_dir.parent / "占用文件.pdf").exists())
        self.assertTrue((failing_dir.parent / "正常文件").is_dir())
        # 失败目录仍可按 id 访问。
        self.assertEqual(storage.file_dir(failing), failing_dir)
        self.assertEqual(storage.get_file(failing["id"])["name"], "占用文件.pdf")

    def test_case_only_difference_is_not_renamed(self) -> None:
        meta, legacy_dir = self.write_legacy_file("Report.pdf")
        named_dir = legacy_dir.parent / "report"
        legacy_dir.rename(named_dir)

        self.assertEqual(storage.migrate_file_dirs(), 0)
        self.assertTrue(named_dir.is_dir())
        self.assertEqual(storage.file_dir(storage.get_file(meta["id"])), named_dir)


if __name__ == "__main__":
    unittest.main()

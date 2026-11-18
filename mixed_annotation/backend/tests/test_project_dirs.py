"""项目目录命名、重命名、删除与旧 UUID 目录迁移测试。

所有用例把 ``storage.PROJECTS_DIR`` / ``storage.PROJECTS_INDEX_PATH``
指向独立临时目录，避免与其它测试模块共享索引状态。
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


class ProjectDirTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="labelfast-project-dirs-")
        root = Path(self._tmp.name)
        self.projects_dir = root / "projects"
        self.index_path = root / "projects.json"
        self._patchers = [
            mock.patch.object(storage, "PROJECTS_DIR", self.projects_dir),
            mock.patch.object(storage, "PROJECTS_INDEX_PATH", self.index_path),
        ]
        for patcher in self._patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self._patchers):
            patcher.stop()
        self._tmp.cleanup()

    # -- 测试数据工具 -------------------------------------------------

    def _write_legacy_project(
        self,
        name: str,
        project_id: str | None = None,
        labels: list[str] | None = None,
        relation_types: list[str] | None = None,
    ) -> tuple[dict, Path]:
        pid = project_id or str(uuid.uuid4())
        project = {
            "id": pid,
            "name": name,
            "labels": labels or [],
            "relation_types": relation_types or [],
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        legacy_dir = self.projects_dir / pid
        (legacy_dir / "files").mkdir(parents=True, exist_ok=True)
        (legacy_dir / "project.json").write_text(
            json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return project, legacy_dir

    def _write_index(self, projects: list[dict]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps({"projects": projects}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _read_index(self) -> list[dict]:
        if not self.index_path.is_file():
            return []
        data = json.loads(self.index_path.read_text(encoding="utf-8"))
        return data.get("projects", [])


class CreateProjectDirTests(ProjectDirTestBase):
    def test_directory_uses_project_name(self) -> None:
        project = storage.create_project("工艺文件", ["工艺"], ["包含"])

        self.assertEqual(project["id"], str(uuid.UUID(project["id"])))
        project_dir = self.projects_dir / "工艺文件"
        self.assertTrue((project_dir / "project.json").is_file())
        self.assertTrue((project_dir / "files").is_dir())
        self.assertNotIn("dir_name", project)
        self.assertEqual(storage._project_dir(project["id"]), project_dir)

        records = self._read_index()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["dir_name"], "工艺文件")
        # API 输出不暴露内部 dir_name，id 仍为 UUID。
        self.assertNotIn("dir_name", storage.list_projects()[0])
        self.assertNotIn("dir_name", storage.get_project(project["id"]))

    def test_duplicate_names_get_numeric_suffix(self) -> None:
        first = storage.create_project("同名项目", [], [])
        second = storage.create_project("同名项目", [], [])
        third = storage.create_project("同名项目", [], [])

        dirs = sorted(
            path.name
            for path in self.projects_dir.iterdir()
            if path.is_dir()
        )
        self.assertEqual(dirs, ["同名项目", "同名项目 (2)", "同名项目 (3)"])
        self.assertEqual(
            {item["dir_name"] for item in self._read_index()},
            {"同名项目", "同名项目 (2)", "同名项目 (3)"},
        )
        self.assertEqual(
            {first["id"], second["id"], third["id"]},
            {item["id"] for item in self._read_index()},
        )

    def test_sanitizes_illegal_characters_and_trailing_dots(self) -> None:
        project = storage.create_project('a<b>c:d"e/f\\g|h?i*j. ', [], [])
        self.assertEqual(
            storage._project_dir(project["id"]).name,
            "a_b_c_d_e_f_g_h_i_j",
        )

    def test_preserves_chinese_and_trims_spaces(self) -> None:
        project = storage.create_project("  中文项目名称  ", [], [])
        self.assertEqual(storage._project_dir(project["id"]).name, "中文项目名称")

    def test_windows_reserved_name_gets_suffix(self) -> None:
        plain = storage.create_project("CON", [], [])
        with_extension = storage.create_project("con.txt", [], [])
        com = storage.create_project("COM1", [], [])

        self.assertEqual(storage._project_dir(plain["id"]).name, "CON_")
        self.assertEqual(
            storage._project_dir(with_extension["id"]).name, "con.txt_"
        )
        self.assertEqual(storage._project_dir(com["id"]).name, "COM1_")

    def test_empty_name_falls_back_to_project_id_prefix(self) -> None:
        project = storage.create_project("", [], [])
        dir_name = storage._project_dir(project["id"]).name
        self.assertEqual(dir_name, f"项目-{project['id'][:8]}")

    def test_long_name_is_truncated_to_80(self) -> None:
        project = storage.create_project("长" * 120, [], [])
        self.assertEqual(len(storage._project_dir(project["id"]).name), 80)

    def test_create_failure_cleans_directory_and_index(self) -> None:
        with mock.patch.object(
            storage, "_atomic_write_json", side_effect=OSError("磁盘不可写")
        ):
            with self.assertRaises(OSError):
                storage.create_project("创建失败项目", [], [])

        self.assertFalse((self.projects_dir / "创建失败项目").exists())
        self.assertEqual(self._read_index(), [])


class RenameProjectDirTests(ProjectDirTestBase):
    def _create_project_with_file(self, name: str) -> tuple[dict, dict]:
        project = storage.create_project(name, ["标"], ["关系"])
        meta, _ = storage.create_file(
            project["id"],
            "文档.pdf",
            ".pdf",
            source_type="pdf",
            enable_table=True,
            enable_formula=False,
            dpi=200,
        )
        storage.save_markdown(meta["id"], "# 标题\n\n正文\n")
        storage.save_annotations(
            meta["id"],
            {"text": "正文", "spans": [], "relations": [], "paragraphs": []},
        )
        return project, meta

    def test_rename_moves_directory_and_keeps_data_readable(self) -> None:
        project, meta = self._create_project_with_file("旧名称")
        old_dir = storage._project_dir(project["id"])

        updated = storage.update_project(project["id"], {"name": "新名称"})

        new_dir = self.projects_dir / "新名称"
        self.assertFalse(old_dir.exists())
        self.assertTrue((new_dir / "project.json").is_file())
        self.assertEqual(updated["name"], "新名称")
        self.assertEqual(updated["id"], project["id"])
        self.assertEqual(storage._project_dir(project["id"]), new_dir)

        project_json = json.loads(
            (new_dir / "project.json").read_text(encoding="utf-8")
        )
        self.assertEqual(project_json["name"], "新名称")

        records = self._read_index()
        self.assertEqual(records[0]["name"], "新名称")
        self.assertEqual(records[0]["dir_name"], "新名称")

        # 文件与标注仍通过不变的 UUID 访问。
        self.assertEqual(storage.get_file(meta["id"])["project_id"], project["id"])
        self.assertEqual(storage.load_annotations(meta["id"])["text"], "正文")
        self.assertEqual(
            storage.read_markdown(meta["id"]), "# 标题\n\n正文\n"
        )

    def test_rename_collision_gets_suffix(self) -> None:
        first = storage.create_project("目标名称", [], [])
        second = storage.create_project("另一个名称", [], [])

        storage.update_project(second["id"], {"name": "目标名称"})

        self.assertEqual(
            storage._project_dir(first["id"]).name, "目标名称"
        )
        self.assertEqual(
            storage._project_dir(second["id"]).name, "目标名称 (2)"
        )
        names = {item["id"]: item["dir_name"] for item in self._read_index()}
        self.assertEqual(names[first["id"]], "目标名称")
        self.assertEqual(names[second["id"]], "目标名称 (2)")

    def test_updating_labels_does_not_move_directory(self) -> None:
        project = storage.create_project("固定名称", [], [])
        before = storage._project_dir(project["id"])

        storage.update_project(
            project["id"], {"labels": ["新标签"], "relation_types": ["新关系"]}
        )

        self.assertEqual(storage._project_dir(project["id"]), before)
        self.assertTrue(before.is_dir())
        self.assertFalse((self.projects_dir / "固定名称 (2)").exists())

    def test_rename_failure_keeps_old_directory_and_metadata(self) -> None:
        project = storage.create_project("原目录", [], [])
        old_dir = storage._project_dir(project["id"])

        with mock.patch.object(
            storage, "_rename_dir", side_effect=PermissionError("目录被占用")
        ):
            with self.assertRaises(Exception):
                storage.update_project(project["id"], {"name": "新目录"})

        self.assertTrue(old_dir.is_dir())
        self.assertFalse((self.projects_dir / "新目录").exists())
        self.assertEqual(storage.get_project(project["id"])["name"], "原目录")
        self.assertEqual(
            self._read_index()[0]["dir_name"], "原目录"
        )


class DeleteProjectDirTests(ProjectDirTestBase):
    def test_delete_removes_named_directory(self) -> None:
        project = storage.create_project("待删除项目", [], [])
        project_dir = storage._project_dir(project["id"])
        (project_dir / "marker.txt").write_text("x", encoding="utf-8")

        storage.delete_project(project["id"])

        self.assertFalse(project_dir.exists())
        self.assertEqual(self._read_index(), [])
        with self.assertRaises(NotFoundError):
            storage.get_project(project["id"])


class MigrateProjectDirsTests(ProjectDirTestBase):
    def test_uuid_directory_migrates_to_name_directory(self) -> None:
        project, legacy_dir = self._write_legacy_project(
            "旧项目", labels=["实体"], relation_types=["关系"]
        )
        self._write_index([dict(project)])

        migrated = storage.migrate_project_dirs()

        self.assertEqual(migrated, 1)
        new_dir = self.projects_dir / "旧项目"
        self.assertFalse(legacy_dir.exists())
        self.assertTrue((new_dir / "project.json").is_file())
        records = self._read_index()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["id"], project["id"])
        self.assertEqual(records[0]["dir_name"], "旧项目")
        self.assertEqual(storage._project_dir(project["id"]), new_dir)
        self.assertEqual(storage.get_project(project["id"])["name"], "旧项目")

    def test_migration_is_idempotent(self) -> None:
        project, _ = self._write_legacy_project("幂等项目")
        self._write_index([dict(project)])

        self.assertEqual(storage.migrate_project_dirs(), 1)
        index_after_first = self.index_path.read_text(encoding="utf-8")
        self.assertEqual(storage.migrate_project_dirs(), 0)
        self.assertEqual(
            self.index_path.read_text(encoding="utf-8"), index_after_first
        )
        self.assertEqual(
            [
                path.name
                for path in self.projects_dir.iterdir()
                if path.is_dir()
            ],
            ["幂等项目"],
        )

    def test_duplicate_names_get_suffix_during_migration(self) -> None:
        first, _ = self._write_legacy_project("重名项目")
        second, _ = self._write_legacy_project("重名项目")
        self._write_index([dict(first), dict(second)])

        migrated = storage.migrate_project_dirs()

        self.assertEqual(migrated, 2)
        dirs = sorted(
            path.name
            for path in self.projects_dir.iterdir()
            if path.is_dir()
        )
        self.assertEqual(dirs, ["重名项目", "重名项目 (2)"])
        names = {item["id"]: item["dir_name"] for item in self._read_index()}
        self.assertEqual(
            set(names.values()), {"重名项目", "重名项目 (2)"}
        )
        self.assertEqual(
            {storage._project_dir(first["id"]).name, storage._project_dir(second["id"]).name},
            {"重名项目", "重名项目 (2)"},
        )

    def test_single_failure_is_skipped_without_blocking_others(self) -> None:
        failing, failing_dir = self._write_legacy_project("占用项目")
        healthy, _ = self._write_legacy_project("正常项目")
        self._write_index([dict(failing), dict(healthy)])

        original_rename = storage._rename_dir

        def flaky_rename(source: Path, target: Path) -> None:
            if source.name == failing["id"]:
                raise PermissionError("文件被占用")
            original_rename(source, target)

        with mock.patch.object(storage, "_rename_dir", side_effect=flaky_rename):
            migrated = storage.migrate_project_dirs()

        self.assertEqual(migrated, 1)
        self.assertTrue(failing_dir.is_dir())
        self.assertTrue((self.projects_dir / "正常项目").is_dir())
        self.assertFalse((self.projects_dir / "占用项目").exists())
        self.assertEqual(
            storage._project_dir(failing["id"]), failing_dir
        )
        self.assertEqual(storage.get_project(failing["id"])["name"], "占用项目")
        self.assertEqual(storage.get_project(healthy["id"])["name"], "正常项目")

    def test_missing_index_entry_is_added_from_project_json(self) -> None:
        project, _ = self._write_legacy_project(
            "补录项目", labels=["实体"], relation_types=["包含"]
        )
        self._write_index([])

        migrated = storage.migrate_project_dirs()

        self.assertEqual(migrated, 1)
        records = self._read_index()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["id"], project["id"])
        self.assertEqual(record["name"], "补录项目")
        self.assertEqual(record["labels"], ["实体"])
        self.assertEqual(record["relation_types"], ["包含"])
        self.assertEqual(record["created_at"], project["created_at"])
        self.assertEqual(record["updated_at"], project["updated_at"])
        self.assertEqual(record["dir_name"], "补录项目")

    def test_legacy_uuid_fallback_when_index_has_no_dir_name(self) -> None:
        project, legacy_dir = self._write_legacy_project("回退项目")
        self._write_index([dict(project)])

        self.assertEqual(storage._project_dir(project["id"]), legacy_dir)
        self.assertEqual(storage.get_project(project["id"])["name"], "回退项目")

    def test_migration_ignores_non_project_directories(self) -> None:
        orphan = self.projects_dir / "orphan"
        orphan.mkdir(parents=True)
        (orphan / "keep.txt").write_text("keep", encoding="utf-8")

        self.assertEqual(storage.migrate_project_dirs(), 0)

        self.assertTrue((orphan / "keep.txt").is_file())


if __name__ == "__main__":
    unittest.main()

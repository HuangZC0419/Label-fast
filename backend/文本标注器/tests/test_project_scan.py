"""project_scan_service 的单元测试。

每个用例使用临时目录中的独立 SQLite 文件，通过自定义 session_factory
注入扫描服务，避免触碰真实数据库与真实 projects 目录。
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ..services import project_scan_service
from ..services.project_scan_service import scan_projects_directory
from ..storage.db import Base
from ..storage.schema import Document, Project

TEXT_A = (
    "这是用于扫描测试的第一段中文内容。新发现的项目文件夹应当被注册，"
    "其中的文本文件会作为待标注文档导入数据库。"
)
TEXT_B = (
    "这是另一段完全不同的中文内容，用于验证同一个项目可以导入多个文本文件，"
    "并且每份文件只生成一条文档记录。"
)


class ProjectScanTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_root = Path(self._tmpdir.name)
        self.projects_root = self.tmp_root / "projects"
        self.projects_root.mkdir()

        db_path = self.tmp_root / "test.db"
        self.engine = create_engine("sqlite:///" + db_path.as_posix(), future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
        # 需要在清理临时目录前先解除 junction，避免 rmtree 递归到目标目录
        self._junction_links = []

    def tearDown(self) -> None:
        for link in self._junction_links:
            try:
                os.rmdir(link)
            except OSError:
                pass
        self.engine.dispose()
        self._tmpdir.cleanup()

    def _scan(self, root=None) -> dict:
        return scan_projects_directory(
            str(root if root is not None else self.projects_root),
            self.Session,
        )

    def _write_import(
        self, project_name: str, filename: str, content: str, encoding: str = "utf-8"
    ) -> Path:
        imports_dir = self.projects_root / project_name / "imports"
        imports_dir.mkdir(parents=True, exist_ok=True)
        path = imports_dir / filename
        path.write_text(content, encoding=encoding)
        return path

    def _create_project(self, name: str, text: str = None, status: str = "done") -> None:
        with self.Session() as session:
            project = Project(
                name=name,
                labels=[],
                relation_types=[],
                allow_overlap=0,
            )
            session.add(project)
            session.flush()
            if text is not None:
                session.add(
                    Document(
                        project_id=project.id,
                        text=text,
                        status=status,
                        source_file=None,
                        unit_index=0,
                    )
                )
            session.commit()

    def _all_projects(self) -> list:
        with self.Session() as session:
            return list(session.execute(select(Project)).scalars().all())

    def _all_documents(self) -> list:
        with self.Session() as session:
            return list(session.execute(select(Document)).scalars().all())

    def _assert_empty_summary(self, result: dict) -> None:
        self.assertEqual(result["created_projects"], [])
        self.assertEqual(result["imported_documents"], 0)
        self.assertEqual(result["skipped_documents"], 0)
        self.assertEqual(result["existing_projects"], 0)
        self.assertEqual(result["errors"], [])

    def test_empty_directory_creates_nothing(self) -> None:
        result = self._scan()

        self._assert_empty_summary(result)
        self.assertEqual(self._all_projects(), [])

    def test_imports_txt_creates_project_and_document(self) -> None:
        txt_path = self._write_import("测试项目", "a.txt", TEXT_A)

        result = self._scan()

        self.assertEqual(result["created_projects"], ["测试项目"])
        self.assertEqual(result["imported_documents"], 1)
        self.assertEqual(result["skipped_documents"], 0)
        self.assertEqual(result["existing_projects"], 0)
        self.assertEqual(result["errors"], [])

        projects = self._all_projects()
        self.assertEqual(len(projects), 1)
        project = projects[0]
        self.assertEqual(project.name, "测试项目")
        self.assertEqual(project.labels, [])
        self.assertEqual(project.relation_types, [])
        self.assertEqual(project.allow_overlap, 0)

        documents = self._all_documents()
        self.assertEqual(len(documents), 1)
        document = documents[0]
        self.assertEqual(document.project_id, project.id)
        self.assertEqual(document.text, TEXT_A)
        self.assertEqual(document.status, "pending")
        self.assertEqual(
            os.path.normcase(document.source_file),
            os.path.normcase(os.path.abspath(txt_path)),
        )
        self.assertEqual(document.unit_index, 0)

    def test_repeated_scan_is_idempotent(self) -> None:
        self._write_import("重复扫描项目", "a.txt", TEXT_A)

        first = self._scan()
        second = self._scan()

        self.assertEqual(first["created_projects"], ["重复扫描项目"])
        self.assertEqual(first["imported_documents"], 1)
        self.assertEqual(first["existing_projects"], 0)

        self.assertEqual(second["created_projects"], [])
        self.assertEqual(second["imported_documents"], 0)
        self.assertEqual(second["skipped_documents"], 0)
        self.assertEqual(second["existing_projects"], 1)
        self.assertEqual(second["errors"], [])

        self.assertEqual(len(self._all_projects()), 1)
        self.assertEqual(len(self._all_documents()), 1)

    def test_two_txt_files_create_two_documents(self) -> None:
        self._write_import("多文件项目", "a.txt", TEXT_A)
        # 扩展名大写也应被识别
        self._write_import("多文件项目", "b.TXT", TEXT_B)
        # 纯空白文件应被跳过，不产生文档
        self._write_import("多文件项目", "blank.txt", "   \n\t\n")

        result = self._scan()

        self.assertEqual(result["created_projects"], ["多文件项目"])
        self.assertEqual(result["imported_documents"], 2)
        self.assertEqual(result["skipped_documents"], 0)
        self.assertEqual(result["errors"], [])

        documents = self._all_documents()
        self.assertEqual(len(documents), 2)
        self.assertEqual({d.text for d in documents}, {TEXT_A, TEXT_B})

    def test_skips_pycache_and_hidden_directories(self) -> None:
        self._write_import("__pycache__", "cache.txt", TEXT_A)
        self._write_import(".hidden", "hidden.txt", TEXT_B)
        self._write_import("可见项目", "visible.txt", TEXT_A)

        result = self._scan()

        self.assertEqual(result["created_projects"], ["可见项目"])
        self.assertEqual(result["imported_documents"], 1)
        self.assertEqual(result["existing_projects"], 0)
        self.assertEqual([p.name for p in self._all_projects()], ["可见项目"])
        self.assertEqual(len(self._all_documents()), 1)

    def test_existing_project_with_same_text_is_not_imported_again(self) -> None:
        self._create_project("已有项目", text=TEXT_A)
        self._write_import("已有项目", "a.txt", TEXT_A)

        result = self._scan()

        self.assertEqual(result["created_projects"], [])
        self.assertEqual(result["imported_documents"], 0)
        self.assertEqual(result["skipped_documents"], 0)
        self.assertEqual(result["existing_projects"], 1)
        self.assertEqual(result["errors"], [])

        documents = self._all_documents()
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].status, "done")

    def test_existing_project_folder_without_documents_is_not_imported(self) -> None:
        """既有项目即使库里没有文档，也不会因文件夹存在而补导。"""
        self._create_project("空文档项目")
        self._write_import("空文档项目", "a.txt", TEXT_A)

        result = self._scan()

        self.assertEqual(result["created_projects"], [])
        self.assertEqual(result["imported_documents"], 0)
        self.assertEqual(result["skipped_documents"], 0)
        self.assertEqual(result["existing_projects"], 1)
        self.assertEqual(result["errors"], [])

        self.assertEqual(len(self._all_projects()), 1)
        self.assertEqual(self._all_documents(), [])

    def test_sanitized_directory_does_not_create_ghost_project(self) -> None:
        """项目名 `测试（一）` 映射到目录 `测试一`，不得再建同名幽灵项目。"""
        self._create_project("测试（一）")
        self._write_import("测试一", "a.txt", TEXT_A)

        result = self._scan()

        self.assertEqual(result["created_projects"], [])
        self.assertEqual(result["imported_documents"], 0)
        self.assertEqual(result["existing_projects"], 1)
        self.assertEqual(result["errors"], [])

        projects = self._all_projects()
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].name, "测试（一）")
        self.assertEqual(self._all_documents(), [])

    def test_same_text_in_two_new_projects_is_imported_twice(self) -> None:
        self._write_import("项目甲", "a.txt", TEXT_A)
        self._write_import("项目乙", "a.txt", TEXT_A)

        result = self._scan()

        self.assertEqual(set(result["created_projects"]), {"项目甲", "项目乙"})
        self.assertEqual(result["imported_documents"], 2)
        self.assertEqual(result["skipped_documents"], 0)
        self.assertEqual(result["errors"], [])

        documents = self._all_documents()
        self.assertEqual(len(documents), 2)
        self.assertEqual({d.text for d in documents}, {TEXT_A})

    def test_duplicate_text_within_new_project_is_skipped(self) -> None:
        self._write_import("重复文本项目", "a.txt", TEXT_A)
        self._write_import("重复文本项目", "b.txt", TEXT_A)

        result = self._scan()

        self.assertEqual(result["created_projects"], ["重复文本项目"])
        self.assertEqual(result["imported_documents"], 1)
        self.assertEqual(result["skipped_documents"], 1)
        self.assertEqual(result["errors"], [])

        self.assertEqual(len(self._all_documents()), 1)

    def test_mixed_files_continue_after_read_error(self) -> None:
        # utf-8-sig 会写入 BOM，验证 BOM 去除后仍按空白文件跳过
        self._write_import("混合项目", "blank.txt", "   \n\t\n", encoding="utf-8-sig")
        self._write_import("混合项目", "broken.txt", "无法读取的内容")
        self._write_import("混合项目", "normal.txt", TEXT_A)

        real_read_file_text = project_scan_service.read_file_text

        def fake_read_file_text(path: str) -> str:
            if os.path.basename(path) == "broken.txt":
                raise RuntimeError("模拟读取失败")
            return real_read_file_text(path)

        with mock.patch.object(
            project_scan_service, "read_file_text", side_effect=fake_read_file_text
        ):
            result = self._scan()

        self.assertEqual(result["created_projects"], ["混合项目"])
        self.assertEqual(result["imported_documents"], 1)
        self.assertEqual(result["skipped_documents"], 0)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("混合项目/broken.txt", result["errors"][0])
        self.assertIn("RuntimeError", result["errors"][0])

        documents = self._all_documents()
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].text, TEXT_A)

    def test_is_link_or_junction_returns_false_for_regular_directory(self) -> None:
        regular_dir = self.projects_root / "普通目录"
        regular_dir.mkdir()

        self.assertFalse(
            project_scan_service._is_link_or_junction(str(regular_dir))
        )
        self.assertFalse(
            project_scan_service._is_link_or_junction(str(self.projects_root))
        )

    @unittest.skipUnless(os.name == "nt", "Windows junction 测试仅在 Windows 下运行")
    def test_windows_junction_is_skipped(self) -> None:
        target = self.tmp_root / "junction_target"
        target.mkdir()
        link = self.projects_root / "junction_project"

        try:
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            self.skipTest(f"当前系统无法创建 junction: {exc.stderr or exc}")

        self._junction_links.append(link)
        self.assertTrue(project_scan_service._is_link_or_junction(str(link)))

        result = self._scan()

        self.assertEqual(result["created_projects"], [])
        self.assertEqual(result["imported_documents"], 0)
        self.assertEqual(result["existing_projects"], 0)
        self.assertEqual(result["errors"], [])
        self.assertEqual(self._all_projects(), [])

    def test_invalid_projects_root_returns_empty_summary(self) -> None:
        missing_root = self.tmp_root / "missing_root"
        missing_result = self._scan(missing_root)
        self._assert_empty_summary(missing_result)

        file_root = self.tmp_root / "not_a_directory"
        file_root.write_text("我是普通文件", encoding="utf-8")
        file_result = self._scan(file_root)
        self._assert_empty_summary(file_result)

        self.assertEqual(self._all_projects(), [])


if __name__ == "__main__":
    unittest.main()

"""项目按文件序号区间拆分（``POST /api/projects/{pid}/split``）测试。

覆盖 ``docs/项目拆分与自定义快捷键.md`` 第 1 节与第 3 节的后端验收项：

1. 区间正确移动：文件序号与 ``GET /api/projects/{pid}`` 的 files 顺序一致
   （``created_at`` 倒序、``queue_seq`` 兜底），``uploading`` 被排除；
2. 文件 id 不变、整个目录一起移动、``annotations.json`` 仍可读取；
3. 新项目全量继承 ``labels`` / ``relation_types`` / ``shortcuts``；
4. 源项目剩余文件正确，全部拆走时源项目仍存在但文件为空；
5. 区间重叠 / 越界 / 重名 / 空组 / 超过 50 组 → 400，且不产生任何副作用；
6. 含 ``converting`` 文件 → 409，detail 列出文件名，且没有创建任何项目；
7. 移动到一半失败 → 回滚（源项目文件恢复、文件目录移回、新项目删除）。

与 ``test_project_labels.py`` 一致：``_env`` 先把数据目录指到临时目录，再用
``mock.patch.object`` 把 ``PROJECTS_DIR`` / ``PROJECTS_INDEX_PATH`` 指到独立
临时目录，保证用例之间不共享索引、也不碰真实 ``backend/data``。
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
from errors import ConflictError, ServiceError

SOURCE_CONTENT = b"%PDF-1.4 split-test"


class ProjectSplitTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="labelfast-project-split-")
        root = Path(self._tmp.name)
        self.projects_dir = root / "projects"
        self.index_path = root / "projects.json"
        self._patchers = [
            mock.patch.object(storage, "PROJECTS_DIR", self.projects_dir),
            mock.patch.object(storage, "PROJECTS_INDEX_PATH", self.index_path),
        ]
        for patcher in self._patchers:
            patcher.start()
        # 进程级缓存会跨用例残留上一个临时目录的路径，这里显式清空。
        storage._FILE_DIR_CACHE.clear()

    def tearDown(self) -> None:
        storage._FILE_DIR_CACHE.clear()
        for patcher in reversed(self._patchers):
            patcher.stop()
        self._tmp.cleanup()

    # -- 工具 ---------------------------------------------------------

    def _new_project(
        self,
        name: str,
        labels: list[str] | None = None,
        relation_types: list[str] | None = None,
        shortcuts: dict[str, str] | None = None,
    ) -> dict:
        return storage.create_project(
            name,
            list(labels or []),
            list(relation_types or []),
            shortcuts=shortcuts,
        )

    def _new_file(self, project_id: str, name: str, status: str = "completed") -> dict:
        meta, target = storage.create_file(
            project_id,
            name,
            ".pdf",
            source_type="pdf",
            enable_table=True,
            enable_formula=False,
            dpi=200,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(SOURCE_CONTENT)
        if status != meta.get("status"):
            meta = storage.update_file(meta["id"], {"status": status})
        return meta

    def _seed_files(self, project_id: str, count: int) -> list[dict]:
        """按创建顺序创建 ``count`` 个已完成文件，返回 ``list_files`` 顺序。"""

        created = [
            self._new_file(project_id, f"文件{index}.pdf")
            for index in range(1, count + 1)
        ]
        listed = storage.list_files(project_id)
        # 断言测试假设：created_at 同秒时新文件排在前面（queue_seq 倒序）。
        self.assertEqual(
            [meta["id"] for meta in listed],
            [meta["id"] for meta in reversed(created)],
        )
        return listed

    def _annotate(self, file_id: str, text: str = "标注正文") -> None:
        storage.save_annotations(
            file_id,
            {"text": text, "spans": [], "relations": [], "paragraphs": []},
        )

    def _read_project_json(self, project_id: str) -> dict:
        path = storage._project_dir(project_id) / "project.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_index(self) -> list[dict]:
        if not self.index_path.is_file():
            return []
        return json.loads(self.index_path.read_text(encoding="utf-8"))["projects"]

    def _project_dir_names(self) -> set[str]:
        if not self.projects_dir.is_dir():
            return set()
        return {child.name for child in self.projects_dir.iterdir()}

    def _client(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:  # pragma: no cover - 依赖缺失时跳过
            self.skipTest("未安装 FastAPI TestClient")

        import app as app_module

        return TestClient(app_module.app)


class SplitProjectTests(ProjectSplitTestBase):
    """场景 1 / 2 / 3 / 4：区间移动、继承与源项目剩余。"""

    def test_split_moves_ranges_and_keeps_file_ids(self) -> None:
        project = self._new_project(
            "国标3", ["适用范围", "机械性能"], ["包含", "替换"],
            shortcuts={"适用范围": "q"},
        )
        files = self._seed_files(project["id"], 5)
        self._annotate(files[0]["id"], "第一份标注意")

        response = self._client().post(
            f"/api/projects/{project['id']}/split",
            json={
                "groups": [
                    {"name": "国标3-A", "start": 1, "end": 2},
                    {"name": "国标3-B", "start": 4, "end": 5},
                ]
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body["projects"]), 2)
        self.assertEqual(
            [item["file_count"] for item in body["projects"]], [2, 2]
        )
        self.assertEqual(
            body["projects"][0]["file_ids"],
            [files[0]["id"], files[1]["id"]],
        )
        self.assertEqual(
            body["projects"][1]["file_ids"],
            [files[3]["id"], files[4]["id"]],
        )

        # 新项目全量继承字典与快捷键，名称按提交顺序。
        for item, expected_name in zip(body["projects"], ["国标3-A", "国标3-B"]):
            created = item["project"]
            self.assertEqual(created["name"], expected_name)
            self.assertEqual(created["labels"], ["适用范围", "机械性能"])
            self.assertEqual(created["relation_types"], ["包含", "替换"])
            self.assertEqual(created["shortcuts"], {"适用范围": "q"})
            self.assertNotIn("dir_name", created)

        # 源项目只剩未分配的 files[2]，字典与快捷键不被改动。
        self.assertEqual(
            [meta["id"] for meta in storage.list_files(project["id"])],
            [files[2]["id"]],
        )
        source = body["source_project"]
        self.assertEqual(source["id"], project["id"])
        self.assertEqual(source["labels"], ["适用范围", "机械性能"])
        self.assertEqual(source["shortcuts"], {"适用范围": "q"})

        # 文件 id 不变、整个目录搬到新项目、meta 同步更新。
        new_pid = body["projects"][0]["project"]["id"]
        meta = storage.get_file(files[0]["id"])
        self.assertEqual(meta["id"], files[0]["id"])
        self.assertEqual(meta["project_id"], new_pid)
        self.assertEqual(meta["dir_name"], "文件5")
        directory = storage.file_dir(meta)
        self.assertTrue(directory.is_dir())
        self.assertEqual(
            directory.parent.parent, storage._project_dir(new_pid)
        )
        # 源文件与标注随目录一起移动，内容可读。
        self.assertEqual(
            (directory / meta["source_filename"]).read_bytes(), SOURCE_CONTENT
        )
        self.assertEqual(
            storage.load_annotations(files[0]["id"])["text"], "第一份标注意"
        )

        # GET /api/projects/{new_pid} 的文件列表与响应里的 file_ids 一致。
        detail = self._client().get(f"/api/projects/{new_pid}").json()
        self.assertEqual(
            [item["id"] for item in detail["files"]],
            body["projects"][0]["file_ids"],
        )
        # 索引里登记了新项目，且 dir_name 已落盘。
        self.assertEqual(len(self._read_index()), 3)
        self.assertEqual(
            [item["name"] for item in self._read_index()][-1], "国标3-B"
        )

    def test_split_all_files_leaves_source_project_empty(self) -> None:
        project = self._new_project("整包项目", ["甲"], ["包含"])
        files = self._seed_files(project["id"], 3)

        response = self._client().post(
            f"/api/projects/{project['id']}/split",
            json={"groups": [{"name": "整包-A", "start": 1, "end": 3}]},
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["projects"][0]["file_count"], 3)
        self.assertEqual(body["projects"][0]["file_ids"], [m["id"] for m in files])
        self.assertEqual(storage.list_files(project["id"]), [])
        # 源项目仍保留（含字典），只是没有文件。
        detail = self._client().get(f"/api/projects/{project['id']}").json()
        self.assertEqual(detail["files"], [])
        self.assertEqual(detail["labels"], ["甲"])
        self.assertTrue(storage._project_dir(project["id"]).is_dir())

    def test_uploading_files_are_excluded_from_numbering(self) -> None:
        project = self._new_project("上传中项目", [], [])
        files = self._seed_files(project["id"], 3)
        pending = self._new_file(project["id"], "半截.pdf", status="uploading")

        response = self._client().post(
            f"/api/projects/{project['id']}/split",
            json={"groups": [{"name": "上传中-A", "start": 1, "end": 3}]},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["projects"][0]["file_ids"], [m["id"] for m in files]
        )
        # uploading 文件仍留在源项目，且没有跟着被移动。
        self.assertEqual(
            [meta["id"] for meta in storage.list_files(project["id"])],
            [pending["id"]],
        )
        self.assertEqual(
            storage.get_file(pending["id"])["project_id"], project["id"]
        )

    def test_move_file_to_project_dedupes_dir_name(self) -> None:
        first = self._new_project("目标项目", [], [])
        second = self._new_project("来源项目", [], [])
        kept = self._new_file(first["id"], "同名.pdf")
        moved = self._new_file(second["id"], "同名.pdf")

        meta = storage.move_file_to_project(moved["id"], first["id"])

        self.assertEqual(meta["project_id"], first["id"])
        self.assertEqual(meta["dir_name"], "同名 (2)")
        self.assertEqual(
            sorted(item["dir_name"] for item in storage.list_files(first["id"])),
            ["同名", "同名 (2)"],
        )
        self.assertEqual(storage.list_files(second["id"]), [])
        self.assertTrue(
            (storage._project_dir(first["id"]) / "files" / "同名").is_dir()
        )
        self.assertEqual(storage.get_file(kept["id"])["dir_name"], "同名")

    def test_move_file_to_project_rejects_converting_file(self) -> None:
        source = self._new_project("来源项目2", [], [])
        target = self._new_project("目标项目2", [], [])
        meta = self._new_file(source["id"], "转换中.pdf", status="converting")

        with self.assertRaises(ConflictError) as ctx:
            storage.move_file_to_project(meta["id"], target["id"])

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("转换中.pdf", ctx.exception.detail)


class SplitValidationTests(ProjectSplitTestBase):
    """场景 5：参数校验失败一律 400 且不产生任何副作用。"""

    def test_invalid_groups_return_400(self) -> None:
        project = self._new_project("校验项目", ["甲"], [])
        self._seed_files(project["id"], 5)
        before_index = self._read_index()
        before_dirs = self._project_dir_names()
        before_files = [meta["id"] for meta in storage.list_files(project["id"])]

        cases = [
            ({"groups": []}, "拆分分组不能为空"),
            (
                {
                    "groups": [
                        {"name": "A", "start": 1, "end": 3},
                        {"name": "B", "start": 3, "end": 5},
                    ]
                },
                "拆分区间重叠",
            ),
            ({"groups": [{"name": "A", "start": 1, "end": 6}]}, "文件序号"),
            ({"groups": [{"name": "A", "start": 0, "end": 2}]}, "文件序号"),
            ({"groups": [{"name": "A", "start": 4, "end": 2}]}, "文件序号"),
            (
                {
                    "groups": [
                        {"name": "同名", "start": 1, "end": 1},
                        {"name": "同名", "start": 2, "end": 2},
                    ]
                },
                "重复",
            ),
            ({"groups": [{"name": "   ", "start": 1, "end": 1}]}, "名称不能为空"),
            ({"groups": [{"name": "超" * 121, "start": 1, "end": 1}]}, "过长"),
        ]

        client = self._client()
        for payload, keyword in cases:
            with self.subTest(keyword=keyword):
                response = client.post(
                    f"/api/projects/{project['id']}/split", json=payload
                )
                self.assertEqual(response.status_code, 400, response.text)
                self.assertIn(keyword, response.json()["detail"])

        # 400 全部在「创建项目/移动文件」之前抛出：索引、目录、文件都不变。
        self.assertEqual(self._read_index(), before_index)
        self.assertEqual(self._project_dir_names(), before_dirs)
        self.assertEqual(
            [meta["id"] for meta in storage.list_files(project["id"])],
            before_files,
        )

    def test_more_than_50_groups_returns_400(self) -> None:
        project = self._new_project("分组上限项目", [], [])
        self._seed_files(project["id"], 2)
        groups = [
            {"name": f"组{index}", "start": 1, "end": 1}
            for index in range(51)
        ]

        response = self._client().post(
            f"/api/projects/{project['id']}/split", json={"groups": groups}
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("最多 50 组", response.json()["detail"])
        self.assertEqual(len(self._read_index()), 1)

    def test_split_unknown_project_returns_404(self) -> None:
        response = self._client().post(
            f"/api/projects/{uuid.uuid4()}/split",
            json={"groups": [{"name": "A", "start": 1, "end": 1}]},
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("项目不存在", response.json()["detail"])


class SplitConvertingConflictTests(ProjectSplitTestBase):
    """场景 6：含 converting 文件 → 409，且没有创建任何项目。"""

    def test_converting_file_blocks_split_without_side_effects(self) -> None:
        project = self._new_project("转换中项目", ["甲"], [])
        files = self._seed_files(project["id"], 4)
        storage.update_file(files[1]["id"], {"status": "converting"})
        before_index = self._read_index()
        before_dirs = self._project_dir_names()

        response = self._client().post(
            f"/api/projects/{project['id']}/split",
            json={"groups": [{"name": "转换中-A", "start": 1, "end": 4}]},
        )

        self.assertEqual(response.status_code, 409, response.text)
        detail = response.json()["detail"]
        self.assertIn("正在转换", detail)
        # files[1] 是第 2 个文件，即 created 顺序里的「文件3.pdf」。
        self.assertIn("文件3.pdf", detail)
        self.assertNotIn("文件5.pdf", detail)

        self.assertEqual(self._read_index(), before_index)
        self.assertEqual(self._project_dir_names(), before_dirs)
        self.assertEqual(
            len(storage.list_files(project["id"])), 4
        )

    def test_converted_and_failed_files_can_be_moved(self) -> None:
        project = self._new_project("可移动状态项目", [], [])
        completed = self._new_file(project["id"], "已完成.pdf", status="completed")
        failed = self._new_file(project["id"], "失败.pdf", status="failed")
        uploaded = self._new_file(project["id"], "排队.pdf", status="uploaded")

        response = self._client().post(
            f"/api/projects/{project['id']}/split",
            json={"groups": [{"name": "可移动-A", "start": 1, "end": 3}]},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["projects"][0]["file_ids"],
            [uploaded["id"], failed["id"], completed["id"]],
        )
        self.assertEqual(storage.list_files(project["id"]), [])


class SplitRollbackTests(ProjectSplitTestBase):
    """场景 7：移动到一半失败 → 全量回滚。"""

    def test_failure_on_second_file_rolls_back_everything(self) -> None:
        project = self._new_project("回滚项目", ["甲", "乙"], ["包含"])
        files = self._seed_files(project["id"], 5)
        self._annotate(files[0]["id"], "回滚前标注")
        before_files = [meta["id"] for meta in files]
        before_index = self._read_index()
        before_dirs = self._project_dir_names()

        real_move = storage.move_file_to_project
        calls = {"count": 0}

        def flaky_move(file_id: str, target_project_id: str) -> dict:
            calls["count"] += 1
            if calls["count"] == 2:
                raise OSError("模拟磁盘写入失败")
            return real_move(file_id, target_project_id)

        with mock.patch.object(
            storage, "move_file_to_project", side_effect=flaky_move
        ):
            with self.assertRaises(ServiceError) as ctx:
                storage.split_project(
                    project["id"],
                    [
                        {"name": "回滚-A", "start": 1, "end": 2},
                        {"name": "回滚-B", "start": 3, "end": 4},
                    ],
                )

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertIn("已回滚", ctx.exception.detail)
        # 第二个文件失败 → 第一个已移动的文件必须被移回源项目。
        self.assertEqual(calls["count"], 3)
        self.assertEqual(
            [meta["id"] for meta in storage.list_files(project["id"])],
            before_files,
        )
        meta = storage.get_file(files[0]["id"])
        self.assertEqual(meta["project_id"], project["id"])
        self.assertEqual(meta["dir_name"], "文件5")
        self.assertEqual(
            storage.file_dir(meta).parent.parent,
            storage._project_dir(project["id"]),
        )
        self.assertEqual(
            storage.load_annotations(files[0]["id"])["text"], "回滚前标注"
        )
        self.assertEqual(
            (storage.source_path(meta)).read_bytes(), SOURCE_CONTENT
        )
        # 已创建的项目（目录 + 索引）全部删除。
        self.assertEqual(self._read_index(), before_index)
        self.assertEqual(self._project_dir_names(), before_dirs)
        self.assertEqual(
            [item["id"] for item in storage.list_projects()], [project["id"]]
        )

    def test_metadata_write_failure_restores_directory(self) -> None:
        project = self._new_project("元数据回滚项目", [], [])
        target = self._new_project("目标项目3", [], [])
        meta = self._new_file(project["id"], "元数据.pdf")

        real_write = storage._atomic_write_json

        def failing_write(path: Path, payload) -> None:
            if Path(path).name == "meta.json":
                raise OSError("模拟元数据写入失败")
            return real_write(path, payload)

        with mock.patch.object(
            storage, "_atomic_write_json", side_effect=failing_write
        ):
            with self.assertRaises(OSError):
                storage.move_file_to_project(meta["id"], target["id"])

        # 目录 rename 已回滚：文件仍在源项目，目标项目里没有残留目录。
        restored = storage.get_file(meta["id"])
        self.assertEqual(restored["project_id"], project["id"])
        self.assertTrue(
            (storage._project_dir(project["id"]) / "files" / "元数据").is_dir()
        )
        self.assertFalse(
            (storage._project_dir(target["id"]) / "files" / "元数据").exists()
        )

    def test_partial_rollback_keeps_new_project_to_avoid_data_loss(self) -> None:
        """回滚边界：文件移不回去时宁可保留新项目，也绝不删掉用户数据。"""

        project = self._new_project("部分回滚项目", ["甲"], [])
        self._seed_files(project["id"], 3)
        files = storage.list_files(project["id"])

        real_move = storage.move_file_to_project
        calls = {"count": 0}

        def flaky_move(file_id: str, target_project_id: str) -> dict:
            calls["count"] += 1
            # 第 2 次是第 2 个文件的移动，第 3 次是回滚时移回第 1 个文件。
            if calls["count"] in (2, 3):
                raise OSError("模拟移动失败")
            return real_move(file_id, target_project_id)

        with mock.patch.object(
            storage, "move_file_to_project", side_effect=flaky_move
        ):
            with self.assertRaises(ServiceError) as ctx:
                storage.split_project(
                    project["id"], [{"name": "部分-A", "start": 1, "end": 2}]
                )

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertIn("未能回滚", ctx.exception.detail)
        # 新建项目保留，被移动的文件仍可读取（没有数据丢失）。
        projects = storage.list_projects()
        self.assertEqual(len(projects), 2)
        new_project = next(item for item in projects if item["id"] != project["id"])
        new_files = storage.list_files(new_project["id"])
        self.assertEqual([meta["id"] for meta in new_files], [files[0]["id"]])
        meta = storage.get_file(files[0]["id"])
        self.assertEqual(meta["project_id"], new_project["id"])
        self.assertEqual(
            (storage.source_path(meta)).read_bytes(), SOURCE_CONTENT
        )
        # 源项目保留未移动的两个文件。
        self.assertEqual(
            [item["id"] for item in storage.list_files(project["id"])],
            [files[1]["id"], files[2]["id"]],
        )


if __name__ == "__main__":
    unittest.main()

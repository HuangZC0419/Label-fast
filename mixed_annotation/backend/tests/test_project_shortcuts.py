"""项目级自定义快捷键（``PATCH /api/projects/{pid}`` 的 shortcuts_*）测试。

覆盖 ``docs/项目拆分与自定义快捷键.md`` 第 2 节与第 3 节的后端验收项：

1. 新建项目 ``shortcuts == {}``，旧项目缺字段时按 ``{}`` 读取；
2. 默认前 9 个标签对应数字 1–9，覆盖项优先，两个项目互不影响；
3. ``shortcuts_set`` / ``shortcuts_unset`` 增量提交，规范化后落盘（三层一致：
   响应、``project.json``、``projects.json``）；
4. 格式规范化：``CTRL+k`` → ``Ctrl+K``、``shift+alt+p`` → ``Alt+Shift+P``、
   单键字母小写、功能键大写；
5. 保留键（``Delete`` / ``Escape`` / 方向键 / ``Ctrl+Z`` / ``Ctrl+1``…）→ 400；
6. 标签不存在 → 400；标签在同一请求里通过 ``labels_add`` 新增则可直接设置；
7. 有效快捷键冲突 → 409，且一字未写；
8. 删除标签（``labels_remove``）同步清理该标签的覆盖项；
9. 旧客户端整份 ``labels`` 提交仍只做追加，不会连带删掉快捷键。

与 ``test_project_labels.py`` 一致：``_env`` 先把数据目录指到临时目录，再用
``mock.patch.object`` 把 ``PROJECTS_DIR`` / ``PROJECTS_INDEX_PATH`` 指到独立
临时目录。
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
from errors import BadRequestError, ConflictError
from services import shortcut_service

LABELS = ["适用范围", "机械性能", "实验步骤", "工艺参数"]


class ProjectShortcutTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="labelfast-shortcuts-")
        root = Path(self._tmp.name)
        self.projects_dir = root / "projects"
        self.index_path = root / "projects.json"
        self._patchers = [
            mock.patch.object(storage, "PROJECTS_DIR", self.projects_dir),
            mock.patch.object(storage, "PROJECTS_INDEX_PATH", self.index_path),
        ]
        for patcher in self._patchers:
            patcher.start()
        storage._FILE_DIR_CACHE.clear()

    def tearDown(self) -> None:
        storage._FILE_DIR_CACHE.clear()
        for patcher in reversed(self._patchers):
            patcher.stop()
        self._tmp.cleanup()

    # -- 工具 ---------------------------------------------------------

    def _new_project(
        self, name: str, labels: list[str] | None = None
    ) -> dict:
        return storage.create_project(name, list(labels or LABELS), ["包含"])

    def _read_project_json(self, project_id: str) -> dict:
        path = storage._project_dir(project_id) / "project.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_index(self) -> list[dict]:
        if not self.index_path.is_file():
            return []
        return json.loads(self.index_path.read_text(encoding="utf-8"))["projects"]

    def _write_project_json(self, project_id: str, payload: dict) -> None:
        path = storage._project_dir(project_id) / "project.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _client(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:  # pragma: no cover - 依赖缺失时跳过
            self.skipTest("未安装 FastAPI TestClient")

        import app as app_module

        return TestClient(app_module.app)


class ShortcutDefaultsTests(ProjectShortcutTestBase):
    """场景 1 / 2：默认值、缺字段兼容、项目间独立。"""

    def test_new_project_has_empty_shortcuts(self) -> None:
        project = storage.create_project("新项目", ["甲", "乙"], ["包含"])

        self.assertEqual(project["shortcuts"], {})
        self.assertEqual(storage.get_project(project["id"])["shortcuts"], {})
        self.assertEqual(self._read_project_json(project["id"])["shortcuts"], {})
        self.assertEqual(self._read_index()[0]["shortcuts"], {})
        self.assertEqual(
            self._client().get(f"/api/projects/{project['id']}").json()["shortcuts"],
            {},
        )

    def test_defaults_cover_first_nine_labels(self) -> None:
        labels = [f"标签{index}" for index in range(1, 12)]

        effective = shortcut_service.effective_shortcuts(labels, {})

        self.assertEqual(
            effective,
            {f"标签{index}": str(index) for index in range(1, 10)},
        )
        # 超过 9 个的标签默认没有快捷键。
        self.assertNotIn("标签10", effective)
        self.assertNotIn("标签11", effective)

    def test_overrides_win_over_defaults(self) -> None:
        labels = ["甲", "乙", "丙"]

        effective = shortcut_service.effective_shortcuts(
            labels, {"甲": "q", "丙": "Ctrl+K"}
        )

        self.assertEqual(effective, {"甲": "q", "乙": "2", "丙": "Ctrl+K"})
        # 字典里不存在的标签覆盖项被忽略（历史脏数据不报错）。
        self.assertEqual(
            shortcut_service.effective_shortcuts(
                labels, {"已删除标签": "z"}
            ),
            {"甲": "1", "乙": "2", "丙": "3"},
        )

    def test_projects_keep_independent_shortcuts(self) -> None:
        first = self._new_project("项目甲")
        second = self._new_project("项目乙")

        client = self._client()
        client.patch(
            f"/api/projects/{first['id']}",
            json={"shortcuts_set": {"适用范围": "q"}},
        )
        client.patch(
            f"/api/projects/{second['id']}",
            json={"shortcuts_set": {"适用范围": "Ctrl+K"}},
        )

        self.assertEqual(
            storage.get_project(first["id"])["shortcuts"], {"适用范围": "q"}
        )
        self.assertEqual(
            storage.get_project(second["id"])["shortcuts"],
            {"适用范围": "Ctrl+K"},
        )

    def test_legacy_project_without_shortcuts_field_reads_empty(self) -> None:
        project = self._new_project("旧项目")
        payload = self._read_project_json(project["id"])
        payload.pop("shortcuts", None)
        self._write_project_json(project["id"], payload)
        index = self._read_index()
        index[0].pop("shortcuts", None)
        self.index_path.write_text(
            json.dumps({"projects": index}, ensure_ascii=False), encoding="utf-8"
        )

        self.assertEqual(storage.get_project(project["id"])["shortcuts"], {})
        client = self._client()
        self.assertEqual(
            client.get(f"/api/projects/{project['id']}").json()["shortcuts"], {}
        )
        self.assertEqual(
            client.get("/api/projects").json()[0]["shortcuts"], {}
        )


class ShortcutPatchTests(ProjectShortcutTestBase):
    """场景 3 / 4：set / unset 与格式规范化。"""

    def test_set_and_unset_overrides(self) -> None:
        project = self._new_project("快捷键项目")
        client = self._client()

        response = client.patch(
            f"/api/projects/{project['id']}",
            json={
                "shortcuts_set": {"适用范围": "q", "机械性能": "Ctrl+K"},
                "shortcuts_unset": ["实验步骤"],
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["shortcuts"],
            {"适用范围": "q", "机械性能": "Ctrl+K"},
        )
        # 三层一致：响应、project.json、索引。
        self.assertEqual(
            self._read_project_json(project["id"])["shortcuts"],
            {"适用范围": "q", "机械性能": "Ctrl+K"},
        )
        self.assertEqual(
            self._read_index()[0]["shortcuts"],
            {"适用范围": "q", "机械性能": "Ctrl+K"},
        )

        unset = client.patch(
            f"/api/projects/{project['id']}",
            json={"shortcuts_unset": ["机械性能"]},
        )

        self.assertEqual(unset.status_code, 200, unset.text)
        self.assertEqual(unset.json()["shortcuts"], {"适用范围": "q"})
        # 清除后回落到默认 1–9。
        effective = shortcut_service.effective_shortcuts(
            unset.json()["labels"], unset.json()["shortcuts"]
        )
        self.assertEqual(effective["机械性能"], "2")
        self.assertEqual(effective["适用范围"], "q")

    def test_shortcut_format_is_normalized(self) -> None:
        project = storage.create_project(
            "规范化项目", ["甲", "乙", "丙", "丁", "戊"], []
        )

        response = self._client().patch(
            f"/api/projects/{project['id']}",
            json={
                "shortcuts_set": {
                    "甲": "CTRL+k",
                    "乙": "shift+alt+p",
                    "丙": "P",
                    "丁": "f2",
                    "戊": "  !  ",
                }
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["shortcuts"],
            {
                "甲": "Ctrl+K",
                "乙": "Alt+Shift+P",
                "丙": "p",
                "丁": "F2",
                "戊": "!",
            },
        )
        self.assertEqual(
            self._read_project_json(project["id"])["shortcuts"],
            response.json()["shortcuts"],
        )

    def test_modifier_order_is_fixed(self) -> None:
        project = self._new_project("顺序项目")

        response = self._client().patch(
            f"/api/projects/{project['id']}",
            json={"shortcuts_set": {"适用范围": "Shift+Alt+Ctrl+U"}},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["shortcuts"], {"适用范围": "Ctrl+Alt+Shift+U"}
        )

    def test_label_added_in_same_request_can_get_shortcut(self) -> None:
        project = self._new_project("同请求新增项目")
        client = self._client()

        response = client.patch(
            f"/api/projects/{project['id']}",
            json={
                "labels_add": ["新标签"],
                "shortcuts_set": {"新标签": "q"},
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("新标签", response.json()["labels"])
        self.assertEqual(response.json()["shortcuts"], {"新标签": "q"})


class ShortcutValidationTests(ProjectShortcutTestBase):
    """场景 5 / 6 / 7：保留键 400、标签不存在 400、冲突 409。"""

    def test_reserved_shortcuts_rejected_with_400(self) -> None:
        project = self._new_project("保留键项目")
        client = self._client()
        reserved = [
            "Escape",
            "Delete",
            "Backspace",
            "Enter",
            "Tab",
            "Space",
            "ArrowUp",
            "ArrowDown",
            "ArrowLeft",
            "ArrowRight",
            "Home",
            "End",
            "PageUp",
            "PageDown",
            "Ctrl+Z",
            "Ctrl+S",
            "Ctrl+1",
            "ctrl+9",
        ]

        for shortcut in reserved:
            with self.subTest(shortcut=shortcut):
                response = client.patch(
                    f"/api/projects/{project['id']}",
                    json={"shortcuts_set": {"适用范围": shortcut}},
                )
                self.assertEqual(response.status_code, 400, response.text)
                detail = response.json()["detail"]
                self.assertTrue(
                    "保留" in detail or "保留快捷键" in detail, detail
                )

        # 全部失败 ⇒ 一个覆盖项都没有写入。
        self.assertEqual(storage.get_project(project["id"])["shortcuts"], {})
        self.assertEqual(
            self._read_project_json(project["id"])["shortcuts"], {}
        )

    def test_unknown_label_rejected_with_400(self) -> None:
        project = self._new_project("未知标签项目")

        response = self._client().patch(
            f"/api/projects/{project['id']}",
            json={"shortcuts_set": {"不存在的标签": "q"}},
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("标签「不存在的标签」不存在", response.json()["detail"])
        self.assertEqual(storage.get_project(project["id"])["shortcuts"], {})

    def test_removed_label_cannot_get_shortcut_in_same_request(self) -> None:
        project = self._new_project("删除加设置项目")

        response = self._client().patch(
            f"/api/projects/{project['id']}",
            json={
                "labels_remove": ["实验步骤"],
                "shortcuts_set": {"实验步骤": "q"},
            },
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("标签「实验步骤」不存在", response.json()["detail"])
        # 字典与快捷键都没有被写。
        self.assertIn("实验步骤", storage.get_project(project["id"])["labels"])

    def test_conflict_with_default_shortcut_returns_409(self) -> None:
        project = self._new_project("冲突项目")

        response = self._client().patch(
            f"/api/projects/{project['id']}",
            json={"shortcuts_set": {"机械性能": "1"}},
        )

        # 「适用范围」默认占 1，覆盖项写成 1 即冲突。
        self.assertEqual(response.status_code, 409, response.text)
        detail = response.json()["detail"]
        self.assertIn("快捷键「1」", detail)
        self.assertIn("「适用范围」", detail)
        self.assertIn("「机械性能」", detail)
        self.assertEqual(storage.get_project(project["id"])["shortcuts"], {})

    def test_conflict_between_two_overrides_returns_409(self) -> None:
        project = self._new_project("覆盖冲突项目")

        response = self._client().patch(
            f"/api/projects/{project['id']}",
            json={"shortcuts_set": {"适用范围": "q", "机械性能": "Q"}},
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("快捷键「q」", response.json()["detail"])
        self.assertEqual(storage.get_project(project["id"])["shortcuts"], {})

    def test_blank_shortcut_value_rejected(self) -> None:
        project = self._new_project("空快捷键项目")

        response = self._client().patch(
            f"/api/projects/{project['id']}",
            json={"shortcuts_set": {"适用范围": "   "}},
        )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(storage.get_project(project["id"])["shortcuts"], {})

    def test_service_level_errors_are_business_errors(self) -> None:
        project = self._new_project("服务层项目")

        with self.assertRaises(BadRequestError) as ctx:
            storage.update_project_dictionary(
                project["id"], shortcuts_set={"适用范围": "Delete"}
            )
        self.assertEqual(ctx.exception.status_code, 400)

        with self.assertRaises(ConflictError) as ctx2:
            storage.update_project_dictionary(
                project["id"], shortcuts_set={"机械性能": "1"}
            )
        self.assertEqual(ctx2.exception.status_code, 409)


class ShortcutLabelLifecycleTests(ProjectShortcutTestBase):
    """场景 8 / 9：删除标签清理覆盖项；旧客户端整份提交不回归。"""

    def test_removing_label_clears_its_override(self) -> None:
        project = self._new_project("删除标签项目")
        storage.update_project_dictionary(
            project["id"],
            shortcuts_set={"实验步骤": "q", "适用范围": "Ctrl+K"},
        )

        updated = storage.update_project_dictionary(
            project["id"], labels_remove=["实验步骤"]
        )

        self.assertNotIn("实验步骤", updated["labels"])
        self.assertEqual(updated["shortcuts"], {"适用范围": "Ctrl+K"})
        self.assertEqual(
            self._read_project_json(project["id"])["shortcuts"],
            {"适用范围": "Ctrl+K"},
        )

    def test_removing_force_deleted_label_clears_override(self) -> None:
        project = self._new_project("强删标签项目")
        storage.update_project_dictionary(
            project["id"], shortcuts_set={"实验步骤": "q"}
        )

        updated = storage.update_project_dictionary(
            project["id"], labels_remove=["实验步骤"], force=True
        )

        self.assertNotIn("实验步骤", updated["labels"])
        self.assertEqual(updated["shortcuts"], {})

    def test_legacy_full_labels_payload_keeps_shortcuts(self) -> None:
        project = self._new_project("旧客户端项目")
        storage.update_project_dictionary(
            project["id"], shortcuts_set={"适用范围": "q"}
        )

        response = self._client().patch(
            f"/api/projects/{project['id']}",
            json={"labels": list(LABELS)},
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        # 旧客户端整份提交：不删标签、不动快捷键。
        self.assertEqual(body["labels"], LABELS)
        self.assertEqual(body["shortcuts"], {"适用范围": "q"})
        self.assertEqual(
            self._read_project_json(project["id"])["shortcuts"],
            {"适用范围": "q"},
        )

    def test_patch_without_shortcut_fields_keeps_shortcuts(self) -> None:
        project = self._new_project("无关更新项目")
        storage.update_project_dictionary(
            project["id"], shortcuts_set={"适用范围": "q"}
        )

        updated = storage.update_project_dictionary(
            project["id"], name="无关更新项目改名"
        )

        self.assertEqual(updated["shortcuts"], {"适用范围": "q"})
        self.assertEqual(updated["name"], "无关更新项目改名")


class ShortcutPatchRouteTests(ProjectShortcutTestBase):
    """路由层：未知项目 404、非字典类型 422。"""

    def test_patch_unknown_project_returns_404(self) -> None:
        response = self._client().patch(
            f"/api/projects/{uuid.uuid4()}",
            json={"shortcuts_set": {"适用范围": "q"}},
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("项目不存在", response.json()["detail"])

    def test_shortcuts_set_must_be_object(self) -> None:
        project = self._new_project("类型校验项目")

        response = self._client().patch(
            f"/api/projects/{project['id']}",
            json={"shortcuts_set": ["适用范围"]},
        )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(storage.get_project(project["id"])["shortcuts"], {})


if __name__ == "__main__":
    unittest.main()

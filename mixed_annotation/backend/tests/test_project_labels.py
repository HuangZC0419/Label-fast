"""项目字典（实体标签 / 关系类型）增量合并与缺失标签恢复测试。

覆盖线上事故（多人协同把 project.json 整份覆盖）的回归场景：

1. 旧客户端只发全量 ``labels`` 时，服务端只做追加，原有标签全部保留；
2. ``labels_remove`` 可删除未被引用的标签；
3. 删除仍被 span/paragraph 引用的标签 → 409，且字典一字未改；
4. ``force=True`` 才真正删除，且不触碰任何 annotations.json；
5. ``project_label_usage`` 统计 spans + paragraphs，并跳过损坏 JSON；
6. ``labels/usage`` 的 ``missing`` 排序（引用数降序、其次标签名）；
7. ``labels/restore`` 补回全部 missing 且不改变已有顺序；
8. 两个客户端先后各追加不同标签，最终字典同时包含两者。

与 ``test_project_dirs.py`` 一致：``_env`` 先把数据目录指到临时目录，再用
``mock.patch.object`` 把 ``PROJECTS_DIR`` / ``PROJECTS_INDEX_PATH`` 指到独立
临时目录，保证用例之间不共享索引状态、也不碰真实 ``backend/data``。
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
from errors import ConflictError, NotFoundError

# 足够长的占位正文：spans 的偏移只需落在范围内即可，storage 不再做区间校验。
PLACEHOLDER_TEXT = "标注占位文本" * 200


class ProjectLabelsTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="labelfast-project-labels-")
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

    # -- 工具 ---------------------------------------------------------

    def _annotations(
        self,
        span_labels: list[str],
        paragraph_labels: list[str] | None = None,
    ) -> dict:
        spans = []
        for index, label in enumerate(span_labels, start=1):
            start = (index - 1) * 4
            spans.append(
                {
                    "id": index,
                    "start": start,
                    "end": start + 4,
                    "label": label,
                    "text": "标注占位",
                    "blockId": "",
                }
            )
        paragraphs = [
            {"blockId": f"b{index:04d}", "label": label, "note": ""}
            for index, label in enumerate(paragraph_labels or [], start=1)
        ]
        return {
            "text": PLACEHOLDER_TEXT,
            "spans": spans,
            "relations": [],
            "paragraphs": paragraphs,
        }

    def _new_file(self, project_id: str, name: str) -> dict:
        meta, _ = storage.create_file(
            project_id,
            name,
            ".pdf",
            source_type="pdf",
            enable_table=True,
            enable_formula=False,
            dpi=200,
        )
        return meta

    def _annotate(
        self,
        project_id: str,
        name: str,
        span_labels: list[str],
        paragraph_labels: list[str] | None = None,
    ) -> dict:
        meta = self._new_file(project_id, name)
        storage.save_annotations(
            meta["id"], self._annotations(span_labels, paragraph_labels)
        )
        return meta

    def _annotation_bytes(self, project_id: str, file_id: str) -> bytes:
        return storage._annotation_path(project_id, file_id).read_bytes()

    def _read_project_json(self, project_id: str) -> dict:
        path = storage._project_dir(project_id) / "project.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_index(self) -> list[dict]:
        if not self.index_path.is_file():
            return []
        return json.loads(self.index_path.read_text(encoding="utf-8"))["projects"]

    def _client(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:  # pragma: no cover - 依赖缺失时跳过
            self.skipTest("未安装 FastAPI TestClient")

        import app as app_module

        return TestClient(app_module.app)


class LegacyPatchMergeTests(ProjectLabelsTestBase):
    """场景 1 / 8：旧客户端全量提交、双客户端并发追加。"""

    def test_legacy_full_labels_payload_only_appends(self) -> None:
        project = storage.create_project("旧客户端项目", ["已有A", "已有B"], [])

        response = self._client().patch(
            f"/api/projects/{project['id']}",
            json={"labels": ["已有A", "新标签"]},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["labels"], ["已有A", "已有B", "新标签"])
        self.assertEqual(body["id"], project["id"])
        # 三层都要一致：响应、project.json、projects.json 索引。
        self.assertEqual(
            self._read_project_json(project["id"])["labels"],
            ["已有A", "已有B", "新标签"],
        )
        self.assertEqual(
            self._read_index()[0]["labels"], ["已有A", "已有B", "新标签"]
        )

    def test_legacy_full_relation_types_payload_only_appends(self) -> None:
        project = storage.create_project("旧关系项目", [], ["包含", "使用"])

        storage.update_project_dictionary(
            project["id"], relation_types_add=["替换", "包含"]
        )

        self.assertEqual(
            storage.get_project(project["id"])["relation_types"],
            ["包含", "使用", "替换"],
        )

    def test_two_clients_appending_different_labels_keep_both(self) -> None:
        project = storage.create_project("协同项目", ["初始标签"], [])

        first = self._client().patch(
            f"/api/projects/{project['id']}",
            json={"labels_add": ["客户端A标签"]},
        )
        second = self._client().patch(
            f"/api/projects/{project['id']}",
            json={"labels": ["初始标签", "客户端B标签"]},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        labels = storage.get_project(project["id"])["labels"]
        self.assertIn("客户端A标签", labels)
        self.assertIn("客户端B标签", labels)
        # 顺序：原有 → A 的追加 → B 的追加。
        self.assertEqual(labels, ["初始标签", "客户端A标签", "客户端B标签"])

    def test_name_and_dictionary_update_in_one_call(self) -> None:
        project = storage.create_project("原名项目", ["旧标签"], [])

        updated = storage.update_project_dictionary(
            project["id"], name="改名项目", labels_add=["新标签"]
        )

        self.assertEqual(updated["name"], "改名项目")
        self.assertEqual(updated["labels"], ["旧标签", "新标签"])
        self.assertEqual(
            storage._project_dir(project["id"]).name, "改名项目"
        )
        self.assertEqual(self._read_index()[0]["name"], "改名项目")

    def test_single_write_per_call(self) -> None:
        """一次 PATCH 只落盘 project.json + projects.json 各一次。"""

        project = storage.create_project("写盘次数项目", ["标签A"], [])
        with mock.patch.object(
            storage, "_atomic_write_json", wraps=storage._atomic_write_json
        ) as writer:
            storage.update_project_dictionary(
                project["id"],
                labels_add=["标签B"],
                labels_remove=["标签A"],
            )

        self.assertEqual(writer.call_count, 2)
        written = {Path(call.args[0]).name for call in writer.call_args_list}
        self.assertEqual(written, {"project.json", "projects.json"})

    def test_updated_at_is_refreshed(self) -> None:
        project = storage.create_project("时间戳项目", [], [])
        before = storage.get_project(project["id"])["updated_at"]

        updated = storage.update_project_dictionary(
            project["id"], labels_add=["新标签"]
        )

        self.assertGreaterEqual(updated["updated_at"], before)
        self.assertEqual(
            self._read_index()[0]["updated_at"], updated["updated_at"]
        )


class RemoveLabelTests(ProjectLabelsTestBase):
    """场景 2 / 3 / 4：显式删除、引用冲突 409、force 强删。"""

    def test_remove_unreferenced_label(self) -> None:
        project = storage.create_project("删除项目", ["在用", "闲置"], [])
        self._annotate(project["id"], "甲.pdf", ["在用"])

        updated = storage.update_project_dictionary(
            project["id"], labels_remove=["闲置"]
        )

        self.assertEqual(updated["labels"], ["在用"])
        self.assertEqual(self._read_project_json(project["id"])["labels"], ["在用"])
        self.assertEqual(self._read_index()[0]["labels"], ["在用"])

    def test_remove_referenced_label_conflicts_with_counts(self) -> None:
        project = storage.create_project(
            "冲突项目", ["适用范围", "机械性能", "安全"], []
        )
        self._annotate(
            project["id"],
            "甲.pdf",
            ["适用范围"] * 4 + ["机械性能"] * 2 + ["安全"],
        )
        self._annotate(
            project["id"],
            "乙.pdf",
            ["适用范围"] * 2 + ["机械性能"],
            ["适用范围", "机械性能"],
        )
        before = self._read_project_json(project["id"])

        response = self._client().patch(
            f"/api/projects/{project['id']}",
            json={"labels_remove": ["适用范围", "机械性能", "安全"]},
        )

        self.assertEqual(response.status_code, 409)
        detail = response.json()["detail"]
        self.assertEqual(
            detail,
            "标签「适用范围」7 处、「机械性能」4 处、「安全」1 处 仍被标注引用，"
            "删除后这些标注将失去标签。请先调整标注，或确认后强制删除。",
        )
        # 409 时字典与索引一字未改。
        self.assertEqual(self._read_project_json(project["id"]), before)
        self.assertEqual(
            self._read_index()[0]["labels"], ["适用范围", "机械性能", "安全"]
        )

    def test_remove_referenced_label_raises_conflict_error(self) -> None:
        project = storage.create_project("冲突项目2", ["在用标签"], [])
        self._annotate(project["id"], "甲.pdf", [], ["在用标签"])

        with self.assertRaises(ConflictError) as ctx:
            storage.update_project_dictionary(
                project["id"], labels_remove=["在用标签"]
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("「在用标签」1 处", ctx.exception.detail)
        self.assertEqual(storage.get_project(project["id"])["labels"], ["在用标签"])

    def test_force_removes_referenced_label_without_touching_annotations(
        self,
    ) -> None:
        project = storage.create_project(
            "强删项目", ["在用标签", "另一个"], []
        )
        first = self._annotate(
            project["id"], "甲.pdf", ["在用标签"] * 2, ["在用标签"]
        )
        second = self._annotate(project["id"], "乙.pdf", ["另一个"])
        before_first = self._annotation_bytes(project["id"], first["id"])
        before_second = self._annotation_bytes(project["id"], second["id"])

        response = self._client().patch(
            f"/api/projects/{project['id']}",
            json={"labels_remove": ["在用标签"], "force": True},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["labels"], ["另一个"])
        # 标注数据本身绝不能被字典维护改动。
        self.assertEqual(
            self._annotation_bytes(project["id"], first["id"]), before_first
        )
        self.assertEqual(
            self._annotation_bytes(project["id"], second["id"]), before_second
        )

    def test_remove_and_add_same_label_keeps_it(self) -> None:
        project = storage.create_project("增删同项项目", ["标签X"], [])

        updated = storage.update_project_dictionary(
            project["id"],
            labels_add=["标签X"],
            labels_remove=["标签X"],
        )

        self.assertEqual(updated["labels"], ["标签X"])

    def test_removing_unknown_label_is_noop(self) -> None:
        project = storage.create_project("未知项项目", ["已有标签"], [])

        updated = storage.update_project_dictionary(
            project["id"], labels_remove=["不存在的标签"]
        )

        self.assertEqual(updated["labels"], ["已有标签"])

    def test_relation_type_removal_is_not_blocked_by_usages(self) -> None:
        project = storage.create_project("关系删除项目", [], ["包含"])
        self._annotate(project["id"], "甲.pdf", ["实体"])

        updated = storage.update_project_dictionary(
            project["id"], relation_types_remove=["包含"]
        )

        self.assertEqual(updated["relation_types"], [])


class LabelUsageTests(ProjectLabelsTestBase):
    """场景 5 / 6：引用统计与 missing 排序。"""

    def test_usage_counts_spans_and_paragraphs_and_skips_broken_json(self) -> None:
        project = storage.create_project("统计项目", ["甲"], [])
        self._annotate(
            project["id"], "甲.pdf", ["甲", "甲"], ["段标签"]
        )
        self._annotate(
            project["id"], "乙.pdf", ["甲"], ["段标签", "段标签"]
        )
        # 只有 meta.json、没有 annotations.json 的文件应被跳过。
        self._new_file(project["id"], "无标注.pdf")
        # 损坏 JSON 也不能让统计整体失败。
        broken = self._new_file(project["id"], "损坏.pdf")
        storage._annotation_path(project["id"], broken["id"]).write_text(
            "{ 这不是合法 JSON", encoding="utf-8"
        )

        usage = storage.project_label_usage(project["id"])

        self.assertEqual(usage, {"甲": 3, "段标签": 3})

    def test_usage_for_unknown_project_raises_not_found(self) -> None:
        with self.assertRaises(NotFoundError):
            storage.project_label_usage(str(uuid.uuid4()))

    def test_usage_endpoint_returns_sorted_missing(self) -> None:
        project = storage.create_project("缺失标签项目", ["已有标签"], [])
        # 计数：甲 3、丙 3、乙 1；同计数按标签名升序（丙 U+4E19 < 甲 U+7532）。
        self._annotate(project["id"], "甲.pdf", ["甲"] * 3 + ["丙"] * 2)
        self._annotate(project["id"], "乙.pdf", ["丙", "乙"], ["已有标签"])

        response = self._client().get(
            f"/api/projects/{project['id']}/labels/usage"
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["used"], {"丙": 3, "甲": 3, "已有标签": 1, "乙": 1}
        )
        self.assertEqual(body["missing"], ["丙", "甲", "乙"])

    def test_usage_endpoint_has_empty_missing_for_consistent_dictionary(
        self,
    ) -> None:
        project = storage.create_project("一致项目", ["实体标签"], [])
        self._annotate(project["id"], "甲.pdf", ["实体标签"], ["实体标签"])

        body = self._client().get(
            f"/api/projects/{project['id']}/labels/usage"
        ).json()

        self.assertEqual(body, {"used": {"实体标签": 2}, "missing": []})

    def test_usage_endpoint_returns_404_for_missing_project(self) -> None:
        response = self._client().get(
            f"/api/projects/{uuid.uuid4()}/labels/usage"
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("项目不存在", response.json()["detail"])


class RestoreMissingLabelsTests(ProjectLabelsTestBase):
    """场景 7：缺失标签整体恢复。"""

    def test_restore_appends_missing_after_existing_order(self) -> None:
        project = storage.create_project("恢复项目", ["乙", "已有标签"], [])
        self._annotate(
            project["id"],
            "甲.pdf",
            ["乙", "甲", "甲", "甲", "丙", "丙", "丙"],
            ["历史段落标签"],
        )
        meta_annotation = self._annotation_bytes(
            project["id"], storage.list_files(project["id"])[0]["id"]
        )

        response = self._client().post(
            f"/api/projects/{project['id']}/labels/restore"
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        # 已有标签保持原顺序，缺失标签按「引用数降序、其次标签名」追加到末尾。
        self.assertEqual(
            body["labels"], ["乙", "已有标签", "丙", "甲", "历史段落标签"]
        )
        self.assertEqual(body["restored"], ["丙", "甲", "历史段落标签"])
        self.assertEqual(body["id"], project["id"])
        self.assertEqual(
            self._read_project_json(project["id"])["labels"],
            ["乙", "已有标签", "丙", "甲", "历史段落标签"],
        )
        self.assertEqual(
            self._read_index()[0]["labels"],
            ["乙", "已有标签", "丙", "甲", "历史段落标签"],
        )
        # 恢复字典不改标注数据。
        self.assertEqual(
            self._annotation_bytes(
                project["id"], storage.list_files(project["id"])[0]["id"]
            ),
            meta_annotation,
        )
        # 恢复后 missing 清空。
        self.assertEqual(
            storage.project_label_usage_report(project["id"])["missing"], []
        )

    def test_restore_is_idempotent(self) -> None:
        project = storage.create_project("幂等恢复项目", ["已有"], [])
        self._annotate(project["id"], "甲.pdf", ["缺失标签"])

        self._client().post(f"/api/projects/{project['id']}/labels/restore")
        updated_at = storage.get_project(project["id"])["updated_at"]
        second = self._client().post(
            f"/api/projects/{project['id']}/labels/restore"
        )

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["restored"], [])
        self.assertEqual(
            storage.get_project(project["id"])["updated_at"], updated_at
        )
        self.assertEqual(
            storage.get_project(project["id"])["labels"], ["已有", "缺失标签"]
        )

    def test_restore_returns_404_for_missing_project(self) -> None:
        response = self._client().post(
            f"/api/projects/{uuid.uuid4()}/labels/restore"
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("项目不存在", response.json()["detail"])


class ProjectPatchValidationTests(ProjectLabelsTestBase):
    """新字段沿用统一的列表校验；未知项目仍是 404。"""

    def test_blank_and_duplicate_items_are_normalized(self) -> None:
        project = storage.create_project("清洗项目", [], [])

        updated = storage.update_project_dictionary(
            project["id"], labels_add=["  新标签  ", "新标签", "", "另一个"]
        )

        self.assertEqual(updated["labels"], ["新标签", "另一个"])

    def test_overlong_label_rejected_with_422(self) -> None:
        project = storage.create_project("超长项目", [], [])

        response = self._client().patch(
            f"/api/projects/{project['id']}",
            json={"labels_add": ["超" * 201]},
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("请求参数不合法", response.json()["detail"])
        self.assertEqual(storage.get_project(project["id"])["labels"], [])

    def test_patch_missing_project_returns_404(self) -> None:
        response = self._client().patch(
            f"/api/projects/{uuid.uuid4()}", json={"labels_add": ["标签"]}
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("项目不存在", response.json()["detail"])

    def test_invalid_project_id_returns_404(self) -> None:
        response = self._client().patch(
            "/api/projects/not-a-uuid", json={"labels_add": ["标签"]}
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()

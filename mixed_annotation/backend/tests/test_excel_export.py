"""多项目标注明细 Excel 导出接口契约测试。

只覆盖对外契约：HTTP 形状（状态码 / content-type / 文件名）、工作簿结构
（表头、sheet 名、明细行、汇总行、冻结窗格）、以及三个边界（空选择、
项目不存在、id 重复）。数据全部落在 ``_env`` 的临时目录。
"""

from __future__ import annotations

import unittest
import uuid
from io import BytesIO

import _env  # noqa: F401  # 必须在 config/storage 之前导入

import storage
from openpyxl import load_workbook

EXCEL_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

# 独立于实现重新声明的列契约：服务层改动若破坏列顺序，这里必须失败。
EXPECTED_HEADERS = [
    "编号",
    "项目名称",
    "文件名称",
    "类型",
    "内容",
    "标签",
    "文件知识数",
    "文件图表数",
    "文件存储地址",
    "标注文件路径",
    "图表完整路径",
    "最后更新时间",
]

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class ExcelExportEndpointTests(unittest.TestCase):
    """POST /api/projects/export-excel 的多项目导出契约。"""

    def setUp(self) -> None:
        self.project_a = storage.create_project("项目A", [], [])
        self.project_b = storage.create_project("项目B", [], [])
        self.file_a = self._new_file(self.project_a["id"], "甲文件.pdf")
        self.file_b = self._new_file(self.project_b["id"], "乙文件.pdf")

    def _new_file(self, project_id: str, name: str) -> dict:
        """建文件并写入 2 条知识 + 1 张图表，保证两类行都出现。"""

        meta, source_target = storage.create_file(
            project_id,
            name,
            ".pdf",
            source_type="pdf",
            enable_table=True,
            enable_formula=False,
            dpi=200,
        )
        source_target.write_bytes(b"%PDF-1.4 test")
        storage.save_markdown(meta["id"], "甲实体与乙实体均用于测试。")
        storage.save_annotations(
            meta["id"],
            {
                "text": "甲实体与乙实体均用于测试。",
                "spans": [
                    {
                        "id": 1,
                        "start": 0,
                        "end": 3,
                        "label": "对象",
                        "text": "甲实体",
                        "blockId": "",
                    },
                    {
                        "id": 2,
                        "start": 4,
                        "end": 7,
                        "label": "用途",
                        "text": "乙实体",
                        "blockId": "",
                    },
                ],
                "relations": [],
                "paragraphs": [],
            },
        )
        storage.add_figure(
            meta["id"],
            {
                "kind": "table",
                "page": 1,
                "bbox": [1, 2, 3, 4],
                "caption": "尺寸参数表",
                "note": "",
            },
            PNG_BYTES,
        )
        return meta

    def _client(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:  # pragma: no cover - 依赖缺失时跳过
            self.skipTest("未安装 FastAPI TestClient")

        import app as app_module

        return TestClient(app_module.app)

    def _export(self, project_ids: list[str]):
        return self._client().post(
            "/api/projects/export-excel",
            json={"project_ids": project_ids},
        )

    @staticmethod
    def _data_rows(sheet) -> list[list]:
        """返回表头之后、汇总行之前的明细行。"""

        rows: list[list] = []
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if row and row[0] == "合计":
                break
            rows.append(list(row))
        return rows

    @staticmethod
    def _summary_row(sheet) -> list:
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if row and row[0] == "合计":
                return list(row)
        raise AssertionError("工作簿缺少汇总行")

    def test_exports_only_selected_projects(self) -> None:
        response = self._export([self.project_a["id"], self.project_b["id"]])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], EXCEL_MEDIA_TYPE)
        self.assertIn(
            ".xlsx", response.headers.get("content-disposition", "")
        )

        workbook = load_workbook(BytesIO(response.content))
        self.assertEqual(workbook.sheetnames, ["标注明细"])
        sheet = workbook["标注明细"]

        headers = [cell.value for cell in sheet[1]]
        self.assertEqual(headers, EXPECTED_HEADERS)
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertEqual(sheet.auto_filter.ref, "A1:L7")

        rows = self._data_rows(sheet)
        # 两个文件各 2 条知识 + 1 张图表。
        self.assertEqual(len(rows), 6)
        knowledge_rows = [row for row in rows if row[3] == "知识"]
        figure_rows = [row for row in rows if row[3] == "图表"]
        self.assertEqual(len(knowledge_rows), 4)
        self.assertEqual(len(figure_rows), 2)
        # 编号连续，从 1 开始。
        self.assertEqual([row[0] for row in rows], [1, 2, 3, 4, 5, 6])

        self.assertEqual({row[1] for row in rows}, {"项目A", "项目B"})
        # 行按（项目名, 文件名）排序：项目A 的 3 行在前。
        self.assertEqual([row[1] for row in rows], ["项目A"] * 3 + ["项目B"] * 3)
        self.assertEqual(
            {row[2] for row in rows}, {"甲文件.pdf", "乙文件.pdf"}
        )

        # 每个文件的行都带该文件的知识数/图表数。
        for row in rows:
            self.assertEqual(row[6], 2)
            self.assertEqual(row[7], 1)
            self.assertTrue(row[8])
            self.assertTrue(row[9].endswith("annotations.json"))
            self.assertTrue(row[11])

        knowledge_contents = {row[4] for row in knowledge_rows}
        self.assertEqual(knowledge_contents, {"甲实体", "乙实体"})
        self.assertEqual({row[5] for row in knowledge_rows}, {"对象", "用途"})
        # 图表内容取 caption，标签 table → 「表」，路径指向真实资产。
        self.assertEqual({row[4] for row in figure_rows}, {"尺寸参数表"})
        self.assertEqual({row[5] for row in figure_rows}, {"表"})
        for row in figure_rows:
            self.assertTrue(row[10].endswith(".png"))

        summary = self._summary_row(sheet)
        self.assertEqual(summary[1], "2 个项目")
        self.assertEqual(summary[2], "2 个文件")
        self.assertEqual(summary[4], "知识 4 条 / 图表 2 张")
        self.assertEqual(summary[6], 4)
        self.assertEqual(summary[7], 2)

    def test_duplicate_project_ids_export_once(self) -> None:
        response = self._export([self.project_a["id"], self.project_a["id"]])
        self.assertEqual(response.status_code, 200)

        sheet = load_workbook(BytesIO(response.content))["标注明细"]
        rows = self._data_rows(sheet)
        # 单项目：2 条知识 + 1 张图表，重复 id 不再复制一份。
        self.assertEqual(len(rows), 3)
        self.assertEqual({row[1] for row in rows}, {"项目A"})
        summary = self._summary_row(sheet)
        self.assertEqual(summary[1], "1 个项目")
        self.assertEqual(summary[6], 2)
        self.assertEqual(summary[7], 1)

    def test_empty_selection_rejected(self) -> None:
        response = self._export([])
        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertIn("请求参数不合法", detail)
        self.assertIn("请至少选择一个项目", detail)

    def test_blank_project_id_rejected(self) -> None:
        response = self._export(["   ", "\t"])
        self.assertEqual(response.status_code, 422)
        self.assertIn("请至少选择一个项目", response.json()["detail"])

    def test_missing_project_returns_404(self) -> None:
        response = self._export([str(uuid.uuid4())])
        self.assertEqual(response.status_code, 404)
        self.assertIn("项目不存在", response.json()["detail"])

    def test_invalid_project_id_returns_404(self) -> None:
        response = self._export(["not-a-uuid"])
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""文本规范化与 Excel 读取的单元测试。"""

import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from excel_io import ExcelError, deduplicate, load_pending, pick, read_table
from text import base_code, normalize_code, normalize_name


def make_workbook(path, rows, title="待分类目录", leading_rows=0):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = title
    for _ in range(leading_rows):
        worksheet.append([])
    for row in rows:
        worksheet.append(row)
    workbook.save(path)


class TextTests(unittest.TestCase):
    def test_normalize_code_unifies_prefix_and_two_digit_year(self):
        self.assertEqual(normalize_code("GB/T 699-15"), "GBT6992015")
        self.assertEqual(normalize_code("gjb/t 6045-2008"), "GJBT60452008")

    def test_normalize_name_removes_width_space_and_punctuation(self):
        self.assertEqual(normalize_name("  ＡＢＣ 标准-名称 "), "abc标准名称")

    def test_base_code_removes_four_digit_year(self):
        self.assertEqual(base_code("GBT6992015"), "GBT699")


class ExcelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "sample.xlsx"

    def test_read_table_finds_header_below_title_rows(self):
        make_workbook(
            self.path,
            [
                ["航空标准目录"],
                [],
                ["标准号", "标准名称", "备注"],
                ["GB/T 699-2015", "优质碳素结构钢", "示例"],
            ],
            leading_rows=0,
        )
        _header, records, _sheet = read_table(self.path)
        self.assertEqual(records[0]["标准名称"], "优质碳素结构钢")

    def test_pick_accepts_column_aliases(self):
        record = {"名称": "液压油", "专业名称": "润滑油"}
        self.assertEqual(pick(record, "name"), "液压油")
        self.assertEqual(pick(record, "profession"), "润滑油")

    def test_load_pending_rejects_missing_name_column(self):
        make_workbook(self.path, [["标准号"], ["GB/T 1-2020"]])
        with self.assertRaises(ExcelError) as context:
            load_pending(self.path)
        self.assertEqual(context.exception.code, "INVALID_FILE")

    def test_deduplicate_reports_duplicate_code_and_same_name(self):
        records = [
            {"标准号": "GB/T 1-2020", "标准名称": "甲"},
            {"标准号": "GB/T1-2020", "标准名称": "甲"},
            {"标准号": "GB/T 2-2020", "标准名称": "甲"},
            {"标准号": "GB/T 3-2020", "标准名称": "乙"},
        ]
        items, reports = deduplicate(records)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["count"], 2)
        kinds = {report["type"] for report in reports}
        self.assertIn("待分类-重复记录", kinds)
        self.assertIn("待分类-同名不同标准号", kinds)

    def test_load_pending_returns_clean_items(self):
        make_workbook(
            self.path,
            [
                ["标准号", "标准名称"],
                ["GB/T 699-2015", "优质碳素结构钢"],
                ["GB/T 699-2015", "优质碳素结构钢"],
            ],
        )
        items, reports = load_pending(self.path)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "优质碳素结构钢")
        self.assertTrue(any(item["type"] == "待分类-重复记录" for item in reports))

    def test_deduplicate_merges_gb_and_gjb_writing_variants(self):
        records = [
            {"_row": 2, "标准号": "GB/T13808-1992", "标准名称": "铜及铜合金挤制棒"},
            {"_row": 3, "标准号": "GB13808-92", "标准名称": "铜及铜合金挤制棒"},
            {"_row": 4, "标准号": "GJB/T 1-2020", "标准名称": "某规范"},
            {"_row": 5, "标准号": "GJB 1-2020", "标准名称": "某规范"},
        ]
        items, reports = deduplicate(records)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["code"], "GB/T13808-1992")
        self.assertEqual(items[0]["count"], 2)
        self.assertEqual(items[1]["code"], "GJB/T 1-2020")
        self.assertEqual(items[1]["count"], 2)
        variant_reports = [report for report in reports if report["type"] == "待分类-写法变体合并"]
        self.assertEqual(len(variant_reports), 2)
        self.assertIn("GB13808-92", variant_reports[0]["detail"])
        self.assertFalse(any(report["type"] == "待分类-同名不同标准号" for report in reports))

    def test_deduplicate_keeps_same_name_with_different_year_or_code(self):
        records = [
            {"_row": 2, "标准号": "GB/T 2040-2017", "标准名称": "铜及铜合金板材"},
            {"_row": 3, "标准号": "GB/T2040-2002", "标准名称": "铜及铜合金板材"},
            {"_row": 4, "标准号": "GB/T 2-2020", "标准名称": "铜及铜合金板材"},
        ]
        items, reports = deduplicate(records)
        self.assertEqual(len(items), 3)
        self.assertFalse(any(report["type"] == "待分类-写法变体合并" for report in reports))
        same_name = [report for report in reports if report["type"] == "待分类-同名不同标准号"]
        self.assertEqual(len(same_name), 1)
        self.assertEqual(same_name[0]["count"], 3)

    def test_real_pending_catalog_dedups_to_179(self):
        path = Path(__file__).resolve().parents[1] / "data" / "待分类目录.xlsx"
        if not path.exists():
            self.skipTest("真实待分类目录不存在")
        items, reports = load_pending(path)
        self.assertEqual(len(items), 179)
        self.assertTrue(any(report["type"] == "待分类-写法变体合并" for report in reports))


if __name__ == "__main__":
    unittest.main()

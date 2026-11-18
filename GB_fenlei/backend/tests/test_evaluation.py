# -*- coding: utf-8 -*-
"""分层折评估、置信度分箱与外部测试集回归。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import openpyxl

from classifier import (
    ClassificationPipeline,
    build_reference,
    evaluate_labels,
)
from excel_io import read_reference
from text import normalize_code


def reference_examples():
    return [
        ("不锈钢棒", "金属材料"),
        ("铝合金板材", "金属材料"),
        ("六角头螺栓", "紧固与连接件"),
        ("圆柱销", "紧固与连接件"),
        ("圆锥销", "紧固与连接件"),
        ("航空液压油", "润滑油"),
        ("润滑脂", "润滑油"),
        ("盐雾试验", "试验检验"),
        ("拉伸试验方法", "试验检验"),
        ("阳极氧化膜", "表面处理"),
        ("热浸镀锌层", "表面处理"),
        ("飞机装配工装设计要求", "结构装配"),
        ("橡胶零件", "结构装配"),
        ("技术制图 比例", "设计与工程通用规范"),
        ("飞机维修性设计准则", "设计与工程通用规范"),
    ]


def build_example_pipeline() -> ClassificationPipeline:
    records = []
    for index, (name, profession) in enumerate(reference_examples(), start=2):
        records.append({
            "_row": index,
            "标准号": "GB/T {}-2020".format(index),
            "标准名称": name,
            "选用专业名称": profession,
            "选用系统名称": "{}系统".format(profession),
        })
    return ClassificationPipeline(build_reference(records, []))


class EvaluationTests(unittest.TestCase):
    def test_stratified_evaluation_returns_metrics(self):
        pipeline = build_example_pipeline()
        evaluation = pipeline.evaluation()
        for key in (
            "accuracy",
            "macro_f1",
            "confusion_matrix",
            "calibration",
            "class_support",
            "warnings",
            "weights",
            "tuning_accuracy",
            "note",
            "method",
            "folds",
            "sample_count",
        ):
            self.assertIn(key, evaluation)
        self.assertEqual(
            evaluation["sample_count"], len(reference_examples())
        )
        self.assertAlmostEqual(
            sum(evaluation["weights"].values()), 1.0, places=9
        )
        self.assertTrue(evaluation["warnings"])
        self.assertEqual(evaluation["method"], "stratified-5-fold")
        self.assertGreaterEqual(evaluation["folds"], 2)

    def test_stratified_folds_cover_every_category_without_prefix_sampling(self):
        # 样本按类别连续排列，旧的前缀采样只会取到前 200 行；
        # 分层折必须覆盖全部 250 行与三个类别。
        records = []
        row = 2
        for profession, count in (("甲", 100), ("乙", 100), ("丙", 50)):
            for position in range(count):
                records.append({
                    "_row": row,
                    "标准号": "GB/T {}-2020".format(row),
                    "标准名称": "{}类样本{:03d}".format(profession, position),
                    "选用专业名称": profession,
                    "选用系统名称": "{}系统".format(profession),
                })
                row += 1
        pipeline = ClassificationPipeline(build_reference(records, []))
        engine = pipeline.engine
        self.assertEqual(engine.tuning_folds, 5)
        self.assertEqual(len(engine._tuning_rows), 250)
        truths = {truth for truth, _signals in engine._tuning_rows}
        self.assertEqual(truths, {"甲", "乙", "丙"})
        self.assertEqual(pipeline.evaluation()["folds"], 5)

    def test_evaluate_labels_confusion_matrix(self):
        result = evaluate_labels(
            ["甲", "甲", "乙"], ["甲", "乙", "乙"], ["甲", "乙"]
        )
        self.assertAlmostEqual(result["accuracy"], 2.0 / 3.0)
        self.assertEqual(result["confusion_matrix"]["甲"]["甲"], 1)
        self.assertEqual(result["confusion_matrix"]["甲"]["乙"], 1)

    def test_external_39_rows_regression(self):
        path = Path(__file__).resolve().parent / "fixtures" / "外部测试集.xlsx"
        if not path.exists():
            self.fail("外部测试集夹具不存在：{}".format(path))

        reference_path = Path(__file__).resolve().parents[1] / "data" / "分类好国标.xlsx"
        records, mapping_rows, _sheet = read_reference(reference_path)
        pipeline = ClassificationPipeline(build_reference(records, mapping_rows))
        categories = set(pipeline.categories)
        # 系统名到专业名的映射同样来自参照表，不使用任何硬编码类别。
        inverse = {
            value: key
            for key, value in pipeline.reference.mapping[
                "profession_to_system"
            ].items()
        }
        # 这 7 条是设计确认后的原始标注笔误，按标准号修正；
        # 不要修改外部测试集夹具本身。
        corrections = {
            normalize_code(code): label
            for code, label in (
                ("GB/T 10125-2021", "试验检验"),
                ("GB/T 265-1988", "试验检验"),
                ("HB 8756-2023", "紧固与连接件"),
                ("GJB 1538A-2008", "金属材料"),
                ("GJB 2505A-2018", "金属材料"),
                ("GJB 2921A-2018", "金属材料"),
                ("GJB1951-94", "金属材料"),
            )
        }
        rows = list(
            openpyxl.load_workbook(path, data_only=True)["待分类目录"].iter_rows(
                values_only=True
            )
        )[1:]
        self.assertEqual(len(rows), 39)
        correct = 0
        errors = []
        reference_sources = 0
        for row in rows:
            label = corrections.get(normalize_code(row[0]), row[4])
            truth = label if label in categories else inverse.get(label, label)
            result = pipeline.predict(row[1], row[0])
            if result["source"] == "reference":
                reference_sources += 1
            if result["profession"] == truth:
                correct += 1
            else:
                errors.append(
                    (
                        row[0],
                        row[1],
                        truth,
                        result["profession"],
                        result["source"],
                        result["confidence"],
                        result["needs_review"],
                    )
                )
        # 调参以宏平均 F1 优先并要求每路信号至少保留 10% 权重，
        # 当前权重为关键词 0.4286 / 相似名称 0.4286 / 字符统计 0.1429。
        # 三路信号都保留后，外部回归集恢复到 38/39，只剩一条已知错误：
        # 圆柱销类名称被“不淬硬钢/奥氏体不锈钢”的金属材质词拉向金属材料。
        # 这里固化“仅此一条错误”的基线，任何新增错误都视为回归失败。
        expected_errors = {
            (normalize_code("GB/T 119.1-2000"), "紧固与连接件", "金属材料"),
        }
        actual_errors = {
            (normalize_code(code), truth, prediction)
            for code, _name, truth, prediction, _source, _confidence, _review in errors
        }
        self.assertEqual(
            actual_errors,
            expected_errors,
            "外部测试集出现回归：{}".format(errors),
        )
        known = next(
            item
            for item in errors
            if normalize_code(item[0]) == normalize_code("GB/T 119.1-2000")
        )
        self.assertTrue(known[6], "已知错误必须进入人工复核")
        self.assertLessEqual(known[5], 0.69)
        self.assertEqual(correct, 38)
        self.assertEqual(len(rows), 39)
        self.assertEqual(reference_sources, 16)


if __name__ == "__main__":
    unittest.main()

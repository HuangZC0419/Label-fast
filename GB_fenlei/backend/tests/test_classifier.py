# -*- coding: utf-8 -*-
"""参照表校验、冲突检测与纯统计分类引擎的单元测试。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from classifier import ClassificationPipeline, build_reference
from excel_io import read_reference
from text import normalize_name


def record(code, name, profession, system, row=2):
    return {
        "_row": row,
        "标准号": code,
        "标准名称": name,
        "选用专业名称": profession,
        "选用系统名称": system,
    }


def reference_records():
    pairs = [
        ("结构装配", "机体装配技术", "飞机装配工装设计要求", "航空橡胶零件胶料规范"),
        ("金属材料", "航空金属材料技术", "不锈钢棒", "铝合金板材"),
        ("紧固与连接件", "机械连接与紧固技术", "六角头螺栓", "自锁螺母"),
        ("润滑油", "航空润滑与流体介质技术", "航空液压油", "润滑脂"),
        ("试验检验", "质量检验与试验技术", "盐雾试验方法", "硬度试验"),
        ("表面处理", "表面工程与防护技术", "阳极氧化膜", "热浸镀锌层"),
        ("设计与工程通用规范", "工程设计与标准化技术", "机械制图尺寸标注", "飞机维修性设计准则"),
    ]
    records = []
    row = 2
    for profession, system, first, second in pairs:
        records.append(record("GB/T {}-2020".format(row), first, profession, system, row))
        row += 1
        records.append(record("GB/T {}-2020".format(row), second, profession, system, row))
        row += 1
    return records


class ReferenceTests(unittest.TestCase):
    def test_mapping_detects_profession_and_system_not_one_to_one(self):
        records = [
            record("GB/T 1-2020", "甲", "金属材料", "航空金属材料技术", 2),
            record("GB/T 2-2020", "乙", "金属材料", "航空金属材料技术", 3),
            record("GB/T 3-2020", "丙", "金属材料", "材料第二系统", 4),
            record("GB/T 4-2020", "丁", "结构装配", "航空金属材料技术", 5),
        ]
        reference = build_reference(records, [])
        self.assertFalse(reference.mapping["is_one_to_one"])
        self.assertEqual(reference.mapping["profession_to_system"]["金属材料"], "航空金属材料技术")
        types = {issue["type"] for issue in reference.mapping["issues"]}
        self.assertIn("专业对应多个系统", types)
        self.assertIn("系统对应多个专业", types)

    def test_mapping_sheet_mismatch_is_reported(self):
        records = [
            record("GB/T 1-2020", "甲", "金属材料", "航空金属材料技术", 2),
            record("GB/T 2-2020", "乙", "结构装配", "机体装配技术", 3),
        ]
        mapping_rows = [
            {"选用专业名称": "金属材料", "选用系统名称": "错误的系统"},
            {"选用专业名称": "结构装配", "选用系统名称": "机体装配技术"},
        ]
        reference = build_reference(records, mapping_rows)
        types = {issue["type"] for issue in reference.mapping["issues"]}
        self.assertIn("映射表与总表不一致", types)

    def test_duplicate_code_conflict_rows_are_excluded_from_training(self):
        records = [
            record("GB/T 1-2020", "同一个名称", "金属材料", "航空金属材料技术", 2),
            record("GB/T 1-2020", "同一个名称", "金属材料", "航空金属材料技术", 3),
            record("GB/T 1-2020", "同一个名称", "结构装配", "机体装配技术", 4),
            record("GB/T 2-2020", "干净样本", "润滑油", "航空润滑与流体介质技术", 5),
        ]
        reference = build_reference(records, [])
        conflict = next(
            item for item in reference.conflicts
            if item["type"] == "同号同名不同分类"
        )
        self.assertEqual(conflict["count"], 3)
        self.assertEqual(conflict["rows"], [2, 3, 4])
        self.assertEqual(reference.excluded_rows, [2, 3, 4])
        training_names = {name for name, _profession in reference.training_examples}
        self.assertNotIn("同一个名称", training_names)
        self.assertIn("干净样本", training_names)
        self.assertTrue(reference.warnings)

    def test_ambiguous_name_is_excluded_but_unambiguous_name_is_kept(self):
        records = [
            record("GB/T 1-2020", "甲", "金属材料", "航空金属材料技术", 2),
            record("GB/T 2-2020", "甲", "结构装配", "机体装配技术", 3),
            record("GB/T 3-2020", "乙", "润滑油", "航空润滑与流体介质技术", 4),
        ]
        reference = build_reference(records, [])
        self.assertTrue(
            any(conflict["type"] == "同名不同分类" for conflict in reference.conflicts)
        )
        names = {name for name, _profession in reference.training_examples}
        self.assertNotIn("甲", names)
        self.assertIn("乙", names)

    def test_same_code_different_name_different_profession_is_excluded(self):
        records = [
            record("GB/T 1-2020", "名称甲", "金属材料", "航空金属材料技术", 2),
            record("GB/T 1-2020", "名称乙", "结构装配", "机体装配技术", 3),
            record("GB/T 2-2020", "干净样本", "润滑油", "航空润滑与流体介质技术", 4),
        ]
        reference = build_reference(records, [])
        self.assertTrue(
            any(conflict["type"] == "同号不同分类" for conflict in reference.conflicts)
        )
        names = {name for name, _profession in reference.training_examples}
        self.assertEqual(names, {"干净样本"})
        self.assertEqual(reference.excluded_rows, [2, 3])

    def test_same_name_same_profession_different_system_is_not_excluded(self):
        records = [
            record("GB/T 1-2020", "相同名称", "金属材料", "系统甲", 2),
            record("GB/T 1-2020", "相同名称", "金属材料", "系统乙", 3),
            record("GB/T 2-2020", "干净样本", "润滑油", "系统丙", 4),
        ]
        reference = build_reference(records, [])
        self.assertEqual(reference.excluded_rows, [])
        names = {name for name, _profession in reference.training_examples}
        self.assertIn("相同名称", names)
        self.assertIn(normalize_name("相同名称"), reference.by_name)

    def test_training_examples_are_unique_by_name(self):
        records = [
            record("GB/T 1-2020", "甲", "金属材料", "航空金属材料技术", 2),
            record("GB/T 2-2020", "甲", "金属材料", "航空金属材料技术", 3),
        ]
        reference = build_reference(records, [])
        self.assertEqual(len(reference.training_examples), 1)

    def test_categories_are_fully_dynamic(self):
        records = [
            record("GB/T 1-2020", "甲样本", "甲", "系统甲", 2),
            record("GB/T 2-2020", "乙样本", "乙", "系统乙", 3),
            record("GB/T 3-2020", "丙样本", "丙", "系统丙", 4),
            record("GB/T 4-2020", "甲样本二", "甲", "系统甲", 5),
            record("GB/T 5-2020", "乙样本二", "乙", "系统乙", 6),
            record("GB/T 6-2020", "丙样本二", "丙", "系统丙", 7),
        ]
        reference = build_reference(records, [])
        self.assertEqual(set(reference.categories), {"甲", "乙", "丙"})

        pipeline = ClassificationPipeline(reference)
        self.assertEqual(set(pipeline.categories), {"甲", "乙", "丙"})
        self.assertEqual(set(pipeline.weights), {"term", "knn", "nb"})
        self.assertAlmostEqual(sum(pipeline.weights.values()), 1.0, places=9)

        result = pipeline.predict("甲样本三")
        self.assertIn(result["profession"], reference.categories)
        self.assertIn(result["evidence_level"], ("ensemble", "term", "similar", "nb"))


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.reference = build_reference(reference_records(), [])
        self.pipeline = ClassificationPipeline(self.reference)

    def test_exact_code_match_returns_reference_profession_with_high_confidence(self):
        result = self.pipeline.predict("完全没见过的名称", "GB/T 2-2020")
        self.assertEqual(result["profession"], "结构装配")
        self.assertTrue(result["method"].startswith("参照表"))
        self.assertGreaterEqual(result["confidence"], 0.9)

    def test_exact_name_match_returns_reference_profession(self):
        result = self.pipeline.predict("不锈钢棒")
        self.assertEqual(result["profession"], "金属材料")
        self.assertEqual(result["source"], "reference")

    def test_low_support_reference_hit_still_needs_review(self):
        # 精确命中不改变预测，但类别样本少于阈值时必须提示复核。
        for name, code in (("不锈钢棒", ""), ("完全没见过的名称", "GB/T 2-2020")):
            result = self.pipeline.predict(name, code)
            self.assertEqual(result["source"], "reference")
            self.assertTrue(result["needs_review"], name)
            support = self.pipeline.class_support.get(result["profession"], 0)
            self.assertLess(support, 10)
            # 精确命中的置信度本身仍然较高，复核来自样本量而非低置信度。
            self.assertGreaterEqual(result["confidence"], 0.90)

    def test_statistical_prediction_has_confidence_and_top_three(self):
        result = self.pipeline.predict("钛合金板材")
        self.assertIn(
            result["evidence_level"], ("ensemble", "term", "similar", "nb")
        )
        self.assertIn(result["profession"], self.reference.categories)
        self.assertGreaterEqual(result["confidence"], 0.0)
        self.assertLessEqual(result["confidence"], 0.95)
        self.assertEqual(len(result["top3"]), 3)
        self.assertTrue(result["evidence"])

    def test_evaluation_reports_statistical_metrics(self):
        evaluation = self.pipeline.evaluation()
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
        self.assertGreaterEqual(evaluation["accuracy"], 0.0)
        self.assertLessEqual(evaluation["accuracy"], 1.0)
        self.assertEqual(set(evaluation["weights"]), {"term", "knn", "nb"})
        self.assertAlmostEqual(
            sum(evaluation["weights"].values()), 1.0, places=9
        )
        self.assertEqual(evaluation["method"], "stratified-5-fold")
        self.assertGreaterEqual(evaluation["folds"], 2)
        self.assertEqual(
            evaluation["sample_count"],
            len(self.reference.training_examples),
        )

    def test_top3_score_is_monotonic_with_probability(self):
        result = self.pipeline.predict("某种未见过的高温合金棒材")
        probabilities = [item["probability"] for item in result["top3"]]
        scores = [item["score"] for item in result["top3"]]
        self.assertEqual(probabilities, sorted(probabilities, reverse=True))
        self.assertEqual(scores, sorted(scores, reverse=True))
        for item in result["top3"]:
            self.assertAlmostEqual(
                item["score"],
                item["probability"] * 8.0,
                places=4,
            )

    def test_confidence_is_capped(self):
        for name in ("钛合金板材", "六角头螺栓", "阳极氧化膜"):
            result = self.pipeline.predict(name)
            self.assertLessEqual(result["confidence"], 0.95)
            self.assertLessEqual(max(item["probability"] for item in result["top3"]), 0.95)
            self.assertLessEqual(sum(item["probability"] for item in result["top3"]), 1.0 + 1e-6)

    def test_prediction_confidence_and_top3_are_well_formed(self):
        result = self.pipeline.predict("某种未见过的高温合金棒材")
        self.assertIn(result["profession"], self.reference.categories)
        self.assertTrue(0.0 <= result["confidence"] <= 1.0)
        self.assertEqual(len(result["top3"]), 3)
        probabilities = [item["probability"] for item in result["top3"]]
        self.assertEqual(probabilities, sorted(probabilities, reverse=True))
        self.assertTrue(all(0.0 <= value <= 1.0 for value in probabilities))
        self.assertIn(
            result["source"], ("reference", "ensemble", "term", "knn", "nb", "manual")
        )
        self.assertEqual(
            result["top3"][0]["profession"], result["profession"]
        )


class RealReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "data" / "分类好国标.xlsx"
        if not path.exists():
            raise unittest.SkipTest("真实参照表不存在")
        records, mapping, _sheet = read_reference(path)
        cls.pipeline = ClassificationPipeline(build_reference(records, mapping))

    def test_surface_treatment_sample_is_classified(self):
        result = self.pipeline.predict("阳极氧化膜")
        self.assertEqual(result["profession"], "表面处理")
        self.assertIn(
            result["source"], ("ensemble", "term", "knn", "nb")
        )
        self.assertTrue(result["evidence"])
        self.assertGreaterEqual(result["confidence"], 0.60)

    def test_stratified_evaluation_meets_statistical_baseline(self):
        evaluation = self.pipeline.evaluation()
        # 纯统计引擎的评估准确率明显低于原规则引擎，这里只守住合理下限。
        self.assertGreaterEqual(evaluation["accuracy"], 0.50)
        self.assertGreaterEqual(evaluation["macro_f1"], 0.40)
        self.assertAlmostEqual(
            sum(evaluation["weights"].values()), 1.0, places=9
        )
        self.assertEqual(evaluation["sample_count"], 103)
        self.assertEqual(evaluation["method"], "stratified-5-fold")
        self.assertGreaterEqual(evaluation["folds"], 2)


if __name__ == "__main__":
    unittest.main()

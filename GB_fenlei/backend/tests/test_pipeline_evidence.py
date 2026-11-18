# -*- coding: utf-8 -*-
"""统计集成证据链、置信度、Top3 与待复核标记。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from classifier import ClassificationPipeline, EvidenceEngine, build_reference
from config import ENSEMBLE_MIN_WEIGHT, LOW_SUPPORT_THRESHOLD
from text import char_ngrams


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
        ("结构装配", "机体装配技术", ["飞机装配工装设计要求", "航空橡胶零件胶料规范"]),
        ("金属材料", "航空金属材料技术", ["不锈钢棒", "铝合金板材"]),
        ("紧固与连接件", "机械连接与紧固技术", ["六角头螺栓", "自锁螺母", "圆柱销"]),
        ("润滑油", "航空润滑与流体介质技术", ["航空液压油", "润滑脂"]),
        ("试验检验", "质量检验与试验技术", ["盐雾试验", "硬度试验"]),
        ("表面处理", "表面工程与防护技术", ["阳极氧化膜", "热浸镀锌层"]),
        ("设计与工程通用规范", "工程设计与标准化技术", ["机械制图尺寸标注", "飞机维修性设计准则"]),
    ]
    records = []
    row = 2
    for profession, system, names in pairs:
        for name in names:
            records.append(record("GB/T {}-2020".format(row), name, profession, system, row))
            row += 1
    return records


STATISTICAL_LEVELS = ("ensemble", "term", "similar", "nb")


class EvidenceEngineTests(unittest.TestCase):
    def setUp(self):
        self.reference = build_reference(reference_records(), [])
        self.engine = EvidenceEngine(
            self.reference.training_examples,
            self.reference.categories,
            self.reference.system_map,
        )

    def test_statistical_prediction_has_evidence_and_level(self):
        result = self.engine.predict_name("内六角圆柱头螺钉")
        self.assertEqual(result["profession"], "紧固与连接件")
        self.assertIn(result["evidence_level"], STATISTICAL_LEVELS)
        self.assertIn(result["source"], ("ensemble", "term", "knn", "nb"))
        self.assertTrue(result["evidence"])
        self.assertTrue(result["evidence_detail"])
        self.assertLessEqual(result["confidence"], 0.95)

    def test_similarity_fallback_when_term_evidence_is_missing(self):
        result = self.engine.predict_name("未见过的高强度连接件")
        self.assertIn(result["evidence_level"], STATISTICAL_LEVELS)
        self.assertTrue(result["evidence"])

    def test_unseen_name_is_capped_and_needs_review(self):
        result = self.engine.predict_name("zzzzqqqqxxxx")
        self.assertIn(result["evidence_level"], STATISTICAL_LEVELS)
        # 每个类别样本都少于阈值，置信度被压到 0.75 以下并强制复核。
        self.assertLessEqual(result["confidence"], 0.75)
        self.assertTrue(result["needs_review"])
        self.assertTrue(result["evidence"])

    def test_top3_is_well_formed(self):
        result = self.engine.predict_name("六角螺栓")
        self.assertEqual(len(result["top3"]), 3)
        probabilities = [item["probability"] for item in result["top3"]]
        scores = [item["score"] for item in result["top3"]]
        self.assertEqual(probabilities, sorted(probabilities, reverse=True))
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertLessEqual(sum(probabilities), 1.0 + 1e-6)
        for item in result["top3"]:
            self.assertIn("profession", item)
            self.assertIn("score", item)
            self.assertAlmostEqual(
                item["score"], item["probability"] * 8.0, places=4
            )

    def test_top_contributions_only_use_query_ngrams(self):
        contributions = self.engine.nb.top_contributions(
            "六角头螺栓", "紧固与连接件", 5
        )
        self.assertTrue(contributions)
        query_grams = set(char_ngrams("六角头螺栓", (2, 3)))
        for gram, _score in contributions:
            self.assertIn(gram, query_grams)
        scores = [score for _gram, score in contributions]
        self.assertEqual(scores, sorted(scores, reverse=True))
        # 结果确定：同样输入重复查询完全一致。
        self.assertEqual(
            contributions,
            self.engine.nb.top_contributions("六角头螺栓", "紧固与连接件", 5),
        )
        self.assertEqual(
            self.engine.nb.top_contributions("钢", "紧固与连接件", 5), []
        )

    def test_nb_evidence_shows_query_grams(self):
        original = dict(self.engine.weights)
        self.engine.weights = {"term": 0.0, "knn": 0.0, "nb": 1.0}
        try:
            result = self.engine.predict_name("六角头螺栓")
        finally:
            self.engine.weights = original
        line = next(
            item for item in result["evidence"]
            if item.startswith("字符统计：")
        )
        listed = set(line.split("：", 1)[1].split("/"))
        self.assertTrue(listed)
        self.assertTrue(
            listed.issubset(set(char_ngrams("六角头螺栓", (2, 3))))
        )

    def test_nb_evidence_falls_back_when_query_has_no_ngrams(self):
        original = dict(self.engine.weights)
        self.engine.weights = {"term": 0.0, "knn": 0.0, "nb": 1.0}
        try:
            result = self.engine.predict_name("钢")
        finally:
            self.engine.weights = original
        self.assertTrue(
            any(
                item.startswith("类别高概率 n-gram：")
                for item in result["evidence"]
            )
        )

    def test_knn_evidence_includes_neighbor_category(self):
        neighbors = self.engine.similarity.query("内六角圆柱头螺钉")
        self.assertTrue(neighbors)
        lines = self.engine._format_neighbors(neighbors)
        self.assertIn("相似标准：", lines[0])
        self.assertIn(neighbors[0].profession, lines[0])

    def test_weights_sum_to_one_and_cover_all_signals(self):
        self.assertEqual(set(self.engine.weights), {"term", "knn", "nb"})
        self.assertAlmostEqual(
            sum(self.engine.weights.values()), 1.0, places=9
        )
        for weight in self.engine.weights.values():
            self.assertGreaterEqual(weight, 0.0)
            self.assertLessEqual(weight, 1.0)

    def test_no_weight_below_min_weight(self):
        # 调参以宏平均 F1 优先，但每路信号都必须保留最小权重，
        # 避免把某一路压到 0 后丢掉外部回归集上的纠错能力。
        for key, weight in self.engine.weights.items():
            self.assertGreaterEqual(
                weight,
                ENSEMBLE_MIN_WEIGHT - 1e-12,
                "信号 {} 的权重 {} 低于最小值 {}".format(
                    key, weight, ENSEMBLE_MIN_WEIGHT
                ),
            )
        evaluation = self.engine.evaluate()
        self.assertAlmostEqual(
            sum(evaluation["weights"].values()), 1.0, places=9
        )
        for weight in evaluation["weights"].values():
            self.assertGreaterEqual(weight, ENSEMBLE_MIN_WEIGHT - 1e-12)

    def test_class_support_counts_training_examples(self):
        self.assertEqual(
            dict(self.engine.class_support),
            {
                "结构装配": 2,
                "金属材料": 2,
                "紧固与连接件": 3,
                "润滑油": 2,
                "试验检验": 2,
                "表面处理": 2,
                "设计与工程通用规范": 2,
            },
        )

    def test_low_support_categories_produce_warnings(self):
        evaluation = self.engine.evaluate()
        self.assertTrue(evaluation["warnings"])
        for category, count in evaluation["class_support"].items():
            if count < LOW_SUPPORT_THRESHOLD:
                self.assertTrue(
                    any(category in warning for warning in evaluation["warnings"])
                )
        self.assertAlmostEqual(
            sum(evaluation["weights"].values()), 1.0, places=9
        )
        self.assertIn("note", evaluation)
        self.assertIn("tuning_accuracy", evaluation)


class PipelineEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = ClassificationPipeline(build_reference(reference_records(), []))

    def test_reference_code_beats_statistics(self):
        result = self.pipeline.predict("完全陌生的名称", "GB/T 2-2020")
        self.assertEqual(result["evidence_level"], "reference")
        self.assertEqual(result["profession"], "结构装配")
        self.assertGreaterEqual(result["confidence"], 0.90)

    def test_reference_name_beats_statistics(self):
        result = self.pipeline.predict("不锈钢棒")
        self.assertEqual(result["evidence_level"], "reference")
        self.assertEqual(result["profession"], "金属材料")

    def test_reference_hit_on_low_support_category_needs_review(self):
        result = self.pipeline.predict("不锈钢棒")
        self.assertEqual(result["source"], "reference")
        self.assertEqual(result["profession"], "金属材料")
        self.assertGreaterEqual(result["confidence"], 0.90)
        self.assertTrue(result["needs_review"])

    def test_confidence_never_exceeds_cap(self):
        for name in ("六角头螺栓", "阳极氧化膜", "不锈钢棒"):
            result = self.pipeline.predict(name)
            self.assertLessEqual(result["confidence"], 0.95)

    def test_low_support_result_is_marked_for_review(self):
        result = self.pipeline.predict("zzzzqqqqxxxx")
        self.assertIn(result["evidence_level"], STATISTICAL_LEVELS)
        self.assertLessEqual(result["confidence"], 0.75)
        self.assertTrue(result["needs_review"])

    def test_signal_disagreement_forces_review(self):
        result = self.pipeline.predict("圆柱销 不淬硬钢和奥氏体不锈钢")
        self.assertTrue(result["needs_review"])
        self.assertLessEqual(result["confidence"], 0.69)
        self.assertTrue(
            any("信号分歧" in item for item in result["evidence"])
        )

    def test_evaluation_reports_new_fields(self):
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
        self.assertEqual(evaluation["method"], "stratified-5-fold")
        self.assertGreaterEqual(evaluation["folds"], 2)
        self.assertEqual(
            evaluation["sample_count"],
            len(self.pipeline.reference.training_examples),
        )

    def test_top3_invariants_for_reference_and_statistics(self):
        pipeline = ClassificationPipeline(build_reference(reference_records(), []))
        for name, code in (
            ("不锈钢棒", ""),
            ("六角头螺栓", ""),
            ("完全陌生的名称", "GB/T 2-2020"),
        ):
            result = pipeline.predict(name, code)
            probabilities = [item["probability"] for item in result["top3"]]
            self.assertEqual(len(probabilities), 3)
            self.assertEqual(probabilities, sorted(probabilities, reverse=True))
            self.assertLessEqual(max(probabilities), 0.95)
            self.assertLessEqual(sum(probabilities), 1.0 + 1e-6)
            self.assertEqual(
                result["top3"][0]["profession"], result["profession"]
            )

    def test_reference_top1_probability_matches_confidence(self):
        pipeline = ClassificationPipeline(build_reference(reference_records(), []))
        result = pipeline.predict("完全陌生的名称", "GB/T 2-2020")
        self.assertAlmostEqual(
            result["top3"][0]["probability"], result["confidence"], places=4
        )


if __name__ == "__main__":
    unittest.main()

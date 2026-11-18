# -*- coding: utf-8 -*-
"""统计词条（log-odds）、依据词表与相似名称索引。"""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mining import (
    LOW_SUPPORT_THRESHOLD,
    NameSimilarityIndex,
    keyword_report,
    mine_terms,
)


EXAMPLES = [
    ("阳极氧化膜", "表面处理"),
    ("铝合金阳极氧化膜", "表面处理"),
    ("热浸镀锌层", "表面处理"),
    ("六角头螺栓", "紧固与连接件"),
    ("圆柱销", "紧固与连接件"),
    ("圆锥销", "紧固与连接件"),
    ("不锈钢棒", "金属材料"),
    ("铝合金板材", "金属材料"),
    ("航空液压油", "润滑油"),
    ("航空润滑脂", "润滑油"),
]

# “航空”同时出现在两个类别，支持度满足但纯度不足，应被过滤。
CROSS_CLASS_EXAMPLES = [
    ("航空液压油", "润滑油"),
    ("航空润滑脂", "润滑油"),
    ("航空铝合金板", "金属材料"),
    ("航空不锈钢棒", "金属材料"),
    ("阳极氧化膜", "表面处理"),
    ("热浸镀锌层", "表面处理"),
]


class MinedTermTests(unittest.TestCase):
    def test_discriminative_term_has_positive_log_odds(self):
        mined = mine_terms(EXAMPLES)
        terms = {item.term: item for item in mined["表面处理"]}
        self.assertIn("阳极氧化", terms)
        self.assertEqual(terms["阳极氧化"].support, 2)
        self.assertEqual(terms["阳极氧化"].purity, 1.0)
        self.assertGreater(terms["阳极氧化"].log_odds, 0.0)

    def test_weight_is_length_adjusted_log_odds(self):
        mined = mine_terms(EXAMPLES)
        term = next(item for item in mined["表面处理"] if item.term == "阳极氧化")
        class_total = 3
        total = len(EXAMPLES)
        log_odds = math.log((2 + 0.5) / (class_total + 1)) - math.log(
            0.5 / (total - class_total + 1)
        )
        self.assertAlmostEqual(term.log_odds, log_odds, places=6)
        self.assertAlmostEqual(term.weight, log_odds * (1 + 0.1 * 2), places=6)

    def test_terms_are_sorted_by_weight_desc(self):
        mined = mine_terms(EXAMPLES)
        for items in mined.values():
            weights = [item.weight for item in items]
            self.assertEqual(weights, sorted(weights, reverse=True))

    def test_max_terms_caps_each_category(self):
        mined = mine_terms(EXAMPLES, max_terms=2)
        for items in mined.values():
            self.assertLessEqual(len(items), 2)
        self.assertEqual(len(mined["表面处理"]), 2)

    def test_cross_class_low_purity_terms_are_filtered(self):
        mined = mine_terms(CROSS_CLASS_EXAMPLES)
        all_terms = {item.term for items in mined.values() for item in items}
        self.assertNotIn("航空", all_terms)
        for items in mined.values():
            for item in items:
                self.assertGreaterEqual(item.purity, 0.8)
                self.assertGreater(item.log_odds, 0.0)


class KeywordReportTests(unittest.TestCase):
    def test_report_is_purely_statistical(self):
        mined = mine_terms(EXAMPLES)
        report = keyword_report(
            mined, EXAMPLES, {"表面处理": "表面工程与防护技术"}
        )
        group = next(item for item in report if item["profession"] == "表面处理")
        self.assertEqual(group["system"], "表面工程与防护技术")
        self.assertEqual(group["class_support"], 3)
        self.assertTrue(group["warning"])
        self.assertTrue(group["keywords"])
        self.assertEqual(
            {item["source"] for item in group["keywords"]}, {"statistical"}
        )
        first = group["keywords"][0]
        for field in (
            "term",
            "support",
            "purity",
            "log_odds",
            "weight",
            "source",
            "examples",
        ):
            self.assertIn(field, first)
        self.assertGreater(first["log_odds"], 0.0)
        self.assertTrue(first["examples"])
        self.assertTrue(group["top_examples"])

    def test_report_includes_all_categories_sorted_by_profession(self):
        mined = mine_terms(EXAMPLES)
        report = keyword_report(mined, EXAMPLES, {})
        names = [item["profession"] for item in report]
        self.assertEqual(names, sorted(names))
        self.assertEqual(set(names), {label for _name, label in EXAMPLES})

    def test_category_without_mined_terms_is_still_reported(self):
        examples = [("销", "紧固与连接件"), ("阳极氧化膜", "表面处理")]
        mined = mine_terms(examples)
        report = keyword_report(mined, examples, {})
        group = next(item for item in report if item["profession"] == "紧固与连接件")
        self.assertEqual(group["keywords"], [])
        self.assertEqual(group["class_support"], 1)
        self.assertTrue(group["warning"])

    def test_single_example_category_warns(self):
        examples = [
            ("阳极氧化膜", "表面处理"),
            ("六角头螺栓", "紧固与连接件"),
        ]
        mined = mine_terms(examples)
        report = keyword_report(mined, examples, {})
        self.assertEqual(len(report), 2)
        for group in report:
            self.assertEqual(group["class_support"], 1)
            self.assertLess(group["class_support"], LOW_SUPPORT_THRESHOLD)
            self.assertEqual(
                group["warning"],
                f"样本少于 {LOW_SUPPORT_THRESHOLD} 条，统计结果不稳定",
            )

    def test_enough_samples_have_no_warning(self):
        examples = [
            (f"阳极氧化膜试样{index}", "表面处理")
            for index in range(LOW_SUPPORT_THRESHOLD)
        ]
        mined = mine_terms(examples)
        report = keyword_report(mined, examples, {})
        self.assertEqual(report[0]["class_support"], LOW_SUPPORT_THRESHOLD)
        self.assertEqual(report[0]["warning"], "")

    def test_max_keywords_caps_report(self):
        mined = mine_terms(EXAMPLES)
        report = keyword_report(mined, EXAMPLES, {}, max_keywords=1)
        for group in report:
            self.assertLessEqual(len(group["keywords"]), 1)


class NameSimilarityTests(unittest.TestCase):
    def test_similarity_returns_same_class_neighbor(self):
        index = NameSimilarityIndex(EXAMPLES)
        neighbors = index.query("六角螺栓", top_k=3)
        self.assertTrue(neighbors)
        self.assertEqual(neighbors[0].profession, "紧固与连接件")
        self.assertGreater(neighbors[0].similarity, 0.0)

    def test_similarity_filters_unrelated_names(self):
        index = NameSimilarityIndex(EXAMPLES)
        self.assertEqual(index.query("完全无关的量子计算协议"), [])

    def test_similarity_uses_construction_ngram_sizes(self):
        index = NameSimilarityIndex(EXAMPLES, sizes=(4,))
        neighbors = index.query("阳极氧化膜", top_k=3)
        self.assertTrue(neighbors)

    def test_similarity_min_threshold_filters_all(self):
        index = NameSimilarityIndex(EXAMPLES)
        self.assertEqual(index.query("六角螺栓", min_similarity=0.99), [])


class EmptyInputTests(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(mine_terms([]), {})
        self.assertEqual(keyword_report({}, [], {}), [])
        self.assertEqual(NameSimilarityIndex([]).query("任意名称"), [])


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""统计模型层测试：字符 n-gram 贝叶斯与集成权重搜索。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import ENSEMBLE_MIN_WEIGHT
from statistical import (
    NaiveBayesNgram,
    combine_signals,
    evaluate_ensemble,
    tune_ensemble_weights,
)

METAL = "金属材料"
FASTENER = "紧固件"
LUBRICANT = "润滑油"

CATEGORIES = [METAL, FASTENER, LUBRICANT]

TRAINING = [
    ("钛合金棒材", METAL),
    ("铝合金板材", METAL),
    ("结构钢棒", METAL),
    ("铜合金丝材", METAL),
    ("镁合金锻件", METAL),
    ("镍基合金板", METAL),
    ("六角头螺栓", FASTENER),
    ("内六角螺钉", FASTENER),
    ("自攻螺钉", FASTENER),
    ("六角螺母", FASTENER),
    ("平垫圈", FASTENER),
    ("开口销", FASTENER),
    ("航空发动机润滑油", LUBRICANT),
    ("液压油", LUBRICANT),
    ("齿轮油", LUBRICANT),
    ("润滑脂", LUBRICANT),
    ("防锈油", LUBRICANT),
    ("机械油", LUBRICANT),
]

# 三个信号在每条样本上的概率；term / knn 各对一半样本正确，nb 也是 50%。
# term + knn 等权融合可以做到全对，因此搜索应不劣于任何单信号。
ROWS = [
    (
        "甲",
        {
            "term": {"甲": 0.9, "乙": 0.1},
            "knn": {"甲": 0.2, "乙": 0.8},
            "nb": {"甲": 0.6, "乙": 0.4},
        },
    ),
    (
        "乙",
        {
            "term": {"甲": 0.8, "乙": 0.2},
            "knn": {"甲": 0.1, "乙": 0.9},
            "nb": {"甲": 0.4, "乙": 0.6},
        },
    ),
    (
        "甲",
        {
            "term": {"甲": 0.8, "乙": 0.2},
            "knn": {"甲": 0.35, "乙": 0.65},
            "nb": {"甲": 0.45, "乙": 0.55},
        },
    ),
    (
        "乙",
        {
            "term": {"甲": 0.7, "乙": 0.3},
            "knn": {"甲": 0.2, "乙": 0.8},
            "nb": {"甲": 0.55, "乙": 0.45},
        },
    ),
]

BINARY_CATEGORIES = ["甲", "乙"]
SIGNAL_KEYS = {"term", "knn", "nb"}


class NaiveBayesNgramTests(unittest.TestCase):
    def setUp(self):
        self.model = NaiveBayesNgram(TRAINING, CATEGORIES)

    def test_separates_three_toy_classes(self):
        correct = 0
        for name, label in TRAINING:
            probabilities = self.model.predict_proba(name)
            prediction = max(probabilities, key=probabilities.get)
            if prediction == label:
                correct += 1
        accuracy = correct / len(TRAINING)
        self.assertGreaterEqual(accuracy, 0.9)

    def test_predict_proba_sums_to_one_and_is_deterministic(self):
        first = self.model.predict_proba("六角头螺栓")
        second = self.model.predict_proba("六角头螺栓")

        self.assertEqual(first, second)
        self.assertEqual(set(first), set(CATEGORIES))
        self.assertAlmostEqual(sum(first.values()), 1.0, places=12)
        for probability in first.values():
            self.assertGreaterEqual(probability, 0.0)
            self.assertLessEqual(probability, 1.0)

    def test_top_grams_returns_evidence_for_category(self):
        grams = self.model.top_grams(LUBRICANT, limit=3)

        self.assertTrue(grams)
        self.assertLessEqual(len(grams), 3)
        self.assertEqual(grams, self.model.top_grams(LUBRICANT, limit=3))
        self.assertEqual(grams[0][0], "润滑")
        scores = [score for _, score in grams]
        self.assertEqual(scores, sorted(scores, reverse=True))
        for gram, score in grams:
            self.assertIsInstance(gram, str)
            self.assertIsInstance(score, float)

    def test_empirical_prior_uses_class_frequency(self):
        model = NaiveBayesNgram(
            [
                ("甲类样本", "甲"),
                ("甲类样本二", "甲"),
                ("乙类样本", "乙"),
            ],
            ["甲", "乙"],
            uniform_prior=False,
        )
        # 空名称没有 n-gram，后验退化为类别先验。
        probabilities = model.predict_proba("")
        self.assertAlmostEqual(probabilities["甲"], 2.0 / 3.0, places=12)
        self.assertAlmostEqual(probabilities["乙"], 1.0 / 3.0, places=12)

    def test_one_class_and_empty_examples_do_not_crash(self):
        single = NaiveBayesNgram([("钛合金棒材", "金属")], ["金属"])
        probabilities = single.predict_proba("钛合金棒材")
        self.assertEqual(set(probabilities), {"金属"})
        self.assertAlmostEqual(probabilities["金属"], 1.0, places=12)
        self.assertTrue(single.top_grams("金属"))

        empty = NaiveBayesNgram([], BINARY_CATEGORIES)
        uniform = empty.predict_proba("任意名称")
        self.assertEqual(set(uniform), set(BINARY_CATEGORIES))
        for probability in uniform.values():
            self.assertAlmostEqual(probability, 0.5, places=12)
        self.assertAlmostEqual(sum(uniform.values()), 1.0, places=12)
        self.assertEqual(empty.top_grams("甲"), [])

        with self.assertRaises(ValueError):
            NaiveBayesNgram([], [])
        with self.assertRaises(ValueError):
            NaiveBayesNgram([("样本", "未知类别")], ["已知类别"])
        with self.assertRaises(ValueError):
            NaiveBayesNgram(TRAINING, CATEGORIES, alpha=0.0)


class CombineSignalsTests(unittest.TestCase):
    def test_all_zero_weights_return_uniform(self):
        signals = {
            "term": {"甲": 0.9, "乙": 0.1},
            "knn": {"甲": 0.2, "乙": 0.8},
        }
        result = combine_signals(signals, {"term": 0.0, "knn": 0.0}, BINARY_CATEGORIES)

        self.assertAlmostEqual(result["甲"], 0.5, places=12)
        self.assertAlmostEqual(result["乙"], 0.5, places=12)
        self.assertAlmostEqual(sum(result.values()), 1.0, places=12)

    def test_weighted_result_sums_to_one_and_favors_high_weight(self):
        signals = {
            "term": {"甲": 0.9, "乙": 0.1},
            "knn": {"甲": 0.2, "乙": 0.8},
        }
        result = combine_signals(
            signals, {"term": 3.0, "knn": 1.0}, BINARY_CATEGORIES
        )

        self.assertAlmostEqual(sum(result.values()), 1.0, places=12)
        self.assertGreater(result["甲"], result["乙"])
        self.assertAlmostEqual(result["甲"], (3.0 * 0.9 + 1.0 * 0.2) / 4.0, places=12)

    def test_unknown_keys_ignored_and_vectors_normalized(self):
        signals = {"term": {"甲": 9.0, "乙": 1.0}}
        ignored = combine_signals(
            signals, {"other": 1.0}, BINARY_CATEGORIES
        )
        self.assertAlmostEqual(ignored["甲"], 0.5, places=12)
        self.assertAlmostEqual(ignored["乙"], 0.5, places=12)

        normalized = combine_signals(
            signals, {"term": 1.0}, BINARY_CATEGORIES
        )
        self.assertAlmostEqual(normalized["甲"], 0.9, places=12)
        self.assertAlmostEqual(normalized["乙"], 0.1, places=12)


class EnsembleTests(unittest.TestCase):
    def _single_signal_accuracy(self, key):
        weights = {name: 1.0 if name == key else 0.0 for name in SIGNAL_KEYS}
        return evaluate_ensemble(ROWS, BINARY_CATEGORIES, weights)["accuracy"]

    def test_tune_weights_sum_to_one_and_beat_single_signals(self):
        weights, accuracy = tune_ensemble_weights(
            ROWS, BINARY_CATEGORIES, min_weight=ENSEMBLE_MIN_WEIGHT
        )

        self.assertEqual(set(weights), SIGNAL_KEYS)
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=12)
        for value in weights.values():
            # 最小权重约束作用在归一化后的权重上：每路信号都必须保留
            # ENSEMBLE_MIN_WEIGHT，调参不能把某一路压到 0。
            self.assertGreaterEqual(value, ENSEMBLE_MIN_WEIGHT - 1e-12)
            self.assertLessEqual(value, 1.0)

        # 宏平均 F1 优先的搜索不应劣于任何单信号。
        for key in SIGNAL_KEYS:
            self.assertGreaterEqual(
                accuracy,
                self._single_signal_accuracy(key),
                "调参结果不应劣于单信号 {}".format(key),
            )
        self.assertGreaterEqual(accuracy, 0.99)

        # 调参结果交给评估函数应得到一致的准确率。
        evaluation = evaluate_ensemble(ROWS, BINARY_CATEGORIES, weights)
        self.assertAlmostEqual(evaluation["accuracy"], accuracy, places=12)

    def test_tune_weights_explicit_min_weight_is_respected(self):
        weights, accuracy = tune_ensemble_weights(
            ROWS, BINARY_CATEGORIES, min_weight=0.2
        )

        self.assertAlmostEqual(sum(weights.values()), 1.0, places=12)
        for value in weights.values():
            self.assertGreaterEqual(value, 0.2 - 1e-12)
        evaluation = evaluate_ensemble(ROWS, BINARY_CATEGORIES, weights)
        self.assertAlmostEqual(evaluation["accuracy"], accuracy, places=12)

    def test_tune_weights_accepts_zero_min_weight(self):
        # min_weight=0 表示不启用最小权重约束，应正常返回归一化权重。
        weights, _accuracy = tune_ensemble_weights(
            ROWS, BINARY_CATEGORIES, min_weight=0.0
        )
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=12)
        self.assertGreaterEqual(min(weights.values()), 0.0)

    def test_evaluate_ensemble_returns_required_fields(self):
        result = evaluate_ensemble(ROWS, BINARY_CATEGORIES)

        for key in (
            "accuracy",
            "macro_f1",
            "per_class",
            "confusion_matrix",
            "sample_count",
            "weights",
        ):
            self.assertIn(key, result)
        self.assertEqual(result["sample_count"], len(ROWS))
        self.assertGreaterEqual(result["accuracy"], 0.0)
        self.assertLessEqual(result["accuracy"], 1.0)
        self.assertGreaterEqual(result["macro_f1"], 0.0)
        self.assertLessEqual(result["macro_f1"], 1.0)
        self.assertEqual(set(result["per_class"]), set(BINARY_CATEGORIES))
        self.assertAlmostEqual(sum(result["weights"].values()), 1.0, places=12)

        confusion = result["confusion_matrix"]
        total = sum(sum(row.values()) for row in confusion.values())
        self.assertEqual(total, len(ROWS))
        self.assertEqual(sum(item["support"] for item in result["per_class"].values()), len(ROWS))

    def test_explicit_single_signal_accuracy(self):
        weights = {"term": 1.0, "knn": 0.0, "nb": 0.0}
        result = evaluate_ensemble(ROWS, BINARY_CATEGORIES, weights)

        self.assertAlmostEqual(result["weights"]["term"], 1.0, places=12)
        self.assertAlmostEqual(result["weights"]["knn"], 0.0, places=12)
        self.assertAlmostEqual(result["accuracy"], 0.5, places=12)

    def test_empty_rows_do_not_crash(self):
        weights, accuracy = tune_ensemble_weights([], BINARY_CATEGORIES)
        self.assertEqual(weights, {})
        self.assertEqual(accuracy, 0.0)

        result = evaluate_ensemble([], BINARY_CATEGORIES)
        self.assertEqual(result["sample_count"], 0)
        self.assertEqual(result["accuracy"], 0.0)
        self.assertEqual(result["weights"], {})
        self.assertEqual(set(result["per_class"]), set(BINARY_CATEGORIES))


if __name__ == "__main__":
    unittest.main()

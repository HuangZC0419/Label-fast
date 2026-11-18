# -*- coding: utf-8 -*-
"""数据驱动的统计模型层：字符 n-gram 朴素贝叶斯与多信号集成权重搜索。

设计要点：

- 不依赖任何硬编码分类体系或 CONCEPTS，类别、词表、先验全部来自训练数据；
- 贝叶斯使用字符 n-gram 与拉普拉斯平滑，log 空间计算并用 log-sum-exp 归一化；
- 集成层只做加权概率融合，输入信号的结构由调用方决定（SignalMap）；
- 权重搜索以宏平均 F1 优先、准确率次之，并要求每个信号保留最小权重，
  避免调参把某一路信号压到 0 而丢掉外部回归集上的纠错能力；
- Python 3.8 兼容（typing.Dict/List/Tuple/Optional，不使用 ``X | Y``）。
"""

import itertools
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from text import char_ngrams

SignalMap = Dict[str, Dict[str, float]]

_NEG_INF = float("-inf")


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


def _unique_categories(categories: Sequence[str]) -> List[str]:
    """按首次出现顺序去重，保证概率向量与类别顺序稳定。"""
    result: List[str] = []
    seen = set()
    for category in categories:
        if category not in seen:
            seen.add(category)
            result.append(category)
    return result


def _uniform(categories: Sequence[str]) -> Dict[str, float]:
    """返回类别上的均匀分布；空类别返回空字典。"""
    if not categories:
        return {}
    probability = 1.0 / len(categories)
    return {category: probability for category in categories}


def _positive_weight(value: Any) -> float:
    """把任意输入安全地转成正权重；非法值或非正值返回 0。"""
    try:
        weight = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(weight) or weight <= 0.0:
        return 0.0
    return weight


def _normalize_vector(
    values: Dict[str, float], categories: Sequence[str]
) -> List[float]:
    """按类别顺序取信号值并归一化；缺失、负数或非有限值按 0 处理。

    信号值不是概率时（例如相似度分数）也能安全融合；向量总和为 0 时退化为均匀分布。
    """
    if not isinstance(values, dict):
        values = {}
    vector: List[float] = []
    for category in categories:
        try:
            value = float(values.get(category, 0.0))
        except (TypeError, ValueError):
            value = 0.0
        if not math.isfinite(value) or value < 0.0:
            value = 0.0
        vector.append(value)
    total = math.fsum(vector)
    if total <= 0.0:
        if not categories:
            return []
        return [1.0 / len(categories)] * len(categories)
    return [value / total for value in vector]


def _combine_prepared(
    prepared: Dict[str, List[float]],
    weights: Dict[str, float],
    categories: Sequence[str],
) -> Dict[str, float]:
    """融合已归一化的信号向量。

    只使用 ``prepared`` 中存在且权重为正的信号；总权重为 0 时返回均匀分布。
    迭代 key 排序后进行，保证浮点求和顺序与结果完全确定。
    """
    if not categories:
        return {}
    total_weight = 0.0
    totals = [0.0] * len(categories)
    for key in sorted(prepared):
        weight = _positive_weight(weights.get(key, 0.0))
        if weight <= 0.0:
            continue
        vector = prepared[key]
        if len(vector) != len(categories):
            continue
        total_weight += weight
        for index, value in enumerate(vector):
            totals[index] += weight * value

    if total_weight <= 0.0:
        return _uniform(categories)

    probabilities = [
        max(0.0, total / total_weight) for total in totals
    ]
    normalizer = math.fsum(probabilities)
    if normalizer <= 0.0:
        return _uniform(categories)
    return {
        category: probability / normalizer
        for category, probability in zip(categories, probabilities)
    }


def _softmax(
    scores: Dict[str, float], categories: Sequence[str]
) -> Dict[str, float]:
    """log 空间分数转概率，使用 log-sum-exp 防止下溢。"""
    if not categories:
        return {}
    finite_scores = [score for score in scores.values() if score != _NEG_INF]
    if not finite_scores:
        return _uniform(categories)
    maximum = max(finite_scores)

    weights: Dict[str, float] = {}
    total = 0.0
    for category in categories:
        score = scores.get(category, _NEG_INF)
        weight = 0.0 if score == _NEG_INF else math.exp(score - maximum)
        weights[category] = weight
        total += weight

    if total <= 0.0 or not math.isfinite(total):
        return _uniform(categories)
    return {category: weights[category] / total for category in categories}


# ---------------------------------------------------------------------------
# 字符 n-gram 朴素贝叶斯
# ---------------------------------------------------------------------------


class NaiveBayesNgram:
    """字符 n-gram 朴素贝叶斯模型。

    Parameters
    ----------
    examples:
        ``(名称, 类别)`` 序列；类别必须包含在 ``categories`` 中。
    categories:
        完整类别集合；即使某个类别没有训练样本也保留，便于统一输出维度。
    sizes:
        字符 n-gram 长度，默认 ``(2, 3)``。
    alpha:
        拉普拉斯平滑系数，必须为正数。
    uniform_prior:
        ``True`` 时使用 1/K 均匀先验；否则使用经验类别先验。
    """

    def __init__(
        self,
        examples: Sequence[Tuple[str, str]],
        categories: Sequence[str],
        sizes: Tuple[int, ...] = (2, 3),
        alpha: float = 1.0,
        uniform_prior: bool = True,
    ) -> None:
        try:
            alpha_value = float(alpha)
        except (TypeError, ValueError):
            raise ValueError("alpha 必须为正数")
        if not math.isfinite(alpha_value) or alpha_value <= 0.0:
            raise ValueError("alpha 必须为正数")

        self._sizes: Tuple[int, ...] = tuple(int(size) for size in sizes)
        self._alpha: float = alpha_value
        self._categories: Tuple[str, ...] = tuple(
            _unique_categories(categories)
        )
        if not self._categories:
            raise ValueError("categories 不能为空")

        known_categories = set(self._categories)
        counts: Dict[str, Dict[str, int]] = {
            category: {} for category in self._categories
        }
        totals: Dict[str, int] = {category: 0 for category in self._categories}
        class_documents: Dict[str, int] = {
            category: 0 for category in self._categories
        }
        vocabulary = set()

        for name, label in examples:
            if label not in known_categories:
                raise ValueError(
                    "样本类别 {0!r} 不在 categories 中".format(label)
                )
            class_documents[label] += 1
            category_counts = counts[label]
            for gram in char_ngrams(name, self._sizes):
                category_counts[gram] = category_counts.get(gram, 0) + 1
                totals[label] += 1
                vocabulary.add(gram)

        self._counts = counts
        self._totals = totals
        self._vocabulary: Tuple[str, ...] = tuple(sorted(vocabulary))
        self._vocab_size: int = len(self._vocabulary)
        # 平滑后的分母与词表大小相关，预先缓存避免每次预测重复计算。
        self._denominators: Dict[str, float] = {
            category: totals[category] + self._alpha * self._vocab_size
            for category in self._categories
        }

        if uniform_prior:
            self._priors: Dict[str, float] = {
                category: 1.0 / len(self._categories)
                for category in self._categories
            }
        else:
            document_count = sum(class_documents.values())
            if document_count <= 0:
                # 没有任何样本时无法估计经验先验，退化为均匀分布。
                self._priors = {
                    category: 1.0 / len(self._categories)
                    for category in self._categories
                }
            else:
                self._priors = {
                    category: class_documents[category] / document_count
                    for category in self._categories
                }

        self._log_priors: Dict[str, float] = {
            category: (
                math.log(probability)
                if probability > 0.0
                else _NEG_INF
            )
            for category, probability in self._priors.items()
        }

    def _log_likelihood(self, category: str, gram: str) -> float:
        """单个 n-gram 在指定类别下的对数似然（含拉普拉斯平滑）。"""
        count = self._counts[category].get(gram, 0)
        denominator = self._denominators[category]
        return math.log((count + self._alpha) / denominator)

    def predict_proba(self, name: str) -> Dict[str, float]:
        """返回名称在各类别上的后验概率，概率之和为 1。"""
        grams = char_ngrams(name, self._sizes)
        scores: Dict[str, float] = {}

        for category in self._categories:
            log_prior = self._log_priors[category]
            if log_prior == _NEG_INF:
                scores[category] = _NEG_INF
                continue
            score = log_prior
            if self._vocab_size:
                for gram in grams:
                    score += self._log_likelihood(category, gram)
            scores[category] = score

        return _softmax(scores, self._categories)

    def top_grams(
        self, category: str, limit: int = 10
    ) -> List[Tuple[str, float]]:
        """返回该类别下对数似然贡献最高的 n-gram（用于证据展示）。

        值为 ``log((count + alpha) / (total + alpha * V))``，按贡献降序、
        n-gram 字典序升序排列，保证结果确定。
        """
        if category not in self._counts:
            raise ValueError("未知类别: {0!r}".format(category))
        try:
            limit_value = int(limit)
        except (TypeError, ValueError):
            limit_value = 0
        if limit_value <= 0 or not self._vocabulary:
            return []

        denominator = self._denominators[category]
        scored: List[Tuple[str, float]] = []
        for gram in self._vocabulary:
            count = self._counts[category].get(gram, 0)
            scored.append(
                (
                    gram,
                    math.log((count + self._alpha) / denominator),
                )
            )
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored[:limit_value]

    def top_contributions(
        self, name: str, category: str, limit: int = 5
    ) -> List[Tuple[str, float]]:
        """返回查询自身 n-gram 对该类别的对数似然贡献，按贡献降序。

        与 :meth:`top_grams` 不同，这里只评估查询名称中实际出现的 n-gram，
        因此证据展示能直接对应待分类名称，而不是类别词表中的任意高频片段。
        查询没有可用 n-gram 时返回空列表，由调用方决定兜底策略。
        """
        if category not in self._counts:
            raise ValueError("未知类别: {0!r}".format(category))
        try:
            limit_value = int(limit)
        except (TypeError, ValueError):
            limit_value = 0
        if limit_value <= 0:
            return []

        grams = char_ngrams(name, self._sizes)
        if not grams:
            return []

        denominator = self._denominators[category]
        scored: List[Tuple[str, float]] = []
        for gram in grams:
            count = self._counts[category].get(gram, 0)
            scored.append(
                (
                    gram,
                    math.log((count + self._alpha) / denominator),
                )
            )
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored[:limit_value]


# ---------------------------------------------------------------------------
# 集成层
# ---------------------------------------------------------------------------


def combine_signals(
    signals: Dict[str, Dict[str, float]],
    weights: Dict[str, float],
    categories: Sequence[str],
) -> Dict[str, float]:
    """按权重融合多个信号，返回类别概率分布。

    - 忽略不在 ``weights`` 中或权重非正的信号；
    - 每个信号向量先防御性归一化（总和非正时视为均匀分布）；
    - 总权重为 0 时返回类别均匀分布。
    """
    unique = _unique_categories(categories)
    if not unique:
        return {}
    prepared = {
        key: _normalize_vector(values, unique)
        for key, values in signals.items()
    }
    return _combine_prepared(prepared, weights, unique)


def _score_predictions(
    true_labels: Sequence[str],
    predictions: Sequence[str],
    categories: Sequence[str],
) -> Tuple[float, float]:
    """返回 (accuracy, macro_f1)；宏平均覆盖 ``categories`` 中的全部类别。"""
    sample_count = len(true_labels)
    if sample_count <= 0:
        return 0.0, 0.0

    correct = 0
    support: Dict[str, int] = {category: 0 for category in categories}
    predicted: Dict[str, int] = {category: 0 for category in categories}
    true_positive: Dict[str, int] = {
        category: 0 for category in categories
    }

    for truth, prediction in zip(true_labels, predictions):
        if truth == prediction:
            correct += 1
        if truth in support:
            support[truth] += 1
        if prediction in predicted:
            predicted[prediction] += 1
        if truth == prediction and truth in true_positive:
            true_positive[truth] += 1

    accuracy = correct / sample_count
    if not categories:
        return accuracy, 0.0

    f1_total = 0.0
    for category in categories:
        tp = true_positive[category]
        fp = predicted[category] - tp
        fn = support[category] - tp
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        if precision + recall:
            f1_total += 2.0 * precision * recall / (precision + recall)
    return accuracy, f1_total / len(categories)


def tune_ensemble_weights(
    rows: Sequence[Tuple[str, SignalMap]],
    categories: Sequence[str],
    grid: Sequence[float] = (0.0, 0.25, 0.5, 0.75, 1.0),
    min_weight: float = 0.10,
) -> Tuple[Dict[str, float], float]:
    """网格搜索信号权重，返回 (归一化权重, 对应准确率)。

    搜索空间由第一行 SignalMap 中出现的信号键决定。约束如下：

    - 原始组合总权重必须大于 0；
    - ``min_weight > 0`` 时，**归一化到总和 1 之后**每个信号权重都必须
      ``>= min_weight``（即最小权重约束作用在归一化后的权重上，而不是
      原始网格值上）。这样调参不会把任何一路信号压到 0；
    - 每个候选都用 :func:`evaluate_ensemble` 评估，排序依次为：宏平均 F1
      更高、准确率更高、最小权重更大（偏好更均衡的组合）、归一化权重
      字典序更小（确定性兜底）。

    ``min_weight`` 非有限或为负时按 0 处理（不启用最小权重约束）。没有
    任何组合满足约束时退化为均匀权重，保证调用方总能拿到可用结果。
    """
    if not rows:
        return {}, 0.0
    unique = _unique_categories(categories)
    if not unique:
        return {}, 0.0

    keys = sorted(rows[0][1].keys())
    if not keys:
        return {}, 0.0

    try:
        minimum = float(min_weight)
    except (TypeError, ValueError):
        minimum = 0.0
    if not math.isfinite(minimum) or minimum < 0.0:
        minimum = 0.0

    grid_values: List[float] = []
    for value in grid:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number >= 0.0:
            grid_values.append(number)
    # 去重并保持输入顺序，减少重复计算。
    grid_values = list(dict.fromkeys(grid_values))

    if not grid_values:
        uniform = tuple(1.0 / len(keys) for _ in keys)
        accuracy = evaluate_ensemble(
            rows,
            unique,
            {key: value for key, value in zip(keys, uniform)},
        )["accuracy"]
        return {key: value for key, value in zip(keys, uniform)}, accuracy

    best_weights: Optional[Tuple[float, ...]] = None
    best_accuracy = 0.0
    # 排序键最后一项取负号，使字典序更小的组合在 ``max`` 下胜出。
    best_key: Optional[
        Tuple[float, float, float, Tuple[float, ...]]
    ] = None

    for combination in itertools.product(grid_values, repeat=len(keys)):
        total = math.fsum(combination)
        if total <= 0.0:
            continue
        candidate = tuple(value / total for value in combination)
        if minimum > 0.0 and any(
            value < minimum - 1e-12 for value in candidate
        ):
            # 归一化后仍有信号低于最小权重，直接丢弃该组合。
            continue
        weight_map = {key: value for key, value in zip(keys, candidate)}
        metrics = evaluate_ensemble(rows, unique, weight_map)
        accuracy = float(metrics["accuracy"])
        macro_f1 = float(metrics["macro_f1"])
        rounded = tuple(round(value, 12) for value in candidate)
        tie_key = (
            macro_f1,
            accuracy,
            min(rounded),
            tuple(-value for value in rounded),
        )
        if best_key is None or tie_key > best_key:
            best_key = tie_key
            best_weights = candidate
            best_accuracy = accuracy

    if best_weights is None:
        # 没有组合满足最小权重约束（例如信号数过多）：退化为均匀权重，
        # 此时最小权重约束不再适用，但保证返回值可用。
        uniform = tuple(1.0 / len(keys) for _ in keys)
        accuracy = evaluate_ensemble(
            rows,
            unique,
            {key: value for key, value in zip(keys, uniform)},
        )["accuracy"]
        return {key: value for key, value in zip(keys, uniform)}, accuracy

    return (
        {key: value for key, value in zip(keys, best_weights)},
        best_accuracy,
    )


def evaluate_ensemble(
    rows: Sequence[Tuple[str, SignalMap]],
    categories: Sequence[str],
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """评估集成效果，返回准确率、宏平均 F1、分类指标与混淆矩阵。

    ``weights`` 为 ``None`` 时对第一行出现的所有信号使用均匀权重。
    """
    unique = _unique_categories(categories)

    if weights is None:
        keys = sorted(rows[0][1].keys()) if rows else []
        used_weights: Dict[str, float] = (
            {key: 1.0 / len(keys) for key in keys} if keys else {}
        )
    else:
        keys = sorted(weights.keys())
        positive_total = math.fsum(
            _positive_weight(weights[key]) for key in keys
        )
        if positive_total > 0.0:
            used_weights = {
                key: (
                    _positive_weight(weights[key]) / positive_total
                    if _positive_weight(weights[key]) > 0.0
                    else 0.0
                )
                for key in keys
            }
        else:
            used_weights = (
                {key: 1.0 / len(keys) for key in keys} if keys else {}
            )

    true_labels: List[str] = []
    predictions: List[str] = []
    for truth, signals in rows:
        true_labels.append(truth)
        probabilities = combine_signals(signals, used_weights, unique)
        if unique:
            predictions.append(
                max(
                    unique,
                    key=lambda category: probabilities.get(category, 0.0),
                )
            )
        else:
            predictions.append("")

    accuracy, macro_f1 = _score_predictions(
        true_labels, predictions, unique
    )

    per_class: Dict[str, Dict[str, float]] = {}
    confusion: Dict[str, Dict[str, int]] = {
        truth: {prediction: 0 for prediction in unique}
        for truth in unique
    }
    for truth, prediction in zip(true_labels, predictions):
        if truth not in confusion:
            confusion[truth] = {item: 0 for item in unique}
        confusion[truth][prediction] = (
            confusion[truth].get(prediction, 0) + 1
        )

    for category in unique:
        true_positive = confusion.get(category, {}).get(category, 0)
        support = sum(confusion.get(category, {}).values())
        predicted_count = sum(
            row.get(category, 0) for row in confusion.values()
        )
        false_positive = predicted_count - true_positive
        false_negative = support - true_positive
        precision = (
            true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else 0.0
        )
        recall = (
            true_positive / (true_positive + false_negative)
            if true_positive + false_negative
            else 0.0
        )
        f1 = (
            2.0 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
        per_class[category] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }

    return {
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "per_class": per_class,
        "confusion_matrix": confusion,
        "sample_count": len(rows),
        "weights": used_weights,
    }

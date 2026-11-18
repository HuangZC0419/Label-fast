# -*- coding: utf-8 -*-
"""从参照表学习类别对数几率（log-odds）词条，并构建相似名称索引。"""

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

from config import (
    KNN_MIN_SIMILARITY,
    KNN_TOP_K,
    LOW_SUPPORT_THRESHOLD,
    MINING_LONG_TERM_LENGTH,
    MINING_MAX_TERMS_PER_CLASS,
    MINING_MIN_PURITY,
    MINING_MIN_SUPPORT,
)
from text import candidate_terms, char_ngrams

Example = Tuple[str, str]


@dataclass
class MinedTerm:
    term: str
    support: int
    purity: float
    weight: float
    examples: List[str]
    log_odds: float = 0.0


def mine_terms(
    examples: Sequence[Example],
    min_support: int = MINING_MIN_SUPPORT,
    min_purity: float = MINING_MIN_PURITY,
    max_terms: int = MINING_MAX_TERMS_PER_CLASS,
    min_long_term_length: int = MINING_LONG_TERM_LENGTH,
    smoothing: float = 0.5,
) -> Dict[str, List[MinedTerm]]:
    """按类别从参照表学习对数几率（log-odds）特征词。

    只使用参照表自身的统计量，不依赖任何人工种子词：

        p_c      = (df_c + smoothing) / (N_c + 2*smoothing)
        p_o      = (df_total - df_c + smoothing) / (N - N_c + 2*smoothing)
        log_odds = log(p_c / p_o)
        weight   = max(0, log_odds) * (1 + 0.1 * (len(term) - 2))

    保留条件：``df_c >= min_support``，或 ``df_c == 1`` 且词长达到
    ``min_long_term_length``；同时纯度（df_c / df_total）不低于
    ``min_purity``，且 log_odds 为正。
    """
    max_terms = max(0, max_terms)
    smoothing = max(0.0, float(smoothing))
    class_totals: Counter = Counter()
    class_terms: Dict[str, Counter] = defaultdict(Counter)
    all_terms: Counter = Counter()
    term_examples: Dict[str, Dict[str, List[str]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for name, label in examples:
        class_totals[label] += 1
        for term in candidate_terms(name):
            all_terms[term] += 1
            class_terms[label][term] += 1
            if len(term_examples[label][term]) < 3:
                term_examples[label][term].append(name)

    total = len(examples)
    result: Dict[str, List[MinedTerm]] = {}
    for label in class_totals:
        counter = class_terms.get(label, {})
        class_total = class_totals[label]
        other_total = total - class_total
        scored: List[MinedTerm] = []
        for term, support in counter.items():
            document_frequency = all_terms[term]
            long_single = (
                support == 1 and len(term) >= min_long_term_length
            )
            if support < min_support and not long_single:
                continue
            purity = float(support) / document_frequency
            if purity < min_purity:
                continue
            p_c = (support + smoothing) / (class_total + 2.0 * smoothing)
            p_o = (document_frequency - support + smoothing) / (
                other_total + 2.0 * smoothing
            )
            # smoothing=0 且词条只出现在当前类别时 p_o 为 0，无法计算对数几率。
            if p_o <= 0.0:
                continue
            log_odds = math.log(p_c / p_o)
            if log_odds <= 0.0:
                continue
            weight = log_odds * (1 + 0.1 * (len(term) - 2))
            scored.append(
                MinedTerm(
                    term=term,
                    support=support,
                    purity=purity,
                    weight=weight,
                    examples=list(term_examples[label][term]),
                    log_odds=log_odds,
                )
            )
        scored.sort(key=lambda item: (-item.weight, -len(item.term), item.term))
        result[label] = scored[:max_terms]
    return result


def keyword_report(
    mined: Dict[str, List[MinedTerm]],
    examples: Sequence[Example],
    system_map: Dict[str, str],
    max_keywords: int = MINING_MAX_TERMS_PER_CLASS,
) -> List[Dict[str, Any]]:
    """生成每个专业的纯数据依据词表。

    词条全部来自参照表统计（``source="statistical"``），不再合并人工种子。
    出现在 examples 或 mined 中的类别都会输出，即使其词表为空。
    """
    examples_by_class: Dict[str, List[str]] = defaultdict(list)
    for name, label in examples:
        examples_by_class[label].append(name)

    professions = set(examples_by_class) | set(mined)
    limit = max(0, max_keywords)
    warning_text = (
        f"样本少于 {LOW_SUPPORT_THRESHOLD} 条，统计结果不稳定"
    )
    report: List[Dict[str, Any]] = []
    for profession in sorted(professions):
        class_support = len(examples_by_class.get(profession, []))
        keywords = [
            {
                "term": item.term,
                "support": item.support,
                "purity": round(item.purity, 4),
                "log_odds": round(item.log_odds, 4),
                "weight": round(item.weight, 4),
                "source": "statistical",
                "examples": list(item.examples),
            }
            for item in mined.get(profession, [])[:limit]
        ]
        report.append({
            "profession": profession,
            "system": system_map.get(profession, ""),
            "class_support": class_support,
            "warning": (
                warning_text
                if class_support < LOW_SUPPORT_THRESHOLD
                else ""
            ),
            "keywords": keywords,
            "top_examples": examples_by_class.get(profession, [])[:5],
        })
    report.sort(key=lambda item: item["profession"])
    return report


@dataclass
class Neighbor:
    name: str
    profession: str
    similarity: float


class NameSimilarityIndex:
    """字符 2~3 元组 TF-IDF 余弦相似度。"""

    def __init__(self, examples: Sequence[Example], sizes: Tuple[int, ...] = (2, 3)) -> None:
        self._examples = [(name, label) for name, label in examples]
        self._sizes = tuple(sizes)
        grams_list: List[Set[str]] = []
        document_frequency: Counter = Counter()
        for name, _label in self._examples:
            grams = set(char_ngrams(name, sizes))
            grams_list.append(grams)
            for gram in grams:
                document_frequency[gram] += 1
        count = len(self._examples) or 1
        self._idf = {
            gram: math.log((count + 1.0) / (frequency + 1.0)) + 1.0
            for gram, frequency in document_frequency.items()
        }
        self._grams = grams_list
        self._norms = [
            math.sqrt(sum(self._idf[gram] ** 2 for gram in grams))
            for grams in grams_list
        ]

    def query(
        self,
        name: str,
        top_k: int = KNN_TOP_K,
        min_similarity: float = KNN_MIN_SIMILARITY,
    ) -> List[Neighbor]:
        """返回相似参照名称。

        TF-IDF 词表仅来自参照语料，语料外（OOV）的 n-gram 在查询向量
        范数和点积中都会被忽略，因此相似度可能被抬高而不是降低。
        """
        top_k = max(0, top_k)
        grams = set(char_ngrams(name, self._sizes))
        if not grams:
            return []
        norm = math.sqrt(sum(self._idf.get(gram, 0.0) ** 2 for gram in grams))
        if norm <= 0.0:
            return []

        neighbors: List[Neighbor] = []
        for index, other_grams in enumerate(self._grams):
            other_norm = self._norms[index]
            if other_norm <= 0.0:
                continue
            common = grams & other_grams
            if not common:
                continue
            dot = sum(self._idf.get(gram, 0.0) ** 2 for gram in common)
            similarity = dot / (norm * other_norm)
            if similarity >= min_similarity:
                neighbor_name, profession = self._examples[index]
                neighbors.append(Neighbor(neighbor_name, profession, similarity))
        neighbors.sort(key=lambda item: (-item.similarity, item.name))
        return neighbors[:top_k]

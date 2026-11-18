# -*- coding: utf-8 -*-
"""参照表校验、冲突检测与纯统计集成分类。

分类证据完全来自上传参照表的统计结果，不依赖任何硬编码专业类别或
人工种子词。三路信号（log-odds 词条、相似名称、字符 n-gram 贝叶斯）
的融合权重在参照表上做确定性分层 5 折网格搜索，以宏平均 F1 优先、
准确率次之，并要求每路信号保留最小权重（``ENSEMBLE_MIN_WEIGHT``）。
"""

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config import (
    CONFLICT_DOMINANCE,
    NEIGHBOR_CONFLICT_SIMILARITY,
    ENSEMBLE_MIN_WEIGHT,
    ENSEMBLE_STRONG_SCORE,
    ENSEMBLE_WEIGHT_GRID,
    LOW_SUPPORT_THRESHOLD,
    MAX_CONFIDENCE,
    NB_ALPHA,
    NB_SIZES,
    REVIEW_THRESHOLD,
    TERM_SMOOTHING,
)
from excel_io import ExcelError, pick, variant_code_key
from mining import NameSimilarityIndex, keyword_report, mine_terms
from statistical import (
    NaiveBayesNgram,
    combine_signals,
    evaluate_ensemble,
    tune_ensemble_weights,
)
from text import base_code, normalize_code, normalize_name

SignalMap = Dict[str, Dict[str, float]]

# 单信号模式下，内部键到对外证据等级的映射。
SIGNAL_LEVELS = {"term": "term", "knn": "similar", "nb": "nb"}
SIGNAL_METHODS = {"term": "关键词统计", "knn": "相似名称", "nb": "贝叶斯"}
SIGNAL_LABELS = {"term": "关键词", "knn": "相似名称", "nb": "字符统计"}
SIGNAL_ORDER = ("term", "knn", "nb")


@dataclass
class ReferenceData:
    training_examples: List[Tuple[str, str]]
    by_code: Dict[str, Dict[str, Any]]
    by_name: Dict[str, Dict[str, Any]]
    by_base: Dict[str, Dict[str, Any]]
    system_map: Dict[str, str]
    mapping: Dict[str, Any]
    conflicts: List[Dict[str, Any]]
    categories: List[str]
    warnings: List[str] = field(default_factory=list)
    excluded_rows: List[int] = field(default_factory=list)
    row_count: int = 0


def _majority(counter: Counter) -> Tuple[Any, int]:
    return counter.most_common(1)[0]


def _label_text(profession: str, system: str) -> str:
    return "{} / {}".format(profession, system) if system else profession


def _resolve_group(group: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    counter = Counter((item["profession"], item["system"]) for item in group)
    (profession, system), votes = _majority(counter)
    total = sum(counter.values())
    return {
        "profession": profession,
        "system": system,
        "votes": votes,
        "total": total,
        "ratio": float(votes) / total if total else 0.0,
    }


def _conflict_for_group(group: Sequence[Dict[str, Any]], conflict_type: str) -> Optional[Dict[str, Any]]:
    # 模型只预测专业；专业一致时，系统写法差异不算分类冲突。
    if len({item["profession"] for item in group}) <= 1:
        return None
    counter = Counter((item["profession"], item["system"]) for item in group)
    (profession, _system), _votes = _majority(counter)
    labels = [
        "{} {}票".format(_label_text(item[0], item[1]), count)
        for item, count in counter.most_common()
    ]
    first = group[0]
    return {
        "type": conflict_type,
        "code": first.get("code", ""),
        "name": first.get("name", ""),
        "count": sum(counter.values()),
        "labels": labels,
        "chosen": profession,
    }


def build_reference(
    records: Sequence[Dict[str, Any]],
    mapping_rows: Sequence[Dict[str, Any]],
) -> ReferenceData:
    """从参照表构建映射、冲突报告、查找索引和训练样本。

    类别完全由上传的参照表决定，不再依赖写死的固定分类。相同标准号、
    相同标准名称但选用专业不一致的记录视为脏数据，整组排除出训练集；
    系统差异单独报告，不影响训练。
    """
    mapping_hint: Dict[str, str] = {}
    for row in mapping_rows:
        profession = pick(row, "profession")
        system = pick(row, "system")
        if profession and system:
            mapping_hint[profession] = system

    items: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for row in records:
        code = pick(row, "code")
        name = pick(row, "name")
        profession = pick(row, "profession")
        if not name or not profession:
            continue
        system = pick(row, "system") or mapping_hint.get(profession, "")
        items.append({
            "code": code,
            "name": name,
            "profession": profession,
            "system": system,
            "row": row.get("_row", ""),
        })

    if not items:
        raise ExcelError("INVALID_FILE", "参照表没有可用的分类记录，请检查标准名称和选用专业名称")

    # 训练集只保留完全干净的数据：
    # 1) 同号 + 同名但分类不一致；
    # 2) 同名不同号且分类不一致；
    # 3) 同号不同名且分类不一致。
    labels_by_name: Dict[str, set] = defaultdict(set)
    labels_by_code: Dict[str, set] = defaultdict(set)
    for item in items:
        # 只按专业判断冲突：模型预测专业，系统差异不构成训练冲突。
        label = item["profession"]
        name_key = normalize_name(item["name"])
        code_key = variant_code_key(item["code"])
        if name_key:
            labels_by_name[name_key].add(label)
        if code_key:
            labels_by_code[code_key].add(label)

    groups_by_code_name: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for item in items:
        code_key = variant_code_key(item["code"])
        name_key = normalize_name(item["name"])
        if code_key and name_key:
            groups_by_code_name[(code_key, name_key)].append(item)

    excluded_rows: set = set()
    excluded_conflicts: List[Dict[str, Any]] = []

    def add_conflict(
        conflict_type: str,
        group: Sequence[Dict[str, Any]],
        code: Optional[str] = None,
        name: Optional[str] = None,
    ) -> None:
        if len({item["profession"] for item in group}) <= 1:
            return
        counter = Counter((item["profession"], item["system"]) for item in group)
        rows = [item["row"] for item in group if item.get("row") != ""]
        if not rows or set(rows).issubset(excluded_rows):
            return
        excluded_rows.update(rows)
        excluded_conflicts.append({
            "type": conflict_type,
            "code": code if code is not None else group[0]["code"],
            "name": name if name is not None else group[0]["name"],
            "count": len(group),
            "labels": [
                "{} {}票".format(_label_text(profession, system), count)
                for (profession, system), count in counter.most_common()
            ],
            "chosen": "",
            "rows": rows,
        })

    for group in groups_by_code_name.values():
        add_conflict("同号同名不同分类", group)

    for name_key, labels in labels_by_name.items():
        if len(labels) <= 1:
            continue
        group = [
            item for item in items
            if normalize_name(item["name"]) == name_key
        ]
        add_conflict(
            "同名不同分类",
            group,
            code="、".join(sorted({item["code"] for item in group if item["code"]})),
        )

    for code_key, labels in labels_by_code.items():
        if len(labels) <= 1:
            continue
        group = [
            item for item in items
            if variant_code_key(item["code"]) == code_key
        ]
        add_conflict(
            "同号不同分类",
            group,
            name="、".join(sorted({item["name"] for item in group if item["name"]})),
        )

    if excluded_conflicts:
        warnings.append(
            "参照表中同号同名、同名不同号或同号不同名且分类不一致："
            "{} 组、{} 行，已整组排除出训练集".format(
                len(excluded_conflicts), len(excluded_rows)
            )
        )

    items = [item for item in items if item.get("row", "") not in excluded_rows]
    if not items:
        raise ExcelError(
            "INVALID_FILE", "参照表的记录全部存在分类冲突，没有可用于训练的干净数据"
        )

    categories = sorted({item["profession"] for item in items})
    profession_systems: Dict[str, Counter] = defaultdict(Counter)
    system_professions: Dict[str, Counter] = defaultdict(Counter)
    for item in items:
        profession_systems[item["profession"]][item["system"]] += 1
        system_professions[item["system"]][item["profession"]] += 1

    profession_to_system = {
        profession: _majority(counter)[0]
        for profession, counter in profession_systems.items()
    }
    system_to_profession = {
        system: _majority(counter)[0]
        for system, counter in system_professions.items()
    }

    issues: List[Dict[str, Any]] = []
    for profession, counter in sorted(profession_systems.items()):
        if len(counter) > 1:
            issues.append({
                "type": "专业对应多个系统",
                "profession": profession,
                "values": ["{}（{}票）".format(name, count) for name, count in counter.most_common()],
            })
    for system, counter in sorted(system_professions.items()):
        if len(counter) > 1:
            issues.append({
                "type": "系统对应多个专业",
                "system": system,
                "values": ["{}（{}票）".format(name, count) for name, count in counter.most_common()],
            })
    for profession, system in sorted(mapping_hint.items()):
        chosen = profession_to_system.get(profession)
        if chosen and chosen != system:
            issues.append({
                "type": "映射表与总表不一致",
                "profession": profession,
                "values": ["映射表：{}；总表多数：{}".format(system, chosen)],
            })

    inverse_ok = all(
        system_to_profession.get(system) == profession
        for profession, system in profession_to_system.items()
    )
    is_one_to_one = not issues and inverse_ok and len(profession_to_system) == len(system_to_profession)

    # 冲突检测：按标准号、按标准名称分别分组。
    by_code_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_name_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_base_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in items:
        code_key = normalize_code(item["code"])
        name_key = normalize_name(item["name"])
        if code_key:
            by_code_groups[code_key].append(item)
            by_base_groups[base_code(code_key)].append(item)
        if name_key:
            by_name_groups[name_key].append(item)

    conflicts: List[Dict[str, Any]] = list(excluded_conflicts)
    for group in by_code_groups.values():
        conflict = _conflict_for_group(group, "标准号")
        if conflict:
            conflicts.append(conflict)
    for group in by_name_groups.values():
        conflict = _conflict_for_group(group, "标准名称")
        if conflict:
            conflicts.append(conflict)

    by_code = {
        key: _resolve_group(group)
        for key, group in by_code_groups.items()
    }
    by_base = {
        key: _resolve_group(group)
        for key, group in by_base_groups.items()
        if key
    }

    # 名称必须唯一对应一个专业，才允许用于名称匹配和训练。
    by_name: Dict[str, Dict[str, Any]] = {}
    ambiguous_names: List[str] = []
    for key, group in by_name_groups.items():
        professions = {item["profession"] for item in group}
        if len(professions) == 1:
            by_name[key] = _resolve_group(group)
        else:
            ambiguous_names.append(group[0]["name"])
    if ambiguous_names:
        preview = "、".join(ambiguous_names[:5])
        suffix = " 等 {} 个".format(len(ambiguous_names)) if len(ambiguous_names) > 5 else ""
        warnings.append("以下名称对应多个专业，未参与训练和名称匹配：{}{}".format(preview, suffix))

    training_by_name: Dict[str, Tuple[str, str]] = {}
    for item in items:
        key = normalize_name(item["name"])
        if key not in by_name:
            continue
        training_by_name.setdefault(key, (item["name"], item["profession"]))
    training_examples = list(training_by_name.values())
    if not training_examples:
        warnings.append("参照表没有可用于训练的唯一名称记录")

    # 系统名称只来自上传表（总表与映射表），没有硬编码兜底。
    system_map = dict(profession_to_system)

    mapping = {
        "is_one_to_one": is_one_to_one,
        "profession_to_system": profession_to_system,
        "system_to_profession": system_to_profession,
        "issues": issues,
        "categories": categories,
    }

    return ReferenceData(
        training_examples=training_examples,
        by_code=by_code,
        by_name=by_name,
        by_base=by_base,
        system_map=system_map,
        mapping=mapping,
        conflicts=conflicts,
        categories=categories,
        warnings=warnings,
        excluded_rows=sorted(excluded_rows),
        row_count=len(records),
    )


def _softmax_scores(scores: Dict[str, float], categories: Sequence[str]) -> Dict[str, float]:
    """把类别分数转成概率；全部为 0 时退化为均匀分布。"""
    if not categories:
        return {}
    values = [float(scores.get(category, 0.0)) for category in categories]
    maximum = max(values)
    exponentials = [math.exp(value - maximum) for value in values]
    total = math.fsum(exponentials)
    if total <= 0.0 or not math.isfinite(total):
        uniform = 1.0 / len(categories)
        return {category: uniform for category in categories}
    return {
        category: value / total
        for category, value in zip(categories, exponentials)
    }


class EvidenceEngine:
    """三路统计信号的加权集成：log-odds 词条、相似名称、字符 n-gram 贝叶斯。

    本引擎只处理参照表未精确命中的名称；类别、词表与权重全部来自
    上传的参照表，不依赖任何硬编码分类体系。
    """

    def __init__(
        self,
        examples: Sequence[Tuple[str, str]],
        categories: Sequence[str],
        system_map: Dict[str, str],
    ) -> None:
        self.examples = list(examples)
        self.categories = list(categories)
        self.system_map = dict(system_map)
        self.mined_terms = mine_terms(self.examples, smoothing=TERM_SMOOTHING)
        self.similarity = NameSimilarityIndex(self.examples)
        self.nb = NaiveBayesNgram(
            self.examples,
            self.categories,
            sizes=NB_SIZES,
            alpha=NB_ALPHA,
            uniform_prior=True,
        )
        self.class_support: Counter = Counter(
            label for _name, label in self.examples
        )
        (
            self.weights,
            self.tuning_accuracy,
            self._tuning_rows,
            self.tuning_folds,
        ) = self._tune_weights()

    # -- 词条信号 --------------------------------------------------------

    def _matched_terms(
        self,
        mined_terms: Dict[str, List[Any]],
        category: str,
        normalized: str,
    ) -> List[Any]:
        """按“长词优先、同类不重叠”的贪心策略返回命中的统计词条。"""
        items = sorted(
            mined_terms.get(category, []),
            key=lambda item: (-len(item.term), -item.weight, item.term),
        )
        occupied: List[Tuple[int, int]] = []
        matched: List[Any] = []
        for item in items:
            if not item.term:
                continue
            start = normalized.find(item.term)
            if start < 0:
                continue
            end = start + len(item.term)
            if any(
                start < other_end and other_start < end
                for other_start, other_end in occupied
            ):
                continue
            occupied.append((start, end))
            matched.append(item)
        return matched

    def _term_probabilities_from(
        self,
        mined_terms: Dict[str, List[Any]],
        name: str,
    ) -> Dict[str, float]:
        normalized = normalize_name(name)
        scores: Dict[str, float] = {}
        for category in self.categories:
            scores[category] = math.fsum(
                float(item.weight)
                for item in self._matched_terms(mined_terms, category, normalized)
            )
        return _softmax_scores(scores, self.categories)

    # -- 相似名称信号 ----------------------------------------------------

    def _knn_probabilities_from(
        self,
        index: NameSimilarityIndex,
        name: str,
    ) -> Dict[str, float]:
        votes: Dict[str, float] = {category: 0.0 for category in self.categories}
        for neighbor in index.query(name):
            if neighbor.profession in votes:
                votes[neighbor.profession] += float(neighbor.similarity)
        total = math.fsum(votes.values())
        if total <= 0.0:
            if not self.categories:
                return {}
            uniform = 1.0 / len(self.categories)
            return {category: uniform for category in self.categories}
        return {
            category: votes[category] / total
            for category in self.categories
        }

    # -- 信号组装 --------------------------------------------------------

    def _signals_from(
        self,
        mined_terms: Dict[str, List[Any]],
        index: NameSimilarityIndex,
        nb: NaiveBayesNgram,
        name: str,
    ) -> SignalMap:
        return {
            "term": self._term_probabilities_from(mined_terms, name),
            "knn": self._knn_probabilities_from(index, name),
            "nb": nb.predict_proba(name),
        }

    def _signals(self, name: str) -> SignalMap:
        return self._signals_from(
            self.mined_terms, self.similarity, self.nb, name
        )

    def _combined(self, name: str) -> Dict[str, float]:
        return combine_signals(self._signals(name), self.weights, self.categories)

    def _stratified_folds(self, k: int = 5):
        """按类别轮流分配样本，返回确定性的分层折索引。

        每个类别内部按原始顺序轮转写入各折，保证各折类别比例接近；
        类别样本不足时自动降低折数（至少 2 折）。
        """
        by_label = defaultdict(list)
        for index, (_name, label) in enumerate(self.examples):
            by_label[label].append(index)
        counts = [len(v) for v in by_label.values()]
        k = max(2, min(k, min(counts))) if counts else 2
        folds = [[] for _ in range(k)]
        position = 0
        for label in sorted(by_label):
            for index in by_label[label]:
                folds[position % k].append(index)
                position += 1
        return [fold for fold in folds if fold]

    def _tune_weights(self):
        """分层 5 折网格搜索集成权重。

        每折用其余折重建全部统计结构，只对留出折计算三路信号，
        因此每条样本恰好贡献一次 out-of-fold 信号。搜索以宏平均 F1
        优先、准确率次之，并强制每路信号保留 ``ENSEMBLE_MIN_WEIGHT``
        的最小权重，避免某一路被压到 0 后丢掉纠错能力。
        """
        rows: List[Tuple[str, SignalMap]] = []
        folds = self._stratified_folds(5)
        for fold in folds:
            fold_set = set(fold)
            train = [
                example
                for index, example in enumerate(self.examples)
                if index not in fold_set
            ]
            mined = mine_terms(train, smoothing=TERM_SMOOTHING)
            index = NameSimilarityIndex(train)
            nb = NaiveBayesNgram(
                train,
                self.categories,
                sizes=NB_SIZES,
                alpha=NB_ALPHA,
                uniform_prior=True,
            )
            for held_out in fold:
                name, truth = self.examples[held_out]
                rows.append(
                    (truth, self._signals_from(mined, index, nb, name))
                )
        weights, accuracy = tune_ensemble_weights(
            rows,
            self.categories,
            grid=ENSEMBLE_WEIGHT_GRID,
            min_weight=ENSEMBLE_MIN_WEIGHT,
        )
        return weights, accuracy, rows, len(folds)

    # -- 置信度与 Top3 ---------------------------------------------------

    def _confidence(self, top: float, second: float, support: int) -> float:
        dominance = top / (top + second) if top + second > 0 else 1.0
        raw = 0.55 + 0.40 * (2.0 * dominance - 1.0)
        if support < LOW_SUPPORT_THRESHOLD:
            raw = min(raw, 0.75)
        return max(0.0, min(MAX_CONFIDENCE, raw))

    def _top3(
        self,
        probabilities: Dict[str, float],
        primary: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """构造 Top3：主类别概率对齐置信度，其余按比例缩放且不超过主类别。"""
        vector: Dict[str, float] = {}
        for category in self.categories:
            try:
                value = float(probabilities.get(category, 0.0))
            except (TypeError, ValueError):
                value = 0.0
            vector[category] = max(0.0, value)
        if primary is not None and primary not in vector:
            vector[primary] = 0.0

        total = math.fsum(vector.values())
        if total > 0.0:
            vector = {
                category: value / total
                for category, value in vector.items()
            }
        elif vector:
            uniform = 1.0 / len(vector)
            vector = {category: uniform for category in vector}

        if primary is not None:
            base = confidence if confidence is not None else vector.get(primary, 0.0)
            base = max(0.0, min(MAX_CONFIDENCE, float(base)))
            rest_total = math.fsum(
                value for category, value in vector.items() if category != primary
            )
            scale = (1.0 - base) / rest_total if rest_total > 0.0 else 0.0
            scaled: Dict[str, float] = {}
            for category, value in vector.items():
                if category == primary:
                    continue
                scaled[category] = min(value * scale, base)
            scaled[primary] = base
            vector = scaled

        ranked = sorted(vector.items(), key=lambda item: (-item[1], item[0]))
        if primary is not None:
            ordered = [(primary, vector.get(primary, 0.0))] + [
                item for item in ranked if item[0] != primary
            ]
        else:
            ordered = ranked

        result: List[Dict[str, Any]] = []
        for profession, probability in ordered[:3]:
            shown_probability = round(
                min(MAX_CONFIDENCE, max(0.0, probability)), 4
            )
            result.append({
                "profession": profession,
                "system": self.system_map.get(profession, ""),
                "probability": shown_probability,
                # 分数与展示概率同尺度，保证“分数”随概率单调，便于前端排序展示。
                "score": round(shown_probability * ENSEMBLE_STRONG_SCORE, 4),
            })

        # 4 位小数分别取整后可能让 Top3 之和略超 1，把误差从非主类别扣回。
        total_probability = math.fsum(item["probability"] for item in result)
        if total_probability > 1.0:
            excess = total_probability - 1.0
            for item in reversed(result):
                if item["profession"] != primary and item["probability"] > 0.0:
                    item["probability"] = round(
                        max(0.0, item["probability"] - excess), 4
                    )
                    break

        for category in self.categories:
            if len(result) >= 3:
                break
            if any(item["profession"] == category for item in result):
                continue
            result.append({
                "profession": category,
                "system": self.system_map.get(category, ""),
                "probability": 0.0,
                "score": 0.0,
            })
        return result

    # -- 证据文本 --------------------------------------------------------

    def _format_term_evidence(
        self, category: str, name: str, limit: int = 3
    ) -> List[str]:
        matched = self._matched_terms(
            self.mined_terms, category, normalize_name(name)
        )
        matched.sort(key=lambda item: (-item.weight, item.term))
        return [
            "关键词统计：{}（权重 {:.2f}）".format(item.term, item.weight)
            for item in matched[:limit]
        ]

    def _format_neighbors(
        self, neighbors: Sequence[Any], limit: int = 2
    ) -> List[str]:
        return [
            "相似标准：{}（{}，相似度 {:.0%}）".format(
                neighbor.name, neighbor.profession, neighbor.similarity
            )
            for neighbor in neighbors[:limit]
        ]

    def _format_weights(self) -> str:
        return "统计权重：关键词 {:.0%} · 相似名称 {:.0%} · 字符统计 {:.0%}".format(
            float(self.weights.get("term", 0.0)),
            float(self.weights.get("knn", 0.0)),
            float(self.weights.get("nb", 0.0)),
        )

    def _confidence_reason(
        self,
        confidence: float,
        dominance: float,
        support: int,
        disagreement: bool = False,
    ) -> str:
        if disagreement:
            return "证据存在分歧，建议人工复核"
        if support < LOW_SUPPORT_THRESHOLD:
            return "类别样本不足 {} 条，统计结果不稳定".format(
                LOW_SUPPORT_THRESHOLD
            )
        if dominance < CONFLICT_DOMINANCE:
            return "类别证据接近，存在歧义"
        if confidence >= 0.90:
            return "统计集成证据一致且 Top2 差距明显"
        if confidence >= REVIEW_THRESHOLD:
            return "统计集成证据较强"
        return "统计集成证据偏弱，建议人工复核"

    # -- 预测 ------------------------------------------------------------

    def predict_name(self, name: str) -> Dict[str, Any]:
        signals = self._signals(name)
        neighbors = self.similarity.query(name)
        combined = combine_signals(signals, self.weights, self.categories)
        ranked = sorted(
            self.categories,
            key=lambda category: (-combined.get(category, 0.0), category),
        )
        profession = ranked[0] if ranked else ""
        top = combined.get(profession, 0.0)
        second = combined.get(ranked[1], 0.0) if len(ranked) > 1 else 0.0
        support = int(self.class_support.get(profession, 0))
        confidence = self._confidence(top, second, support)
        dominance = top / (top + second) if top + second > 0 else 1.0

        active = [
            key for key in SIGNAL_ORDER
            if float(self.weights.get(key, 0.0)) > 0.0
        ]
        signal_tops: Dict[str, str] = {}
        for key in active:
            probabilities = signals.get(key, {})
            if probabilities:
                signal_tops[key] = max(probabilities, key=probabilities.get)
        agreement = sum(
            float(self.weights.get(key, 0.0))
            for key in active
            if signal_tops.get(key) == profession
        )
        disagreement = agreement < 0.5
        neighbor_conflict = (
            bool(neighbors)
            and neighbors[0].profession != profession
            and neighbors[0].similarity >= NEIGHBOR_CONFLICT_SIMILARITY
        )
        if disagreement or neighbor_conflict:
            confidence = min(confidence, 0.69)
        needs_review = (
            confidence < REVIEW_THRESHOLD
            or support < LOW_SUPPORT_THRESHOLD
            or dominance < CONFLICT_DOMINANCE
            or disagreement
            or neighbor_conflict
        )

        if len(active) > 1:
            level = "ensemble"
            method = "统计集成"
            source = "ensemble"
        elif active:
            level = SIGNAL_LEVELS[active[0]]
            method = SIGNAL_METHODS[active[0]]
            source = active[0]
        else:
            # 权重搜索没有可用样本时的兜底：仍返回均匀分布结果并强制复核。
            level = "manual"
            method = "人工"
            source = "manual"

        evidence: List[str] = []
        evidence_detail: List[Dict[str, Any]] = []
        if float(self.weights.get("term", 0.0)) > 0.0:
            matched = self._matched_terms(
                self.mined_terms, profession, normalize_name(name)
            )
            matched.sort(key=lambda item: (-item.weight, item.term))
            evidence.extend(self._format_term_evidence(profession, name))
            evidence_detail.extend(
                {
                    "type": "term",
                    "term": item.term,
                    "profession": profession,
                    "weight": round(float(item.weight), 4),
                    "source": "statistical",
                }
                for item in matched[:5]
            )
        if float(self.weights.get("knn", 0.0)) > 0.0:
            evidence.extend(self._format_neighbors(neighbors))
            evidence_detail.extend(
                {
                    "type": "similar",
                    "name": neighbor.name,
                    "profession": neighbor.profession,
                    "similarity": round(neighbor.similarity, 4),
                }
                for neighbor in neighbors[:3]
            )
        if float(self.weights.get("nb", 0.0)) > 0.0:
            grams = (
                self.nb.top_contributions(name, profession, 5)
                if profession
                else []
            )
            evidence_label = "字符统计"
            if not grams and profession:
                # 查询没有可用 n-gram（例如单字名称）时，退化为类别高概率片段。
                grams = self.nb.top_grams(profession, 5)
                evidence_label = "类别高概率 n-gram"
            if grams:
                evidence.append(
                    "{}：{}".format(
                        evidence_label,
                        "/".join(gram for gram, _score in grams),
                    )
                )
            evidence_detail.extend(
                {
                    "type": "nb",
                    "term": gram,
                    "profession": profession,
                    "weight": round(score, 4),
                }
                for gram, score in grams[:5]
            )
        evidence.append(self._format_weights())
        if disagreement:
            evidence.append(
                "信号分歧：{}".format(
                    "；".join(
                        "{}→{}".format(
                            SIGNAL_LABELS[key], signal_tops.get(key, "—")
                        )
                        for key in active
                    )
                )
            )
        if neighbor_conflict:
            evidence.append(
                "最近邻类别与集成结果不一致：{}（{}，相似度 {:.0%}）".format(
                    neighbors[0].name,
                    neighbors[0].profession,
                    neighbors[0].similarity,
                )
            )
        evidence_detail.extend(
            {
                "type": "ensemble",
                "name": key,
                "profession": profession,
                "weight": round(float(self.weights.get(key, 0.0)), 4),
                "source": key,
            }
            for key in active
        )

        weight_text = " · ".join(
            "{} {:.0%}".format(
                SIGNAL_LABELS[key], float(self.weights.get(key, 0.0))
            )
            for key in SIGNAL_ORDER
        )
        return {
            "profession": profession,
            "system": self.system_map.get(profession, ""),
            "confidence": round(confidence, 4),
            "method": method,
            "source": source,
            "evidence_level": level,
            "confidence_reason": self._confidence_reason(
                confidence, dominance, support, disagreement or neighbor_conflict
            ),
            "needs_review": needs_review,
            "evidence": evidence,
            "evidence_detail": evidence_detail,
            "top3": self._top3(combined, profession, confidence),
            "detail": "统计集成权重：{}；类别样本 {} 条".format(
                weight_text, support
            ),
        }

    def evaluate(self) -> Dict[str, Any]:
        """用分层折的 out-of-fold 信号评估集成效果。"""
        result = evaluate_ensemble(
            self._tuning_rows, self.categories, self.weights
        )

        labels: List[str] = []
        predictions: List[str] = []
        confidences: List[float] = []
        for truth, signals in self._tuning_rows:
            combined = combine_signals(
                signals, self.weights, self.categories
            )
            labels.append(truth)
            if not self.categories:
                predictions.append("")
                confidences.append(0.0)
                continue
            ranked = sorted(
                self.categories,
                key=lambda category: (-combined.get(category, 0.0), category),
            )
            prediction = ranked[0]
            second = combined.get(ranked[1], 0.0) if len(ranked) > 1 else 0.0
            confidences.append(
                self._confidence(
                    combined.get(prediction, 0.0),
                    second,
                    int(self.class_support.get(prediction, 0)),
                )
            )
            predictions.append(prediction)

        result["calibration"] = _calibration_report(
            confidences, labels, predictions
        )
        result["class_support"] = dict(self.class_support)
        result["warnings"] = [
            "{} 样本仅 {} 条，统计结果不稳定".format(category, count)
            for category, count in sorted(self.class_support.items())
            if count < LOW_SUPPORT_THRESHOLD
        ]
        result["weights"] = dict(self.weights)
        result["tuning_accuracy"] = round(float(self.tuning_accuracy), 4)
        result["method"] = "stratified-5-fold"
        result["folds"] = self.tuning_folds
        result["sample_count"] = len(self._tuning_rows)
        result["name_mode"] = True
        result["note"] = (
            "分层折 out-of-fold；权重在同一批 out-of-fold 行上搜索，"
            "指标偏乐观，但泄漏程度低于同数据留一法；每类样本量见 class_support"
        )
        return result


def evaluate_labels(
    labels: Sequence[str],
    predictions: Sequence[str],
    categories: Sequence[str],
) -> Dict[str, Any]:
    total = len(labels)
    correct = sum(1 for truth, prediction in zip(labels, predictions) if truth == prediction)
    per_class: Dict[str, Dict[str, float]] = {}
    f1_scores: List[float] = []
    confusion: Dict[str, Dict[str, int]] = {
        category: {other: 0 for other in categories}
        for category in categories
    }
    for truth, prediction in zip(labels, predictions):
        if truth in confusion and prediction in confusion[truth]:
            confusion[truth][prediction] += 1
    for category in categories:
        true_positive = sum(
            1 for truth, prediction in zip(labels, predictions)
            if truth == category and prediction == category
        )
        false_positive = sum(
            1 for truth, prediction in zip(labels, predictions)
            if truth != category and prediction == category
        )
        false_negative = sum(
            1 for truth, prediction in zip(labels, predictions)
            if truth == category and prediction != category
        )
        support = sum(1 for truth in labels if truth == category)
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[category] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }
        f1_scores.append(f1)
    return {
        "accuracy": float(correct) / total if total else 0.0,
        "macro_f1": sum(f1_scores) / len(f1_scores) if f1_scores else 0.0,
        "per_class": per_class,
        "sample_count": total,
        "confusion_matrix": confusion,
    }


def _calibration_report(
    confidences: Sequence[float],
    labels: Sequence[str],
    predictions: Sequence[str],
) -> List[Dict[str, Any]]:
    bins = [
        # 置信度为 0 时单独成箱，避免样本被静默丢弃。
        (0.0, 0.50, "<0.50"),
        (0.50, 0.60, "0.50-0.60"),
        (0.60, 0.70, "0.60-0.70"),
        (0.70, 0.80, "0.70-0.80"),
        (0.80, 0.85, "0.80-0.85"),
        (0.85, 0.90, "0.85-0.90"),
        (0.90, 0.9501, "0.90-0.95"),
    ]
    report: List[Dict[str, Any]] = []
    for low, high, label in bins:
        indices = [index for index, value in enumerate(confidences) if low <= value < high]
        if not indices:
            continue
        correct = sum(1 for index in indices if labels[index] == predictions[index])
        report.append({
            "bin": label,
            "count": len(indices),
            "accuracy": round(float(correct) / len(indices), 4),
        })
    return report


class ClassificationPipeline:
    """参照表精确命中 + 纯统计集成证据引擎。"""

    def __init__(self, reference: ReferenceData) -> None:
        self.reference = reference
        self.categories = list(reference.categories)
        if not reference.training_examples:
            raise ExcelError("INVALID_FILE", "参照表没有可用于训练的唯一名称记录")
        self.engine = EvidenceEngine(
            reference.training_examples,
            self.categories,
            reference.system_map,
        )
        self.mined_terms = self.engine.mined_terms
        self.similarity = self.engine.similarity
        self.weights = self.engine.weights
        self.class_support = self.engine.class_support

    def evaluation(self) -> Dict[str, Any]:
        return self.engine.evaluate()

    def keyword_report(self) -> List[Dict[str, Any]]:
        return keyword_report(
            self.mined_terms,
            self.reference.training_examples,
            self.reference.system_map,
        )

    def _reference_result(
        self,
        name: str,
        label: Dict[str, Any],
        method: str,
        confidence: float,
    ) -> Dict[str, Any]:
        combined = self.engine._combined(name)
        neighbors = self.engine.similarity.query(name)
        evidence = [
            "参照表命中：{}（一致率 {:.0%}）".format(method, label["ratio"]),
            "参照表 {} 条同组记录，多数票 {}/{}。".format(
                label["total"], label["votes"], label["total"]
            ),
        ]
        evidence.extend(self.engine._format_neighbors(neighbors, 2))
        return {
            "profession": label["profession"],
            "system": label["system"],
            "confidence": round(min(MAX_CONFIDENCE, confidence), 4),
            "method": method,
            "source": "reference",
            "evidence_level": "reference",
            "confidence_reason": "参照表精确命中",
            # 同组记录存在分歧、置信度偏低或类别样本不足时都应人工复核；
            # 精确命中的预测结果本身保持不变。
            "needs_review": (
                label.get("ratio", 1.0) < 1.0
                or confidence < REVIEW_THRESHOLD
                or int(self.engine.class_support.get(label["profession"], 0))
                < LOW_SUPPORT_THRESHOLD
            ),
            "evidence": evidence,
            "evidence_detail": [
                {
                    "type": "reference",
                    "name": method,
                    "profession": label["profession"],
                    "weight": round(label["ratio"], 4),
                    "source": "reference",
                }
            ],
            "top3": self.engine._top3(
                combined, label["profession"], confidence
            ),
            "detail": "参照表 {} 条同组记录，多数票 {}/{}。".format(
                label["total"], label["votes"], label["total"]
            ),
        }

    def predict(self, name: str, code: str = "") -> Dict[str, Any]:
        clean_name = str(name or "").strip()

        code_key = normalize_code(code)
        if code_key and code_key in self.reference.by_code:
            label = self.reference.by_code[code_key]
            confidence = (
                MAX_CONFIDENCE
                if label["ratio"] >= 1.0
                else 0.90 + 0.03 * label["ratio"]
            )
            return self._reference_result(
                clean_name, label, "参照表·标准号", confidence
            )

        name_key = normalize_name(clean_name)
        if name_key and name_key in self.reference.by_name:
            label = self.reference.by_name[name_key]
            return self._reference_result(
                clean_name, label, "参照表·名称", 0.93
            )

        code_base = base_code(code_key) if code_key else ""
        if code_base and code_base in self.reference.by_base:
            label = self.reference.by_base[code_base]
            confidence = min(0.90, 0.85 + 0.05 * label["ratio"])
            return self._reference_result(
                clean_name, label, "参照表·标准号主体", confidence
            )

        return self.engine.predict_name(clean_name)


def classify_pending_groups(
    pipeline: ClassificationPipeline,
    items: Sequence[Dict[str, Any]],
    threshold: float,
    dedup_reports: Sequence[Dict[str, Any]],
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """只对无歧义的组调用模型；有歧义的组留空，交给人工分类。"""
    rows: List[Dict[str, Any]] = []
    low_rows: List[Dict[str, Any]] = []
    profession_counts: Counter = Counter()
    system_counts: Counter = Counter()
    low_count = 0

    for item in items:
        status = item.get("status", "auto")
        result: Dict[str, Any] = {}
        if status == "auto":
            result = pipeline.predict(item.get("name", ""), item.get("code", ""))
            profession = result["profession"]
            system = result["system"]
            confidence = float(result["confidence"])
            low = confidence < threshold or bool(result.get("needs_review"))
            if low:
                low_count += 1
            profession_counts[profession] += 1
            system_counts[system] += 1
        else:
            profession = ""
            system = ""
            confidence = 0.0
            low = False

        row = {
            "index": item["index"],
            "code": item.get("code", ""),
            "name": item.get("name", ""),
            "system": system,
            "profession": profession,
            "confidence": round(confidence, 4),
            "method": result.get("method", "人工"),
            "source": result.get("source", "manual"),
            "top3": result.get("top3", []),
            "evidence": result.get("evidence", []),
            "evidence_detail": result.get("evidence_detail", []),
            "evidence_level": result.get("evidence_level", "manual"),
            "confidence_reason": result.get("confidence_reason", ""),
            "needs_review": bool(result.get("needs_review", low)),
            "detail": result.get("detail", ""),
            "low_confidence": low,
            "duplicate_count": item.get("count", 1),
            "source_rows": list(item.get("source_rows", [])),
            "units": list(item.get("units", [])),
            "status": status,
            "reason": item.get("reason", ""),
            "needs_confirmation": bool(item.get("needs_confirmation")),
        }
        rows.append(row)
        if low:
            low_rows.append(row)

    auto_rows = [row for row in rows if row["status"] == "auto"]
    manual_rows = [row for row in rows if row["status"] == "manual"]
    multi_unit_count = sum(1 for row in rows if row["needs_confirmation"])
    summary_meta = dict(meta or {})
    summary = {
        "raw_rows": summary_meta.get(
            "raw_rows", sum(int(item.get("count", 1)) for item in items)
        ),
        "unique_rows": len(rows),
        "group_count": len(rows),
        "auto_count": len(auto_rows),
        "manual_count": len(manual_rows),
        "multi_unit_count": multi_unit_count,
        "low_confidence_count": low_count,
        "threshold": threshold,
        "dedup_basis": summary_meta.get("dedup_basis", ""),
    }

    return {
        "rows": rows,
        "auto_rows": auto_rows,
        "manual_rows": manual_rows,
        "low_rows": low_rows,
        "categories": [
            {
                "profession": profession,
                "system": pipeline.reference.system_map.get(profession, ""),
            }
            for profession in pipeline.categories
        ],
        "summary": summary,
        "stats": {
            "professions": dict(profession_counts),
            "systems": dict(system_counts),
            "total": len(auto_rows),
        },
        "conflicts": pipeline.reference.conflicts,
        "mapping": pipeline.reference.mapping,
        "warnings": pipeline.reference.warnings,
        "dedup_reports": list(dedup_reports),
        "evaluation": pipeline.evaluation(),
        "keyword_report": pipeline.keyword_report(),
        "ensemble_weights": dict(pipeline.weights),
        "class_support": dict(pipeline.class_support),
    }


def classify_pending(
    pipeline: ClassificationPipeline,
    items: Sequence[Dict[str, Any]],
    threshold: float,
    dedup_reports: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """批量分类去重后的标准，并生成统计与低置信度清单。"""
    rows: List[Dict[str, Any]] = []
    low_rows: List[Dict[str, Any]] = []
    method_counts: Counter = Counter()
    confidence_bins: Counter = Counter()
    profession_counts: Counter = Counter()
    system_counts: Counter = Counter()

    for index, item in enumerate(items, start=1):
        result = pipeline.predict(item["name"], item["code"])
        row = {
            "index": index,
            "code": item["code"],
            "name": item["name"],
            "system": result["system"],
            "profession": result["profession"],
            "confidence": result["confidence"],
            "method": result["method"],
            "source": result["source"],
            "top3": result["top3"],
            "evidence": result["evidence"],
            "evidence_detail": result.get("evidence_detail", []),
            "evidence_level": result.get("evidence_level", "manual"),
            "confidence_reason": result.get("confidence_reason", ""),
            "needs_review": bool(result.get("needs_review", False)),
            "detail": result["detail"],
            "low_confidence": result["confidence"] < threshold or bool(result.get("needs_review")),
            "duplicate_count": item.get("count", 1),
            "source_rows": item.get("source_rows", []),
        }
        rows.append(row)
        method_counts[result["method"]] += 1
        profession_counts[result["profession"]] += 1
        system_counts[result["system"]] += 1

        if result["confidence"] >= 0.85:
            confidence_bins["高（≥0.85）"] += 1
        elif result["confidence"] >= 0.70:
            confidence_bins["中（0.70–0.84）"] += 1
        else:
            confidence_bins["低（<0.70）"] += 1

        if row["low_confidence"]:
            low_rows.append(row)

    raw_rows = sum(int(item.get("count", 1)) for item in items)
    reference_rows = sum(1 for row in rows if row["source"] == "reference")
    model_rows = len(rows) - reference_rows
    non_reference_rows = len(rows) - reference_rows
    new_rows = [row for row in rows if row["source"] != "reference"]

    return {
        "rows": rows,
        "new_rows": new_rows,
        "low_rows": low_rows,
        "categories": [
            {
                "profession": profession,
                "system": pipeline.reference.system_map.get(profession, ""),
            }
            for profession in pipeline.categories
        ],
        "summary": {
            "raw_rows": raw_rows,
            "unique_rows": len(rows),
            "reference_rows": reference_rows,
            "model_rows": model_rows,
            "non_reference_rows": non_reference_rows,
            "low_confidence_count": len(low_rows),
            "threshold": threshold,
            "method_counts": dict(method_counts),
            "confidence_bins": dict(confidence_bins),
        },
        "stats": {
            "professions": dict(profession_counts),
            "systems": dict(system_counts),
            "total": len(rows),
        },
        "conflicts": pipeline.reference.conflicts,
        "mapping": pipeline.reference.mapping,
        "warnings": pipeline.reference.warnings,
        "dedup_reports": list(dedup_reports),
        "evaluation": pipeline.evaluation(),
        "keyword_report": pipeline.keyword_report(),
        "ensemble_weights": dict(pipeline.weights),
        "class_support": dict(pipeline.class_support),
    }

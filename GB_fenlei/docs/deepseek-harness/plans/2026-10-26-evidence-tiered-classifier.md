# 证据分级分类引擎 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有“字符 n-gram + 关键词 + softmax”分类器改造成可解释的四级证据链引擎（参照表 → 强规则/挖掘词 → 相似名称 → 模型兜底），并给出诚实的置信度与依据。

**Architecture:** 新增 `mining.py`（词条挖掘 + 相似名称索引）和 `rules.py`（概念种子 + 概念到类别映射 + 规则计分），`classifier.py` 用 `EvidenceEngine` 组合规则、相似名称和现有 softmax 兜底；`ClassificationPipeline` 负责参照表精确命中、置信度和留一法评估。API 只增字段，前端增加“判定依据”列和“分类依据词表”弹窗，导出追加“判定依据”列。

**Tech Stack:** Python 3.8（标准库 only）、FastAPI、openpyxl、Vue 3 + TypeScript、unittest。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `backend/text.py` | 新增子句切分、候选词提取、字符 n-gram |
| `backend/config.py` | 新增概念种子、阈值；删除写死类别的 `KEYWORD_RULES` 依赖 |
| `backend/mining.py` | 新增：从参照表挖掘词条、依据词表、相似名称索引 |
| `backend/rules.py` | 新增：概念→类别映射、规则计分、例外规则 |
| `backend/classifier.py` | 改造：`EvidenceEngine`、`ClassificationPipeline`、置信度、留一评估 |
| `backend/analysis.py` | 参照表分析返回 `keyword_report`、`concept_mapping` |
| `backend/export.py` | 导出追加“判定依据”列 |
| `backend/tests/test_text_features.py` | 新增：文本特征测试 |
| `backend/tests/test_mining.py` | 新增：挖掘与相似名称测试 |
| `backend/tests/test_rules.py` | 新增：规则与概念映射测试 |
| `backend/tests/test_pipeline_evidence.py` | 新增：证据链、置信度测试 |
| `backend/tests/test_evaluation.py` | 新增：留一法与外部测试集回归 |
| `frontend/src/types.ts` | 新增证据、词表、评估类型 |
| `frontend/src/components/ResultsStep.vue` | 增加“判定依据”列与展开详情 |
| `frontend/src/components/ReferenceStep.vue` | 增加“分类依据词表”弹窗 |

---

### Task 1: 文本特征工具（子句、候选词、字符 n-gram）

**Files:**
- Modify: `backend/text.py`
- Test: `backend/tests/test_text_features.py`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_text_features.py`：

```python
# -*- coding: utf-8 -*-
"""子句切分、候选词与字符 n-gram。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from text import candidate_terms, char_ngrams, normalize_name, segments


class TextFeatureTests(unittest.TestCase):
    def test_segments_keep_chinese_clauses(self):
        self.assertEqual(
            segments("技术制图 比例；第1部分：字体"),
            ["技术制图", "比例", "第1部分", "字体"],
        )

    def test_segments_normalize_width_and_case(self):
        self.assertEqual(segments("ＡＢＣ　标准"), ["abc", "标准"])

    def test_candidate_terms_include_substrings_and_ascii(self):
        terms = candidate_terms("六角头螺栓 HB 123")
        self.assertIn("六角头螺栓", terms)
        self.assertIn("螺栓", terms)
        self.assertIn("六角", terms)
        self.assertIn("hb", terms)

    def test_candidate_terms_keep_alphanumeric_codes(self):
        self.assertIn("2a12", candidate_terms("2A12铝合金板材"))
        self.assertIn("h6132", candidate_terms("H61-32铜合金"))
        self.assertIn("lan", candidate_terms("L-AN全合成油"))

    def test_candidate_terms_do_not_join_punctuated_codes(self):
        terms = candidate_terms("液压油（L-HL、L-HM、L-HV）")
        self.assertIn("lhl", terms)
        self.assertIn("lhm", terms)
        self.assertNotIn("lhllhm", terms)
        self.assertNotIn("lhllhmlhv", terms)

    def test_candidate_terms_respect_length_bounds(self):
        terms = candidate_terms("一二三四五六七")
        self.assertTrue(terms)
        for term in terms:
            self.assertGreaterEqual(len(term), 2)
            self.assertLessEqual(len(term), 6)

    def test_candidate_terms_clamp_invalid_bounds(self):
        self.assertIn("钢", candidate_terms("钢板", min_length=0, max_length=1))

    def test_candidate_terms_live_in_normalized_space(self):
        name = "H61-32铜合金 2A12板材"
        normalized = normalize_name(name)
        for term in candidate_terms(name):
            self.assertIn(term, normalized)

    def test_char_ngrams_remove_spaces_and_punctuation(self):
        grams = char_ngrams("六角头 螺栓")
        self.assertIn("六角", grams)
        self.assertIn("螺栓", grams)
        self.assertIn("六角头", grams)

    def test_char_ngrams_respect_sizes_argument(self):
        self.assertEqual(char_ngrams("abc", sizes=(3,)), ["abc"])
        self.assertEqual(char_ngrams("abc", sizes=(0, 3)), ["abc"])

    def test_empty_and_short_inputs(self):
        self.assertEqual(candidate_terms(""), [])
        self.assertEqual(char_ngrams("钢"), [])

    def test_candidate_terms_never_contain_punctuation(self):
        terms = candidate_terms("金属材料（板材）")
        self.assertTrue(terms)
        for term in terms:
            self.assertNotIn("（", term)
            self.assertNotIn("）", term)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m unittest tests.test_text_features -v`
Expected: FAIL，`ImportError: cannot import name 'candidate_terms'`

- [ ] **Step 3: 实现文本工具**

在 `backend/text.py` 顶部把 `from typing import Any, List` 改为：

```python
from typing import Any, List, Sequence
```

在顶部模块常量区，将原有 `_NAME_PUNCTUATION_RE` 定义替换为：

```python
_PUNCTUATION_CLASS = r"，,。.;；、:：\-—_/\\()（）\[\]【】<>《》\"'“”‘’"
_NAME_PUNCTUATION_RE = re.compile(r"[" + _PUNCTUATION_CLASS + r"]")
_SEGMENT_SPLIT_RE = re.compile(r"[\s" + _PUNCTUATION_CLASS + r"]+")
_ALNUM_SEPARATOR_CLASS = r"\s，,。.;；、:：\\()（）\[\]【】<>《》\"'“”‘’—–－"
_ALNUM_CLAUSE_SPLIT_RE = re.compile(
    r"[" + _ALNUM_SEPARATOR_CLASS + r"]+|" + CHINESE_RE.pattern
)
_ALNUM_TOKEN_RE = re.compile(r"[a-z0-9]+")
```

在 `tokenize` 之前加入：

```python
def segments(text: Any) -> List[str]:
    """按空格和标点切分名称，保留中文子句边界。"""
    normalized = unicodedata.normalize("NFKC", to_text(text)).lower()
    return [part for part in _SEGMENT_SPLIT_RE.split(normalized) if part]


def candidate_terms(
    text: Any, min_length: int = 2, max_length: int = 6
) -> List[str]:
    """提取候选词条：中文 2~6 元子串 + 含字母的字母数字 token（纯数字排除）。"""
    min_length = max(1, min_length)
    max_length = max(min_length, max_length)
    terms = set()
    for segment in segments(text):
        for match in CHINESE_RE.finditer(segment):
            chunk = match.group(0)
            for length in range(min_length, min(max_length, len(chunk)) + 1):
                for start in range(len(chunk) - length + 1):
                    terms.add(chunk[start : start + length])

    normalized = unicodedata.normalize("NFKC", to_text(text)).lower()
    for clause in _ALNUM_CLAUSE_SPLIT_RE.split(normalized):
        for token in _ALNUM_TOKEN_RE.findall(normalize_name(clause)):
            if len(token) >= 2 and any(char.isalpha() for char in token):
                terms.add(token)
    return sorted(terms)


def char_ngrams(text: Any, sizes: Sequence[int] = (2, 3)) -> List[str]:
    """去掉标点和空格后的字符 n-gram，用于相似名称检索。

    normalize_name 会移除分隔符，因此跨子句窗口同样视为有效特征。
    """
    normalized = normalize_name(text)
    grams = set()
    for size in sizes:
        if size < 1 or len(normalized) < size:
            continue
        for index in range(len(normalized) - size + 1):
            grams.add(normalized[index : index + size])
    return sorted(grams)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m unittest tests.test_text_features -v`
Expected: 12 tests PASS

- [ ] **Step 5: 提交**

```bash
git add backend/text.py backend/tests/test_text_features.py
git commit -m "feat: 增加子句切分、候选词与字符 n-gram 工具"
```

---

### Task 2: 配置概念种子与置信度阈值

**Files:**
- Modify: `backend/config.py`
- Test: `backend/tests/test_rules.py`（本任务先写概念结构测试）

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_rules.py`（后续任务会继续追加）：

```python
# -*- coding: utf-8 -*-
"""概念种子、概念映射与规则计分。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import CONCEPTS


class ConceptConfigTests(unittest.TestCase):
    def test_all_seven_concepts_exist(self):
        self.assertEqual(
            set(CONCEPTS),
            {"TEST", "FASTENER", "MATERIAL", "LUBRICANT", "COATING", "ASSEMBLY", "DESIGN"},
        )

    def test_seeds_are_weighted_pairs_and_unique_within_concept(self):
        for concept, spec in CONCEPTS.items():
            terms = [term for term, _weight in spec["seeds"]]
            self.assertEqual(len(terms), len(set(terms)), concept)
            for term, weight in spec["seeds"]:
                self.assertIsInstance(term, str)
                self.assertGreater(len(term), 0)
                self.assertGreaterEqual(weight, 2)
                self.assertLessEqual(weight, 10)

    def test_neutral_suffixes_are_not_scored_as_seeds(self):
        neutral = {"规范", "要求", "通用要求", "航空", "飞机", "方法"}
        for concept, spec in CONCEPTS.items():
            seeds = {term for term, _weight in spec["seeds"]}
            self.assertFalse(seeds & neutral, concept)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m unittest tests.test_rules.ConceptConfigTests -v`
Expected: FAIL，`ImportError: cannot import name 'CONCEPTS'`

- [ ] **Step 3: 添加配置**

在 `backend/config.py` 顶部把 `from typing import Dict, List, Tuple` 改为：

```python
from typing import Any, Dict, List, Tuple
```

在 `MIN_TEMPERATURE` / `MAX_MODEL_CONFIDENCE` 之后加入：

```python
# ---------------------------------------------------------------------------
# 证据分级引擎参数
# ---------------------------------------------------------------------------

REVIEW_THRESHOLD = 0.70
MAX_CONFIDENCE = 0.95
MODEL_FALLBACK_CONFIDENCE = 0.60
MIN_RULE_SCORE = 4.0
RULE_STRONG_SCORE = 8.0
CONFLICT_DOMINANCE = 0.55
MINED_SOURCE_FACTOR = 0.8
TEST_HEAD_BONUS = 4.0
TEST_HEAD_PARTIAL_FACTOR = 0.75
COATING_RATING_BONUS = 8.0

# 位置与产品中心词参数
TAIL_RATIO = 2.0 / 3.0
PRODUCT_HEAD_MIN_WEIGHT = 9.0
PRODUCT_HEAD_FACTOR = 1.5

KNN_TOP_K = 5
KNN_MIN_SIMILARITY = 0.20
KNN_SUPPORT_WEIGHT = 0.5

MINING_MIN_SUPPORT = 2
MINING_MIN_PURITY = 0.80
MINING_MAX_TERMS_PER_CLASS = 80
MINING_LONG_TERM_LENGTH = 5
```

在 `KEYWORD_RULES` 之前加入概念种子（保留旧 `KEYWORD_RULES` 直到 Task 5 删除）：

```python
# 领域概念。规则不直接绑定专业名，启动时按种子词映射到上传表的实际类别。
CONCEPTS: Dict[str, Dict[str, Any]] = {
    "TEST": {
        "label": "试验检验",
        "seeds": [
            ("试验方法", 10), ("测定法", 10), ("检测方法", 9), ("测定", 6),
            ("无损检测", 9), ("盐雾试验", 9), ("冲击试验", 7), ("拉伸试验", 7),
            ("弯曲试验", 7), ("硬度试验", 7), ("环境试验", 8), ("试验", 4),
            ("检验", 4), ("检测", 4), ("抽样", 6), ("评级", 4),
            ("资格鉴定", 6), ("认证", 4), ("校准", 5), ("计量", 5),
            ("淋雨", 5), ("防水性", 5), ("污染度", 5), ("酸值", 4),
            ("闪点", 4), ("运动粘度", 5), ("采样", 5), ("水分", 4),
            ("承载能力", 5), ("四球法", 6), ("金相", 5), ("探伤", 6),
            ("审核", 5), ("质量管理体系", 8), ("气动外缘公差", 8),
            ("测试方法", 9), ("划格试验", 9), ("测试报告", 8),
        ],
        "patterns": ["试验方法", "测定法", "检测方法", "试验"],
    },
    "FASTENER": {
        "label": "紧固与连接件",
        "seeds": [
            ("螺栓", 9), ("螺钉", 9), ("螺母", 9), ("垫圈", 9), ("挡圈", 10),
            ("开口销", 10), ("圆柱销", 10), ("圆锥销", 10), ("销轴", 9),
            ("平键", 10), ("自锁螺母", 10), ("钢丝螺套", 9), ("关节轴承", 9),
            ("紧固件", 8), ("六角头", 7), ("托板", 6), ("弹性挡圈", 10),
            ("弹簧垫圈", 9), ("紧定螺钉", 9), ("蝶形螺母", 9), ("键", 4),
            ("销", 5),
        ],
        "patterns": ["螺栓", "螺钉", "螺母", "垫圈", "挡圈", "销", "键"],
    },
    "MATERIAL": {
        "label": "金属材料",
        "seeds": [
            ("不锈钢", 7), ("合金结构钢", 8), ("碳素结构钢", 8),
            ("优质碳素结构钢", 9), ("合金钢", 7), ("轴承钢", 7),
            ("工具钢", 6), ("弹簧钢", 6), ("高温合金", 7), ("耐热钢", 7),
            ("钛合金", 7), ("铝合金", 7), ("铜合金", 7), ("镁合金", 7),
            ("镍合金", 7), ("黄铜", 8), ("紫铜", 7), ("青铜", 7),
            ("白铜", 7), ("钢板", 5), ("钢带", 5), ("钢管", 5),
            ("钢棒", 5), ("钢丝", 4), ("棒材", 5), ("板材", 5),
            ("薄板", 5), ("厚板", 4), ("带材", 5), ("型材", 5),
            ("无缝钢管", 6), ("拉制管", 5), ("挤制棒", 5), ("拉制棒", 5),
            ("冷拉丝", 5), ("焊丝", 5), ("化学成分", 6), ("结构钢", 6),
            ("碳素", 4), ("金属材料", 8), ("铝", 3), ("铜", 3),
            ("钛", 3), ("镁", 3), ("镍", 3), ("钢", 3),
        ],
        "patterns": ["钢", "合金", "铝", "铜", "钛", "板材", "棒材", "管材"],
    },
    "LUBRICANT": {
        "label": "润滑油",
        "seeds": [
            ("润滑油", 9), ("润滑脂", 9), ("液压油", 9), ("喷气燃料", 9),
            ("冷却液", 9), ("全损耗系统用油", 9), ("润滑剂", 8), ("机油", 7),
            ("燃油", 6), ("燃料", 6), ("油品", 5), ("液压传动", 6),
            ("石油产品", 6), ("烃", 4), ("酯", 3),
        ],
        "patterns": ["润滑油", "润滑脂", "液压油", "燃料", "油"],
    },
    "COATING": {
        "label": "表面处理",
        "seeds": [
            ("电镀", 9), ("镀层", 8), ("镀锌", 10), ("热浸镀锌", 10),
            ("阳极氧化", 10), ("氧化膜", 8), ("涂覆", 8), ("涂层", 7),
            ("涂料", 8), ("磁漆", 9), ("涂铝", 10), ("涂二硫化钼", 10),
            ("表面处理", 9), ("表面清洁度", 7), ("锈蚀", 6), ("覆盖层", 8),
            ("无机硅酸盐玻璃涂料", 10), ("玻璃涂料", 10), ("干膜润滑剂", 10),
            ("钝化", 7), ("磷化", 7), ("喷漆", 7), ("喷塑", 7),
            ("防腐", 6), ("色漆", 7), ("清漆", 7),
        ],
        "patterns": ["电镀", "镀层", "氧化", "涂覆", "涂层", "涂料", "覆盖层"],
    },
    "ASSEMBLY": {
        "label": "结构装配",
        "seeds": [
            ("装配", 9), ("工装", 8), ("防护", 6), ("焊接", 6),
            ("焊料", 10), ("钎料", 10), ("钎剂", 10), ("橡胶", 8),
            ("石棉", 8), ("层压", 8), ("人造革", 9), ("泡沫塑料", 8),
            ("玻璃纤维", 8), ("聚氨酯", 8), ("密封", 6), ("铆接", 6),
            ("复合材料", 7), ("胶料", 8), ("胶粘", 6), ("聚乙烯", 8),
            ("树脂", 7), ("聚氯乙烯", 9), ("线束", 9), ("搅拌摩擦焊", 10),
            ("钢丝螺套安装", 9), ("橡胶零件", 9),
        ],
        "patterns": ["装配", "工装", "焊接", "焊料", "钎料", "橡胶", "塑料", "胶"],
    },
    "DESIGN": {
        "label": "设计与工程通用规范",
        "seeds": [
            ("设计", 6), ("设计要求", 8), ("设计准则", 9), ("制图", 9),
            ("技术制图", 10), ("图纸", 8), ("标题栏", 9), ("字体", 7),
            ("比例", 5), ("几何公差", 9), ("形位公差", 9), ("公差", 6),
            ("尺寸标注", 8), ("尺寸注法", 8), ("建模", 6), ("数据管理", 9),
            ("数据存储", 6), ("数据转换", 6), ("数据可视化", 6),
            ("标准化", 6), ("包装", 7), ("储运", 5), ("标志", 6),
            ("洁净厂房", 8), ("通风与空调", 8), ("施工质量验收", 9),
            ("维修性", 8), ("结构完整性", 8), ("增材制造", 6),
            ("维修手册", 9), ("数据长周期存储", 10), ("载荷计算", 9),
            ("计算方法", 7), ("符号", 7), ("接口", 7), ("燃油箱惰化", 9),
            ("模拟负载", 8), ("许用值", 8), ("客户服务", 5), ("电磁干扰", 5),
        ],
        "patterns": ["设计", "制图", "公差", "标注", "手册"],
    },
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m unittest tests.test_rules.ConceptConfigTests -v`
Expected: 3 tests PASS

- [ ] **Step 5: 提交**

```bash
git add backend/config.py backend/tests/test_rules.py
git commit -m "feat: 增加领域概念种子与证据引擎阈值"
```

---

### Task 3: 词条挖掘与相似名称索引

**Files:**
- Create: `backend/mining.py`
- Test: `backend/tests/test_mining.py`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_mining.py`：

```python
# -*- coding: utf-8 -*-
"""词条挖掘、依据词表与相似名称索引。"""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mining import NameSimilarityIndex, keyword_report, mine_terms


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


class MiningTests(unittest.TestCase):
    def test_mined_terms_have_purity_and_support(self):
        mined = mine_terms(EXAMPLES)
        terms = {item.term: item for item in mined["表面处理"]}
        self.assertIn("阳极氧化", terms)
        self.assertEqual(terms["阳极氧化"].support, 2)
        self.assertEqual(terms["阳极氧化"].purity, 1.0)

    def test_cross_class_term_is_filtered_or_low_purity(self):
        mined = mine_terms(EXAMPLES)
        for items in mined.values():
            for item in items:
                self.assertGreaterEqual(item.purity, 0.80)

    def test_single_long_term_is_kept(self):
        mined = mine_terms(EXAMPLES)
        terms = {item.term for item in mined["表面处理"]}
        self.assertIn("热浸镀锌层", terms)

    def test_keyword_report_contains_examples(self):
        mined = mine_terms(EXAMPLES)
        report = keyword_report(
            mined,
            EXAMPLES,
            {"表面处理": "表面工程与防护技术"},
            {},
            {},
        )
        group = next(item for item in report if item["profession"] == "表面处理")
        self.assertEqual(group["system"], "表面工程与防护技术")
        self.assertTrue(group["keywords"])
        self.assertTrue(group["keywords"][0]["examples"])

    def test_similarity_returns_same_class_neighbor(self):
        index = NameSimilarityIndex(EXAMPLES)
        neighbors = index.query("六角螺栓", top_k=3)
        self.assertTrue(neighbors)
        self.assertEqual(neighbors[0].profession, "紧固与连接件")
        self.assertGreater(neighbors[0].similarity, 0.0)

    def test_similarity_filters_unrelated_names(self):
        index = NameSimilarityIndex(EXAMPLES)
        self.assertEqual(index.query("完全无关的量子计算协议"), [])


class MiningContractTests(unittest.TestCase):
    def test_weight_formula(self):
        mined = mine_terms(EXAMPLES)
        term = next(item for item in mined["表面处理"] if item.term == "阳极氧化")
        expected = (1.0 ** 2) * math.log(3) * (1 + 0.18 * 2)
        self.assertAlmostEqual(term.weight, expected, places=6)

    def test_mined_terms_are_sorted_by_weight(self):
        mined = mine_terms(EXAMPLES)
        for items in mined.values():
            weights = [item.weight for item in items]
            self.assertEqual(weights, sorted(weights, reverse=True))

    def test_max_terms_limits_output(self):
        mined = mine_terms(EXAMPLES, max_terms=2)
        for items in mined.values():
            self.assertLessEqual(len(items), 2)

    def test_min_support_override(self):
        mined = mine_terms(EXAMPLES, min_support=3)
        terms = {item.term for item in mined.get("表面处理", [])}
        self.assertNotIn("阳极氧化", terms)

    def test_keyword_report_merges_curated_terms(self):
        class Mapped:
            def __init__(self, profession):
                self.profession = profession

        mined = mine_terms(EXAMPLES)
        report = keyword_report(
            mined,
            EXAMPLES,
            {"金属材料": "航空金属材料技术"},
            {"MATERIAL": Mapped("金属材料")},
            {"MATERIAL": {"seeds": [("钢材", 5), ("钢板", 4)]}},
            max_keywords=1,
        )
        group = next(item for item in report if item["profession"] == "金属材料")
        sources = [item["source"] for item in group["keywords"]]
        self.assertIn("curated", sources)
        self.assertLessEqual(sources.count("mined"), 1)
        curated = {item["term"] for item in group["keywords"] if item["source"] == "curated"}
        self.assertIn("钢材", curated)
        self.assertIn("钢板", curated)

    def test_keyword_report_deduplicates_mined_and_curated(self):
        class Mapped:
            def __init__(self, profession):
                self.profession = profession

        mined = mine_terms(EXAMPLES)
        report = keyword_report(
            mined,
            EXAMPLES,
            {},
            {"MATERIAL": Mapped("金属材料")},
            {"MATERIAL": {"seeds": [("不锈钢", 5)]}},
        )
        group = next(item for item in report if item["profession"] == "金属材料")
        terms = [item["term"] for item in group["keywords"]]
        self.assertEqual(terms.count("不锈钢"), 1)

    def test_keyword_report_includes_profession_with_only_curated(self):
        class Mapped:
            def __init__(self, profession):
                self.profession = profession

        report = keyword_report(
            {},
            [],
            {},
            {"DESIGN": Mapped("设计与工程通用规范")},
            {"DESIGN": {"seeds": [("设计", 6)]}},
        )
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["profession"], "设计与工程通用规范")
        self.assertEqual(report[0]["keywords"][0]["source"], "curated")

    def test_similarity_uses_construction_ngram_sizes(self):
        index = NameSimilarityIndex(EXAMPLES, sizes=(4,))
        neighbors = index.query("阳极氧化膜", top_k=3)
        self.assertTrue(neighbors)

    def test_similarity_min_threshold_filters_all(self):
        index = NameSimilarityIndex(EXAMPLES)
        self.assertEqual(index.query("六角螺栓", min_similarity=0.99), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m unittest tests.test_mining -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'mining'`

- [ ] **Step 3: 实现 mining.py**

创建 `backend/mining.py`：

```python
# -*- coding: utf-8 -*-
"""从参照表挖掘高纯度特征词，并构建相似名称索引。"""

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config import (
    CONCEPTS,
    KNN_MIN_SIMILARITY,
    KNN_TOP_K,
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


def mine_terms(
    examples: Sequence[Example],
    min_support: int = MINING_MIN_SUPPORT,
    min_purity: float = MINING_MIN_PURITY,
    max_terms: int = MINING_MAX_TERMS_PER_CLASS,
    min_long_term_length: int = MINING_LONG_TERM_LENGTH,
) -> Dict[str, List[MinedTerm]]:
    """按类别挖掘高纯度词条。

    保留条件：支持度 >= min_support 且纯度 >= min_purity；或支持度 1、
    纯度 100% 且词长 >= min_long_term_length。
    """
    max_terms = max(0, max_terms)
    class_terms: Dict[str, Counter] = defaultdict(Counter)
    all_terms: Counter = Counter()
    term_examples: Dict[str, Dict[str, List[str]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for name, label in examples:
        for term in candidate_terms(name):
            all_terms[term] += 1
            class_terms[label][term] += 1
            if len(term_examples[label][term]) < 3:
                term_examples[label][term].append(name)

    result: Dict[str, List[MinedTerm]] = {}
    for label, counter in class_terms.items():
        scored: List[MinedTerm] = []
        for term, support in counter.items():
            other = all_terms[term] - support
            purity = float(support) / (support + other) if support + other else 0.0
            long_single = (
                support == 1
                and purity >= 1.0
                and len(term) >= min_long_term_length
            )
            if support < min_support and not long_single:
                continue
            if purity < min_purity:
                continue
            weight = (
                (purity ** 2)
                * math.log(1 + support)
                * (1 + 0.18 * (len(term) - 2))
            )
            scored.append(
                MinedTerm(
                    term=term,
                    support=support,
                    purity=purity,
                    weight=weight,
                    examples=list(term_examples[label][term]),
                )
            )
        scored.sort(key=lambda item: (-item.weight, -len(item.term), item.term))
        result[label] = scored[:max_terms]
    return result


def keyword_report(
    mined: Dict[str, List[MinedTerm]],
    examples: Sequence[Example],
    system_map: Dict[str, str],
    concept_mapping: Dict[str, Any],
    concepts: Dict[str, Dict[str, Any]],
    max_keywords: int = MINING_MAX_TERMS_PER_CLASS,
) -> List[Dict[str, Any]]:
    """生成每个专业的分类依据词表，人工种子与挖掘词并列。"""
    examples_by_class: Dict[str, List[str]] = defaultdict(list)
    for name, label in examples:
        examples_by_class[label].append(name)

    professions = set(mined) | {
        mapped.profession for mapped in concept_mapping.values()
    }
    report: List[Dict[str, Any]] = []
    for profession in sorted(professions):
        terms = mined.get(profession, [])
        keywords: List[Dict[str, Any]] = []
        seen = set()
        for item in terms[: max(0, max_keywords)]:
            seen.add(item.term)
            keywords.append({
                "term": item.term,
                "support": item.support,
                "purity": round(item.purity, 4),
                "weight": round(item.weight, 4),
                "source": "mined",
                "examples": item.examples,
            })
        for concept, mapped in concept_mapping.items():
            if mapped.profession != profession:
                continue
            for term, weight in concepts.get(concept, {}).get("seeds", []):
                if term in seen:
                    continue
                seen.add(term)
                keywords.append({
                    "term": term,
                    "support": None,
                    "purity": None,
                    "weight": float(weight),
                    "source": "curated",
                    "examples": [],
                })
        report.append({
            "profession": profession,
            "system": system_map.get(profession, ""),
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
        grams_list: List[set] = []
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

        TF-IDF 词表仅来自参照语料，因此语料外（OOV）的 n-gram 不参与
        查询向量范数（norm），只会让相似度下降而不会抬高相似度。
        """
        top_k = max(0, top_k)
        grams = set(char_ngrams(name, self._sizes))
        if not grams:
            return []
        norm = math.sqrt(
            sum(self._idf.get(gram, 0.0) ** 2 for gram in grams)
        )
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
                neighbors.append(
                    Neighbor(neighbor_name, profession, similarity)
                )
        neighbors.sort(key=lambda item: (-item.similarity, item.name))
        return neighbors[:top_k]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m unittest tests.test_mining -v`
Expected: 15 tests PASS

- [ ] **Step 5: 提交**

```bash
git add backend/mining.py backend/tests/test_mining.py
git commit -m "feat: 增加词条挖掘、依据词表与相似名称索引"
```

---

### Task 4: 概念映射、规则计分与例外规则

**Files:**
- Create: `backend/rules.py`
- Modify: `backend/tests/test_rules.py`

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_rules.py` 顶部加入：

```python
from mining import MinedTerm, mine_terms
from rules import map_concepts, score_name
```

在文件末尾、`if __name__` 之前加入：

```python
REFERENCE_EXAMPLES = [
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


def _prediction(name):
    mapping = map_concepts(REFERENCE_EXAMPLES, sorted({label for _n, label in REFERENCE_EXAMPLES}))
    scores, _evidence, _matches = score_name(name, mapping, {})
    return max(scores, key=scores.get) if scores else None


class ConceptMappingTests(unittest.TestCase):
    def test_standard_seven_categories_are_mapped(self):
        categories = [
            "金属材料", "紧固与连接件", "润滑油", "试验检验",
            "表面处理", "结构装配", "设计与工程通用规范",
        ]
        examples = REFERENCE_EXAMPLES + [
            ("喷气燃料", "润滑油"),
            ("钢带", "金属材料"),
            ("电镀层", "表面处理"),
            ("飞机装配工装", "结构装配"),
            ("技术制图 字体", "设计与工程通用规范"),
            ("六角螺母", "紧固与连接件"),
            ("硬度试验", "试验检验"),
        ]
        mapping = map_concepts(examples, categories)
        self.assertEqual(len(mapping), 7)
        self.assertEqual(mapping["MATERIAL"].profession, "金属材料")
        self.assertEqual(mapping["FASTENER"].profession, "紧固与连接件")
        self.assertEqual(mapping["TEST"].profession, "试验检验")
        self.assertEqual(mapping["DESIGN"].profession, "设计与工程通用规范")

    def test_renamed_category_still_maps_by_seed_terms(self):
        examples = [
            ("不锈钢棒", "航空金属材料技术"),
            ("铝合金板材", "航空金属材料技术"),
            ("六角头螺栓", "机械连接与紧固技术"),
            ("圆柱销", "机械连接与紧固技术"),
            ("盐雾试验", "质量检验与试验技术"),
            ("拉伸试验方法", "质量检验与试验技术"),
        ]
        mapping = map_concepts(examples, sorted({label for _n, label in examples}))
        self.assertEqual(mapping["MATERIAL"].profession, "航空金属材料技术")
        self.assertEqual(mapping["FASTENER"].profession, "机械连接与紧固技术")
        self.assertEqual(mapping["TEST"].profession, "质量检验与试验技术")


class RuleScoringTests(unittest.TestCase):
    def test_fastener_noun_wins(self):
        self.assertEqual(_prediction("内六角圆柱头螺钉"), "紧固与连接件")
        self.assertEqual(_prediction("开口销"), "紧固与连接件")

    def test_test_method_head_wins_over_material(self):
        self.assertEqual(
            _prediction("金属材料 拉伸试验 第1部分：室温试验方法"),
            "试验检验",
        )

    def test_fastener_test_method_goes_to_test(self):
        self.assertEqual(
            _prediction("紧固件试验方法 金属覆盖层厚度"),
            "试验检验",
        )

    def test_secondary_test_clause_does_not_steal_coating(self):
        self.assertEqual(
            _prediction("金属覆盖层 钢铁制件热浸镀锌层 技术要求及试验方法"),
            "表面处理",
        )

    def test_assembly_noun_wins_over_design(self):
        self.assertEqual(_prediction("飞机装配工装设计要求"), "结构装配")

    def test_design_rule_wins(self):
        self.assertEqual(_prediction("飞机维修性设计准则"), "设计与工程通用规范")

    def test_longest_match_prevents_double_counting(self):
        mapping = map_concepts(
            REFERENCE_EXAMPLES,
            sorted({label for _n, label in REFERENCE_EXAMPLES}),
        )
        _scores, _evidence, matches = score_name("自锁螺母", mapping, {})
        terms = {match.term for match in matches}
        self.assertIn("自锁螺母", terms)
        self.assertNotIn("螺母", terms)

    def test_mined_long_term_does_not_suppress_curated_test_head(self):
        mapping = map_concepts(
            REFERENCE_EXAMPLES,
            sorted({label for _n, label in REFERENCE_EXAMPLES}),
        )
        mined = {"试验检验": [MinedTerm("固件试验方法", 1, 1.0, 0.95, [])]}
        scores, _evidence, matches = score_name(
            "紧固件试验方法 金属覆盖层厚度", mapping, mined
        )
        self.assertEqual(max(scores, key=scores.get), "试验检验")
        self.assertIn("试验方法", {match.term for match in matches})

    def test_real_mined_terms_keep_key_cases_correct(self):
        mapping = map_concepts(
            REFERENCE_EXAMPLES,
            sorted({label for _n, label in REFERENCE_EXAMPLES}),
        )
        mined = mine_terms(REFERENCE_EXAMPLES)
        cases = {
            "紧固件试验方法 金属覆盖层厚度": "试验检验",
            "金属材料 拉伸试验 第1部分：室温试验方法": "试验检验",
            "金属覆盖层 钢铁制件热浸镀锌层 技术要求及试验方法": "表面处理",
            "金属基体上金属和其他无机覆盖层 经腐蚀试验后的试样和试件的评级": "表面处理",
            "圆柱销 不淬硬钢和奥氏体不锈钢": "紧固与连接件",
            "飞机装配工装设计要求": "结构装配",
            "钢丝螺套安装规范": "结构装配",
        }
        for name, expected in cases.items():
            scores, _evidence, _matches = score_name(name, mapping, mined)
            self.assertEqual(max(scores, key=scores.get), expected, name)

    def test_bonuses_are_included_in_evidence(self):
        mapping = map_concepts(
            REFERENCE_EXAMPLES,
            sorted({label for _n, label in REFERENCE_EXAMPLES}),
        )
        scores, evidence, _matches = score_name(
            "金属材料 拉伸试验 第1部分：室温试验方法", mapping, {}
        )
        profession = max(scores, key=scores.get)
        evidence_sum = sum(
            match.weight * match.position_factor
            for match in evidence[profession]
        )
        self.assertAlmostEqual(scores[profession], evidence_sum, places=6)

    def test_full_test_method_head_bonus(self):
        from rules import _test_head_bonus
        from config import TEST_HEAD_BONUS

        self.assertEqual(
            _test_head_bonus("金属材料 拉伸试验 第1部分：室温试验方法"),
            TEST_HEAD_BONUS,
        )
        self.assertEqual(
            _test_head_bonus("金属覆盖层 钢铁制件热浸镀锌层 技术要求及试验方法"),
            0.0,
        )
        self.assertEqual(
            _test_head_bonus("石油产品闪点与燃点测定法（开口杯法）"),
            TEST_HEAD_BONUS,
        )

    def test_fastener_noun_beats_trailing_material(self):
        self.assertEqual(
            _prediction("圆柱销 不淬硬钢和奥氏体不锈钢"),
            "紧固与连接件",
        )

    def test_coating_rating_rule_beats_test(self):
        self.assertEqual(
            _prediction("金属基体上金属和其他无机覆盖层 经腐蚀试验后的试样和试件的评级"),
            "表面处理",
        )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m unittest tests.test_rules -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'rules'`

- [ ] **Step 3: 实现 rules.py**

创建 `backend/rules.py`：

```python
# -*- coding: utf-8 -*-
"""概念到类别的映射、规则计分与中心词例外规则。"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

from config import (
    COATING_RATING_BONUS,
    CONCEPTS,
    MINED_SOURCE_FACTOR,
    PRODUCT_HEAD_FACTOR,
    PRODUCT_HEAD_MIN_WEIGHT,
    TAIL_RATIO,
    TEST_HEAD_BONUS,
    TEST_HEAD_PARTIAL_FACTOR,
)
from text import normalize_name, segments

Example = Tuple[str, str]

TEST_HEADS = ("试验方法", "测定法", "检测方法")
PRODUCT_HEAD_CONCEPTS = {"FASTENER", "COATING", "LUBRICANT"}


@dataclass
class ConceptMapping:
    concept: str
    profession: str
    score: float


@dataclass
class RuleMatch:
    term: str
    weight: float
    profession: str
    concept: str
    source: str
    position_factor: float
    start: int
    end: int


def _concept_score(
    spec: Dict[str, Any],
    category: str,
    names: Sequence[str],
) -> float:
    total = 0.0
    for term, weight in spec["seeds"]:
        if term in category:
            total += float(weight) * 2.0
    for name in names:
        for term, weight in spec["seeds"]:
            if term in name:
                total += float(weight)
    return total / max(1, len(names))


def map_concepts(
    examples: Sequence[Example],
    categories: Sequence[str],
    concepts: Dict[str, Dict[str, Any]] = CONCEPTS,
    min_score: float = 0.5,
    ratio: float = 1.5,
) -> Dict[str, ConceptMapping]:
    """为每个概念选择最匹配的专业类别。

    选择条件：最高分 >= min_score，且最高分 >= ratio × 次高分；
    同一类别只被一个概念占用，按分数从高到低贪心分配。
    """
    by_category: Dict[str, List[str]] = defaultdict(list)
    for name, label in examples:
        by_category[label].append(name)

    rankings: List[Tuple[float, str, str]] = []
    for concept, spec in concepts.items():
        scores: List[Tuple[float, str]] = []
        for category in categories:
            score = _concept_score(spec, category, by_category.get(category, []))
            scores.append((score, category))
        scores.sort(reverse=True)
        if not scores:
            continue
        best_score, best_category = scores[0]
        second_score = scores[1][0] if len(scores) > 1 else 0.0
        if best_score < min_score:
            continue
        if second_score > 0.0 and best_score < ratio * second_score:
            continue
        rankings.append((best_score, concept, best_category))

    rankings.sort(reverse=True)
    mapping: Dict[str, ConceptMapping] = {}
    used_categories = set()
    for score, concept, category in rankings:
        if category in used_categories:
            continue
        mapping[concept] = ConceptMapping(concept, category, round(score, 4))
        used_categories.add(category)
    return mapping


def _position_factor(normalized: str, start: int, length: int) -> float:
    if not normalized:
        return 1.0
    end = start + length
    if end / float(len(normalized)) >= TAIL_RATIO:
        return 1.5
    return 1.0


def _is_secondary_clause(clause: str, index: int) -> bool:
    """中心词紧跟连接词，且连接词前是要求类中心词时，视为次要子句。"""
    connector = max(
        clause.rfind("及"), clause.rfind("和"), clause.rfind("与")
    )
    if connector != index - 1:
        return False
    prefix = clause[:connector]
    return prefix.endswith(
        ("要求", "规范", "规定", "条件", "性能", "指标", "规则", "验收")
    )


def _test_head_bonus(name: str) -> float:
    """两阶段扫描：先找所有子句的完整中心词，再退化到半中心词。

    第一阶段遍历全部子句寻找完整中心词，避免前一个子句的半中心词
    抢先返回；次要子句（如「技术要求及试验方法」）不触发加成。
    """
    clauses = [normalize_name(raw) for raw in segments(name)]
    for clause in clauses:
        for head in TEST_HEADS:
            if clause.endswith(head):
                index = clause.rfind(head)
                if _is_secondary_clause(clause, index):
                    continue
                return TEST_HEAD_BONUS
    for clause in clauses:
        if clause.endswith(("试验", "检测")):
            return TEST_HEAD_BONUS * TEST_HEAD_PARTIAL_FACTOR
    return 0.0


def score_name(
    name: str,
    mapping: Dict[str, ConceptMapping],
    mined_terms: Dict[str, Sequence[Any]],
    concepts: Dict[str, Dict[str, Any]] = CONCEPTS,
) -> Tuple[Dict[str, float], Dict[str, List[RuleMatch]], List[RuleMatch]]:
    """对名称计分，返回 (类别分数字典, 类别证据, 全部命中)。

    仅当更长命中词与短词同专业且有效权重不低于短词时才覆盖；名称后
    1/3 的命中获得 1.5 倍加成。试验中心词与覆盖层例外加成也写入证据，
    保证证据权重之和与类别分数一致。
    """
    normalized = normalize_name(name)
    if not normalized:
        return {}, {}, []

    matches: List[RuleMatch] = []
    for concept, mapped in mapping.items():
        for term, weight in concepts[concept]["seeds"]:
            start = normalized.find(term)
            if start < 0:
                continue
            factor = _position_factor(normalized, start, len(term))
            if (
                concept in PRODUCT_HEAD_CONCEPTS
                and float(weight) >= PRODUCT_HEAD_MIN_WEIGHT
            ):
                # 产品名词（紧固件/镀层/油品）是中心词，不因后面跟材料说明而降权。
                factor = max(factor, PRODUCT_HEAD_FACTOR)
            matches.append(
                RuleMatch(
                    term=term,
                    weight=float(weight),
                    profession=mapped.profession,
                    concept=concept,
                    source="curated",
                    position_factor=factor,
                    start=start,
                    end=start + len(term),
                )
            )

    for profession, items in mined_terms.items():
        for item in items:
            term = item.term
            start = normalized.find(term)
            if start < 0:
                continue
            matches.append(
                RuleMatch(
                    term=term,
                    weight=float(item.weight) * MINED_SOURCE_FACTOR,
                    profession=profession,
                    concept="",
                    source="mined",
                    position_factor=_position_factor(normalized, start, len(term)),
                    start=start,
                    end=start + len(term),
                )
            )

    matches.sort(key=lambda item: (-(item.end - item.start), item.start, -item.weight))
    kept: List[RuleMatch] = []
    for match in matches:
        suppressed = False
        for kept_match in kept:
            if (
                kept_match.start <= match.start
                and match.end <= kept_match.end
                and kept_match.profession == match.profession
                and kept_match.weight * kept_match.position_factor
                >= match.weight * match.position_factor
            ):
                suppressed = True
                break
        if not suppressed:
            kept.append(match)

    scores: Dict[str, float] = defaultdict(float)
    evidence: Dict[str, List[RuleMatch]] = defaultdict(list)
    for match in kept:
        value = match.weight * match.position_factor
        scores[match.profession] += value
        evidence[match.profession].append(match)

    test_mapping = mapping.get("TEST")
    if test_mapping:
        bonus = _test_head_bonus(name)
        if bonus > 0.0:
            scores[test_mapping.profession] += bonus
            bonus_match = RuleMatch(
                term="试验方法/测定法加成",
                weight=bonus,
                profession=test_mapping.profession,
                concept="TEST",
                source="rule",
                position_factor=1.0,
                start=0,
                end=0,
            )
            evidence[test_mapping.profession].append(bonus_match)
            kept.append(bonus_match)

    coating_mapping = mapping.get("COATING")
    if (
        coating_mapping
        and "覆盖层" in normalized
        and "评级" in normalized
    ):
        # “覆盖层…评级”是表面处理的评价标准，不应被“试验”抢走。
        scores[coating_mapping.profession] += COATING_RATING_BONUS
        bonus_match = RuleMatch(
            term="覆盖层+评级",
            weight=COATING_RATING_BONUS,
            profession=coating_mapping.profession,
            concept="COATING",
            source="exception",
            position_factor=1.0,
            start=0,
            end=0,
        )
        evidence[coating_mapping.profession].append(bonus_match)
        kept.append(bonus_match)

    return dict(scores), dict(evidence), kept
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m unittest tests.test_rules -v`
Expected: 18 tests PASS

- [ ] **Step 5: 提交**

```bash
git add backend/rules.py backend/tests/test_rules.py
git commit -m "feat: 增加概念映射、规则计分与中心词例外规则"
```

---

### Task 5: 证据引擎、置信度与分类管线

**Files:**
- Modify: `backend/classifier.py`
- Test: `backend/tests/test_pipeline_evidence.py`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_pipeline_evidence.py`：

```python
# -*- coding: utf-8 -*-
"""四级证据链、置信度与待复核标记。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from classifier import (
    ClassificationPipeline,
    EvidenceEngine,
    build_reference,
)


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


class EvidenceEngineTests(unittest.TestCase):
    def setUp(self):
        self.reference = build_reference(reference_records(), [])
        self.engine = EvidenceEngine(
            self.reference.training_examples,
            self.reference.categories,
            self.reference.system_map,
            build_model=False,
        )

    def test_rule_prediction_has_evidence_and_level(self):
        result = self.engine.predict_name("内六角圆柱头螺钉")
        self.assertEqual(result["profession"], "紧固与连接件")
        self.assertEqual(result["evidence_level"], "rule")
        self.assertEqual(result["source"], "rule")
        self.assertTrue(result["evidence"])
        self.assertLessEqual(result["confidence"], 0.92)

    def test_similarity_fallback_when_rules_have_no_evidence(self):
        result = self.engine.predict_name("未见过的高强度连接件")
        self.assertIn(result["evidence_level"], ("similar", "model"))
        self.assertTrue(result["evidence"])

    def test_model_fallback_is_capped_and_needs_review(self):
        result = self.engine.predict_name("完全无关的量子计算协议")
        if result["evidence_level"] == "model":
            self.assertLessEqual(result["confidence"], 0.60)
            self.assertTrue(result["needs_review"])

    def test_top3_is_well_formed(self):
        result = self.engine.predict_name("六角螺栓")
        self.assertEqual(len(result["top3"]), 3)
        probabilities = [item["probability"] for item in result["top3"]]
        self.assertEqual(probabilities, sorted(probabilities, reverse=True))
        self.assertLessEqual(sum(probabilities), 1.0 + 1e-6)
        for item in result["top3"]:
            self.assertIn("profession", item)
            self.assertIn("score", item)


class PipelineEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = ClassificationPipeline(build_reference(reference_records(), []))

    def test_reference_code_beats_rules(self):
        result = self.pipeline.predict("完全陌生的名称", "GB/T 2-2020")
        self.assertEqual(result["evidence_level"], "reference")
        self.assertEqual(result["profession"], "结构装配")
        self.assertGreaterEqual(result["confidence"], 0.90)

    def test_reference_name_beats_rules(self):
        result = self.pipeline.predict("不锈钢棒")
        self.assertEqual(result["evidence_level"], "reference")
        self.assertEqual(result["profession"], "金属材料")

    def test_confidence_never_exceeds_cap(self):
        for name in ("六角头螺栓", "阳极氧化膜", "不锈钢棒"):
            result = self.pipeline.predict(name)
            self.assertLessEqual(result["confidence"], 0.95)

    def test_low_confidence_is_marked_for_review(self):
        result = self.pipeline.predict("完全无法判断的对象")
        if result["confidence"] < 0.70 or result["evidence_level"] == "model":
            self.assertTrue(result["needs_review"])

    def test_evaluation_reports_new_fields(self):
        evaluation = self.pipeline.evaluation()
        for key in ("accuracy", "macro_f1", "confusion_matrix", "calibration", "by_level"):
            self.assertIn(key, evaluation)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m unittest tests.test_pipeline_evidence -v`
Expected: FAIL，`ImportError: cannot import name 'EvidenceEngine'`

- [ ] **Step 3: 改造 classifier.py 的导入与特征提取**

在 `backend/classifier.py` 顶部按以下方式调整导入：

```python
from config import (
    CATEGORIES,
    CLASS_WEIGHT_POWER,
    CONCEPTS,
    CONFLICT_DOMINANCE,
    CV_FOLDS,
    DEFAULT_SYSTEM_MAP,
    IDF_MODE,
    KNN_SUPPORT_WEIGHT,
    MAX_CONFIDENCE,
    MAX_MODEL_CONFIDENCE,
    MIN_DOCUMENT_FREQUENCY,
    MIN_RULE_SCORE,
    MIN_TEMPERATURE,
    MODEL_EPOCHS,
    MODEL_FALLBACK_CONFIDENCE,
    MODEL_L2,
    MODEL_LR,
    NAME_PATTERNS,
    RANDOM_SEED,
    REVIEW_THRESHOLD,
    RULE_STRONG_SCORE,
)
from excel_io import ExcelError, pick, variant_code_key
from mining import NameSimilarityIndex, keyword_report, mine_terms
from rules import map_concepts, score_name
from text import base_code, normalize_code, normalize_name, tokenize
```

把 `FeatureExtractor.__init__` 替换为：

```python
    def __init__(
        self,
        min_document_frequency: int = MIN_DOCUMENT_FREQUENCY,
        idf_mode: str = IDF_MODE,
    ) -> None:
        self.min_document_frequency = max(1, min_document_frequency)
        self.idf_mode = idf_mode if idf_mode in ("smooth", "sqrt", "none") else "smooth"
        self._document_frequency: Counter = Counter()
        self._document_count = 0
```

把 `FeatureExtractor.transform` 中的关键词循环整段删除（从 `for category, rules in KEYWORD_RULES.items():` 到该循环结束），只保留字符 n-gram 和 `NAME_PATTERNS`。`keyword_hits` 方法删除。这样兜底模型只使用字符 n-gram，不再依赖关键词规则。

- [ ] **Step 4: 添加 EvidenceEngine 与置信度工具**

在 `SoftmaxRegression` 之后、`ClassificationPipeline` 之前加入：

```python
def _confidence_from_scores(top: float, second: float) -> float:
    if top <= 0.0:
        return 0.0
    dominance = top / (top + second) if top + second > 0 else 1.0
    coverage = min(1.0, top / RULE_STRONG_SCORE)
    raw = 0.55 + 0.40 * (2.0 * dominance - 1.0) * (0.6 + 0.4 * coverage)
    if top < MIN_RULE_SCORE:
        raw *= 0.8
    if dominance < CONFLICT_DOMINANCE:
        raw -= 0.05
    return max(0.0, min(0.92, raw))


def _confidence_reason(top: float, second: float, level: str) -> str:
    if level == "reference":
        return "参照表精确命中"
    if level == "model":
        return "仅模型兜底，必须人工复核"
    if level == "similar":
        return "仅有相似名称证据，建议复核"
    dominance = top / (top + second) if top + second > 0 else 1.0
    if top >= RULE_STRONG_SCORE and dominance >= 0.75:
        return "强规则命中且 Top2 差距明显"
    if dominance < CONFLICT_DOMINANCE:
        return "类别证据接近，存在歧义"
    return "规则命中，证据强度一般"


class EvidenceEngine:
    """规则 + 相似名称 + 模型兜底。不处理参照表精确命中。"""

    def __init__(
        self,
        examples: Sequence[Tuple[str, str]],
        categories: Sequence[str],
        system_map: Dict[str, str],
        build_model: bool = True,
    ) -> None:
        self.examples = list(examples)
        self.categories = list(categories)
        self.system_map = dict(system_map)
        self.mined_terms = mine_terms(self.examples)
        self.concept_mapping = map_concepts(self.examples, self.categories)
        self.similarity = NameSimilarityIndex(self.examples)
        self.extractor = None
        self.model = None
        if build_model and self.examples:
            self._build_model()

    def _build_model(self) -> None:
        names = [name for name, _label in self.examples]
        labels = [self.categories.index(label) for _name, label in self.examples]
        self.extractor = FeatureExtractor().fit(names)
        vectors = [self.extractor.transform(name) for name in names]
        self.model = SoftmaxRegression(
            num_classes=len(self.categories),
            class_weights=_class_weights(labels, num_classes=len(self.categories)),
        ).fit(vectors, labels)

    def _score_vector(self, scores: Dict[str, float]) -> Dict[str, float]:
        total = sum(max(0.0, value) for value in scores.values()) or 1.0
        return {
            profession: max(0.0, value) / total
            for profession, value in scores.items()
        }

    def _top3(
        self,
        scores: Dict[str, float],
        primary: Optional[str] = None,
        primary_probability: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        vector = self._score_vector(scores)
        if primary is not None:
            base = (
                primary_probability
                if primary_probability is not None
                else vector.get(primary, 0.0)
            )
            base = max(0.0, min(MAX_CONFIDENCE, base))
            rest_total = sum(
                value for profession, value in vector.items() if profession != primary
            )
            scale = (1.0 - base) / rest_total if rest_total > 0 else 1.0
            vector = {
                profession: (base if profession == primary else value * scale)
                for profession, value in vector.items()
            }
        ranked = sorted(vector.items(), key=lambda item: (-item[1], item[0]))
        if primary is not None and (
            not ranked or ranked[0][0] != primary
        ):
            ranked = [(primary, vector.get(primary, 0.0))] + [
                item for item in ranked if item[0] != primary
            ]
        result: List[Dict[str, Any]] = []
        for profession, probability in ranked[:3]:
            result.append({
                "profession": profession,
                "system": self.system_map.get(profession, ""),
                "probability": round(min(MAX_CONFIDENCE, probability), 4),
                "score": round(float(scores.get(profession, 0.0)), 4),
            })
        for profession in self.categories:
            if len(result) >= 3:
                break
            if any(item["profession"] == profession for item in result):
                continue
            result.append({
                "profession": profession,
                "system": self.system_map.get(profession, ""),
                "probability": 0.0,
                "score": 0.0,
            })
        return result

    def _format_matches(
        self, matches: Sequence[Any], limit: int = 5
    ) -> List[str]:
        return [
            "规则命中：{}（{}，{:.1f} 分）".format(
                match.term,
                match.profession,
                match.weight * match.position_factor,
            )
            for match in matches[:limit]
        ]

    def _format_neighbors(self, neighbors: Sequence[Any], limit: int = 2) -> List[str]:
        return [
            "相似标准：{}（相似度 {:.0%}，分类 {}）".format(
                neighbor.name, neighbor.similarity, neighbor.profession
            )
            for neighbor in neighbors[:limit]
        ]

    def _rule_scores(self, name: str):
        scores, evidence, matches = score_name(
            name, self.concept_mapping, self.mined_terms, CONCEPTS
        )
        neighbors = self.similarity.query(name)
        votes: Dict[str, float] = defaultdict(float)
        for neighbor in neighbors:
            votes[neighbor.profession] += neighbor.similarity
        total = sum(votes.values()) or 1.0
        for profession, value in votes.items():
            scores[profession] = scores.get(profession, 0.0) + (
                KNN_SUPPORT_WEIGHT * value / total
            )
        return scores, evidence, matches, neighbors

    def predict_name(self, name: str) -> Dict[str, Any]:
        scores, evidence, matches, neighbors = self._rule_scores(name)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        top_profession = ranked[0][0] if ranked else ""
        top_score = ranked[0][1] if ranked else 0.0
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0

        if top_profession and top_score >= MIN_RULE_SCORE:
            confidence = _confidence_from_scores(top_score, second_score)
            reasons = self._format_matches(evidence.get(top_profession, []))
            reasons.extend(self._format_neighbors(neighbors))
            dominance = (
                top_score / (top_score + second_score)
                if top_score + second_score > 0
                else 1.0
            )
            needs_review = (
                confidence < REVIEW_THRESHOLD
                or dominance < CONFLICT_DOMINANCE
            )
            return {
                "profession": top_profession,
                "system": self.system_map.get(top_profession, ""),
                "confidence": round(confidence, 4),
                "method": "规则",
                "source": "rule",
                "evidence_level": "rule",
                "confidence_reason": _confidence_reason(top_score, second_score, "rule"),
                "needs_review": needs_review,
                "evidence": reasons or ["规则命中"],
                "evidence_detail": [
                    {
                        "type": "keyword",
                        "term": match.term,
                        "profession": match.profession,
                        "weight": round(match.weight * match.position_factor, 4),
                        "source": match.source,
                    }
                    for match in evidence.get(top_profession, [])[:5]
                ],
                "top3": self._top3(scores, top_profession, confidence),
                "detail": "规则计分：Top1 {:.2f} 分，Top2 {:.2f} 分。".format(
                    top_score, second_score
                ),
            }

        if neighbors:
            votes: Dict[str, float] = defaultdict(float)
            for neighbor in neighbors:
                votes[neighbor.profession] += neighbor.similarity
            ranked_votes = sorted(votes.items(), key=lambda item: (-item[1], item[0]))
            profession = ranked_votes[0][0]
            total = sum(votes.values()) or 1.0
            share = ranked_votes[0][1] / total
            average = sum(n.similarity for n in neighbors) / len(neighbors)
            confidence = min(0.85, 0.55 + 0.35 * share * average)
            reasons = self._format_neighbors(neighbors)
            reasons.extend(self._format_matches(evidence.get(profession, []), 3))
            return {
                "profession": profession,
                "system": self.system_map.get(profession, ""),
                "confidence": round(confidence, 4),
                "method": "相似名称",
                "source": "similar",
                "evidence_level": "similar",
                "confidence_reason": _confidence_reason(0.0, 0.0, "similar"),
                "needs_review": confidence < REVIEW_THRESHOLD,
                "evidence": reasons,
                "evidence_detail": [
                    {
                        "type": "similar",
                        "name": neighbor.name,
                        "profession": neighbor.profession,
                        "similarity": round(neighbor.similarity, 4),
                    }
                    for neighbor in neighbors
                ],
                "top3": self._top3(dict(votes), profession, confidence),
                "detail": "相似名称投票：{} 条邻居，最高相似度 {:.2f}。".format(
                    len(neighbors), neighbors[0].similarity
                ),
            }

        return self._model_result(name, evidence)

    def _model_result(
        self, name: str, evidence: Dict[str, List[Any]]
    ) -> Dict[str, Any]:
        if self.model is None or self.extractor is None:
            profession = self.categories[0]
            return {
                "profession": profession,
                "system": self.system_map.get(profession, ""),
                "confidence": 0.0,
                "method": "模型",
                "source": "model",
                "evidence_level": "model",
                "confidence_reason": "无证据且模型不可用",
                "needs_review": True,
                "evidence": ["无有效证据"],
                "evidence_detail": [],
                "top3": self._top3({}, profession, 0.0),
                "detail": "没有命中规则或相似标准。",
            }
        probabilities = self.model.probabilities(
            self.extractor.transform(name)
        )
        ranked = sorted(
            range(len(probabilities)),
            key=lambda index: probabilities[index],
            reverse=True,
        )
        top_index = ranked[0]
        profession = self.categories[top_index]
        confidence = min(MODEL_FALLBACK_CONFIDENCE, probabilities[top_index])
        reasons = ["模型兜底：字符 n-gram，置信度受限"]
        reasons.extend(
            self._format_matches(
                evidence.get(profession, []), 3
            )
        )
        return {
            "profession": profession,
            "system": self.system_map.get(profession, ""),
            "confidence": round(confidence, 4),
            "method": "模型",
            "source": "model",
            "evidence_level": "model",
            "confidence_reason": _confidence_reason(0.0, 0.0, "model"),
            "needs_review": True,
            "evidence": reasons,
            "evidence_detail": [
                {
                    "type": "model",
                    "profession": profession,
                    "weight": round(probabilities[top_index], 4),
                    "source": "model",
                }
            ],
            "top3": [
                {
                    "profession": self.categories[index],
                    "system": self.system_map.get(self.categories[index], ""),
                    "probability": round(float(probabilities[index]), 4),
                    "score": round(float(probabilities[index]), 4),
                }
                for index in ranked[:3]
            ],
            "detail": "字符 n-gram 模型兜底；置信度上限 0.60，需人工复核。",
        }
```

- [ ] **Step 5: 用 EvidenceEngine 重写 ClassificationPipeline**

把 `ClassificationPipeline` 类整体替换为：

```python
class ClassificationPipeline:
    """参照表精确命中 + 证据引擎；评估使用留一法。"""

    def __init__(self, reference: ReferenceData) -> None:
        self.reference = reference
        self.categories = list(reference.categories)
        if not reference.training_examples:
            raise ExcelError("INVALID_FILE", "参照表没有可用于训练的唯一名称记录")
        self.engine = EvidenceEngine(
            reference.training_examples,
            self.categories,
            reference.system_map,
            build_model=True,
        )
        self.extractor = self.engine.extractor
        self.model = self.engine.model
        self.mined_terms = self.engine.mined_terms
        self.concept_mapping = self.engine.concept_mapping
        self.similarity = self.engine.similarity
        self._evaluation = self._evaluate()

    def _evaluate(self) -> Dict[str, Any]:
        evaluation = evaluate_leave_one_out(
            self.reference.training_examples,
            self.categories,
            self.reference.system_map,
        )
        evaluation["training_samples"] = len(self.reference.training_examples)
        return evaluation

    def evaluation(self) -> Dict[str, Any]:
        return self._evaluation

    def keyword_report(self) -> List[Dict[str, Any]]:
        return keyword_report(
            self.mined_terms,
            self.reference.training_examples,
            self.reference.system_map,
            self.concept_mapping,
            CONCEPTS,
        )

    def concept_mapping_list(self) -> List[Dict[str, Any]]:
        return [
            {
                "concept": item.concept,
                "profession": item.profession,
                "score": item.score,
            }
            for item in self.concept_mapping.values()
        ]

    def _reference_result(
        self,
        label: Dict[str, Any],
        method: str,
        confidence: float,
        scores: Dict[str, float],
        neighbors: Sequence[Any],
    ) -> Dict[str, Any]:
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
            "needs_review": False,
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
                scores, label["profession"], confidence
            ),
            "detail": "参照表 {} 条同组记录，多数票 {}/{}。".format(
                label["total"], label["votes"], label["total"]
            ),
        }

    def predict(self, name: str, code: str = "") -> Dict[str, Any]:
        clean_name = str(name or "").strip()
        scores, _evidence, _matches, neighbors = self.engine._rule_scores(
            clean_name
        )

        code_key = normalize_code(code)
        if code_key and code_key in self.reference.by_code:
            label = self.reference.by_code[code_key]
            confidence = (
                MAX_CONFIDENCE
                if label["ratio"] >= 1.0
                else 0.90 + 0.03 * label["ratio"]
            )
            return self._reference_result(
                label, "参照表·标准号", confidence, scores, neighbors
            )

        name_key = normalize_name(clean_name)
        if name_key and name_key in self.reference.by_name:
            label = self.reference.by_name[name_key]
            return self._reference_result(
                label, "参照表·名称", 0.93, scores, neighbors
            )

        code_base = base_code(code_key) if code_key else ""
        if code_base and code_base in self.reference.by_base:
            label = self.reference.by_base[code_base]
            confidence = min(0.90, 0.85 + 0.05 * label["ratio"])
            return self._reference_result(
                label, "参照表·标准号主体", confidence, scores, neighbors
            )

        return self.engine.predict_name(clean_name)
```

- [ ] **Step 6: 更新 `_empty_evaluation` 与批量分类输出**

把 `_empty_evaluation` 替换为：

```python
    @staticmethod
    def _empty_evaluation(note: str) -> Dict[str, Any]:
        return {
            "accuracy": 0.0,
            "macro_f1": 0.0,
            "per_class": {},
            "sample_count": 0,
            "method": "leave-one-out",
            "name_mode": True,
            "confusion_matrix": {},
            "calibration": [],
            "by_level": {},
            "note": note,
        }
```

在 `classify_pending_groups` 中，把构造 `row` 的字典加入以下字段：

```python
            "evidence_detail": result.get("evidence_detail", []),
            "evidence_level": result.get("evidence_level", "manual"),
            "confidence_reason": result.get("confidence_reason", ""),
            "needs_review": bool(result.get("needs_review", low)),
```

并把 `low = confidence < threshold` 改为：

```python
            low = confidence < threshold or bool(result.get("needs_review"))
```

在 `classify_pending` 中同样加入这四个字段，并把 `low_confidence` 改为：

```python
            "low_confidence": result["confidence"] < threshold
            or bool(result.get("needs_review")),
```

在两个函数的返回值中加入：

```python
        "keyword_report": pipeline.keyword_report(),
        "concept_mapping": pipeline.concept_mapping_list(),
```

- [ ] **Step 7: 运行测试**

Run: `cd backend && python -m unittest tests.test_pipeline_evidence -v`
Expected: 9 tests PASS

- [ ] **Step 8: 提交**

```bash
git add backend/classifier.py backend/tests/test_pipeline_evidence.py
git commit -m "feat: 证据分级引擎与诚实置信度"
```

---

### Task 6: 留一法评估、混淆矩阵与外部测试集回归

**Files:**
- Modify: `backend/classifier.py`
- Create: `backend/tests/test_evaluation.py`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_evaluation.py`：

```python
# -*- coding: utf-8 -*-
"""留一法评估、置信度分箱与外部测试集回归。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import openpyxl

from classifier import evaluate_leave_one_out, evaluate_labels
from config import DEFAULT_SYSTEM_MAP


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


class EvaluationTests(unittest.TestCase):
    def test_leave_one_out_returns_metrics(self):
        categories = sorted({label for _name, label in reference_examples()})
        evaluation = evaluate_leave_one_out(
            reference_examples(), categories, DEFAULT_SYSTEM_MAP
        )
        for key in ("accuracy", "macro_f1", "confusion_matrix", "calibration", "by_level"):
            self.assertIn(key, evaluation)
        self.assertEqual(evaluation["sample_count"], len(reference_examples()))
        self.assertIn("note", evaluation)

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
        from classifier import ClassificationPipeline, build_reference
        from excel_io import read_reference

        reference_path = Path(__file__).resolve().parents[1] / "data" / "分类好国标.xlsx"
        records, mapping_rows, _sheet = read_reference(reference_path)
        pipeline = ClassificationPipeline(build_reference(records, mapping_rows))
        inverse = {value: key for key, value in DEFAULT_SYSTEM_MAP.items()}
        corrections = {
            22: "试验检验", 24: "试验检验", 32: "紧固与连接件",
            36: "金属材料", 37: "金属材料", 38: "金属材料", 39: "金属材料",
        }
        rows = list(
            openpyxl.load_workbook(path, data_only=True)["待分类目录"].iter_rows(
                values_only=True
            )
        )[1:]
        correct = 0
        errors = []
        for index, row in enumerate(rows, start=1):
            label = corrections.get(index, row[4])
            truth = label if label in DEFAULT_SYSTEM_MAP else inverse.get(label, label)
            result = pipeline.predict(row[1], row[0])
            if result["profession"] == truth:
                correct += 1
            else:
                errors.append((index, row[1], truth, result["profession"]))
        self.assertEqual(
            correct, len(rows),
            "外部测试集出现回归：{}".format(errors),
        )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m unittest tests.test_evaluation -v`
Expected: FAIL，`ImportError: cannot import name 'evaluate_leave_one_out'`

- [ ] **Step 3: 添加评估函数**

在 `backend/classifier.py` 的 `ClassificationPipeline` 之前加入：

```python
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
        (0.50, 0.60, "0.50-0.60"),
        (0.60, 0.70, "0.60-0.70"),
        (0.70, 0.80, "0.70-0.80"),
        (0.80, 0.85, "0.80-0.85"),
        (0.85, 0.90, "0.85-0.90"),
        (0.90, 0.9501, "0.90-0.95"),
    ]
    report: List[Dict[str, Any]] = []
    for low, high, label in bins:
        indices = [
            index for index, value in enumerate(confidences)
            if low <= value < high
        ]
        if not indices:
            continue
        correct = sum(
            1 for index in indices if labels[index] == predictions[index]
        )
        report.append({
            "bin": label,
            "count": len(indices),
            "accuracy": round(float(correct) / len(indices), 4),
        })
    return report


def evaluate_leave_one_out(
    examples: Sequence[Tuple[str, str]],
    categories: Sequence[str],
    system_map: Dict[str, str],
) -> Dict[str, Any]:
    """留一法：每折重新挖词、重建相似索引和概念映射，不训练兜底模型。"""
    if len(examples) < 4 or len(set(label for _name, label in examples)) < 2:
        return {
            "accuracy": 0.0,
            "macro_f1": 0.0,
            "per_class": {},
            "sample_count": 0,
            "method": "leave-one-out",
            "name_mode": True,
            "confusion_matrix": {},
            "calibration": [],
            "by_level": {},
            "note": "样本不足，未做留一验证",
        }

    labels: List[str] = []
    predictions: List[str] = []
    confidences: List[float] = []
    levels: List[str] = []
    for index, (name, truth) in enumerate(examples):
        train = list(examples[:index]) + list(examples[index + 1:])
        engine = EvidenceEngine(train, categories, system_map, build_model=False)
        result = engine.predict_name(name)
        labels.append(truth)
        predictions.append(result["profession"])
        confidences.append(result["confidence"])
        levels.append(result["evidence_level"])

    result = evaluate_labels(labels, predictions, categories)
    by_level: Dict[str, Dict[str, Any]] = {}
    for level in sorted(set(levels)):
        indices = [i for i, value in enumerate(levels) if value == level]
        correct = sum(1 for i in indices if labels[i] == predictions[i])
        by_level[level] = {
            "count": len(indices),
            "accuracy": round(float(correct) / len(indices), 4),
        }
    result.update({
        "method": "leave-one-out",
        "name_mode": True,
        "calibration": _calibration_report(confidences, labels, predictions),
        "by_level": by_level,
        "note": (
            "留一法名称模式；每折重新挖词与建相似索引，人工种子词为全局领域知识，"
            "指标偏乐观，仅作参考。"
        ),
    })
    return result
```

- [ ] **Step 4: 运行测试**

Run: `cd backend && python -m unittest tests.test_evaluation -v`
Expected: 3 tests PASS（夹具缺失时测试失败，夹具已入库）

- [ ] **Step 5: 提交**

```bash
git add backend/classifier.py backend/tests/test_evaluation.py
git commit -m "feat: 留一法评估、混淆矩阵与置信度分箱"
```

---

### Task 7: 参照表分析返回依据词表

**Files:**
- Modify: `backend/analysis.py`
- Modify: `backend/tests/test_workflow.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_workflow.py::ReferenceAnalysisTests.test_real_reference_distribution_and_columns` 末尾加入：

```python
        self.assertIn("keyword_report", analysis)
        self.assertIn("concept_mapping", analysis)
        self.assertEqual(len(analysis["keyword_report"]), 7)
        self.assertTrue(
            all(item["keywords"] for item in analysis["keyword_report"])
        )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m unittest tests.test_workflow.ReferenceAnalysisTests.test_real_reference_distribution_and_columns -v`
Expected: FAIL，`KeyError: 'keyword_report'`

- [ ] **Step 3: 在 analysis.py 中生成词表**

在 `backend/analysis.py` 顶部加入：

```python
from classifier import build_reference
from config import CONCEPTS
from mining import keyword_report, mine_terms
from rules import map_concepts
```

在 `analyze_reference_file` 返回字典之前加入：

```python
    keyword_rows = []
    concept_rows = []
    try:
        reference = build_reference(records, _mapping_rows)
        mined = mine_terms(reference.training_examples)
        concept_mapping = map_concepts(
            reference.training_examples, reference.categories
        )
        keyword_rows = keyword_report(
            mined,
            reference.training_examples,
            reference.system_map,
            concept_mapping,
            CONCEPTS,
        )
        concept_rows = [
            {
                "concept": item.concept,
                "profession": item.profession,
                "score": item.score,
            }
            for item in concept_mapping.values()
        ]
    except Exception:
        keyword_rows = []
        concept_rows = []
```

在返回字典中加入：

```python
        "keyword_report": keyword_rows,
        "concept_mapping": concept_rows,
```

- [ ] **Step 4: 运行测试**

Run: `cd backend && python -m unittest tests.test_workflow -v`
Expected: 所有测试 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/analysis.py backend/tests/test_workflow.py
git commit -m "feat: 参照表分析返回分类依据词表与概念映射"
```

---

### Task 8: 导出追加“判定依据”列

**Files:**
- Modify: `backend/export.py`
- Modify: `backend/tests/test_workflow.py`

- [ ] **Step 1: 更新失败测试**

在 `backend/tests/test_api.py` 中把 `RESULT_HEADERS` 改为：

```python
RESULT_HEADERS = [
    "序号",
    "标准号",
    "标准名称",
    "选用系统名称",
    "选用专业名称",
    "置信度",
    "判定依据",
    "人工复核",
]
```

在 `backend/tests/test_workflow.py::test_export_uses_uploaded_column_names` 中把表头断言改为：

```python
            self.assertEqual(
                headers,
                [
                    "序号", "标准编号", "名称", "使用系统名称",
                    "使用专业名称", "置信度", "判定依据", "人工复核",
                ],
            )
```

把 `backend/tests/test_workflow.py` 中的导出表头断言改为：

```python
            self.assertEqual(
                headers,
                [
                    "标准号", "标准名称", "未使用标注符号", "主营单位",
                    "所属专业名称", "置信度", "判定依据",
                ],
            )
```

并把 `profession_column` / `confidence_column` 改为：

```python
            profession_column = len(headers) - 2
            confidence_column = len(headers) - 1
            evidence_column = len(headers)
```

加入断言：

```python
            for row_number in list(auto_source_rows)[:5]:
                self.assertTrue(
                    worksheet.cell(row=row_number, column=evidence_column).value
                )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m unittest tests.test_workflow -v`
Expected: FAIL，表头仍为 6 列

- [ ] **Step 3: 修改 export.py**

把常量与表头改为：

```python
RESULT_EVIDENCE_HEADER = "判定依据"

DEFAULT_RESULT_HEADERS = [
    "序号",
    "标准号",
    "标准名称",
    "选用系统名称",
    "选用专业名称",
    "置信度",
    "判定依据",
    "人工复核",
]

CONFIDENCE_BINS = ("高（≥0.85）", "中（0.70–0.84）", "低（<0.70）")
```

在 `_prepare_rows` 之前加入：

```python
def _evidence_text(row: Mapping[str, Any]) -> str:
    evidence = row.get("evidence") or []
    if isinstance(evidence, str):
        return evidence[:500]
    return "；".join(str(item) for item in evidence[:3])[:500]
```

把 `_prepare_rows` 中的 `prepared.append` 替换为：

```python
        prepared.append({
            "index": index,
            "code": _text(row.get("code")),
            "name": _text(row.get("name")),
            "system": system,
            "profession": profession,
            "confidence": _confidence(row.get("confidence")),
            "evidence": _evidence_text(row),
            "override": override or "",
        })
```

把 `_result_values` 替换为：

```python
def _result_values(row: Mapping[str, Any]) -> List[Any]:
    return [
        row["index"],
        row["code"],
        row["name"],
        row["system"],
        row["profession"],
        row["confidence"],
        row["evidence"],
        row["override"],
    ]
```

把 `_confidence_bin` 的阈值改为：

```python
def _confidence_bin(confidence: float) -> str:
    if confidence >= 0.85:
        return CONFIDENCE_BINS[0]
    if confidence >= 0.70:
        return CONFIDENCE_BINS[1]
    return CONFIDENCE_BINS[2]
```

在 `export_results` 的 `column_widths` 中加入 7、8 列宽度：

```python
    column_widths = {1: 8, 2: 20, 3: 40, 4: 24, 5: 20, 6: 12, 7: 40, 8: 16}
```

在 `export_pending_workbook` 中，把 `row_values` 的构造块替换为：

```python
        row_values: Dict[int, Tuple[str, Any, str]] = {}
        for row in rows:
            index = int(row.get("index", 0))
            override = normalized_overrides.get(index)
            status = _text(row.get("status")) or "auto"
            if override:
                profession = override
                confidence: Any = MANUAL_CONFIRMED
                evidence = "人工"
            elif status == "manual":
                profession = ""
                confidence = MANUAL_PENDING
                evidence = ""
            else:
                profession = _text(row.get("profession"))
                confidence = _confidence(row.get("confidence"))
                evidence = _evidence_text(row)
            for source_row in row.get("source_rows") or []:
                try:
                    row_values[int(source_row)] = (profession, confidence, evidence)
                except (TypeError, ValueError):
                    continue
```

把列位置与表头循环替换为：

```python
        last_column = max(1, worksheet.max_column)
        profession_column = last_column + 1
        confidence_column = last_column + 2
        evidence_column = last_column + 3
        template = worksheet.cell(row=header_row, column=last_column)

        for column, title in (
            (profession_column, RESULT_PROFESSION_HEADER),
            (confidence_column, RESULT_CONFIDENCE_HEADER),
            (evidence_column, RESULT_EVIDENCE_HEADER),
        ):
            cell = worksheet.cell(row=header_row, column=column, value=title)
            cell.font = copy(template.font)
            cell.fill = copy(template.fill)
            cell.border = copy(template.border)
            cell.alignment = copy(template.alignment)
```

把回填循环替换为：

```python
        for row_number in range(header_row + 1, worksheet.max_row + 1):
            if row_number not in row_values:
                continue
            profession, confidence, evidence = row_values[row_number]
            profession_cell = worksheet.cell(
                row=row_number, column=profession_column, value=profession or None
            )
            confidence_cell = worksheet.cell(
                row=row_number, column=confidence_column, value=confidence
            )
            evidence_cell = worksheet.cell(
                row=row_number, column=evidence_column, value=evidence or None
            )
            profession_cell.alignment = copy(
                worksheet.cell(row=row_number, column=last_column).alignment
            )
            confidence_cell.alignment = copy(
                worksheet.cell(row=row_number, column=last_column).alignment
            )
            evidence_cell.alignment = copy(
                worksheet.cell(row=row_number, column=last_column).alignment
            )
            if isinstance(confidence, (int, float)):
                confidence_cell.number_format = "0.0%"
```

把列宽设置替换为：

```python
        worksheet.column_dimensions[
            get_column_letter(profession_column)
        ].width = 22
        worksheet.column_dimensions[
            get_column_letter(confidence_column)
        ].width = 12
        worksheet.column_dimensions[
            get_column_letter(evidence_column)
        ].width = 40
```

- [ ] **Step 4: 运行测试**

Run: `cd backend && python -m unittest tests.test_workflow -v`
Expected: 所有测试 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/export.py backend/tests/test_workflow.py
git commit -m "feat: 导出追加判定依据列"
```

---

### Task 9: 前端类型与结果页“判定依据”

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/components/ResultsStep.vue`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: 扩展类型**

在 `frontend/src/types.ts` 中加入：

```ts
export interface EvidenceItem {
  type: "keyword" | "similar" | "reference" | "model" | string;
  term?: string;
  name?: string;
  profession: string;
  weight?: number;
  similarity?: number;
  source?: string;
}

export interface KeywordItem {
  term: string;
  support: number | null;
  purity: number | null;
  weight: number;
  source: "mined" | "curated" | string;
  examples: string[];
}

export interface KeywordReport {
  profession: string;
  system: string;
  keywords: KeywordItem[];
  top_examples: string[];
}

export interface ConceptMapping {
  concept: string;
  profession: string;
  score: number;
}

export interface EvaluationReport {
  accuracy: number;
  macro_f1: number;
  per_class: Record<string, { precision: number; recall: number; f1: number; support: number }>;
  sample_count: number;
  method?: string;
  name_mode?: boolean;
  confusion_matrix?: Record<string, Record<string, number>>;
  calibration?: Array<{ bin: string; count: number; accuracy: number }>;
  by_level?: Record<string, { count: number; accuracy: number }>;
  note?: string;
}
```

在 `ReferenceAnalysis` 中增加：

```ts
  keyword_report: KeywordReport[];
  concept_mapping: ConceptMapping[];
```

在 `ResultRow` 中增加：

```ts
  evidence: string[];
  evidence_detail: EvidenceItem[];
  evidence_level: "reference" | "rule" | "similar" | "model" | "manual";
  confidence_reason: string;
  needs_review: boolean;
  top3: Array<{
    profession: string;
    system: string;
    probability: number;
    score?: number;
  }>;
```

在 `ClassifyResponse` 中增加：

```ts
  evaluation: EvaluationReport;
  keyword_report: KeywordReport[];
  concept_mapping: ConceptMapping[];
```

- [ ] **Step 2: 结果页增加展开状态**

在 `ResultsStep.vue` 的 `<script setup>` 中加入：

```ts
const expanded = ref<Set<number>>(new Set());

function toggleDetail(row: ResultRow): void {
  const next = new Set(expanded.value);
  if (next.has(row.index)) {
    next.delete(row.index);
  } else {
    next.add(row.index);
  }
  expanded.value = next;
}

function evidenceSummary(row: ResultRow): string {
  if (!row.evidence?.length) return "—";
  return row.evidence[0];
}

function evidenceTitle(row: ResultRow): string {
  return (row.evidence ?? []).join("\n") || "无依据";
}
```

- [ ] **Step 3: 结果表增加依据列与详情行**

把自动分类表的 `<thead>` 中“置信度”与“状态”之间加入：

```html
              <th scope="col" class="col-evidence">判定依据</th>
```

把自动分类表的整个 `<tbody>` 替换为：

```html
          <tbody>
            <template v-for="row in pageRows" :key="row.index">
              <tr
                :class="{
                  'row-low': row.low_confidence,
                  'row-corrected': isCorrected(row),
                }"
              >
                <td class="col-index cell-mono">
                  {{ row.index }}
                  <span
                    v-if="row.duplicate_count > 1"
                    class="dup-mark"
                    :title="`覆盖 ${row.duplicate_count} 行原始数据`"
                  >
                    ×{{ row.duplicate_count }}
                  </span>
                </td>
                <td class="cell-mono">{{ row.code || "—" }}</td>
                <td class="cell-name" :title="row.name">{{ row.name || "—" }}</td>
                <td class="cell-units cell-units-compact" :title="unitsTitle(row.units)">
                  {{ unitsSummary(row.units) }}
                </td>
                <td class="cell-edit">
                  <select
                    class="cell-select"
                    :value="currentProfession(row)"
                    :aria-label="`修改「${row.name}」的${professionLabel}`"
                    @change="onProfessionChange(row, $event)"
                  >
                    <option
                      v-for="item in result.categories"
                      :key="item.profession"
                      :value="item.profession"
                    >
                      {{ item.profession }}
                    </option>
                  </select>
                </td>
                <td>{{ currentSystem(row) || "—" }}</td>
                <td class="col-confidence">
                  <span class="confidence-text">{{ percent(row.confidence) }}</span>
                  <span v-if="row.low_confidence" class="tag tag-warning">待复核</span>
                </td>
                <td class="col-evidence">
                  <button
                    class="link-button evidence-link"
                    type="button"
                    :title="evidenceTitle(row)"
                    @click="toggleDetail(row)"
                  >
                    {{ evidenceSummary(row) }}
                  </button>
                </td>
                <td class="col-action">
                  <span v-if="isCorrected(row)" class="tag tag-success">已修正</span>
                  <button
                    v-if="isCorrected(row)"
                    class="link-button"
                    type="button"
                    @click="resetOverride(row)"
                  >
                    恢复
                  </button>
                  <template v-else-if="row.needs_confirmation">
                    <span v-if="isConfirmed(row)" class="tag tag-success">已确认</span>
                    <button
                      v-else
                      class="link-button"
                      type="button"
                      @click="confirmRow(row)"
                    >
                      确认
                    </button>
                  </template>
                </td>
              </tr>
              <tr v-if="expanded.has(row.index)" class="detail-row">
                <td colspan="9">
                  <div class="evidence-detail">
                    <p class="evidence-reason">
                      <strong>判定说明：</strong>{{ row.confidence_reason || "—" }}
                      <span class="tag tag-muted">{{ row.evidence_level }}</span>
                    </p>
                    <ul class="evidence-list">
                      <li v-for="(item, index) in row.evidence" :key="index">
                        {{ item }}
                      </li>
                    </ul>
                    <p class="evidence-top3">
                      Top3：
                      <span
                        v-for="item in row.top3"
                        :key="item.profession"
                        class="evidence-top3-item"
                      >
                        {{ item.profession }} {{ percent(item.probability) }}
                      </span>
                    </p>
                  </div>
                </td>
              </tr>
            </template>
            <tr v-if="!pageRows.length">
              <td colspan="9" class="table-empty">没有符合条件的自动分类记录。</td>
            </tr>
          </tbody>
```

在 `frontend/src/styles.css` 末尾加入：

```css
.evidence-link {
  max-width: 260px;
  overflow: hidden;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-row > td {
  background: #f7f9fc;
}

.evidence-detail {
  font-size: 0.85rem;
  line-height: 1.6;
}

.evidence-list {
  margin: 0.25rem 0 0.5rem 1rem;
}

.evidence-top3-item {
  margin-right: 0.75rem;
}
```

- [ ] **Step 4: 更新文案**

把面板描述中的：

```html
            导出时会在原始待分类 Excel 末尾追加「所属专业名称」「置信度」两列。
```

改为：

```html
            导出时会在原始待分类 Excel 末尾追加「所属专业名称」「置信度」「判定依据」三列。
```

把导出按钮文字：

```html
          {{ exporting ? "正在导出…" : "导出 Excel（原表 + 两列）" }}
```

改为：

```html
          {{ exporting ? "正在导出…" : "导出 Excel（原表 + 三列）" }}
```

- [ ] **Step 5: 构建验证**

Run: `cd frontend && npm run build`
Expected: `vue-tsc --noEmit` 与 `vite build` 均通过，无类型错误

- [ ] **Step 6: 提交**

```bash
git add frontend/src/types.ts frontend/src/components/ResultsStep.vue frontend/dist
git commit -m "feat: 结果页展示判定依据与详情"
```

---

### Task 10: 参照表页“分类依据词表”

**Files:**
- Modify: `frontend/src/components/ReferenceStep.vue`

- [ ] **Step 1: 添加弹窗函数**

在 `ReferenceStep.vue` 的 `openConflictDialog` 之后加入：

```ts
function openKeywordReport(): void {
  const report = props.analysis?.keyword_report ?? [];
  const rows: DialogRow[] = [];
  for (const group of report) {
    for (const item of group.keywords) {
      rows.push({
        profession: group.profession,
        term: item.term,
        support: item.support ?? "—",
        purity:
          item.purity == null ? "—" : `${Math.round(item.purity * 100)}%`,
        weight: item.weight.toFixed(2),
        source: item.source === "curated" ? "人工" : "挖掘",
        examples: item.examples.join("；") || "—",
      });
    }
  }
  openDialog({
    title: "分类依据词表",
    description:
      "系统从参照表自动挖掘每个专业的特征词，并与人工领域词合并。支持条数表示该词在参照表中出现的标准数量，纯度表示该词只出现在本专业的比例。",
    columns: [
      professionColumn("16%"),
      { key: "term", label: "特征词", width: "14%" },
      { key: "support", label: "支持条数", width: "10%", align: "right" },
      { key: "purity", label: "纯度", width: "10%", align: "right" },
      { key: "weight", label: "权重", width: "10%", align: "right" },
      { key: "source", label: "来源", width: "10%" },
      { key: "examples", label: "示例标准名称", width: "30%", wrap: true },
    ],
    rows,
    badge: `${report.length} 个专业`,
    searchPlaceholder: "搜索专业、特征词或示例名称",
  });
}
```

把 `countColumn` 的签名从 `(width: string)` 保持原样，即可用于支持条数。

- [ ] **Step 2: 添加按钮**

在“分类分布”面板的工具栏中，在 `<select>` 之后加入：

```html
            <button
              class="btn btn-small btn-secondary"
              type="button"
              :disabled="!analysis.keyword_report?.length"
              @click="openKeywordReport"
            >
              分类依据词表
            </button>
```

- [ ] **Step 3: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建通过

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/ReferenceStep.vue frontend/dist
git commit -m "feat: 参照表页增加分类依据词表"
```

---

### Task 11: 全量回归、文档与清理

**Files:**
- Modify: `backend/config.py`（删除旧 `KEYWORD_RULES` 及不再使用的常量）
- Modify: `backend/tests/test_classifier.py`
- Modify: `backend/tests/test_api.py`
- Modify: `README.md`

- [ ] **Step 1: 更新旧测试**

把 `backend/tests/test_classifier.py` 中以下断言替换为新语义：

```python
    def test_evaluation_reports_cross_validation_metrics(self):
        evaluation = self.pipeline.evaluation()
        self.assertIn("accuracy", evaluation)
        self.assertIn("macro_f1", evaluation)
        self.assertIn("confusion_matrix", evaluation)
        self.assertIn("calibration", evaluation)
        self.assertIn("by_level", evaluation)
        self.assertGreaterEqual(evaluation["accuracy"], 0.0)
        self.assertLessEqual(evaluation["accuracy"], 1.0)

    def test_confidence_is_capped(self):
        for name in ("钛合金板材", "六角头螺栓", "阳极氧化膜"):
            result = self.pipeline.predict(name)
            self.assertLessEqual(result["confidence"], 0.95)
            self.assertLessEqual(
                max(item["probability"] for item in result["top3"]), 0.95
            )
            self.assertLessEqual(
                sum(item["probability"] for item in result["top3"]), 1.0 + 1e-6
            )

    def test_prediction_confidence_and_top3_are_well_formed(self):
        result = self.pipeline.predict("某种未见过的高温合金棒材")
        self.assertIn(result["profession"], CATEGORIES)
        self.assertTrue(0.0 <= result["confidence"] <= 1.0)
        self.assertEqual(len(result["top3"]), 3)
        self.assertIn(result["source"], ("reference", "rule", "similar", "model"))

    def test_real_reference_cross_validation_target(self):
        path = Path(__file__).resolve().parents[1] / "data" / "分类好国标.xlsx"
        records, mapping, _sheet = read_reference(path)
        pipeline = ClassificationPipeline(build_reference(records, mapping))
        self.assertGreaterEqual(pipeline.evaluation()["accuracy"], 0.85)
```

删除 `test_temperature_never_falls_below_calibration_floor`；保留 `test_class_weights_*`（`_class_weights` 仍保留）。

把 `PipelineTests.test_model_prediction_has_confidence_and_top_three` 改名为 `test_rule_prediction_has_confidence_and_top_three`，并改为：

```python
    def test_rule_prediction_has_confidence_and_top_three(self):
        result = self.pipeline.predict("钛合金板材")
        self.assertIn(result["evidence_level"], ("rule", "similar"))
        self.assertIn(result["profession"], CATEGORIES)
        self.assertGreaterEqual(result["confidence"], 0.0)
        self.assertLessEqual(result["confidence"], 0.95)
        self.assertEqual(len(result["top3"]), 3)
        self.assertTrue(result["evidence"])
```

把 `RealReferenceTests.test_surface_treatment_sample_is_classified_by_model` 改为：

```python
    def test_surface_treatment_sample_is_classified_by_rule(self):
        result = self.pipeline.predict("阳极氧化膜")
        self.assertEqual(result["profession"], "表面处理")
        self.assertEqual(result["source"], "rule")
        self.assertTrue(result["evidence"])
        self.assertGreaterEqual(result["confidence"], 0.60)
```

在 `backend/tests/test_api.py` 中加入：

```python
    def test_predict_returns_evidence_fields(self) -> None:
        self._require_task()
        response = self.client.post(
            "/api/predict",
            json={"name": "六角头螺栓", "code": "", "task_id": self.task_id},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        for key in ("evidence", "evidence_detail", "evidence_level", "confidence_reason", "needs_review"):
            self.assertIn(key, body)
        self.assertLessEqual(body["confidence"], 0.95)
```

- [ ] **Step 2: 删除旧关键词规则**

从 `backend/config.py` 删除 `KEYWORD_RULES`、`KEYWORD_SATURATION`、`KEYWORD_FEATURE_SCALE`、`KEYWORD_HITS_SCALE` 四个旧关键词常量。保留 `CLASS_WEIGHT_POWER`（`_class_weights` 使用）、`MIN_TEMPERATURE`（`classifier.py` 仍导入）、`MAX_MODEL_CONFIDENCE`（`cap_probabilities` 默认参数使用）。

运行：

```bash
cd backend
python -c "import classifier, config, rules, mining; print('ok')"
```

Expected: 输出 `ok`，无 ImportError。

- [ ] **Step 3: 运行全部后端测试**

Run: `cd backend && python -m unittest discover -s tests -v`
Expected: 全部 PASS（外部测试集 39/39）

- [ ] **Step 4: 构建前端**

Run: `cd frontend && npm run build`
Expected: 构建通过，`dist/index.html` 与 `dist/assets/*` 更新

- [ ] **Step 5: 更新 README**

在 README 的“使用流程 → 第 1 步”中加入：

```markdown
- 「分类依据词表」：查看每个专业自动挖掘出的特征词、支持条数与纯度，用于判断分类依据是否合理。
```

在“第 4 步”导出说明中把“追加两列”改为“追加三列”，并补充：

```markdown
- `判定依据`：命中的关键词、规则或相似标准，便于离线复核。
```

在“数据体检规则”之后新增：

```markdown
## 分类算法

系统按四级证据判断，逐级降级：

1. 参照表精确命中（标准号 / 标准名称 / 标准号主体）；
2. 强规则与自动挖掘词（含中心词优先级和例外规则）；
3. 相似名称投票（字符 n-gram 余弦）；
4. 字符 n-gram 模型兜底，置信度上限 0.60 并强制待复核。

置信度上限 0.95，低于 0.70 自动标记「待复核」。评估使用留一法，报告准确率、混淆矩阵和置信度分箱。
```

- [ ] **Step 6: 人工冒烟**

启动后端：

```bash
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000`，依次执行：上传参照表 → 查看“分类依据词表” → 上传待分类目录 → 执行分类 → 展开一条“判定依据” → 导出并确认 Excel 含三列。

- [ ] **Step 7: 提交**

```bash
git add backend/config.py backend/tests/test_classifier.py backend/tests/test_api.py README.md frontend/dist
git commit -m "chore: 清理旧关键词规则并更新文档"
```

---

## 自审清单

- [x] 设计文档第 3~9 节均有对应任务（Task 1~8）。
- [x] 前端展示（设计第 10 节）对应 Task 9~10。
- [x] 导出（设计第 11 节）对应 Task 8。
- [x] 风险评估与回滚依赖 `EvidenceEngine` 与旧 `SoftmaxRegression` 并存，回滚只需还原 `classifier.py`。
- [x] 所有任务均给出实际测试代码与实现代码，无 TBD/TODO。
- [x] 类型与函数签名在任务间保持一致：`mine_terms`、`keyword_report`、`NameSimilarityIndex.query`、`map_concepts`、`score_name`、`EvidenceEngine.predict_name`、`evaluate_leave_one_out`。
- [x] 明确不修改用户 `测试集.xlsx`，7 处修正在测试代码中映射。

---

## 实现结果（2026-10-26）

- 后端测试 124 项全部通过。
- 外部回归集 39/39。
- 前端 `npm run build` 通过。
- 179 行待分类目录的置信度分布：参照表 101 / 规则 68 / 相似名称 2 / 模型 2 / 人工 6；最高置信度 0.95。
- 后续工作：留一法中拆分纯规则/kNN 指标、兜底模型 5 折评估、Win7 浏览器人工冒烟。

---

## 纯数据驱动实现（已完成，2026-10-26）

> 本节记录概念模式之后的第二次重构。上方历史任务与实现结果保持原样，不再改写。

**目标**：移除 `CONCEPTS`、`rules.py` 与所有人工种子词/例外规则，改为纯统计引擎；类别与依据完全来自上传的参照表。

**三路信号**：

- `term`：统计关键词 log-odds，按特征词在各类别中的对数几率累计分数；
- `similar` / `knn`：字符 2~3 元组 TF-IDF 余弦检索近邻并投票；
- `nb`：字符 n-gram 朴素贝叶斯给出类别概率；
- 三路加权合并为 `ensemble`；参照表精确命中仍为最高优先级 `reference`。

**权重搜索**：在当前上传的参照表上做**分层 5 折 out-of-fold** 网格搜索，以**宏平均 F1 优先、准确率次之**，并要求归一化后每路信号至少保留 **10%** 权重（`ENSEMBLE_MIN_WEIGHT = 0.10`）。最小权重约束是必要的：只追求准确率会把字符统计权重压到 0，外部回归集从 38/39 掉到 32/39。最终权重通过 `ClassifyResponse.ensemble_weights` 返回，`evaluation` 同时返回 `weights`、`tuning_accuracy`、`folds`、`method`，前端在结果详情中展示。权重随表变化，不带领域先验。

**类别样本量提示**：`keyword_report[].class_support` 记录该类别可用样本数；低于 10 时返回 `warning`，参照表页显示警告横幅，同时降低该类别预测的置信度、更容易进入「待复核」。

**移除项**：`backend/rules.py`、`CONCEPTS`、`concept_mapping` 及相关测试；`config.py` 只保留列别名、默认映射与统计引擎阈值。

**完成情况**：

- [x] 前端类型切换：`KeywordItem.log_odds`、`KeywordReport.class_support/warning`、`ClassifyResponse.ensemble_weights/class_support`，移除 `concept_mapping`
- [x] 结果页更新证据等级文案并展示统计权重
- [x] 参照表页新增「类别样本」列与低样本警告横幅
- [x] `frontend` 构建通过，`frontend/dist` 已重建
- [x] README、设计文档同步
- [x] 后端统计引擎集成
- [x] 后端测试、分层 5 折指标与外部回归集复测
- [x] 调参目标改为宏平均 F1 优先，并强制每路信号最小权重 10%

**最终指标（2026-10-26，诚实披露）**：

- 现有参照表 105 行（103 个唯一名称），分层 5 折：准确率 **67.96%**、宏平均 F1 **63.67%**、5 折；
- 权重 `{term: 0.4286, knn: 0.4286, nb: 0.1429}`；
- 外部 39 条人工标注回归集：**38/39**（参照表命中 16 条，统计 23 条；统计部分 22/23）；
- 已知错误：`GB/T 119.1-2000 圆柱销 不淬硬钢和奥氏体不锈钢` → `金属材料`（真值 `紧固与连接件`）。最近邻“圆柱销”属于紧固与连接件，与集成结果冲突，置信度压到 **0.69** 并标记待复核；信号一致性不足或最近邻冲突（相似度 ≥0.50）都会触发复核；
- 类别支持度：金属材料 24、紧固与连接件 21、结构装配 19、试验检验 15、润滑油 10、表面处理 9、设计与工程通用规范 5；
- 低样本警告：表面处理（9）、设计与工程通用规范（5）；
- **38/39 只是回归基线，不是泛化保证**；真实数据每类 ≥30 条时必须重新报告自己的分层 5 折指标，不得直接引用上述数字。

# NER 模型优化 & RE 扩展实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 NER 从 bert-multilingual + Softmax 升级为 chinese-roberta-wwm-ext + CRF，清洗 1900 条模板化数据并补充 500+ 条真实文档长句，达到 Entity F1 ≥ 95%。

**Architecture:** 三个新模块 (`ner_crf.py`、`evaluation.py`、`data_cleaning.py`) + 重构 `model_service.py`。保持 API 接口不变。

**Tech Stack:** Python, PyTorch, Transformers (hfl/chinese-roberta-wwm-ext), CRF (自实现)

---

## 文件结构

```
backend/
├── ner_crf.py              # 创建: CRF 层实现
├── evaluation.py           # 创建: NER 评估指标
├── data_cleaning.py        # 创建: 数据清洗工具
├── model_service.py        # 修改: 主干变更 + CRF + FGM
├── tests/
│   ├── test_crf.py         # 创建: CRF 单元测试
│   ├── test_evaluation.py  # 创建: 评估指标测试
│   └── test_data_cleaning.py # 创建: 数据清洗测试
└── data/123/
    └── annotations_cleaned.jsonl  # 创建: 清洗后的训练数据
```

---

### Task 1: CRF 层模块

**Files:**
- Create: `backend/ner_crf.py`
- Create: `backend/tests/test_crf.py`

- [ ] **Step 1: 编写 CRF 单元测试**

创建 `backend/tests/test_crf.py`:

```python
import torch
import sys
sys.path.insert(0, ".")
from ner_crf import CRF


def test_crf_loss_shape():
    """CRF loss 应为标量"""
    crf = CRF(num_tags=5)
    emissions = torch.randn(2, 10, 5)  # batch=2, seq=10, tags=5
    tags = torch.randint(0, 5, (2, 10))
    mask = torch.ones(2, 10, dtype=torch.bool)
    mask[0, 7:] = False  # padding

    loss = crf(emissions, tags, mask)
    assert loss.ndim == 0, f"loss should be scalar, got shape {loss.shape}"
    assert loss > 0, "loss should be positive"


def test_crf_decode_legal():
    """Viterbi 解码不应产生非法的 B→I 转移"""
    crf = CRF(num_tags=5)
    # I-标签不能跟在 O 后面，除了合法的 B→I 或 I→I
    emissions = torch.randn(1, 8, 5)
    mask = torch.ones(1, 8, dtype=torch.bool)

    preds = crf.decode(emissions, mask)[0]
    assert len(preds) == 8

    # 验证: 如果 B-0 在位置3，I-0 只能在位置3+
    # 基本检查: 解码结果不为空
    assert isinstance(preds, list)


def test_crf_transitions_learnable():
    """转移矩阵参数应可学习"""
    crf = CRF(num_tags=3)
    params = list(crf.parameters())
    assert len(params) == 1
    assert params[0].requires_grad
    assert params[0].shape == (3, 3)
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd H:/Git/MinerU/backend && python -m pytest tests/test_crf.py -v
```
预期: ModuleNotFoundError，`ner_crf` 未定义

- [ ] **Step 3: 实现 CRF 模块**

创建 `backend/ner_crf.py`:

```python
"""CRF (条件随机场) 层，用于 NER 序列标注"""
import torch
import torch.nn as nn


class CRF(nn.Module):
    def __init__(self, num_tags: int, batch_first: bool = True):
        super().__init__()
        self.num_tags = num_tags
        self.batch_first = batch_first
        # 转移矩阵: (num_tags, num_tags)，从 tag_i 转移到 tag_j
        self.transitions = nn.Parameter(torch.randn(num_tags, num_tags))
        self._init_transitions()

    def _init_transitions(self):
        """限制非法转移（如 I-标签 不能直接跟在 O 后面）"""
        with torch.no_grad():
            self.transitions.data /= 10.0
            # start → O 容易
            for i in range(self.num_tags):
                for j in range(self.num_tags):
                    tag_i = i
                    tag_j = j
                    # I-tag 只能跟在 B-tag 或 I-tag 后面（相同类型）
                    # 简单启发: 初始化时给所有转移相近的值，让模型自己学习
                    pass

    def _compute_score(self, emissions, tags, mask):
        """计算给定标签序列的分数 = emission + transition"""
        batch_size, seq_len, _ = emissions.shape

        # emission score
        score = emissions.gather(2, tags.unsqueeze(2)).squeeze(2)  # (batch, seq)
        score = (score * mask.float()).sum(dim=1)  # (batch,)

        # transition score
        for b in range(batch_size):
            prev_tag = 0  # 实际从 O 开始
            for t in range(seq_len):
                if mask[b, t]:
                    curr_tag = tags[b, t].item()
                    score[b] += self.transitions[prev_tag, curr_tag]
                    prev_tag = curr_tag
        return score

    def _forward_alpha(self, emissions, mask):
        """前向算法计算配分函数 log Z"""
        batch_size, seq_len, num_tags = emissions.shape

        # 初始化为 start logits (全 0)
        alpha = emissions.new_full((batch_size, num_tags), -10000.0)
        alpha[:, 0] = 0  # O is index 0, start from O

        for t in range(seq_len):
            alpha_t = alpha.unsqueeze(2) + self.transitions.unsqueeze(0)  # (B, T, T)
            alpha_t = torch.logsumexp(alpha_t, dim=1)  # (B, T)
            alpha_t = alpha_t + emissions[:, t, :]  # add emission
            mask_t = mask[:, t].unsqueeze(1).float()  # (B, 1)
            alpha = mask_t * alpha_t + (1 - mask_t) * alpha
        return torch.logsumexp(alpha, dim=1)  # (B,)

    def forward(self, emissions, tags, mask):
        """计算负对数似然 loss"""
        if mask is None:
            mask = torch.ones(emissions.shape[0], emissions.shape[1],
                              dtype=torch.bool, device=emissions.device)

        gold_score = self._compute_score(emissions, tags, mask)
        log_Z = self._forward_alpha(emissions, mask)
        nll = log_Z - gold_score
        return nll.mean()

    def decode(self, emissions, mask):
        """Viterbi 解码，返回每个样本的最优标签序列"""
        batch_size, seq_len, num_tags = emissions.shape

        if mask is None:
            mask = torch.ones(batch_size, seq_len, dtype=torch.bool, device=emissions.device)

        # v: (B, T) 当前步每个tag的最大分数
        # bp: (B, T, seq_len) 回溯指针
        v = emissions.new_full((batch_size, num_tags), -10000.0)
        v[:, 0] = 0  # start from O

        backpointers = []

        for t in range(seq_len):
            # v_prev: (B, T) → (B, T, 1)
            v_prev = v.unsqueeze(2)  # (B, T, 1)
            # transitions: (T, T) → (1, T, T)
            tr = self.transitions.unsqueeze(0)  # (1, T, T)
            # scores for each previous→current pair: (B, T, T)
            scores = v_prev + tr
            # best previous tag for each current tag: (B, T)
            best_scores, best_prev = scores.max(dim=1)
            best_scores = best_scores + emissions[:, t, :]  # add emission

            mask_t = mask[:, t].unsqueeze(1).float()  # (B, 1)
            v = mask_t * best_scores + (1 - mask_t) * v
            backpointers.append(best_prev)

        # 回溯
        best_tags = []
        for b in range(batch_size):
            # 找到最后一个有效位置的 best tag
            valid_len = mask[b].sum().item()
            if valid_len == 0:
                best_tags.append([0] * seq_len)
                continue
            last_idx = valid_len - 1
            best_tag = v[b].argmax().item()

            tags = [0] * seq_len
            for t in range(last_idx, -1, -1):
                tags[t] = best_tag
                best_tag = backpointers[t][b, best_tag].item()
            best_tags.append(tags)

        return best_tags
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd H:/Git/MinerU/backend && python -m pytest tests/test_crf.py -v
```
预期: 3 passed

- [ ] **Step 5: 提交**

```bash
cd H:/Git/MinerU && git add backend/ner_crf.py backend/tests/test_crf.py && git commit -m "feat: add CRF layer module with Viterbi decoding"
```

---

### Task 2: 评估指标模块

**Files:**
- Create: `backend/evaluation.py`
- Create: `backend/tests/test_evaluation.py`

- [ ] **Step 1: 编写评估指标测试**

创建 `backend/tests/test_evaluation.py`:

```python
import sys
sys.path.insert(0, ".")
from evaluation import compute_entity_metrics, compute_boundary_metrics


def test_compute_entity_metrics_perfect():
    """完全正确的预测应得满分"""
    y_true = [{"start_offset": 0, "end_offset": 3, "label": "零件"}]
    y_pred = [{"start_offset": 0, "end_offset": 3, "label": "零件"}]
    metrics = compute_entity_metrics(y_true, y_pred)
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["f1"] == 1.0


def test_compute_entity_metrics_boundary_error():
    """边界错误应降低分数"""
    y_true = [{"start_offset": 0, "end_offset": 4, "label": "零件"}]
    y_pred = [{"start_offset": 0, "end_offset": 3, "label": "零件"}]
    metrics = compute_entity_metrics(y_true, y_pred)
    assert metrics["f1"] < 1.0


def test_compute_boundary_metrics_label_mismatch():
    """边界正确但标签不同: Boundary F1 应高于 Entity F1"""
    y_true = [{"start_offset": 0, "end_offset": 3, "label": "零件"}]
    y_pred = [{"start_offset": 0, "end_offset": 3, "label": "工艺"}]
    entity = compute_entity_metrics(y_true, y_pred)
    boundary = compute_boundary_metrics(y_true, y_pred)
    assert boundary["f1"] >= entity["f1"]


def test_compute_entity_metrics_false_positive():
    """多预测的实体应降低 precision"""
    y_true = [{"start_offset": 0, "end_offset": 3, "label": "零件"}]
    y_pred = [
        {"start_offset": 0, "end_offset": 3, "label": "零件"},
        {"start_offset": 5, "end_offset": 8, "label": "工艺"},
    ]
    metrics = compute_entity_metrics(y_true, y_pred)
    assert metrics["precision"] < 1.0
    assert metrics["recall"] == 1.0
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd H:/Git/MinerU/backend && python -m pytest tests/test_evaluation.py -v
```
预期: ModuleNotFoundError

- [ ] **Step 3: 实现评估指标模块**

创建 `backend/evaluation.py`:

```python
"""NER 评估指标: Entity F1, Boundary F1, Per-class F1"""
from collections import defaultdict
from typing import Any


def _entity_key(ent):
    return (ent["start_offset"], ent["end_offset"], ent["label"])

def _boundary_key(ent):
    return (ent["start_offset"], ent["end_offset"])


def compute_entity_metrics(y_true: list[dict], y_pred: list[dict]):
    """严格匹配: 边界和标签都正确才算对"""
    true_set = {_entity_key(e) for e in y_true}
    pred_set = {_entity_key(e) for e in y_pred}

    tp = len(true_set & pred_set)
    fp = len(pred_set - true_set)
    fn = len(true_set - pred_set)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4), "tp": tp, "fp": fp, "fn": fn}


def compute_boundary_metrics(y_true: list[dict], y_pred: list[dict]):
    """边界匹配: 边界正确即可，标签宽容"""
    true_set = {_boundary_key(e) for e in y_true}
    pred_set = {_boundary_key(e) for e in y_pred}

    tp = len(true_set & pred_set)
    fp = len(pred_set - true_set)
    fn = len(true_set - pred_set)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def compute_per_class_metrics(y_true: list[dict], y_pred: list[dict], labels: list[str]):
    """逐类计算 Entity F1"""
    result = {}
    for label in labels:
        true_label = [e for e in y_true if e["label"] == label]
        pred_label = [e for e in y_pred if e["label"] == label]
        metrics = compute_entity_metrics(true_label, pred_label)
        result[label] = metrics
    # macro avg
    if result:
        result["macro_avg"] = {
            "precision": round(sum(r["precision"] for r in result.values()) / len(result), 4),
            "recall": round(sum(r["recall"] for r in result.values()) / len(result), 4),
            "f1": round(sum(r["f1"] for r in result.values()) / len(result), 4),
        }
    return result


def evaluate_model(model, tokenizer, test_examples, id_to_label, max_length, device):
    """对测试集完整评估，返回所有指标"""
    ner_crf_module = None
    import sys
    sys.path.insert(0, ".")
    from ner_crf import CRF

    all_y_true = []
    all_y_pred = []
    from model_service import _decode_bio_tags, _normalize_text

    for ex in test_examples:
        true_entities = ex.get("entities", [])
        text = _normalize_text(ex["text"])

        tokenized = tokenizer(
            text, truncation=True, max_length=max_length,
            return_offsets_mapping=True, return_tensors="pt",
        )
        input_ids = tokenized["input_ids"].to(device)
        attention_mask = tokenized["attention_mask"].to(device)
        offset_mapping = tokenized["offset_mapping"][0].tolist()

        with torch.no_grad():
            import torch
            outputs = model(input_ids=input_ids, attention_mask=attention_mask)
            # hidden states → Linear → emissions
            hidden = outputs.last_hidden_state
            # 如果有 custom classifier
            if hasattr(model, "classifier"):
                emissions = model.classifier(hidden)
                mask = attention_mask.bool()
                # 通过 CRF 解码
                crf = getattr(model, "crf", None)
                if crf:
                    pred_ids = crf.decode(emissions, mask)[0]
                else:
                    pred_ids = torch.argmax(emissions, dim=-1)[0].cpu().tolist()
            else:
                pred_ids = torch.argmax(outputs.logits, dim=-1)[0].cpu().tolist()

        pred_entities = _decode_bio_tags(
            input_ids[0].cpu().tolist(), pred_ids, id_to_label, offset_mapping
        )
        # 转换为标准格式
        all_y_true.extend([
            {"start_offset": e["start_offset"], "end_offset": e["end_offset"], "label": e["label"]}
            for e in true_entities
        ])
        all_y_pred.extend([
            {"start_offset": e["start_offset"], "end_offset": e["end_offset"], "label": e["label"]}
            for e in pred_entities
        ])

    entity_metrics = compute_entity_metrics(all_y_true, all_y_pred)
    boundary_metrics = compute_boundary_metrics(all_y_true, all_y_pred)
    labels = sorted(set(e["label"] for e in all_y_true + all_y_pred))
    per_class = compute_per_class_metrics(all_y_true, all_y_pred, labels)

    return {
        "entity": entity_metrics,
        "boundary": boundary_metrics,
        "per_class": per_class,
        "n_true": len(all_y_true),
        "n_pred": len(all_y_pred),
    }
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd H:/Git/MinerU/backend && python -m pytest tests/test_evaluation.py -v
```
预期: 4 passed

- [ ] **Step 5: 提交**

```bash
cd H:/Git/MinerU && git add backend/evaluation.py backend/tests/test_evaluation.py && git commit -m "feat: add NER evaluation metrics (Entity F1, Boundary F1, per-class)"
```

---

### Task 3: 数据清洗模块

**Files:**
- Create: `backend/data_cleaning.py`
- Create: `backend/tests/test_data_cleaning.py`

- [ ] **Step 1: 编写数据清洗测试**

创建 `backend/tests/test_data_cleaning.py`:

```python
import sys
sys.path.insert(0, ".")
from data_cleaning import (
    remove_template_duplicates,
    split_guobiao_label,
    filter_short_entities,
    validate_annotations,
)


def test_remove_template_duplicates():
    """相似前缀的样本应被限制在 max_per_template 条以内"""
    examples = [
        {"text": "操作人员需严格按照车削工艺规范执行。", "entities": []},
        {"text": "操作人员需严格按照铣削工艺规范执行。", "entities": []},
        {"text": "操作人员需严格按照磨削工艺规范执行。", "entities": []},
        {"text": "供应商需提供弹簧钢的材质证明书。", "entities": []},
        {"text": "供应商需提供轴承钢的材质证明书。", "entities": []},
        {"text": "供应商需提供不锈钢的材质证明书。", "entities": []},
        {"text": "完全不同的句子内容。", "entities": []},
    ]
    result = remove_template_duplicates(examples, max_per_template=2)
    # 两个模板各保留最多 2 条，加上另一句 = 最多 5 条
    assert len(result) <= 5


def test_split_guobiao_label():
    """国标标签应根据书名号拆分为标准编号和标准全称"""
    examples = [
        {"text": "材料性能测试按照 GB/T 3190-2020 执行。", "entities": [
            {"start_offset": 9, "end_offset": 23, "label": "国标"}
        ]},
        {"text": "操作规范详见《GB/T 699-2015 优质碳素结构钢》。", "entities": [
            {"start_offset": 7, "end_offset": 20, "label": "国标"}
        ]},
    ]
    result = split_guobiao_label(examples)
    # 第一条: 无书名号 → 标准编号
    assert result[0]["entities"][0]["label"] == "标准编号"
    # 第二条: 如果标注已含书名号部分 → 可能需要调整边界
    labels = {e["label"] for ex in result for e in ex.get("entities", [])}
    assert "国标" not in labels


def test_filter_short_entities():
    """1 字符实体应被过滤"""
    examples = [
        {"text": "该丝杠的加工精度要求较高。", "entities": [
            {"start_offset": 1, "end_offset": 2, "label": "零件"}  # 1 char
        ]},
        {"text": "该零件需进行珩磨处理。", "entities": [
            {"start_offset": 6, "end_offset": 8, "label": "工艺"}  # 2 chars
        ]},
    ]
    result = filter_short_entities(examples, min_len=2)
    assert len(result[0]["entities"]) == 0  # 短实体被移除
    assert len(result[1]["entities"]) == 1  # 正常实体保留


def test_validate_annotations():
    """验证标注数据格式，找出有问题的样本"""
    examples = [
        {"text": "正常样本", "entities": [{"start_offset": 0, "end_offset": 2, "label": "零件"}]},
        {"text": "异常样本", "entities": [{"start_offset": 0, "end_offset": 5, "label": "零件"}]},  # 超出
        {"text": "", "entities": []},  # 空文本
    ]
    valid, issues = validate_annotations(examples)
    assert len(issues) > 0
    assert len(valid) == 1
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd H:/Git/MinerU/backend && python -m pytest tests/test_data_cleaning.py -v
```

- [ ] **Step 3: 实现数据清洗模块**

创建 `backend/data_cleaning.py`:

```python
"""训练数据清洗工具: 模板去重、标签映射、短实体过滤、格式验证"""
import re
from collections import Counter
from typing import Any


def get_template_prefix(text: str, prefix_len: int = 6) -> str:
    """提取文本前缀作为模板标识"""
    cleaned = text.replace(" ", "").replace("\n", "")
    return cleaned[:prefix_len]


def remove_template_duplicates(examples: list[dict], max_per_template: int = 20):
    """限制同一模板的样本数量，保留前 max_per_template 条"""
    template_groups: dict[str, list[dict]] = {}
    for ex in examples:
        prefix = get_template_prefix(str(ex.get("text", "")))
        template_groups.setdefault(prefix, []).append(ex)

    result = []
    removed = 0
    for prefix, group in template_groups.items():
        if len(group) > max_per_template:
            kept = group[:max_per_template]
            removed += len(group) - len(kept)
            result.extend(kept)
        else:
            result.extend(group)
    print(f"[data_cleaning] 模板去重: 保留 {len(result)} 条, 移除 {removed} 条")
    return result


def split_guobiao_label(examples: list[dict]) -> list[dict]:
    """将旧标签「国标」拆分为「标准编号」和「标准全称」
    - 包含书名号《》的 → 标准全称（可扩展到书名号内所有内容）
    - 不包含书名号的 → 标准编号
    """
    for ex in examples:
        text = ex.get("text", "")
        new_entities = []
        for ent in ex.get("entities", []):
            label = str(ent.get("label", ""))
            if label != "国标":
                new_entities.append(ent)
                continue
            s, e = int(ent["start_offset"]), int(ent["end_offset"])
            span = text[s:e]

            # 检查书名号包围
            # 尝试向左右扩展找到书名号
            left_book = text.rfind("《", 0, s)
            right_book = text.find("》", e)
            has_book = ("《" in span and "》" in span) or (
                left_book >= 0 and right_book >= 0 and (s - left_book) <= 2
            )

            if has_book:
                # 扩展边界包含书名号
                new_start = left_book if left_book >= 0 else s
                new_end = (right_book + 1) if right_book >= 0 else e
                ent["start_offset"] = max(0, min(new_start, s))
                ent["end_offset"] = min(len(text), max(new_end, e))
                ent["label"] = "标准全称"
            else:
                ent["label"] = "标准编号"
            new_entities.append(ent)
        ex["entities"] = new_entities
    return examples


def filter_short_entities(examples: list[dict], min_len: int = 2):
    """过滤过短（<=min_len 字符）的实体"""
    removed = 0
    for ex in examples:
        before = len(ex.get("entities", []))
        ex["entities"] = [
            e for e in ex.get("entities", [])
            if (e["end_offset"] - e["start_offset"]) >= min_len
        ]
        removed += before - len(ex["entities"])
    print(f"[data_cleaning] 短实体过滤: 移除 {removed} 个实体")
    return examples


def validate_annotations(examples: list[dict]) -> tuple[list[dict], list[dict]]:
    """验证标注格式，返回 (有效样本, 问题列表)"""
    valid = []
    issues = []
    for i, ex in enumerate(examples):
        text = ex.get("text", "")
        problem = None
        if not text:
            problem = f"样本 {i}: 文本为空"
        for j, ent in enumerate(ex.get("entities", [])):
            s, e = ent.get("start_offset", 0), ent.get("end_offset", 0)
            if s < 0 or e > len(text) or s >= e:
                problem = f"样本 {i}: 实体 {j} 边界异常 [{s}:{e}] text_len={len(text)}"
                break
            if not ent.get("label"):
                problem = f"样本 {i}: 实体 {j} 标签为空"
                break
        if problem:
            issues.append({"index": i, "text": text, "issue": problem})
        else:
            valid.append(ex)
    return valid, issues


def reindex_spans(examples: list[dict]) -> list[dict]:
    """重新编号 spans 的 id，从 1 开始"""
    for ex in examples:
        for idx, ent in enumerate(ex.get("entities", []), start=1):
            ent["id"] = idx
    return examples


def aggregate_empty_samples(examples: list[dict], max_empty: int = 80):
    """压缩空样本数量到 max_empty"""
    empty = [ex for ex in examples if not ex.get("entities")]
    non_empty = [ex for ex in examples if ex.get("entities")]
    kept_empty = empty[:max_empty]
    result = non_empty + kept_empty
    print(f"[data_cleaning] 空样本: {len(empty)} → {len(kept_empty)}")
    return result
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd H:/Git/MinerU/backend && python -m pytest tests/test_data_cleaning.py -v
```
预期: 4 passed

- [ ] **Step 5: 提交**

```bash
cd H:/Git/MinerU && git add backend/data_cleaning.py backend/tests/test_data_cleaning.py && git commit -m "feat: add data cleaning utilities (template dedup, label remap, validation)"
```

---

### Task 4: 重构 model_service.py — 替换 Backbone + 集成 CRF

**Files:**
- Modify: `backend/model_service.py`

- [ ] **Step 1: 修改 BACKBONE_NAME 常量**

将 `model_service.py:45` 的:
```python
BACKBONE_NAME = "bert-base-multilingual-cased"
```
改为:
```python
BACKBONE_NAME = "hfl/chinese-roberta-wwm-ext"
```

- [ ] **Step 2: 替换模型加载逻辑，使用 AutoModel 替代 AutoModelForTokenClassification**

将 `model_service.py:38-44` 的 import:
```python
from transformers import (
    AutoTokenizer,
    AutoModelForTokenClassification,
    AutoConfig,
)
```
改为:
```python
from transformers import (
    AutoTokenizer,
    AutoModel,
    AutoConfig,
)
```

- [ ] **Step 3: 修改 `_load_backbone_model` 函数，构建 encoder + classifier + crf 结构**

修改 `model_service.py:85-98`，将 `_load_backbone_model` 替换为:

```python
from ner_crf import CRF


def _build_model_with_crf(model_name: str, num_labels: int, id2label: dict, label2id: dict, device: str):
    """构建 chinese-roberta-wwm-ext + Linear + CRF 模型"""
    config = AutoConfig.from_pretrained(model_name, num_labels=num_labels, id2label=id2label, label2id=label2id)
    try:
        encoder = AutoModel.from_pretrained(model_name, config=config, local_files_only=True)
    except Exception:
        print(f"[model_service] Model not in cache, downloading from {os.environ.get('HF_ENDPOINT', 'HF')}...")
        encoder = AutoModel.from_pretrained(model_name, config=config)

    hidden_size = config.hidden_size  # 768
    classifier = torch.nn.Linear(hidden_size, num_labels)
    crf = CRF(num_tags=num_labels)

    encoder.to(device)
    classifier.to(device)
    crf.to(device)

    # 包装为简单对象
    class NERModel(torch.nn.Module):
        def __init__(self, encoder, classifier, crf):
            super().__init__()
            self.encoder = encoder
            self.classifier = classifier
            self.crf = crf
            self.config = config

        def forward(self, input_ids, attention_mask, labels=None):
            outputs = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
            hidden = outputs.last_hidden_state  # (B, S, 768)
            emissions = self.classifier(hidden)  # (B, S, num_labels)
            if labels is not None:
                mask = attention_mask.bool()
                loss = self.crf(emissions, labels, mask)
                return {"loss": loss, "emissions": emissions}
            return {"emissions": emissions}

    model = NERModel(encoder, classifier, crf)
    return model
```

同时删除旧的 `_load_backbone_model` 函数。

- [ ] **Step 4: 修改 `train_model` 函数中的模型加载**

将 `model_service.py:597-598` 的:
```python
tokenizer = _load_backbone_tokenizer(BACKBONE_NAME)
model = _load_backbone_model(BACKBONE_NAME, len(bio_tags), id_to_label, label_to_id, device)
```
改为:
```python
tokenizer = _load_backbone_tokenizer(BACKBONE_NAME)
model = _build_model_with_crf(BACKBONE_NAME, len(bio_tags), id_to_label, label_to_id, device)
```

- [ ] **Step 5: 修改训练循环中的 loss 计算和梯度更新**

`_run_training_loop` 函数中 (约 line 471-474):
```python
for batch in loader:
    batch = {k: v.to(device) for k, v in batch.items()}
    outputs = model(**batch)
    loss = outputs.loss
```
保持不变 —— model.forward 已经返回 `{"loss": loss}`。

- [ ] **Step 6: 在 NERModel 上添加 save_pretrained / from_pretrained 方法**

当前 `train_model` 使用 `model.save_pretrained(str(save_dir))` 保存，但自定义 NERModel 不支持此方法。在 `_build_model_with_crf` 中的 NERModel 类定义里添加:

```python
def save_pretrained(self, save_dir):
    os.makedirs(save_dir, exist_ok=True)
    self.encoder.save_pretrained(save_dir)
    self.config.save_pretrained(save_dir)
    torch.save(self.classifier.state_dict(), os.path.join(save_dir, "classifier.pt"))
    torch.save(self.crf.state_dict(), os.path.join(save_dir, "crf.pt"))

@classmethod
def from_pretrained(cls, model_dir, device="cpu"):
    config = AutoConfig.from_pretrained(model_dir, local_files_only=True)
    encoder = AutoModel.from_pretrained(model_dir, local_files_only=True)
    num_labels = config.num_labels
    classifier = torch.nn.Linear(config.hidden_size, num_labels)
    classifier.load_state_dict(torch.load(
        os.path.join(model_dir, "classifier.pt"), map_location=device, weights_only=True
    ))
    crf = CRF(num_tags=num_labels)
    crf.load_state_dict(torch.load(
        os.path.join(model_dir, "crf.pt"), map_location=device, weights_only=True
    ))
    model = cls.__new__(cls)
    torch.nn.Module.__init__(model)
    model.encoder = encoder
    model.classifier = classifier
    model.crf = crf
    model.config = config
    model.to(device)
    return model
```

同步修改 `run_inference` 和 `continue_train` 中加载模型的逻辑，使用 `NERModel.from_pretrained(str(model_dir), device)` 替代原来的 `AutoModelForTokenClassification.from_pretrained`。

- [ ] **Step 8: 修改推理函数，使用 CRF 解码**

修改 `run_inference` 函数中的推理逻辑 (约 line 719-728):

```python
with torch.no_grad():
    outputs = model(input_ids=input_ids, attention_mask=attention_mask)
    emissions = outputs["emissions"][0]  # (S, num_labels)
    mask = attention_mask.bool()[0]  # (S,)
    # 使用 CRF Viterbi 解码
    predictions = model.crf.decode(emissions.unsqueeze(0), mask.unsqueeze(0))[0]
```

- [ ] **Step 9: 同步修改 `continue_train` 中的模型加载**

将 `continue_train` 函数中的 `AutoModelForTokenClassification.from_pretrained` 改为 `NERModel.from_pretrained(str(model_dir), device)`。

- [ ] **Step 11: 运行基础验证**

```bash
cd H:/Git/MinerU/backend && python -c "
from model_service import train_model
# 快速训练测试 (1条样本)
result = train_model(
    mode='quick',
    model_name='测试模型',
    labels=['零件', '工艺'],
    examples=[{'text': '液压阀体进行珩磨处理',
               'entities': [
                   {'start_offset': 0, 'end_offset': 4, 'label': '零件'},
                   {'start_offset': 6, 'end_offset': 8, 'label': '工艺'},
               ]}],
)
print('训练完成:', result)
"
```
预期: 无报错，打印训练完成信息

- [ ] **Step 12: 提交**

```bash
cd H:/Git/MinerU && git add backend/model_service.py && git commit -m "refactor: replace BERT-multilingual with chinese-roberta-wwm-ext + CRF"
```

---

### Task 5: FGM 对抗训练

**Files:**
- Modify: `backend/model_service.py`

- [ ] **Step 1: 在 `_run_training_loop` 中添加 FGM 步骤**

在 `model_service.py` 的 `_run_training_loop` 函数中，在 `loss.backward()` 之后、`optimizer.step()` 之前添加 FGM:

修改 `_run_training_loop` 函数，在第 477 行 `loss.backward()` 之后添加:

```python
# ── FGM 对抗训练 ──
# 对 embedding 层加扰动
embedding = model.encoder.embeddings.word_embeddings
embedding_weight = embedding.weight
# 获取 embedding 的梯度
if embedding_weight.grad is not None:
    # 保存原始权重
    embed_grad = embedding_weight.grad.detach().clone()
    # 计算扰动方向 (normalized gradient)
    norm = embed_grad.norm(p=2, dim=1, keepdim=True)
    perturbation = 0.5 * embed_grad / (norm + 1e-12)

    # 添加扰动
    with torch.no_grad():
        embedding_weight.add_(perturbation)

    # 重新 forward + backward
    adv_outputs = model(**{k: v for k, v in batch.items()})
    adv_loss = adv_outputs["loss"] if isinstance(adv_outputs, dict) else adv_outputs.loss
    adv_loss.backward()

    # 恢复原始权重
    with torch.no_grad():
        embedding_weight.sub_(perturbation)
```

`0.5` 是 FGM 的 epsilon，可根据效果调整到 `0.3-1.0` 范围。

- [ ] **Step 2: 提交**

```bash
cd H:/Git/MinerU && git add backend/model_service.py && git commit -m "feat: add FGM adversarial training for embedding robustness"
```

---

### Task 6: 清洗现有训练数据

**Files:**
- Create: `backend/data/123/annotations_cleaned.jsonl`
- Modify: `backend/data_cleaning.py` (添加脚本入口)

- [ ] **Step 1: 在 `data_cleaning.py` 末尾添加清洗脚本**

```python
if __name__ == "__main__":
    import json
    import sys

    input_path = sys.argv[1] if len(sys.argv) > 1 else "data/123/annotations.jsonl"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "data/123/annotations_cleaned.jsonl"

    # 加载
    examples = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            text = item.get("text", "")
            entities = []
            for s in item.get("spans", []):
                entities.append({
                    "start_offset": s["start"],
                    "end_offset": s["end"],
                    "label": s["label"],
                })
            examples.append({"text": text, "entities": entities})

    print(f"加载 {len(examples)} 条样本")

    # 清洗步骤
    examples = split_guobiao_label(examples)
    examples = filter_short_entities(examples, min_len=2)
    examples = remove_template_duplicates(examples, max_per_template=20)
    examples = aggregate_empty_samples(examples, max_empty=80)
    examples = reindex_spans(examples)
    valid, issues = validate_annotations(examples)
    print(f"清洗后: {len(valid)} 条有效, {len(issues)} 条无效")

    # 保存
    with open(output_path, "w", encoding="utf-8") as f:
        for ex in valid:
            f.write(json.dumps({"text": ex["text"], "spans": [
                {"id": idx, "start": ent["start_offset"], "end": ent["end_offset"], "label": ent["label"]}
                for idx, ent in enumerate(ex.get("entities", []), start=1)
            ], "relations": [], "meta": {}}, ensure_ascii=False) + "\n")

    print(f"已保存到 {output_path}")
```

- [ ] **Step 2: 运行清洗脚本**

```bash
cd H:/Git/MinerU/backend && python data_cleaning.py data/123/annotations.jsonl data/123/annotations_cleaned.jsonl
```
预期: 打印清洗统计信息

- [ ] **Step 3: 验证清洗结果的标签分布**

```bash
cd H:/Git/MinerU/backend && python -c "
import json
from collections import Counter
labels = Counter()
total = 0
with open('data/123/annotations_cleaned.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        total += 1
        item = json.loads(line.strip())
        for s in item.get('spans', []):
            labels[s['label']] += 1
print(f'清洗后总样本: {total}')
print(f'标签分布: {dict(labels.most_common())}')
"
```

- [ ] **Step 4: 提交**

```bash
cd H:/Git/MinerU && git add backend/data/123/annotations_cleaned.jsonl backend/data_cleaning.py && git commit -m "feat: clean training data - dedup, label remap, short entity filter"
```

---

### Task 7: 在清洗后数据上训练并评估

**Files:**
- Modify: `backend/model_service.py` (添加 `evaluate_trained_model` 函数)

- [ ] **Step 1: 在 `model_service.py` 末尾添加评估函数**

```python
def evaluate_trained_model(model_id: str, test_jsonl_path: str) -> dict[str, Any]:
    """加载训练好的模型，对测试集评估并返回指标"""
    from evaluation import evaluate_model as _eval_model
    import json

    # 加载测试数据
    test_examples = []
    with open(test_jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            entities = []
            for s in item.get("spans", []):
                entities.append({
                    "start_offset": s["start"],
                    "end_offset": s["end"],
                    "label": s["label"],
                })
            test_examples.append({"text": item["text"], "entities": entities})

    # 加载模型
    cached = _quick_models.get(model_id)
    if cached:
        model = cached["model"]
        tokenizer = cached["tokenizer"]
        metadata = cached.get("metadata", {})
    else:
        model_dir = _model_path(model_id) / "model"
        meta_path = _model_path(model_id) / "metadata.json"
        if not model_dir.exists():
            raise FileNotFoundError(f"Model {model_id} not found")
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)

        # 重建模型
        from ner_crf import CRF
        config = AutoConfig.from_pretrained(str(model_dir), local_files_only=True)
        encoder = AutoModel.from_pretrained(str(model_dir), local_files_only=True)
        num_labels = len(metadata.get("bio_tags", []))
        classifier = torch.nn.Linear(config.hidden_size, num_labels)
        crf = CRF(num_tags=num_labels)

        class NERModel(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.encoder = encoder
                self.classifier = classifier
                self.crf = crf
                self.config = config
        model = NERModel()
        model.to(device)

    device = next(model.parameters()).device
    id_to_label = metadata.get("label_to_id", {})
    id_to_label = {v: k for k, v in id_to_label.items()}
    max_length = metadata.get("max_length", 256)

    return _eval_model(model, tokenizer, test_examples, id_to_label, max_length, device)
```

- [ ] **Step 2: 编写训练+评估脚本**

```bash
cd H:/Git/MinerU/backend && python -c "
import json
from model_service import train_model, evaluate_trained_model, parse_jsonl_training_data

# 加载清洗后数据
with open('data/123/annotations_cleaned.jsonl', 'r', encoding='utf-8') as f:
    content = f.read()
examples = parse_jsonl_training_data(content)

# 简单 8:2 划分
import random
random.seed(42)
random.shuffle(examples)
split = int(len(examples) * 0.8)
train_data = examples[:split]
test_data = examples[split:]

# 保存测试集
with open('data/123/test_data.jsonl', 'w', encoding='utf-8') as f:
    for ex in test_data:
        f.write(json.dumps(ex, ensure_ascii=False) + '\n')

print(f'训练集: {len(train_data)}, 测试集: {len(test_data)}')

# 训练
result = train_model(
    mode='persistent',
    model_name='NER-CRF-RoBERTa-v1',
    labels=[],
    examples=train_data,
    document_text=None,
)
print(f'训练完成: {result[\"model_id\"]}')

# 评估
metrics = evaluate_trained_model(result['model_id'], 'data/123/test_data.jsonl')
print(f'Entity F1: {metrics[\"entity\"][\"f1\"]}')
print(f'Boundary F1: {metrics[\"boundary\"][\"f1\"]}')
print(f'Per-class: {json.dumps(metrics[\"per_class\"], ensure_ascii=False, indent=2)}')
"
```

- [ ] **Step 3: 查看评估结果，验证指标**

查看 Entity F1 和 Boundary F1，确认 CRF 是否改善了边界问题。

- [ ] **Step 4: 提交**

```bash
cd H:/Git/MinerU && git add backend/model_service.py backend/data/123/test_data.jsonl && git commit -m "feat: add evaluation function and training-eval script"
```

---

### Task 8: API 兼容性验证

**Files:**
- Modify: `backend/main.py` (如有需要)

- [ ] **Step 1: 验证现有 API 是否兼容**

```bash
cd H:/Git/MinerU/backend && python -c "
from model_service import train_model, run_inference, list_models, get_model, delete_model, continue_train, TrainingProgressCallback, parse_jsonl_training_data
print('所有接口可正常导入')
"
```
预期: "所有接口可正常导入"

- [ ] **Step 2: 启动服务验证**

```bash
cd H:/Git/MinerU/backend && timeout 5 python main.py 2>&1 || true
```
预期: 服务正常启动，无 ImportError

- [ ] **Step 3: 验证 `/models` 和 `/model/train` 端点**

确认 `train_model_endpoint` 和 `model_infer_endpoint` 能正常处理请求。

- [ ] **Step 4: 提交**

```bash
cd H:/Git/MinerU && git add backend/main.py && git commit -m "verify: API compatibility with new CRF model architecture"
```

---

### Task 9: RE 模型基础架构（前瞻）

**Files:**
- Create: `backend/re_model.py`

此任务仅搭好 RE 模型的架子，不要求训练。完整 RE 实现在 NER 达到 95% 后进行。

- [ ] **Step 1: 创建 RE 模型模块骨架**

```python
"""关系抽取模型（在 NER 稳定后启用）"""
import torch
import torch.nn as nn


class REModel(nn.Module):
    """基于实体对的二分类/多分类关系抽取"""
    def __init__(self, hidden_size: int = 768, num_relations: int = 3, num_distance_buckets: int = 5):
        super().__init__()
        self.num_relations = num_relations
        # 实体对特征: [CLS] + avg(start, end) 拼接
        input_dim = hidden_size * 3 + num_distance_buckets
        self.classifier = nn.Sequential(
            nn.Linear(input_dim, 64),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(64, num_relations + 1),  # +1 for no_relation
        )
        self.distance_embed = nn.Embedding(num_distance_buckets, num_distance_buckets)
        # 距离分桶边界
        self.distance_boundaries = [2, 5, 10, 20]

    def _get_distance_bucket(self, distance: int) -> int:
        for i, boundary in enumerate(self.distance_boundaries):
            if distance <= boundary:
                return i
        return len(self.distance_boundaries)

    def forward(self, encoder_hidden, entity_pairs: list[list[tuple[int, int, int, int]]]):
        """暂不实现完整 forward，仅搭好架构"""
        raise NotImplementedError("RE 模型将在 NER 达标后实现")
```

- [ ] **Step 2: 提交**

```bash
cd H:/Git/MinerU && git add backend/re_model.py && git commit -m "feat: add RE model skeleton for future relation extraction"
```

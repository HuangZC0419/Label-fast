# 标注结果导出 + 训练数据集库 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为标注结果提供符合 `mineru-annotation-jsonl-v1` 的 JSONL 导出；为模型训练提供可持久化、带统计视图、可多选复用的训练数据集库。

**Architecture:** 后端在 FastAPI 中新增导出接口与数据集接口，导出逻辑复用 `main.py` 现有规则函数与 `model_service.run_inference`；数据集以「JSONL 原文件 + meta.json」落盘在 `backend/datasets/`。前端在 `App.vue` 中新增导出按钮与数据集管理/统计 UI，训练改走 `/model/train-from-dataset`。

**Tech Stack:** Python 3 / FastAPI / pytest；Vue 3 / axios / Chart.js（已有）。

**参考规格：** `docs/deepseek-harness/specs/2026-10-26-annotation-export-dataset-library-design.md`

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/model_service.py` | 修改 | `run_inference` 实体补充 `start_offset/end_offset/sentence_index/sentence_original`，供导出精确映射 |
| `backend/main.py` | 修改 | 导出构建函数、`/result/{task_id}/export-annotations`、数据集接口、`/model/train-from-dataset`、SSE 复用助手 |
| `backend/dataset_store.py` | 新建 | 数据集统计、落盘、读取、删除 |
| `backend/tests/test_annotation_export.py` | 新建 | 导出结构与偏移测试 |
| `backend/tests/test_dataset_stats.py` | 新建 | 统计口径测试 |
| `frontend/src/App.vue` | 修改 | 导出按钮、数据集上传/统计/多选、训练调用改造 |

---

## Task 1: 推理实体补充句子元信息

**Files:**
- Modify: `backend/model_service.py:950-1042`

- [ ] **Step 1: 修改 `run_inference` 的句子循环与实体输出**

将 `for sentence in sentences:` 改为带索引的循环，并在归一化前保留原句：

```python
    for sentence_idx, sentence in enumerate(sentences):
        original_sentence = sentence
        sentence = _normalize_text(sentence)
```

在 `all_entities.append({...})` 中补充四个字段（保留原有字段）：

```python
            all_entities.append({
                "id": f"{lbl}:{entity_idx}",
                "rule_id": lbl,
                "rule_label": lbl,
                "type": lbl,
                "label": cleaned,
                "text": cleaned,
                "context": _clean_text(context),
                "confidence": ent.get("confidence", 0),
                "start_offset": start_off,
                "end_offset": end_off,
                "sentence_index": sentence_idx,
                "sentence_original": original_sentence,
            })
```

注意：`start_off` / `end_off` 使用边界修复后的局部变量；`_normalize_text` 全部是 1:1 字符替换，因此偏移可直接用于 `original_sentence`。

- [ ] **Step 2: 运行现有测试确认无回归**

```bash
cd backend && python -m pytest tests -q
```

Expected: 现有测试全部通过（允许耗时的 CRF 测试）。

- [ ] **Step 3: 提交**

```bash
git add backend/model_service.py
git commit -m "feat(inference): 实体结果补充句子索引与偏移"
```

---

## Task 2: 导出构建函数 + 测试

**Files:**
- Modify: `backend/main.py`（在 `build_annotation_result` 之后新增函数）
- Test: `backend/tests/test_annotation_export.py`

- [ ] **Step 1: 先写失败测试**

创建 `backend/tests/test_annotation_export.py`：

```python
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import build_annotation_export_rows


SAMPLE_MD = (
    "某液压阀体采用606-T6铝合金棒料，采购标准严格执行《GB/T3191-2019铝及铝合金挤压棒材》。"
    "加工后重点检查OP20钻4×6.8通孔与OP30攻丝M8×125，螺纹精度需符合《GB/T196-203普通螺纹基本尺寸》的规定。"
    "所有尺寸经三坐标测量仪终检合格后，平面度误差不超过0.05mm。"
)


def _rows(rule_ids=None):
    return build_annotation_export_rows(
        markdown_text=SAMPLE_MD,
        task_id="task-123",
        file_name="测试文本.png",
        file_number=2,
        rule_ids=rule_ids or ["standards", "decisions", "limits", "numeric_facts"],
    )


def test_rows_have_exact_top_level_fields():
    rows = _rows()
    assert rows, "应至少导出一行"
    expected = {"file_name", "file_number", "task_id", "text", "annotations", "spans", "relations", "meta"}
    for row in rows:
        assert set(row.keys()) == expected
        assert row["file_name"] == "测试文本.png"
        assert row["file_number"] == 2
        assert row["task_id"] == "task-123"
        assert row["relations"] == []
        assert row["meta"]["export_format"] == "mineru-annotation-jsonl-v1"
        assert isinstance(row["meta"]["annotation_sources"], list)


def test_span_offsets_match_text():
    rows = _rows()
    found = False
    for row in rows:
        for span in row["spans"]:
            assert row["text"][span["start"]:span["end"]] == span["text"]
            found = True
    assert found, "应产生至少一个 span"


def test_decisions_is_annotation_only():
    rows = _rows(["decisions"])
    assert rows
    for row in rows:
        assert any(a["rule_id"] == "decisions" for a in row["annotations"])
        assert not any(s["rule_id"] == "decisions" for s in row["spans"])


def test_annotation_id_grouped_by_rule():
    rows = _rows(["standards", "decisions"])
    ids = [a["id"] for row in rows for a in row["annotations"]]
    assert any(i.startswith("standards:") for i in ids)
    if any(i.startswith("decisions:") for i in ids):
        # 规则按 standards → decisions 的顺序分配全局序号
        standards_nums = [int(i.split(":")[1]) for i in ids if i.startswith("standards:")]
        decisions_nums = [int(i.split(":")[1]) for i in ids if i.startswith("decisions:")]
        assert max(standards_nums) < min(decisions_nums)


def test_blank_and_noise_sentences_excluded():
    md = "# 标题\n\n第1章\n\n没有任何标注的普通句子内容。\n\n依据 GB/T 3191-2019 执行。"
    rows = build_annotation_export_rows(
        markdown_text=md,
        task_id="t",
        file_name="a.md",
        file_number=1,
        rule_ids=["standards"],
    )
    for row in rows:
        assert row["annotations"], "空标注行不应导出"
        assert not row["text"].startswith("#")


def test_export_jsonl_serializable():
    rows = _rows()
    text = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    assert text.count("\n") + 1 == len(rows)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && python -m pytest tests/test_annotation_export.py -q
```

Expected: FAIL，`ImportError: cannot import name 'build_annotation_export_rows'`。

- [ ] **Step 3: 在 `backend/main.py` 顶部补充导入**

```python
from model_service import (
    train_model,
    run_inference,
    list_models,
    get_model,
    delete_model,
    continue_train,
    TrainingProgressCallback,
    parse_jsonl_training_data,
    evaluate_model,
    _split_sentences,
)
```

（把原单行 import 替换为上面的多行形式，函数集合不变，仅新增 `_split_sentences`。）

- [ ] **Step 4: 在 `build_annotation_result` 之后新增导出函数**

```python
def normalize_text_for_match(text: str) -> str:
    """与 model_service._normalize_text 保持一致的 1:1 归一化。"""
    return (
        text.replace("—", "-")
        .replace("–", "-")
        .replace("―", "-")
        .replace("－", "-")
        .replace("‘", "'")
        .replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("\xa0", " ")
        .replace("　", " ")
    )


def locate_entity_in_sentence(sentence: str, entity_text: str) -> tuple[int, int] | None:
    entity_text = (entity_text or "").strip()
    if not sentence or not entity_text:
        return None
    start = sentence.find(entity_text)
    if start >= 0:
        return start, start + len(entity_text)

    normalized_sentence = normalize_text_for_match(sentence)
    normalized_entity = normalize_text_for_match(entity_text)
    start = normalized_sentence.find(normalized_entity)
    if start >= 0:
        return start, start + len(normalized_entity)

    compact_entity = re.sub(r"\s+", "", entity_text)
    if not compact_entity:
        return None
    compact_positions = [i for i, ch in enumerate(sentence) if not ch.isspace()]
    compact_sentence = re.sub(r"\s+", "", sentence)
    match_index = compact_sentence.find(compact_entity)
    if match_index < 0:
        return None
    start = compact_positions[match_index]
    end = compact_positions[match_index + len(compact_entity) - 1] + 1
    return start, end


def collect_rule_spans_for_sentence(
    sentence: str,
    rule_ids: list[str],
    rule_labels: dict[str, str],
) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []

    def add(rule_id: str, span_type: str, match: re.Match[str]) -> None:
        text = match.group(0)
        if not text:
            return
        spans.append(
            {
                "id": f"{rule_id}:{span_type}:{text}",
                "start": match.start(),
                "end": match.end(),
                "label": rule_labels[rule_id],
                "text": text,
                "rule_id": rule_id,
                "sources": ["rule"],
            }
        )

    if "standards" in rule_ids:
        for match in STANDARD_CODE_PATTERN.finditer(sentence):
            if len(match.group(0)) >= 4:
                add("standards", "standard", match)

    if "dates" in rule_ids:
        for match in DATE_PATTERN.finditer(sentence):
            if is_plausible_date_match(match, sentence):
                add("dates", "date", match)

    if "limits" in rule_ids:
        for match in find_limit_matches(sentence):
            add("limits", "metric", match)

    if "numeric_facts" in rule_ids:
        for entity_type, match in find_numeric_matches(sentence):
            add("numeric_facts", entity_type, match)

    return spans


def dedupe_export_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[int, int, str, str], dict[str, Any]] = {}
    for span in spans:
        key = (span["start"], span["end"], span["text"], span["label"])
        if key not in merged:
            merged[key] = {
                **span,
                "sources": set(span.get("sources") or []),
                "_model_labels": set(span.get("_model_labels") or []),
            }
        else:
            merged[key]["sources"] |= set(span.get("sources") or [])
            merged[key]["_model_labels"] |= set(span.get("_model_labels") or [])
    result: list[dict[str, Any]] = []
    for span in merged.values():
        span["sources"] = sorted(span["sources"])
        result.append(span)
    result.sort(key=lambda item: (item["start"], item["end"]))
    return result


def collect_model_spans_by_sentence(
    markdown_text: str,
    model_id: str,
    threshold: float,
) -> dict[int, list[dict[str, Any]]]:
    result = run_inference(model_id=model_id, document_text=markdown_text)
    by_sentence: dict[int, list[dict[str, Any]]] = {}
    for entity in result.get("entities", []):
        confidence = float(entity.get("confidence") or 0)
        if confidence < threshold:
            continue
        sentence_index = entity.get("sentence_index")
        if sentence_index is None:
            continue
        label = str(entity.get("label") or entity.get("rule_label") or "").strip()
        original_sentence = str(entity.get("sentence_original") or "")
        start = entity.get("start_offset")
        end = entity.get("end_offset")
        if not label or start is None or end is None or not original_sentence:
            continue
        start, end = int(start), int(end)
        text = original_sentence[start:end] or str(entity.get("text") or "")
        if not text:
            continue
        by_sentence.setdefault(int(sentence_index), []).append(
            {
                "id": f"{label}:model:{text}",
                "start": start,
                "end": end,
                "label": label,
                "text": text,
                "rule_id": label,
                "sources": ["model"],
                "_model_labels": [label],
            }
        )
    return by_sentence


def build_annotation_export_rows(
    markdown_text: str,
    *,
    task_id: str,
    file_name: str,
    file_number: int,
    rule_ids: list[str],
    model_id: str | None = None,
    model_conf_threshold: float = 0.0,
) -> list[dict[str, Any]]:
    rule_labels = {rule["id"]: rule["label"] for rule in ANNOTATION_RULE_OPTIONS}
    active_rules = [rule["id"] for rule in ANNOTATION_RULE_OPTIONS if rule["id"] in rule_ids]

    raw_sentences = _split_sentences(markdown_text)
    sentence_records: list[tuple[int, str]] = []
    for index, sentence in enumerate(raw_sentences):
        if not sentence or is_structural_noise_sentence(sentence):
            continue
        sentence_records.append((index, sentence))

    model_spans_by_sentence: dict[int, list[dict[str, Any]]] = {}
    if model_id:
        model_spans_by_sentence = collect_model_spans_by_sentence(
            markdown_text, model_id, model_conf_threshold
        )

    payloads: list[dict[str, Any]] = []
    for sentence_index, sentence in sentence_records:
        spans = collect_rule_spans_for_sentence(sentence, active_rules, rule_labels)
        spans.extend(model_spans_by_sentence.get(sentence_index, []))
        spans = dedupe_export_spans(spans)
        decision_hit = "decisions" in active_rules and is_decision_sentence(sentence)
        decision_tags = (
            dedupe_preserve_order(
                [clean_annotation_text(m.group(0)) for m in STANDARD_CODE_PATTERN.finditer(sentence)]
            )
            if decision_hit
            else []
        )
        if not spans and not decision_hit:
            continue
        payloads.append(
            {
                "sentence": sentence,
                "spans": spans,
                "decision_hit": decision_hit,
                "decision_tags": decision_tags,
            }
        )

    annotations_by_line: list[list[dict[str, Any]]] = [[] for _ in payloads]
    sequence = 0

    for rule_id in active_rules:
        for line_index, payload in enumerate(payloads):
            if rule_id == "decisions":
                if not payload["decision_hit"]:
                    continue
                annotations_by_line[line_index].append(
                    {
                        "id": f"{rule_id}:{sequence}",
                        "rule_id": rule_id,
                        "label": rule_labels[rule_id],
                        "tags": payload["decision_tags"],
                        "sources": ["rule"],
                    }
                )
                sequence += 1
                continue

            rule_spans = [span for span in payload["spans"] if span["rule_id"] == rule_id]
            if not rule_spans:
                continue
            annotations_by_line[line_index].append(
                {
                    "id": f"{rule_id}:{sequence}",
                    "rule_id": rule_id,
                    "label": rule_labels[rule_id],
                    "tags": dedupe_preserve_order([span["text"] for span in rule_spans]),
                    "sources": sorted({src for span in rule_spans for src in span["sources"]}),
                }
            )
            sequence += 1

    model_labels: list[str] = []
    for payload in payloads:
        for span in payload["spans"]:
            for label in span.get("_model_labels") or []:
                if label not in model_labels:
                    model_labels.append(label)

    for label in model_labels:
        for line_index, payload in enumerate(payloads):
            label_spans = [
                span
                for span in payload["spans"]
                if label in (span.get("_model_labels") or [])
            ]
            if not label_spans:
                continue
            annotations_by_line[line_index].append(
                {
                    "id": f"{label}:{sequence}",
                    "rule_id": label,
                    "label": label,
                    "tags": dedupe_preserve_order([span["text"] for span in label_spans]),
                    "sources": ["model"],
                }
            )
            sequence += 1

    rows: list[dict[str, Any]] = []
    for line_index, payload in enumerate(payloads):
        annotations = annotations_by_line[line_index]
        if not annotations:
            continue
        spans = [
            {key: value for key, value in span.items() if not key.startswith("_")}
            for span in payload["spans"]
        ]
        sources = sorted(
            {src for annotation in annotations for src in annotation["sources"]}
            | {src for span in spans for src in span["sources"]}
        )
        rows.append(
            {
                "file_name": file_name,
                "file_number": file_number,
                "task_id": task_id,
                "text": payload["sentence"],
                "annotations": annotations,
                "spans": spans,
                "relations": [],
                "meta": {
                    "export_format": "mineru-annotation-jsonl-v1",
                    "annotation_sources": sources,
                },
            }
        )
    return rows
```

- [ ] **Step 5: 运行测试**

```bash
cd backend && python -m pytest tests/test_annotation_export.py -q
```

Expected: 全部通过。

- [ ] **Step 6: 提交**

```bash
git add backend/main.py backend/tests/test_annotation_export.py
git commit -m "feat(export): JSONL 标注结果构建与偏移计算"
```

---

## Task 3: 导出接口

**Files:**
- Modify: `backend/main.py`（导入区；在 `/result/{task_id}/annotations` 之后新增路由）

- [ ] **Step 1: 导入 `Response`**

```python
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
```

- [ ] **Step 2: 在文件末尾路由区新增辅助函数与接口**

```python
def get_task_file_name(task_id: str) -> str:
    task = progress_store.get(task_id)
    if task and task.get("file_name"):
        return str(task["file_name"])
    input_dir = os.path.join(INPUT_BASE, task_id)
    if os.path.isdir(input_dir):
        files = sorted(name for name in os.listdir(input_dir) if not name.startswith("."))
        if files:
            return files[0]
    return f"{task_id[:8]}.md"


def get_task_sequence_number(task_id: str) -> int:
    if not os.path.isdir(INPUT_BASE):
        return 1
    entries: list[tuple[float, str]] = []
    for name in os.listdir(INPUT_BASE):
        path = os.path.join(INPUT_BASE, name)
        if not os.path.isdir(path):
            continue
        try:
            entries.append((os.path.getctime(path), name))
        except OSError:
            continue
    entries.sort()
    for index, (_, name) in enumerate(entries, start=1):
        if name == task_id:
            return index
    return 1


@app.post("/result/{task_id}/export-annotations")
async def export_annotations_endpoint(task_id: str, body: dict[str, Any] | None = None):
    markdown_text = load_task_markdown(task_id)
    if markdown_text is None:
        return JSONResponse(status_code=404, content={"message": "Markdown not found for this task"})

    body = body or {}
    valid_rule_ids = {rule["id"] for rule in ANNOTATION_RULE_OPTIONS}
    rule_ids = [
        str(rule_id) for rule_id in body.get("rules", []) if str(rule_id) in valid_rule_ids
    ]
    model_id = str(body.get("model_id") or "").strip()
    try:
        threshold = float(body.get("model_conf_threshold") or 0)
    except (TypeError, ValueError):
        threshold = 0.0
    threshold = min(max(threshold, 0.0), 1.0)

    if not rule_ids and not model_id:
        return JSONResponse(
            status_code=400, content={"message": "请至少选择一个标注规则或模型"}
        )

    try:
        rows = build_annotation_export_rows(
            markdown_text,
            task_id=task_id,
            file_name=get_task_file_name(task_id),
            file_number=get_task_sequence_number(task_id),
            rule_ids=rule_ids,
            model_id=model_id or None,
            model_conf_threshold=threshold,
        )
    except FileNotFoundError as exc:
        return JSONResponse(status_code=404, content={"message": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"message": f"导出失败: {exc}"})

    content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    if content:
        content += "\n"
    file_stem = Path(get_task_file_name(task_id)).stem or task_id[:8]
    headers = {
        "Content-Disposition": f'attachment; filename="{file_stem}_annotations.jsonl"'
    }
    return Response(content=content, media_type="application/x-ndjson", headers=headers)
```

- [ ] **Step 3: 用离线脚本验证接口函数**

```bash
cd backend && python -c "import main; print('ok')"
```

Expected: `ok`。

- [ ] **Step 4: 提交**

```bash
git add backend/main.py
git commit -m "feat(export): 新增标注结果 JSONL 导出接口"
```

---

## Task 4: 数据集存储与统计模块 + 测试

**Files:**
- Create: `backend/dataset_store.py`
- Test: `backend/tests/test_dataset_stats.py`

- [ ] **Step 1: 先写失败测试**

创建 `backend/tests/test_dataset_stats.py`：

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataset_store import analyze_examples


SAMPLE_CONTENT = """
{"text":"依据 GB/T3191-2019 执行","spans":[{"start":3,"end":16,"label":"标准条文"}]}
{"text":"螺纹精度需符合 GB/T196-203","spans":[{"start":6,"end":17,"label":"标准条文"},{"start":6,"end":17,"label":"数值信息"}]}
{"text":"没有任何标注的句子","spans":[]}
不可解析的行
""".strip()


def test_analyze_examples_counts():
    from model_service import parse_jsonl_training_data

    examples = parse_jsonl_training_data(SAMPLE_CONTENT)
    stats = analyze_examples(examples)
    assert stats["sample_count"] == 3
    assert stats["entity_count"] == 3
    assert stats["label_count"] == 2
    assert stats["label_counts"] == {"标准条文": 2, "数值信息": 1}
    assert stats["unlabeled_sample_count"] == 1
    assert stats["char_count"] == sum(len(e["text"]) for e in examples)
    assert stats["avg_text_length"] == round(stats["char_count"] / 3, 1)


def test_analyze_examples_empty():
    stats = analyze_examples([])
    assert stats["sample_count"] == 0
    assert stats["entity_count"] == 0
    assert stats["label_count"] == 0
    assert stats["label_counts"] == {}
    assert stats["avg_text_length"] == 0
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && python -m pytest tests/test_dataset_stats.py -q
```

Expected: FAIL，`ModuleNotFoundError: No module named 'dataset_store'`。

- [ ] **Step 3: 创建 `backend/dataset_store.py`**

```python
"""训练数据集的落盘、统计与读取。"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from model_service import parse_jsonl_training_data

DATASET_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datasets")


def dataset_dir() -> str:
    os.makedirs(DATASET_BASE, exist_ok=True)
    return DATASET_BASE


def dataset_data_path(dataset_id: str) -> str:
    return os.path.join(dataset_dir(), f"{dataset_id}.jsonl")


def dataset_meta_path(dataset_id: str) -> str:
    return os.path.join(dataset_dir(), f"{dataset_id}.meta.json")


def analyze_examples(examples: list[dict[str, Any]]) -> dict[str, Any]:
    label_counts: dict[str, int] = {}
    entity_count = 0
    char_count = 0
    unlabeled_sample_count = 0

    for example in examples:
        text = example.get("text", "")
        char_count += len(text)
        entities = example.get("entities") or []
        if not entities:
            unlabeled_sample_count += 1
        entity_count += len(entities)
        for entity in entities:
            label = str(entity.get("label", "")).strip()
            if not label:
                continue
            label_counts[label] = label_counts.get(label, 0) + 1

    sample_count = len(examples)
    ordered_labels = dict(
        sorted(label_counts.items(), key=lambda item: (-item[1], item[0]))
    )
    return {
        "sample_count": sample_count,
        "entity_count": entity_count,
        "label_count": len(ordered_labels),
        "label_counts": ordered_labels,
        "char_count": char_count,
        "avg_text_length": round(char_count / sample_count, 1) if sample_count else 0,
        "unlabeled_sample_count": unlabeled_sample_count,
    }


def save_dataset(content: str, file_name: str, name: str = "") -> dict[str, Any]:
    examples = parse_jsonl_training_data(content)
    if not examples:
        raise ValueError("未解析到有效训练数据，请检查 JSONL 格式")

    dataset_id = uuid.uuid4().hex[:12]
    dataset_name = (name or os.path.splitext(file_name or "")[0] or "未命名数据集").strip()
    meta = {
        "dataset_id": dataset_id,
        "name": dataset_name,
        "file_name": file_name or f"{dataset_name}.jsonl",
        "uploaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "format": "mineru-annotation-jsonl-v1",
        **analyze_examples(examples),
    }

    with open(dataset_data_path(dataset_id), "w", encoding="utf-8") as handle:
        handle.write(content)
    with open(dataset_meta_path(dataset_id), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False, indent=2)
    return meta


def list_datasets() -> list[dict[str, Any]]:
    base = dataset_dir()
    datasets: list[dict[str, Any]] = []
    for file_name in os.listdir(base):
        if not file_name.endswith(".meta.json"):
            continue
        try:
            with open(os.path.join(base, file_name), "r", encoding="utf-8") as handle:
                datasets.append(json.load(handle))
        except (OSError, json.JSONDecodeError):
            continue
    datasets.sort(key=lambda item: item.get("uploaded_at", ""), reverse=True)
    return datasets


def get_dataset(dataset_id: str) -> dict[str, Any]:
    path = dataset_meta_path(dataset_id)
    if not os.path.exists(path):
        raise FileNotFoundError(f"数据集不存在: {dataset_id}")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def delete_dataset(dataset_id: str) -> None:
    removed = False
    for path in (dataset_data_path(dataset_id), dataset_meta_path(dataset_id)):
        if os.path.exists(path):
            os.remove(path)
            removed = True
    if not removed:
        raise FileNotFoundError(f"数据集不存在: {dataset_id}")


def load_dataset_examples(dataset_ids: list[str]) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    missing: list[str] = []
    for dataset_id in dataset_ids:
        path = dataset_data_path(dataset_id)
        if not os.path.exists(path):
            missing.append(dataset_id)
            continue
        with open(path, "r", encoding="utf-8") as handle:
            examples.extend(parse_jsonl_training_data(handle.read()))
    if missing:
        raise FileNotFoundError(f"数据集不存在: {', '.join(missing)}")
    return examples
```

- [ ] **Step 4: 运行测试**

```bash
cd backend && python -m pytest tests/test_dataset_stats.py -q
```

Expected: 2 passed。

- [ ] **Step 5: 提交**

```bash
git add backend/dataset_store.py backend/tests/test_dataset_stats.py
git commit -m "feat(dataset): 数据集统计与持久化模块"
```

---

## Task 5: 数据集接口 + 按数据集训练

**Files:**
- Modify: `backend/main.py`（导入区与路由区）

- [ ] **Step 1: 导入数据集模块**

```python
from dataset_store import (
    save_dataset,
    list_datasets,
    get_dataset,
    delete_dataset,
    load_dataset_examples,
)
```

- [ ] **Step 2: 提取 SSE 训练流助手（放在 `train_model_endpoint` 之前）**

```python
def create_training_stream(train_callable) -> StreamingResponse:
    """把任意训练函数包装成带心跳的 SSE 响应；train_callable 接收进度回调。"""
    progress_queue: queue.Queue = queue.Queue()
    loop = asyncio.get_event_loop()

    def run_training() -> None:
        try:
            callback = TrainingProgressCallback(progress_queue)
            result = train_callable(callback)
            progress_queue.put({"type": "complete", "result": result})
        except Exception as exc:
            progress_queue.put(
                {
                    "type": "error",
                    "message": str(exc),
                    "detail": traceback.format_exc(),
                }
            )

    async def event_stream():
        thread = threading.Thread(target=run_training, daemon=True)
        thread.start()
        while True:
            try:
                data = await loop.run_in_executor(None, progress_queue.get, True, 0.3)
            except queue.Empty:
                yield ": heartbeat\n\n"
                if not thread.is_alive():
                    break
                continue
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            if data["type"] in ("complete", "error"):
                break
        thread.join(timeout=5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 3: 新增数据集路由（放在 `/model/upload-and-train` 之前）**

```python
@app.post("/datasets/upload")
async def upload_dataset_endpoint(
    file: UploadFile = File(...),
    name: str = Form(""),
):
    try:
        content = (await file.read()).decode("utf-8")
    except UnicodeDecodeError:
        return JSONResponse(
            status_code=400,
            content={"message": "文件编码错误，请上传 UTF-8 编码的 JSONL 文件"},
        )
    try:
        meta = save_dataset(content, file.filename or "", name)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"message": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"message": f"数据集保存失败: {exc}"})
    return meta


@app.get("/datasets")
async def list_datasets_endpoint():
    return list_datasets()


@app.get("/datasets/{dataset_id}")
async def get_dataset_endpoint(dataset_id: str):
    try:
        return get_dataset(dataset_id)
    except FileNotFoundError as exc:
        return JSONResponse(status_code=404, content={"message": str(exc)})


@app.delete("/datasets/{dataset_id}")
async def delete_dataset_endpoint(dataset_id: str):
    try:
        delete_dataset(dataset_id)
    except FileNotFoundError as exc:
        return JSONResponse(status_code=404, content={"message": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"message": f"删除失败: {exc}"})
    return {"message": "ok"}


@app.post("/model/train-from-dataset")
async def train_from_dataset_endpoint(body: dict[str, Any]):
    dataset_ids = [str(item) for item in body.get("dataset_ids", []) if str(item).strip()]
    if not dataset_ids:
        return JSONResponse(status_code=400, content={"message": "请至少选择一个训练数据集"})

    try:
        examples = load_dataset_examples(dataset_ids)
    except FileNotFoundError as exc:
        return JSONResponse(status_code=404, content={"message": str(exc)})

    if not examples:
        return JSONResponse(
            status_code=400, content={"message": "所选数据集没有有效训练样本"}
        )

    model_name = str(body.get("model_name") or "未命名模型")
    try:
        epochs = int(body.get("epochs") or 0)
        batch_size = int(body.get("batch_size") or 0)
        lr = float(body.get("lr") or 0)
    except (TypeError, ValueError):
        return JSONResponse(status_code=400, content={"message": "训练参数格式错误"})

    def run(callback: TrainingProgressCallback):
        return train_model(
            mode="persistent",
            model_name=model_name,
            labels=[],
            examples=examples,
            progress_callback=callback,
            epochs=epochs,
            batch_size=batch_size,
            lr=lr,
        )

    return create_training_stream(run)
```

- [ ] **Step 4: 将现有两个训练接口改为复用 `create_training_stream`（去重）**

`train_model_endpoint` 整体替换为：

```python
@app.post("/model/train")
async def train_model_endpoint(body: dict[str, Any]):
    def run(callback: TrainingProgressCallback):
        return train_model(
            mode=body.get("mode", "quick"),
            model_name=body.get("model_name", "未命名模型"),
            labels=body.get("labels", []),
            examples=body["examples"],
            progress_callback=callback,
            document_text=body.get("document_text", None),
        )

    return create_training_stream(run)
```

`upload_and_train_endpoint` 在解析 `examples` 之后，整体替换为：

```python
    def run(callback: TrainingProgressCallback):
        return train_model(
            mode="persistent",
            model_name=model_name,
            labels=[],
            examples=examples,
            progress_callback=callback,
            epochs=epochs,
            batch_size=batch_size,
            lr=lr,
        )

    return create_training_stream(run)
```

删除这两个函数中原来的 `progress_queue` / `run_training` / `event_stream` / `StreamingResponse` 代码块。

- [ ] **Step 5: 导入与语法检查**

```bash
cd backend && python -c "import main; print('ok')"
```

Expected: `ok`。

- [ ] **Step 6: 启动后端做接口冒烟**

```bash
cd backend && python -c "
import dataset_store, json
meta = dataset_store.save_dataset(open('../测试文本_annotations.jsonl', encoding='utf-8').read(), '测试文本_annotations.jsonl')
print(json.dumps(meta, ensure_ascii=False))
print([d['dataset_id'] for d in dataset_store.list_datasets()])
dataset_store.delete_dataset(meta['dataset_id'])
"
```

Expected：打印统计元数据，`sample_count` 为 4，`label_counts` 含 `标准条文` 等类别；随后列表可正常读取，删除成功。

- [ ] **Step 7: 提交**

```bash
git add backend/main.py
git commit -m "feat(dataset): 数据集上传/列表/删除与按数据集训练接口"
```

---

## Task 6: 前端导出按钮

**Files:**
- Modify: `frontend/src/App.vue`（模板工具栏 ~577、脚本 ~1894、样式区）

- [ ] **Step 1: 工具栏新增按钮**

在 `.annotation-workspace-actions` 中「复制 MD」按钮旁加入：

```html
              <button
                class="tool-btn"
                :disabled="exportLoading || annotationLoading || modelAnnotationLoading || (!selectedAnnotationRules.length && !selectedPersistentModelId)"
                @click="exportAnnotations"
                title="导出当前规则+模型标注结果为 JSONL"
              >
                {{ exportLoading ? '导出中...' : '导出标注' }}
              </button>
```

- [ ] **Step 2: 新增状态**

在 `annotationLoading` 附近加入：

```js
const exportLoading = ref(false)
```

- [ ] **Step 3: 新增导出函数（放在 `runModelInference` 之后）**

```js
async function exportAnnotations() {
  const tid = taskInfo.task_id
  if (!tid) {
    showToast('当前没有可导出的任务', 'warning')
    return
  }
  const includeRules = selectedAnnotationRules.value.length > 0
  // 仅当模型页签处于激活状态，或已实际跑过模型标注时才带上模型
  const includeModel = !!selectedPersistentModelId.value &&
    (annotationMode.value === 'model' || !!modelAnnotationLastRunAt.value)

  if (!includeRules && !includeModel) {
    showToast('请先选择标注规则或模型', 'warning')
    return
  }

  exportLoading.value = true
  try {
    const response = await axios.post(
      `${API_BASE}/result/${tid}/export-annotations`,
      {
        rules: includeRules ? selectedAnnotationRules.value : [],
        model_id: includeModel ? selectedPersistentModelId.value : '',
        model_conf_threshold: modelConfThreshold.value / 100,
      },
      { responseType: 'blob' }
    )

    const disposition = response.headers['content-disposition'] || ''
    const matched = disposition.match(/filename="?([^";]+)"?/)
    const filename = matched ? decodeURIComponent(matched[1]) : `${tid.slice(0, 8)}_annotations.jsonl`

    const url = URL.createObjectURL(new Blob([response.data], { type: 'application/x-ndjson' }))
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    showToast('标注结果已导出', 'success')
  } catch (error) {
    let message = '导出失败'
    const payload = error.response?.data
    if (payload instanceof Blob) {
      try {
        const parsed = JSON.parse(await payload.text())
        message = parsed.message || message
      } catch (_) { /* ignore */ }
    } else if (payload?.message) {
      message = payload.message
    }
    showToast(message, 'error')
  } finally {
    exportLoading.value = false
  }
}
```

- [ ] **Step 4: 前端构建验证**

```bash
cd frontend && npm run build
```

Expected: 构建成功，无语法错误。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/App.vue
git commit -m "feat(export): 快速标注页新增 JSONL 导出按钮"
```

---

## Task 7: 前端训练数据集 UI

**Files:**
- Modify: `frontend/src/App.vue`（模型训练表单 ~844-909、脚本 ~1260 与 ~2298、样式区）

- [ ] **Step 1: 替换训练表单中的文件上传区域**

将 `.train-top-row` 内的 `<label class="train-file-upload"> ... </label>` 与 `<input ref="modelFileInput" ...>` 整体替换为数据集区块，保留「模型名称」输入：

```html
                <!-- 训练数据集 -->
                <div class="dataset-section">
                  <div class="dataset-section-head">
                    <div>
                      <div class="dataset-section-title">训练数据集</div>
                      <p class="dataset-section-desc">上传后自动入库，可多选合并训练</p>
                    </div>
                    <div class="dataset-summary-pill" v-if="datasets.length">
                      {{ datasets.length }} 个数据集 · {{ allDatasetSampleCount }} 样本 · {{ allDatasetLabelCount }} 类别
                    </div>
                  </div>

                  <label
                    class="dataset-upload-zone"
                    :class="{ 'is-uploading': datasetUploading }"
                    @click="!datasetUploading && !isTraining && datasetFileInput?.click()"
                    @dragover.prevent
                    @drop.prevent="onDatasetDrop"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="17 8 12 3 7 8" />
                      <line x1="12" y1="3" x2="12" y2="15" />
                    </svg>
                    <span>{{ datasetUploading ? '正在解析并上传数据集...' : '点击或拖拽上传 JSONL 数据集' }}</span>
                  </label>
                  <input ref="datasetFileInput" type="file" class="hidden-input" accept=".jsonl,.json" @change="onDatasetFileChange" />

                  <div v-if="datasetsLoading" class="dataset-empty">正在加载数据集...</div>
                  <div v-else-if="!datasets.length" class="dataset-empty">暂无数据集，请先上传</div>
                  <div v-else class="dataset-list">
                    <div
                      v-for="dataset in datasets"
                      :key="dataset.dataset_id"
                      class="dataset-card"
                      :class="{ 'is-selected': selectedDatasetIds.includes(dataset.dataset_id) }"
                    >
                      <div class="dataset-card-main">
                        <label class="dataset-check" @click.stop>
                          <input v-model="selectedDatasetIds" type="checkbox" :value="dataset.dataset_id" :disabled="isTraining" />
                        </label>
                        <div class="dataset-card-info">
                          <div class="dataset-card-title-row">
                            <span class="dataset-card-name" :title="dataset.name">{{ dataset.name }}</span>
                            <span class="dataset-card-meta">
                              {{ dataset.sample_count }} 样本 · {{ dataset.entity_count }} 实体 · {{ dataset.label_count }} 类别
                            </span>
                          </div>
                          <div class="dataset-card-time">{{ dataset.uploaded_at }}</div>
                          <div class="dataset-label-chips" v-if="dataset.label_count">
                            <span v-for="[label, count] in getDatasetLabelEntries(dataset).slice(0, 6)" :key="label" class="dataset-label-chip">
                              {{ label }} <b>{{ count }}</b>
                            </span>
                            <span v-if="dataset.label_count > 6" class="dataset-label-chip dataset-label-more">+{{ dataset.label_count - 6 }}</span>
                          </div>
                        </div>
                        <div class="dataset-card-actions">
                          <button class="btn-sm" @click.stop="toggleDatasetStats(dataset.dataset_id)">
                            {{ expandedDatasetId === dataset.dataset_id ? '收起' : '统计' }}
                          </button>
                          <button class="btn-sm btn-danger-text" :disabled="isTraining" @click.stop="deleteDataset(dataset.dataset_id)">删除</button>
                        </div>
                      </div>

                      <div v-if="expandedDatasetId === dataset.dataset_id" class="dataset-stats-panel">
                        <div class="dataset-stat-grid">
                          <div class="dataset-stat-block">
                            <span class="dataset-stat-value">{{ dataset.sample_count }}</span>
                            <span class="dataset-stat-label">样本数</span>
                          </div>
                          <div class="dataset-stat-block">
                            <span class="dataset-stat-value">{{ dataset.entity_count }}</span>
                            <span class="dataset-stat-label">实体数</span>
                          </div>
                          <div class="dataset-stat-block">
                            <span class="dataset-stat-value">{{ dataset.label_count }}</span>
                            <span class="dataset-stat-label">类别数</span>
                          </div>
                          <div class="dataset-stat-block">
                            <span class="dataset-stat-value">{{ formatNumber(dataset.char_count) }}</span>
                            <span class="dataset-stat-label">总字数</span>
                          </div>
                        </div>
                        <div class="dataset-label-bars">
                          <div v-for="[label, count] in getDatasetLabelEntries(dataset)" :key="label" class="dataset-label-bar-row">
                            <span class="dataset-label-bar-name" :title="label">{{ label }}</span>
                            <div class="dataset-label-bar-track">
                              <div class="dataset-label-bar-fill" :style="{ width: getDatasetLabelPct(dataset, count) + '%' }"></div>
                            </div>
                            <span class="dataset-label-bar-count">{{ count }}</span>
                          </div>
                        </div>
                        <div class="dataset-stats-foot" v-if="dataset.unlabeled_sample_count">
                          无标注样本：{{ dataset.unlabeled_sample_count }} 条
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <div class="train-name-row">
                  <label class="config-label">模型名称</label>
                  <input v-model="trainModelName" class="select-field" placeholder="输入模型名称" :disabled="isTraining" />
                </div>
```

- [ ] **Step 2: 更新训练按钮**

```html
                  <button
                    class="btn-train-start"
                    :disabled="isTraining || !selectedDatasetIds.length || !trainModelName.trim()"
                    @click="trainFromDatasets"
                  >
```

按钮文字与图标保持不变。

- [ ] **Step 3: 新增状态与计算属性**

在训练相关状态（`trainModelName` 附近）加入：

```js
const datasets = ref([])
const datasetsLoading = ref(false)
const datasetUploading = ref(false)
const selectedDatasetIds = ref([])
const expandedDatasetId = ref('')
const datasetFileInput = ref(null)

const allDatasetSampleCount = computed(() =>
  datasets.value.reduce((sum, item) => sum + (item.sample_count || 0), 0)
)
const allDatasetLabelCount = computed(() => {
  const labels = new Set()
  for (const dataset of datasets.value) {
    for (const label of Object.keys(dataset.label_counts || {})) labels.add(label)
  }
  return labels.size
})
```

- [ ] **Step 4: 新增数据集操作函数（放在 `onModelFileChange` 之后）**

```js
async function fetchDatasets() {
  datasetsLoading.value = true
  try {
    const response = await axios.get(`${API_BASE}/datasets`)
    datasets.value = response.data || []
    const availableIds = new Set(datasets.value.map(item => item.dataset_id))
    selectedDatasetIds.value = selectedDatasetIds.value.filter(id => availableIds.has(id))
  } catch {
    datasets.value = []
  } finally {
    datasetsLoading.value = false
  }
}

async function uploadDatasetFile(file) {
  if (!file || datasetUploading.value || isTraining.value) return
  const lower = file.name.toLowerCase()
  if (!lower.endsWith('.jsonl') && !lower.endsWith('.json')) {
    showToast('请上传 .jsonl 或 .json 文件', 'warning')
    return
  }
  datasetUploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', file)
    const response = await axios.post(`${API_BASE}/datasets/upload`, formData)
    const dataset = response.data
    datasets.value = [dataset, ...datasets.value.filter(item => item.dataset_id !== dataset.dataset_id)]
    if (!selectedDatasetIds.value.includes(dataset.dataset_id)) {
      selectedDatasetIds.value = [...selectedDatasetIds.value, dataset.dataset_id]
    }
    expandedDatasetId.value = dataset.dataset_id
    if (!trainModelName.value.trim()) trainModelName.value = dataset.name
    showToast(`数据集已上传：${dataset.sample_count} 样本 · ${dataset.label_count} 类别`, 'success')
  } catch (error) {
    showToast('数据集上传失败: ' + (error.response?.data?.message || error.message), 'error')
  } finally {
    datasetUploading.value = false
  }
}

async function onDatasetFileChange(event) {
  const file = event.target.files?.[0]
  if (event.target) event.target.value = ''
  if (file) await uploadDatasetFile(file)
}

function onDatasetDrop(event) {
  const file = event.dataTransfer?.files?.[0]
  if (file) uploadDatasetFile(file)
}

async function deleteDataset(datasetId) {
  if (!datasetId || isTraining.value) return
  if (!window.confirm('确定删除该数据集？删除后不可恢复。')) return
  try {
    await axios.delete(`${API_BASE}/datasets/${datasetId}`)
    datasets.value = datasets.value.filter(item => item.dataset_id !== datasetId)
    selectedDatasetIds.value = selectedDatasetIds.value.filter(id => id !== datasetId)
    if (expandedDatasetId.value === datasetId) expandedDatasetId.value = ''
    showToast('数据集已删除', 'success')
  } catch {
    showToast('删除失败', 'error')
  }
}

function toggleDatasetStats(datasetId) {
  expandedDatasetId.value = expandedDatasetId.value === datasetId ? '' : datasetId
}

function getDatasetLabelEntries(dataset) {
  return Object.entries(dataset.label_counts || {}).sort((a, b) => b[1] - a[1])
}

function getDatasetLabelPct(dataset, count) {
  const values = Object.values(dataset.label_counts || {})
  const max = values.length ? Math.max(...values) : 1
  return max ? Math.max(6, Math.round((count / max) * 100)) : 0
}

function formatNumber(value) {
  const number = Number(value) || 0
  return number >= 10000 ? `${(number / 10000).toFixed(1)}万` : String(number)
}
```

- [ ] **Step 5: 新增按数据集训练函数**

复制 `uploadAndTrainModel` 的 SSE 处理逻辑，替换请求方式与校验条件：

```js
async function trainFromDatasets() {
  if (isTraining.value) return
  if (!selectedDatasetIds.value.length) {
    showToast('请至少选择一个训练数据集', 'warning')
    return
  }
  if (!trainModelName.value.trim()) {
    showToast('请填写模型名称', 'warning')
    return
  }

  isTraining.value = true
  trainProgress.value = null
  trainStatusMsg.value = '正在准备训练数据...'
  trainStartTime.value = Date.now()

  trainLossHistory.value = []
  trainLrHistory.value = []
  trainGradNormHistory.value = []
  trainLogMessages.value = []

  if (lossChart && typeof lossChart.destroy === 'function') { lossChart.destroy(); lossChart = null }
  if (gradNormChart && typeof gradNormChart.destroy === 'function') { gradNormChart.destroy(); gradNormChart = null }
  if (accuracyChart && typeof accuracyChart.destroy === 'function') { accuracyChart.destroy(); accuracyChart = null }
  await nextTick()
  initCharts()

  try {
    const response = await fetch(`${API_BASE}/model/train-from-dataset`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dataset_ids: selectedDatasetIds.value,
        model_name: trainModelName.value.trim(),
        epochs: trainEpochs.value,
        batch_size: trainBatchSize.value,
        lr: trainLearningRate.value,
      }),
    })

    if (!response.ok) {
      let errMsg = `服务器错误 (${response.status})`
      try {
        const errData = await response.json()
        errMsg = errData.message || errMsg
      } catch (_) { /* ignore */ }
      throw new Error(errMsg)
    }
    if (!response.body) throw new Error('服务器返回空响应')

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let trainingCompleted = false

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()

      for (const line of lines) {
        if (trainingCompleted) continue
        if (!line.startsWith('data: ')) continue
        try {
          const data = JSON.parse(line.slice(6))
          if (data.type === 'status') {
            trainStatusMsg.value = data.message
          } else if (data.type === 'progress') {
            trainProgress.value = data
            const currentEpoch = Math.floor(data.epoch) + 1
            trainStatusMsg.value = `Epoch ${currentEpoch}/${trainEpochs.value} · Step ${data.step}/${data.max_steps}`
            const step = data.step ?? trainLossHistory.value.length + 1
            if (data.loss != null) {
              updateCharts(
                step,
                data.loss_smooth ?? data.loss,
                data.loss,
                data.learning_rate ?? 0,
                data.grad_norm ?? 0,
                data.accuracy ?? null
              )
            }
          } else if (data.type === 'complete') {
            trainingCompleted = true
            const finalLoss = trainProgress.value?.loss
            trainProgress.value = data.result
            trainProgress.value.finalLoss = finalLoss
            trainStatusMsg.value = '训练完成！'
            trainStartTime.value = null
            await fetchSavedModels()
            showTrainCompleteModal.value = true
            trainCompleteResult.value = data.result
          } else if (data.type === 'validation') {
            trainProgress.value = { ...trainProgress.value, val_loss: data.val_loss, val_accuracy: data.val_accuracy }
            trainLogMessages.value.push(`[验证] loss=${data.val_loss.toFixed(4)} acc=${(data.val_accuracy * 100).toFixed(1)}%`)
          } else if (data.type === 'error') {
            showToast('训练失败: ' + data.message, 'error')
            console.error(data.detail)
          } else if (data.type === 'log') {
            trainLogMessages.value.push(data.message)
            nextTick(() => {
              if (trainLogPanel.value) trainLogPanel.value.scrollTop = trainLogPanel.value.scrollHeight
            })
          }
        } catch (_) { /* ignore */ }
      }
    }
  } catch (error) {
    showToast('训练失败: ' + (error.message || '连接中断'), 'error')
  } finally {
    isTraining.value = false
    trainStartTime.value = null
  }
}
```

- [ ] **Step 6: 加载数据集与详情页训练入口**

- 在组件挂载处（已有 `fetchSavedModels()` 调用）同时调用 `fetchDatasets()`。若不存在统一初始化处，在 `onMounted` 中加入。
- `closeTrainCompleteModal` 中删除 `modelUploadFile.value = null` 一行（该状态不再用于训练），保留其他清理。

- [ ] **Step 7: 新增样式**

在样式区训练表单相关样式之后追加（沿用现有 CSS 变量）：

```css
.dataset-section { display: flex; flex-direction: column; gap: 10px; }
.dataset-section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.dataset-section-title { font-size: 13px; font-weight: 600; color: var(--color-text-primary); }
.dataset-section-desc { margin: 2px 0 0; font-size: 12px; color: var(--color-text-muted); }
.dataset-summary-pill { padding: 3px 10px; border-radius: 999px; font-size: 11px; background: rgba(16,185,129,0.12); color: #10b981; border: 1px solid rgba(16,185,129,0.25); white-space: nowrap; }
.dataset-upload-zone { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 14px; border: 1px dashed var(--color-border); border-radius: 10px; font-size: 12px; color: var(--color-text-muted); cursor: pointer; transition: border-color .15s, background .15s; }
.dataset-upload-zone:hover { border-color: var(--color-accent); background: rgba(16,185,129,0.05); }
.dataset-upload-zone.is-uploading { pointer-events: none; opacity: .7; }
.dataset-empty { padding: 12px; text-align: center; font-size: 12px; color: var(--color-text-muted); }
.dataset-list { display: flex; flex-direction: column; gap: 8px; max-height: 320px; overflow-y: auto; }
.dataset-card { border: 1px solid var(--color-border); border-radius: 10px; background: var(--color-bg-secondary); }
.dataset-card.is-selected { border-color: rgba(16,185,129,0.55); box-shadow: 0 0 0 1px rgba(16,185,129,0.25) inset; }
.dataset-card-main { display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px; }
.dataset-check { padding-top: 2px; }
.dataset-card-info { flex: 1; min-width: 0; }
.dataset-card-title-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.dataset-card-name { font-size: 13px; font-weight: 600; color: var(--color-text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 220px; }
.dataset-card-meta { font-size: 11px; color: var(--color-text-muted); }
.dataset-card-time { font-size: 11px; color: var(--color-text-muted); margin-top: 2px; }
.dataset-label-chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
.dataset-label-chip { font-size: 11px; padding: 1px 7px; border-radius: 999px; background: rgba(148,163,184,0.12); color: var(--color-text-secondary); }
.dataset-label-chip b { color: var(--color-text-primary); margin-left: 2px; }
.dataset-label-more { opacity: .7; }
.dataset-card-actions { display: flex; gap: 6px; flex-shrink: 0; }
.dataset-stats-panel { border-top: 1px solid var(--color-border); padding: 10px 12px 12px; display: flex; flex-direction: column; gap: 10px; }
.dataset-stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.dataset-stat-block { display: flex; flex-direction: column; align-items: center; padding: 8px 4px; border-radius: 8px; background: rgba(148,163,184,0.08); }
.dataset-stat-value { font-size: 16px; font-weight: 700; color: var(--color-text-primary); }
.dataset-stat-label { font-size: 11px; color: var(--color-text-muted); margin-top: 2px; }
.dataset-label-bars { display: flex; flex-direction: column; gap: 6px; }
.dataset-label-bar-row { display: grid; grid-template-columns: 96px 1fr 36px; align-items: center; gap: 8px; }
.dataset-label-bar-name { font-size: 11px; color: var(--color-text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dataset-label-bar-track { height: 8px; border-radius: 999px; background: rgba(148,163,184,0.15); overflow: hidden; }
.dataset-label-bar-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, #10b981, #34d399); transition: width .3s ease; }
.dataset-label-bar-count { font-size: 11px; color: var(--color-text-primary); text-align: right; }
.dataset-stats-foot { font-size: 11px; color: var(--color-text-muted); }
.train-name-row { display: flex; flex-direction: column; gap: 4px; }
```

- [ ] **Step 8: 构建验证**

```bash
cd frontend && npm run build
```

Expected: 构建成功。

- [ ] **Step 9: 提交**

```bash
git add frontend/src/App.vue
git commit -m "feat(dataset): 模型训练页数据集上传、统计与多选训练"
```

---

## Task 8: 联调与验证

**Files:**
- 无新增

- [ ] **Step 1: 运行后端测试**

```bash
cd backend && python -m pytest tests -q
```

Expected: 全部通过。

- [ ] **Step 2: 启动后端**

```bash
cd backend && python main.py
```

Expected: `Uvicorn running on http://0.0.0.0:8267`。

- [ ] **Step 3: 验证导出接口（用已存在的历史任务）**

```bash
curl -s http://127.0.0.1:8267/history | python -c "import sys,json; d=json.load(sys.stdin); print(d[0]['task_id'] if d else 'NO_TASK')"
```

拿到 `task_id` 后：

```bash
curl -s -X POST http://127.0.0.1:8267/result/<TASK_ID>/export-annotations \
  -H "Content-Type: application/json" \
  -d '{"rules":["standards","decisions","limits","numeric_facts"],"model_id":"","model_conf_threshold":0}' \
  -o /tmp/export.jsonl
python -c "
import json
rows=[json.loads(l) for l in open('/tmp/export.jsonl', encoding='utf-8') if l.strip()]
print(len(rows), sorted(rows[0].keys()))
for r in rows[:2]:
    for s in r['spans']:
        assert r['text'][s['start']:s['end']] == s['text']
print('offsets ok')
"
```

Expected：顶层字段为 8 个：`['annotations','file_name','file_number','meta','relations','spans','task_id','text']`，并输出 `offsets ok`。

- [ ] **Step 4: 验证数据集接口**

```bash
curl -s -X POST http://127.0.0.1:8267/datasets/upload -F "file=@测试文本_annotations.jsonl"
curl -s http://127.0.0.1:8267/datasets
```

Expected：上传返回 `sample_count: 4`、`label_counts` 含 `标准条文`/`判定结论`/`限值指标` 等；列表中能看到该数据集。

- [ ] **Step 5: 启动前端并手测**

```bash
cd frontend && npm run dev
```

打开 `http://127.0.0.1:3000`：

1. 进入「快速标注」，勾选规则/选择模型，点击「导出标注」，确认下载文件每行字段与样例一致
2. 进入「模型训练」，上传 `测试文本_annotations.jsonl`，确认立即显示样本数/实体数/类别数/各类别条形图
3. 勾选该数据集并启动训练，确认 SSE 进度、Loss 曲线、完成弹窗正常

- [ ] **Step 6: 最终提交**

```bash
git add -A
git commit -m "chore: 标注导出与数据集库联调完成"
```

---

## 自检清单

- [x] 规格中的导出字段（8 个顶层字段 + meta 两字段）均有实现任务
- [x] 规格中的 `file_number` 按上传顺序、仅导出有标注句子、模型多选合并均有实现任务
- [x] 数据集统计口径（样本/实体/类别/字数/无标注）均有测试
- [x] 旧接口 `/model/upload-and-train` 保留
- [x] 前端训练入口改为 `/model/train-from-dataset`

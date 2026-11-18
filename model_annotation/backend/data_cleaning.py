"""NER 训练数据清洗工具模块。

提供以下功能:
- remove_template_duplicates: 限制相似模板样本数量
- split_guobiao_label: 拆分「国标」标签为「标准编号」或「标准全称」
- filter_short_entities: 过滤过短的实体
- validate_annotations: 验证标注数据格式
- reindex_spans: 重新编号 spans
- aggregate_empty_samples: 压缩空样本数量
"""

from typing import Any, Dict, List, Tuple


def get_template_prefix(text: str, prefix_len: int = 6):
    """提取文本前缀用于模板去重。

    对文本做轻度清洗（去空格和换行）后截取前缀。
    空文本返回 None，表示不参与去重，防止所有空文本共享 key ""。
    """
    cleaned = text.replace(" ", "").replace("\n", "")
    if not cleaned:
        return None
    return cleaned[:prefix_len]


def remove_template_duplicates(
    examples: List[Dict[str, Any]], max_per_template: int = 20
) -> List[Dict[str, Any]]:
    """提取文本前 6 字符作为模板标识，每模板保留 <= max_per_template 条。"""
    template_counts: Dict[str, int] = {}
    result: List[Dict[str, Any]] = []
    for ex in examples:
        text = ex.get("text", "")
        key = get_template_prefix(text)
        if key is None:
            # 空文本不参与模板去重，直接保留
            result.append(ex)
            continue
        if template_counts.get(key, 0) < max_per_template:
            result.append(ex)
            template_counts[key] = template_counts.get(key, 0) + 1
    return result


def split_guobiao_label(
    examples: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """将「国标」标签拆分为「标准编号」（无书名号）或「标准全称」（有书名号）。

    在实体左右各扩展最多 10 个字符查找《和》书名号。
    """
    result = []
    for ex in examples:
        text = ex.get("text", "")
        new_entities = []
        for ent in ex.get("entities", []):
            if ent.get("label") != "国标":
                new_entities.append(ent)
                continue
            new_ent = dict(ent)
            start = ent["start_offset"]
            end = ent["end_offset"]

            # 查找实体左侧最近的《和右侧最近的》
            left_book = text.rfind("《", 0, start)
            right_book = text.find("》", end)
            has_book_title = False
            if left_book >= 0 and right_book >= 0:
                # 确认书名号之间没有穿插其他书名号，确保真正包裹实体
                between = text[left_book + 1:right_book]
                if "《" not in between and "》" not in between:
                    has_book_title = True

            new_ent["label"] = "标准全称" if has_book_title else "标准编号"
            new_entities.append(new_ent)
        result.append({**ex, "entities": new_entities})
    return result


def filter_short_entities(
    examples: List[Dict[str, Any]], min_len: int = 2
) -> List[Dict[str, Any]]:
    """过滤长度不足 min_len 字符的实体。"""
    result = []
    for ex in examples:
        text = ex.get("text", "")
        entities = ex.get("entities", [])
        filtered = [
            e for e in entities
            if (e.get("end_offset", 0) - e.get("start_offset", 0)) >= min_len
        ]
        result.append({**ex, "entities": filtered})
    return result


def validate_annotations(
    examples: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """验证标注数据格式，返回 (valid, issues)。

    检查项:
    - 空文本
    - 实体边界越界 (start_offset < 0, end_offset > len(text),
      start_offset >= end_offset)
    - 标签为空
    """
    valid = []
    issues = []
    for idx, ex in enumerate(examples):
        text = ex.get("text", "")
        entities = ex.get("entities", [])
        ex_issues = []

        # 空文本检查
        if not text:
            ex_issues.append("empty_text")

        for ei, ent in enumerate(entities):
            start = ent.get("start_offset")
            end = ent.get("end_offset")
            if start is None or end is None:
                ex_issues.append(
                    f"entity[{ei}]: start_offset 或 end_offset 为 None"
                )
                # 跳过后续边界检查，因为值无效
                label = ent.get("label", "")
                if not label:
                    ex_issues.append(f"entity[{ei}]: empty_label")
                continue
            start = int(start)
            end = int(end)
            label = ent.get("label", "")

            # 标签为空
            if not label:
                ex_issues.append(f"entity[{ei}]: empty_label")

            # 边界越界
            if start < 0:
                ex_issues.append(f"entity[{ei}]: start_offset={start} < 0")
            if end > len(text):
                ex_issues.append(
                    f"entity[{ei}]: end_offset={end} > len(text)={len(text)}"
                )
            if start >= end:
                ex_issues.append(
                    f"entity[{ei}]: start_offset={start} >= end_offset={end}"
                )

        if ex_issues:
            issues.append({"index": idx, "text": text, "issues": ex_issues})
        else:
            valid.append(ex)

    return valid, issues


def reindex_spans(examples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将每个样本中的 spans id 从 1 开始重新编号。"""
    result = []
    for ex in examples:
        spans = ex.get("spans", [])
        if not spans:
            result.append(ex)
            continue
        new_spans = []
        for i, span in enumerate(spans, start=1):
            new_spans.append({**span, "id": i})
        result.append({**ex, "spans": new_spans})
    return result


def aggregate_empty_samples(
    examples: List[Dict[str, Any]], max_empty: int = 80
) -> List[Dict[str, Any]]:
    """压缩空样本数量，最多保留 max_empty 条无实体样本。"""
    result = []
    empty_count = 0
    for ex in examples:
        entities = ex.get("entities", [])
        if not entities:
            if empty_count < max_empty:
                result.append(ex)
                empty_count += 1
        else:
            result.append(ex)
    return result

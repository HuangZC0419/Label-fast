import asyncio
import contextlib
import html
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import sys
import threading
import time
import io
import traceback
import uuid
import zipfile
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

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
    _normalize_text,
)

from dataset_store import (
    save_dataset,
    list_datasets,
    get_dataset,
    delete_dataset,
    load_dataset_examples,
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")
INPUT_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "input")

# 持久模型 id 由 uuid4().hex[:12] 生成；该模式同时阻断路径穿越。
_MODEL_ID_PATTERN = re.compile(r"[0-9a-f]{12}")

# 数据集上传大小上限（20MB），独立常量便于测试与后续调整。
DATASET_MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# 训练任务全局互斥：PyTorch 训练占用大量 CPU/GPU，同一进程只允许一个训练任务。
TRAINING_LOCK = threading.Lock()


def get_runner_script_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "mineru_runner.py")


def get_task_output_dir(task_id: str) -> str:
    return os.path.join(OUTPUT_BASE, task_id)


def get_task_pdf_path(task_id: str) -> str:
    return os.path.join(get_task_output_dir(task_id), "layout.pdf")


def get_task_md_path(task_id: str) -> str:
    return os.path.join(get_task_output_dir(task_id), "result.md")


def get_task_images_dir(task_id: str) -> str:
    return os.path.join(get_task_output_dir(task_id), "images")

progress_store: dict[str, dict[str, Any]] = {}
ANNOTATION_RULE_OPTIONS = [
    {
        "id": "standards",
        "label": "标准条文",
        "description": "识别 GB、GB/T、ISO、IEC、SJ/T 等标准编号，并提取所在句子。",
    },
    {
        "id": "decisions",
        "label": "判定结论",
        "description": "提取包含判定结果、符合性、阴性/阳性、合格/不合格等关键信息的句子。",
    },
    {
        "id": "dates",
        "label": "日期节点",
        "description": "提取发布日期、实施日期及其他明显的日期信息。",
    },
    {
        "id": "limits",
        "label": "限值指标",
        "description": "提取 ppm、mg/kg、百分比等明显指标及对应语句。",
    },
    {
        "id": "numeric_facts",
        "label": "数值信息",
        "description": "提取 CAS 号、比例、网格尺寸、电压尺寸和其他与数值相关的关键信息。",
    },
]

STANDARD_CODE_PATTERN = re.compile(
    r"(?<![a-zA-Z0-9])(?:GB(?:/T|/Z)?|GBZ(?:/T)?|GJB|SJ(?:/T)?|QB(?:/T)?|YY(?:/T)?|HG(?:/T)?|DL(?:/T)?|"
    r"IEC|ISO|ASTM|EN|DIN|JIS)\s*[A-Z0-9]{0,6}(?:[-/ ]?[A-Z0-9]+)*(?:\.\d+)*(?:[—–\-−―]\d{2,4})?(?:（[^）]{1,30}）|\([^)]{1,30}\))?"
)
DATE_PATTERN = re.compile(
    r"(?P<year>19\d{2}|20\d{2}|2100)[-/.年](?P<month>0?[1-9]|1[0-2])[-/.月](?P<day>0?[1-9]|[12]\d|3[01])(?:日)?"
)
NUMBER_TOKEN_PATTERN = r"(?:\d{1,3}(?:[ ,]\d{3})+|\d+)(?:\.\d+)?"
LIMIT_WITH_UNIT_PATTERN = re.compile(
    rf"(?<![\d-])(?<!\d[ ,])(?:≤|≥|<|>|=)?\s*{NUMBER_TOKEN_PATTERN}\s*"
    r"(?:ppm|ppb|mg/kg|g/kg|ug/kg|μg/kg|mg/L|g/L|kV|mV|V|mA|A|℃|°C|cm²|cm2|mm²|mm2|mm|%|％)"
    r"(?=$|[\s,，、。；;:：)\]）】的])",
    re.IGNORECASE,
)
COMPARATIVE_LIMIT_PATTERN = re.compile(
    rf"(?<![\w\"'=/:-])(?:≤|≥|<|>|=)\s*{NUMBER_TOKEN_PATTERN}(?:\s*(?:%|％))?"
)
CAS_PATTERN = re.compile(r"(?<!\d)\d{2,7}-\d{2}-\d(?!\d)")
GRID_DIMENSION_PATTERN = re.compile(
    rf"(?<![\d.]){NUMBER_TOKEN_PATTERN}\s*[×xX*]\s*{NUMBER_TOKEN_PATTERN}(?:\s*[×xX*]\s*{NUMBER_TOKEN_PATTERN})*"
)
RATIO_PATTERN = re.compile(
    rf"(?<![\d.]){NUMBER_TOKEN_PATTERN}\s*[：:]\s*{NUMBER_TOKEN_PATTERN}(?:\s*[：:]\s*{NUMBER_TOKEN_PATTERN})+"
)
DECISION_PATTERNS = [
    re.compile(pattern)
    for pattern in (
        r"判定(?:结果|为|该)",
        r"不符合",
        r"符合(?:[^。；\n]{0,24})(?:要求|规定|限值|标准|表\d+)",
        r"阴性|阳性",
        r"标注为[“\"']?[Oo〇×X]",
        r"不必列入信息表",
        r"按b\)执行",
    )
]
DECISION_EXCLUDE_PATTERNS = [
    re.compile(pattern)
    for pattern in (
        r"合格评定制度",
        r"特制定本文件",
        r"图形规格应符合下列规定",
        r"符合以下要求[:：]?$",
        r"应符合以下要求[:：]?$",
    )
]
DATE_CONTEXT_KEYWORDS = ("发布", "实施", "日期", "时间", "生效", "起始", "截至", "生产日期")
LIMIT_KEYWORDS = ("限值", "限量", "含量", "浓度", "阈值", "要求")
NUMERIC_CONTEXT_KEYWORDS = (
    "数量",
    "比例",
    "比值",
    "网格",
    "尺寸",
    "规格",
    "直径",
    "半径",
    "高度",
    "宽度",
    "长度",
    "面积",
    "体积",
    "厚度",
    "电压",
    "电流",
    "数值",
    "数字",
    "质量分数",
    "字体",
    "CAS",
    "限值",
    "限量",
    "含量",
    "浓度",
)




AVAILABLE_OPTIONS = {
    "backend_types": [
        {
            "value": "pipeline",
            "label": "Pipeline",
            "description": "传统版面分析 + OCR 流程，适合结构化文档与数字敏感场景。",
        },
        {
            "value": "vlm",
            "label": "VLM",
            "description": "多模态模型后端，自动映射为新版 MinerU 的 vlm-auto-engine。",
        },
    ],
    "languages": [
        {"value": "auto", "label": "自动识别"},
        {"value": "zh", "label": "中文"},
        {"value": "en", "label": "英文"},
        {"value": "zh_en", "label": "中英混合"},
    ],
    "ocr_modes": [
        {"value": "auto", "label": "自动判断"},
        {"value": "force_ocr", "label": "强制 OCR"},
        {"value": "text_first", "label": "优先文本层"},
    ],
    "feature_toggles": [
        {"key": "high_accuracy", "label": "高精度模式", "description": "偏向精度，适合数字和细节较多的文档。"},
        {"key": "enable_ocr", "label": "启用 OCR", "description": "允许文档走 OCR 识别流程。"},
        {"key": "enable_layout", "label": "启用版面分析", "description": "识别标题、正文、表格、图片等布局区域。"},
        {"key": "enable_formula", "label": "启用公式识别", "description": "识别公式与数学表达式。"},
        {"key": "enable_table", "label": "启用表格识别", "description": "识别并输出表格结构。"},
        {"key": "enable_image", "label": "提取图片", "description": "保留并输出图片区域。"},
        {"key": "enable_heading", "label": "标题分级", "description": "尝试恢复 Markdown 标题层级。"},
        {"key": "preserve_whitespace", "label": "保留空白细节", "description": "尽量减少合并过度带来的数字粘连。"},
    ],
    "defaults": {
        "backend_type": "pipeline",
        "language": "auto",
        "ocr_mode": "auto",
        "high_accuracy": True,
        "enable_ocr": True,
        "enable_layout": True,
        "enable_formula": False,
        "enable_table": True,
        "enable_image": True,
        "enable_heading": True,
        "preserve_whitespace": True,
    },
}

BACKEND_ALIASES = {
    "auto": None,
    "default": None,
    "pipeline": "pipeline",
    "vlm": "vlm-auto-engine",
    "vlm-auto": "vlm-auto-engine",
    "vlm-auto-engine": "vlm-auto-engine",
    "vlm-http-client": "vlm-http-client",
    "hybrid": "hybrid-auto-engine",
    "hybrid-auto": "hybrid-auto-engine",
    "hybrid-auto-engine": "hybrid-auto-engine",
    "hybrid-http-client": "hybrid-http-client",
}

LANGUAGE_ALIASES = {
    "auto": None,
    "zh": "ch",
    "ch": "ch",
    "en": "en",
    "zh_en": None,
    "ch_en": None,
}

OCR_MODE_ALIASES = {
    "auto": "auto",
    "force_ocr": "ocr",
    "ocr": "ocr",
    "text_first": "txt",
    "txt": "txt",
}


def find_mineru_output_files(output_dir: str):
    """递归扫描 MinerU 生成的输出目录，找到 layout PDF 和 Markdown 文件。"""
    layout_pdf = None
    result_md = None
    images_dir = None
    for root, dirs, files in os.walk(output_dir):
        for f in files:
            if f.endswith("_layout.pdf") and layout_pdf is None:
                layout_pdf = os.path.join(root, f)
            if f.endswith(".md") and result_md is None:
                result_md = os.path.join(root, f)
        if images_dir is None and os.path.isdir(os.path.join(root, "images")):
            images_dir = os.path.join(root, "images")
        if layout_pdf and result_md and images_dir:
            break
    return layout_pdf, result_md, images_dir


def build_task_config(payload: dict[str, Any]) -> dict[str, Any]:
    defaults = AVAILABLE_OPTIONS["defaults"]
    config = defaults.copy()
    config.update(payload)
    return config


def build_stages(config: dict[str, Any]) -> list[tuple[int, str]]:
    backend_name = config["backend_type"].upper()
    language_label = next(
        (item["label"] for item in AVAILABLE_OPTIONS["languages"] if item["value"] == config["language"]),
        config["language"],
    )
    stages = [
        (8, f"初始化 {backend_name} 后端配置..."),
        (18, f"加载语言策略: {language_label}"),
        (32, "执行版面分析并检测文本区域..."),
        (52, "运行 OCR 与阅读顺序恢复..."),
    ]
    if config["enable_formula"]:
        stages.append((66, "识别公式与特殊符号..."))
    if config["enable_table"]:
        stages.append((76, "解析表格结构与单元格内容..."))
    if config["enable_image"]:
        stages.append((84, "提取图片与插图区域..."))
    stages.extend(
        [
            (92, "生成 Markdown、布局 PDF 与可视化资源..."),
            (100, "处理完成"),
        ]
    )
    return stages


def get_stage_index_for_progress(stages: list[tuple[int, str]], progress: int) -> int:
    for index in range(len(stages) - 1, -1, -1):
        if progress >= stages[index][0]:
            return index
    return 0


def find_task_md_path(task_id: str) -> str | None:
    task = progress_store.get(task_id)
    if task and task.get("result") and task["result"].get("markdown"):
        md_path = task["result"]["markdown"]
        if os.path.exists(md_path):
            return md_path

    output_dir = get_task_output_dir(task_id)
    if os.path.exists(output_dir):
        _, result_md, _ = find_mineru_output_files(output_dir)
        if result_md and os.path.exists(result_md):
            return result_md
    return None


def load_task_markdown(task_id: str) -> str | None:
    md_path = find_task_md_path(task_id)
    if not md_path:
        return None
    with open(md_path, "r", encoding="utf-8") as f:
        return f.read()


RE_MD_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|~<>])")


def clean_annotation_text(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = html.unescape(cleaned)
    cleaned = cleaned.replace("\xa0", " ")
    # Strip ALL markdown escapes so entity text matches rendered HTML
    cleaned = RE_MD_ESCAPE.sub(r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" \n\t-:;,.，。、")


def normalize_markdown_for_annotation(raw_text: str) -> str:
    normalized = raw_text.replace("\r\n", "\n")
    normalized = re.sub(r"<\s*br\s*/?>", "\n", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"</(?:p|div|li|tr|table|tbody|thead|tfoot|ul|ol|h[1-6])>", "\n", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"</t[dh]>", " | ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"<[^>]+>", " ", normalized)
    normalized = html.unescape(normalized).replace("\xa0", " ")
    normalized = RE_MD_ESCAPE.sub(r"\1", normalized)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{2,}", "\n", normalized)
    return normalized


def extract_context(raw_text: str, start: int, end: int, window: int = 180) -> str:
    left_candidates = [
        raw_text.rfind("\n", 0, start),
        raw_text.rfind("。", 0, start),
        raw_text.rfind("！", 0, start),
        raw_text.rfind("？", 0, start),
        raw_text.rfind("；", 0, start),
        raw_text.rfind("|", 0, start),
    ]
    right_candidates = [
        pos for pos in (
            raw_text.find("\n", end),
            raw_text.find("。", end),
            raw_text.find("！", end),
            raw_text.find("？", end),
            raw_text.find("；", end),
            raw_text.find("|", end),
        ) if pos != -1
    ]

    left = max(left_candidates)
    right = min(right_candidates) if right_candidates else -1

    if left == -1:
        left = max(0, start - window)
    else:
        left += 1

    if right == -1:
        right = min(len(raw_text), end + window)
    else:
        right += 1

    return clean_annotation_text(raw_text[left:right])


def split_candidate_sentences(raw_text: str) -> list[str]:
    normalized = normalize_markdown_for_annotation(raw_text)
    chunks = re.split(r"(?:\n+|[。！？；;]+|\s+\|\s+)", normalized)
    results: list[str] = []
    for chunk in chunks:
        cleaned = clean_annotation_text(chunk)
        if cleaned and len(cleaned) >= 8:
            results.append(cleaned)
    return results


def is_structural_noise_sentence(text: str) -> bool:
    if not text:
        return True
    lowered = text.lstrip()
    if lowered.startswith("#"):
        return True
    if lowered.startswith("表") and len(lowered) <= 20:
        return True
    if lowered.startswith("附录") and len(lowered) <= 24:
        return True
    if re.fullmatch(r"(?:第?\d+(?:\.\d+)*[章节条款项]?|[A-Z]{1,4}-?[A-Z]?)", lowered):
        return True
    if re.fullmatch(r"[0-9.\- ]+", lowered):
        return True
    return False


def is_plausible_date_match(match: re.Match[str], raw_text: str) -> bool:
    try:
        year = int(match.group("year"))
        month = int(match.group("month"))
        day = int(match.group("day"))
    except (TypeError, ValueError):
        return False

    if year < 1900 or year > 2100:
        return False
    if month < 1 or month > 12:
        return False
    if day < 1 or day > 31:
        return False

    matched_text = match.group(0)
    context = raw_text[max(0, match.start() - 12): min(len(raw_text), match.end() + 12)]
    if any(keyword in context for keyword in DATE_CONTEXT_KEYWORDS):
        return True
    return any(token in matched_text for token in ("年", "月", "日"))


def is_limit_context(text: str) -> bool:
    return any(keyword in text for keyword in LIMIT_KEYWORDS) or "%" in text or "％" in text


def find_limit_matches(raw_text: str) -> list[re.Match[str]]:
    matches: list[re.Match[str]] = []
    seen: set[tuple[int, int]] = set()

    for pattern in (LIMIT_WITH_UNIT_PATTERN, COMPARATIVE_LIMIT_PATTERN):
        for match in pattern.finditer(raw_text):
            span = (match.start(), match.end())
            if span in seen:
                continue

            if pattern is COMPARATIVE_LIMIT_PATTERN:
                context = extract_context(raw_text, match.start(), match.end(), window=120)
                if not is_limit_context(context):
                    continue

            seen.add(span)
            matches.append(match)

    matches.sort(key=lambda item: item.start())
    return matches


def is_numeric_context(text: str) -> bool:
    if any(keyword in text for keyword in NUMERIC_CONTEXT_KEYWORDS):
        return True
    return any(pattern.search(text) for pattern in (CAS_PATTERN, GRID_DIMENSION_PATTERN, RATIO_PATTERN))


def find_numeric_matches(raw_text: str) -> list[tuple[str, re.Match[str]]]:
    matches: list[tuple[str, re.Match[str]]] = []
    seen: set[tuple[int, int]] = set()
    pattern_defs: list[tuple[str, re.Pattern[str]]] = [
        ("cas", CAS_PATTERN),
        ("numeric", GRID_DIMENSION_PATTERN),
        ("numeric", RATIO_PATTERN),
        ("metric", LIMIT_WITH_UNIT_PATTERN),
        ("metric", COMPARATIVE_LIMIT_PATTERN),
    ]

    for entity_type, pattern in pattern_defs:
        for match in pattern.finditer(raw_text):
            span = (match.start(), match.end())
            if span in seen:
                continue

            context = extract_context(raw_text, match.start(), match.end(), window=120)
            if pattern in (GRID_DIMENSION_PATTERN, RATIO_PATTERN) and not is_numeric_context(context):
                continue

            seen.add(span)
            matches.append((entity_type, match))

    matches.sort(key=lambda item: item[1].start())
    return matches


def is_decision_sentence(text: str) -> bool:
    if is_structural_noise_sentence(text):
        return False
    if any(pattern.search(text) for pattern in DECISION_EXCLUDE_PATTERNS):
        return False
    return any(pattern.search(text) for pattern in DECISION_PATTERNS)


def dedupe_annotation_items(items: list[dict[str, Any]], *, key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        key = tuple(item.get(field) for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def dedupe_annotation_snippets(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    ordered_keys: list[tuple[str, str]] = []

    for item in items:
        key = (str(item.get("rule_id")), str(item.get("text")))
        if key not in merged:
            merged[key] = {**item, "tags": dedupe_preserve_order(item.get("tags", []))}
            ordered_keys.append(key)
            continue

        existing_tags = merged[key].get("tags", [])
        incoming_tags = item.get("tags", [])
        merged[key]["tags"] = dedupe_preserve_order([*existing_tags, *incoming_tags])

    return [merged[key] for key in ordered_keys]


def build_annotation_result(markdown_text: str, rule_ids: list[str] | None = None) -> dict[str, Any]:
    active_rules = [rule["id"] for rule in ANNOTATION_RULE_OPTIONS]
    if rule_ids:
        requested = {rule_id for rule_id in rule_ids if rule_id in active_rules}
        active_rules = [rule_id for rule_id in active_rules if rule_id in requested]

    rule_labels = {rule["id"]: rule["label"] for rule in ANNOTATION_RULE_OPTIONS}
    entities: list[dict[str, Any]] = []
    snippets: list[dict[str, Any]] = []
    sentences = split_candidate_sentences(markdown_text)
    def add_entity(rule_id: str, entity_type: str, text: str, context: str):
        cleaned_text = clean_annotation_text(text)
        if not cleaned_text:
            return
        entities.append(
            {
                "id": f"{rule_id}:{entity_type}:{cleaned_text}",
                "rule_id": rule_id,
                "rule_label": rule_labels[rule_id],
                "type": entity_type,
                "label": cleaned_text,
                "text": cleaned_text,
                "context": context,
            }
        )

    def add_snippet(rule_id: str, text: str, tags: list[str] | None = None):
        cleaned_text = clean_annotation_text(text)
        if not cleaned_text:
            return
        snippets.append(
            {
                "id": f"{rule_id}:{len(snippets)}",
                "rule_id": rule_id,
                "rule_label": rule_labels[rule_id],
                "text": cleaned_text,
                "tags": dedupe_preserve_order(tags or []),
            }
        )

    if "standards" in active_rules:
        for match in STANDARD_CODE_PATTERN.finditer(markdown_text):
            matched_text = clean_annotation_text(match.group(0))
            if not matched_text or len(matched_text) < 4:
                continue
            context = extract_context(markdown_text, match.start(), match.end())
            add_entity("standards", "standard", matched_text, context)
            add_snippet("standards", context, [matched_text])

    if "decisions" in active_rules:
        for sentence in sentences:
            if is_decision_sentence(sentence):
                related_standards = [clean_annotation_text(m.group(0)) for m in STANDARD_CODE_PATTERN.finditer(sentence)]
                add_snippet("decisions", sentence, related_standards)

    if "dates" in active_rules:
        for match in DATE_PATTERN.finditer(markdown_text):
            if not is_plausible_date_match(match, markdown_text):
                continue
            context = extract_context(markdown_text, match.start(), match.end())
            add_entity("dates", "date", match.group(0), context)
            add_snippet("dates", context, [clean_annotation_text(match.group(0))])

    if "limits" in active_rules:
        for match in find_limit_matches(markdown_text):
            context = extract_context(markdown_text, match.start(), match.end())
            add_entity("limits", "metric", match.group(0), context)
            add_snippet("limits", context, [clean_annotation_text(match.group(0))])

        for sentence in sentences:
            if any(keyword in sentence for keyword in LIMIT_KEYWORDS):
                metrics = [clean_annotation_text(m.group(0)) for m in find_limit_matches(sentence)]
                if metrics:
                    add_snippet("limits", sentence, metrics)

    if "numeric_facts" in active_rules:
        numeric_source = normalize_markdown_for_annotation(markdown_text)

        for entity_type, match in find_numeric_matches(numeric_source):
            context = extract_context(numeric_source, match.start(), match.end())
            add_entity("numeric_facts", entity_type, match.group(0), context)

        for sentence in sentences:
            numeric_tags = [clean_annotation_text(match.group(0)) for _, match in find_numeric_matches(sentence)]
            if numeric_tags and (is_numeric_context(sentence) or len(numeric_tags) > 1):
                add_snippet("numeric_facts", sentence, numeric_tags)

    entities = dedupe_annotation_items(entities, key_fields=("rule_id", "type", "text"))
    snippets = dedupe_annotation_snippets(snippets)

    counts = {rule_id: 0 for rule_id in active_rules}
    for item in snippets:
        counts[item["rule_id"]] = counts.get(item["rule_id"], 0) + 1

    return {
        "rules": [
            {
                "id": rule_id,
                "label": rule_labels[rule_id],
                "count": counts.get(rule_id, 0),
            }
            for rule_id in active_rules
        ],
        "entities": entities,
        "snippets": snippets,
        "counts": {
            "rules": len(active_rules),
            "entities": len(entities),
            "snippets": len(snippets),
        },
    }


def normalize_text_for_match(text: str) -> str:
    """复用训练侧的 1:1 归一化，保证模型偏移与规则匹配使用同一规则。"""
    return _normalize_text(text)


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
        # limits 已用“限值指标”独占带单位的指标，numeric_facts 不再重复产出 metric。
        skip_metric = "limits" in rule_ids
        for entity_type, match in find_numeric_matches(sentence):
            if skip_metric and entity_type == "metric":
                continue
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
        # run_inference 的 label 字段存放实体文本，rule_label/rule_id 才是模型标签
        label = str(
            entity.get("rule_label") or entity.get("rule_id") or entity.get("type") or ""
        ).strip()
        original_sentence = str(entity.get("sentence_original") or "")
        if not label or not original_sentence:
            continue
        start = entity.get("start_offset")
        end = entity.get("end_offset")
        if start is None or end is None:
            located = locate_entity_in_sentence(
                original_sentence, str(entity.get("text") or "")
            )
            if located is None:
                continue
            start, end = located
        start, end = int(start), int(end)
        if start < 0 or start >= end or end > len(original_sentence):
            continue
        text = original_sentence[start:end]
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


def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def estimate_total_seconds(input_path: str, config: dict[str, Any]) -> int:
    file_size_mb = 1.0
    if os.path.exists(input_path):
        file_size_mb = max(1.0, os.path.getsize(input_path) / (1024 * 1024))

    seconds = 16 + file_size_mb * 4.5
    if config.get("enable_ocr", True):
        seconds += 14
    if config.get("high_accuracy", True):
        seconds += 10
    if config.get("enable_table", True):
        seconds += 8
    if config.get("enable_formula", False):
        seconds += 10
    if config.get("enable_image", True):
        seconds += 4

    backend = resolve_backend(config.get("backend_type"))
    if backend == "vlm-auto-engine":
        seconds += 24
    elif backend and backend.startswith("hybrid-"):
        seconds += 12

    return max(25, min(20 * 60, int(math.ceil(seconds))))


def update_task(
    task: dict[str, Any],
    *,
    status: str | None = None,
    progress: int | None = None,
    message: str | None = None,
    stage_index: int | None = None,
    stage_label: str | None = None,
    eta_seconds: int | None = None,
):
    if status is not None:
        task["status"] = status
    if progress is not None:
        task["progress"] = max(0, min(100, int(progress)))
    if message is not None:
        task["message"] = message
    if stage_index is not None:
        task["stage_index"] = stage_index
    if stage_label is not None:
        task["stage_label"] = stage_label
    task["eta_seconds"] = None if eta_seconds is None else max(0, int(eta_seconds))
    task["updated_at"] = time.time()


def make_runtime_status(
    task: dict[str, Any],
    stages: list[tuple[int, str]],
    elapsed_seconds: float,
    last_log_line: str | None = None,
) -> tuple[int, int, str, str, int]:
    expected_total = max(25, int(task.get("estimated_total_seconds") or 60))
    progress_floor = max(15, int(task.get("progress") or 15))
    progress_ceiling = 96

    # 使用平滑曲线推进，避免长时间停留在 80% 左右不动。
    normalized = min(elapsed_seconds / expected_total, 1.35)
    eased = 1 - math.exp(-2.6 * normalized)
    calculated_progress = 15 + int((progress_ceiling - 15) * eased)
    progress = max(progress_floor, min(progress_ceiling, calculated_progress))

    stage_index = min(
        max(0, get_stage_index_for_progress(stages, progress)),
        max(0, len(stages) - 2),
    )
    stage_label = stages[stage_index][1]

    remaining = max(3, int(math.ceil(expected_total - elapsed_seconds)))
    if elapsed_seconds > expected_total:
        remaining = max(8, int(math.ceil(expected_total * 0.18)))
        message = f"{stage_label} 文档较复杂，OCR 仍在继续，请稍候..."
    else:
        message = stage_label

    if last_log_line:
        message = f"{message} | {last_log_line[:180]}"

    return progress, stage_index, stage_label, message, remaining


def build_feature_summary(config: dict[str, Any]) -> list[str]:
    summary = [
        f"后端: {config['backend_type']}",
        f"语言: {config['language']}",
        f"OCR 模式: {config['ocr_mode']}",
    ]
    for item in AVAILABLE_OPTIONS["feature_toggles"]:
        if config.get(item["key"]):
            summary.append(item["label"])
    return summary


def resolve_backend(backend_type: str | None) -> str | None:
    if backend_type is None:
        return None
    normalized = backend_type.strip().lower()
    return BACKEND_ALIASES.get(normalized, normalized or None)


def resolve_language(language: str | None) -> str | None:
    if language is None:
        return None
    normalized = language.strip().lower()
    return LANGUAGE_ALIASES.get(normalized, normalized or None)


def resolve_ocr_mode(ocr_mode: str | None) -> str:
    if ocr_mode is None:
        return "auto"
    normalized = ocr_mode.strip().lower()
    return OCR_MODE_ALIASES.get(normalized, "auto")


def backend_supports_text_controls(backend: str | None) -> bool:
    if not backend:
        return True
    return backend == "pipeline" or backend.startswith("hybrid-")


def build_mineru_command(task: dict[str, Any]) -> list[str]:
    config = task["config"]
    backend = resolve_backend(config.get("backend_type"))
    language = resolve_language(config.get("language"))
    ocr_mode = resolve_ocr_mode(config.get("ocr_mode"))

    cmd = [
        sys.executable,
        get_runner_script_path(),
        "--input", task["input_path"],
        "--output", get_task_output_dir(task["task_id"]),
        "--backend", backend or "",
        "--language", language or "",
        "--parse-method", ocr_mode,
        "--formula", str(bool(config.get("enable_formula", False))).lower(),
        "--table", str(bool(config.get("enable_table", True))).lower(),
        "--high-accuracy", str(bool(config.get("high_accuracy", True))).lower(),
    ]
    return cmd


async def run_mineru_command(cmd: list[str]):
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    return process, cmd


async def consume_stream(stream, collector: list[str], task: dict[str, Any]):
    while True:
        line = await stream.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        collector.append(text)
        task["last_log_line"] = text[:240]
        task["updated_at"] = time.time()


@app.get("/history")
async def get_history():
    history = []
    
    # scan input directory
    if os.path.exists(INPUT_BASE):
        for task_id in os.listdir(INPUT_BASE):
            task_dir = os.path.join(INPUT_BASE, task_id)
            if not os.path.isdir(task_dir):
                continue
            files = os.listdir(task_dir)
            if not files:
                continue
            file_name = files[0]
            
            # Check if it's in progress_store
            if task_id in progress_store:
                task = progress_store[task_id]
                history.append({
                    "task_id": task_id,
                    "file_name": task.get("file_name", file_name),
                    "status": task.get("status", "idle"),
                    "created_at": task.get("created_at", os.path.getctime(task_dir)),
                    "feature_summary": task.get("feature_summary", [])
                })
                continue
                
            # If not in progress_store, determine status from output dir
            output_dir = os.path.join(OUTPUT_BASE, task_id)
            status = "failed"
            feature_summary = []
            if os.path.exists(output_dir):
                layout_pdf, result_md, _ = find_mineru_output_files(output_dir)
                if layout_pdf and result_md:
                    status = "completed"
            
            history.append({
                "task_id": task_id,
                "file_name": file_name,
                "status": status,
                "created_at": os.path.getctime(task_dir),
                "feature_summary": feature_summary
            })
            
    history.sort(key=lambda x: x["created_at"], reverse=True)
    return history


@app.delete("/history/{task_id}")
async def delete_history(task_id: str):
    errors = []

    if task_id in progress_store:
        del progress_store[task_id]

    input_dir = os.path.join(INPUT_BASE, task_id)
    if os.path.exists(input_dir):
        try:
            shutil.rmtree(input_dir)
        except Exception as e:
            errors.append(f"input: {e}")

    output_dir = get_task_output_dir(task_id)
    if os.path.exists(output_dir):
        try:
            shutil.rmtree(output_dir)
        except Exception as e:
            errors.append(f"output: {e}")

    if errors:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"部分文件清理失败: {'; '.join(errors)}"}
        )

    return {"success": True, "message": f"任务 {task_id[:8]} 已删除"}


@app.get("/options")
async def get_options():
    return AVAILABLE_OPTIONS


@app.get("/annotation/options")
async def get_annotation_options():
    return {"rules": ANNOTATION_RULE_OPTIONS}


def create_training_stream(train_callable) -> Response:
    """把任意训练函数包装成带心跳的 SSE 响应；train_callable 接收进度回调。

    训练线程在返回响应前启动，确保即使客户端不消费流，训练结束后也会释放
    全局训练锁；并发训练直接返回 409。
    """
    progress_queue: queue.Queue = queue.Queue()
    loop = asyncio.get_running_loop()

    if not TRAINING_LOCK.acquire(blocking=False):
        return JSONResponse(
            status_code=409,
            content={"message": "已有训练任务正在进行，请稍后再试"},
        )

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
        finally:
            TRAINING_LOCK.release()

    thread = threading.Thread(target=run_training, daemon=True)
    try:
        thread.start()
    except Exception:
        TRAINING_LOCK.release()
        raise

    async def event_stream():
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


@app.post("/model/infer")
async def model_infer_endpoint(body: dict[str, Any]):
    try:
        result = run_inference(
            model_id=body["model_id"],
            document_text=body["document_text"],
        )
        return result
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"推理失败: {str(e)}"})


@app.get("/models")
async def list_models_endpoint():
    return list_models()


@app.get("/models/{model_id}")
async def get_model_endpoint(model_id: str):
    try:
        return get_model(model_id)
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"message": str(e)})


@app.delete("/models/{model_id}")
async def delete_model_endpoint(model_id: str):
    try:
        delete_model(model_id)
        return {"message": "ok"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"删除失败: {str(e)}"})


@app.post("/models/{model_id}/continue-train")
async def continue_train_endpoint(model_id: str, body: dict[str, Any]):
    try:
        result = continue_train(model_id, body.get("examples", []))
        return result
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"继续训练失败: {str(e)}"})


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    backend_type: str = Form("pipeline"),
    language: str = Form("auto"),
    ocr_mode: str = Form("auto"),
    high_accuracy: bool = Form(True),
    enable_ocr: bool = Form(True),
    enable_layout: bool = Form(True),
    enable_formula: bool = Form(False),
    enable_table: bool = Form(True),
    enable_image: bool = Form(True),
    enable_heading: bool = Form(True),
    preserve_whitespace: bool = Form(True),
):
    task_id = str(uuid.uuid4())
    config = build_task_config(
        {
            "backend_type": backend_type,
            "language": language,
            "ocr_mode": ocr_mode,
            "high_accuracy": high_accuracy,
            "enable_ocr": enable_ocr,
            "enable_layout": enable_layout,
            "enable_formula": enable_formula,
            "enable_table": enable_table,
            "enable_image": enable_image,
            "enable_heading": enable_heading,
            "preserve_whitespace": preserve_whitespace,
        }
    )

    # 保存上传的文件到 input 目录
    task_input_dir = os.path.join(INPUT_BASE, task_id)
    os.makedirs(task_input_dir, exist_ok=True)
    input_path = os.path.join(task_input_dir, file.filename)
    content = await file.read()
    with open(input_path, "wb") as f:
        f.write(content)

    progress_store[task_id] = {
        "task_id": task_id,
        "status": "processing",
        "progress": 0,
        "message": "任务已创建，等待 MinerU 开始处理...",
        "file_name": file.filename,
        "file_stem": os.path.splitext(file.filename)[0],
        "input_path": input_path,
        "config": config,
        "feature_summary": build_feature_summary(config),
        "created_at": time.time(),
        "started_at": None,
        "updated_at": time.time(),
        "stage_index": 0,
        "stage_label": "任务已创建",
        "eta_seconds": None,
        "estimated_total_seconds": estimate_total_seconds(input_path, config),
        "last_log_line": "",
    }

    asyncio.create_task(process_file(task_id))
    return progress_store[task_id]


async def process_file(task_id: str):
    task = progress_store.get(task_id)
    if not task:
        return

    input_path = task.get("input_path")
    if not input_path or not os.path.exists(input_path):
        task["status"] = "failed"
        task["message"] = "输入文件不存在，可能已被清理。"
        return

    output_dir = get_task_output_dir(task_id)
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    config = task["config"]
    backend = resolve_backend(config.get("backend_type"))
    cmd = build_mineru_command(task)

    stages = build_stages(config)

    # 上报启动阶段
    update_task(
        task,
        progress=5,
        message=f"正在启动 MinerU ({backend or 'pipeline'}) 高精度引擎...",
        stage_index=0,
        stage_label=stages[0][1],
        eta_seconds=task.get("estimated_total_seconds"),
    )

    await asyncio.sleep(0.3)

    try:
        task["started_at"] = time.time()
        update_task(
            task,
            progress=15,
            message="MinerU 正在解析文档，请耐心等待...",
            stage_index=1 if len(stages) > 1 else 0,
            stage_label=stages[1][1] if len(stages) > 1 else stages[0][1],
            eta_seconds=task.get("estimated_total_seconds"),
        )

        process, executed_cmd = await run_mineru_command(cmd)

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        stdout_task = asyncio.create_task(consume_stream(process.stdout, stdout_lines, task))
        stderr_task = asyncio.create_task(consume_stream(process.stderr, stderr_lines, task))

        # MinerU 运行期间持续推进进度，避免停在单一百分比。
        mineru_start = time.monotonic()

        async def _bump_progress():
            while True:
                elapsed = time.monotonic() - mineru_start
                progress, stage_index, stage_label, message, remaining = make_runtime_status(
                    task,
                    stages,
                    elapsed,
                    task.get("last_log_line"),
                )
                update_task(
                    task,
                    progress=progress,
                    message=message,
                    stage_index=stage_index,
                    stage_label=stage_label,
                    eta_seconds=remaining,
                )
                await asyncio.sleep(2)

        bump_task = asyncio.create_task(_bump_progress())

        await process.wait()
        bump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bump_task
        await asyncio.gather(stdout_task, stderr_task)

        if process.returncode != 0:
            err_msg = "\n".join(stderr_lines[-12:])[:500] or "\n".join(stdout_lines[-12:])[:500]
            update_task(task, status="failed", eta_seconds=0)
            task["message"] = (
                f"MinerU 进程退出码 {process.returncode}: {err_msg}"
                f" | 执行命令: {' '.join(executed_cmd)}"
            )
            return

        update_task(
            task,
            progress=97,
            message="正在定位 MinerU 输出文件...",
            stage_index=max(0, len(stages) - 2),
            stage_label=stages[-2][1],
            eta_seconds=2,
        )

        # 扫描 MinerU 实际生成的文件
        layout_pdf, result_md, images_dir = find_mineru_output_files(output_dir)

        if not layout_pdf or not result_md:
            # 列出 output_dir 内容以便调试
            listing = []
            for root, dirs, files in os.walk(output_dir):
                for f in files:
                    listing.append(os.path.join(root, f))
            update_task(task, status="failed", eta_seconds=0)
            task["message"] = (
                f"MinerU 输出文件未找到。output_dir 内容: {listing[:20]}"
            )
            return

        update_task(
            task,
            progress=99,
            message="正在准备可视化数据...",
            stage_index=max(0, len(stages) - 2),
            stage_label=stages[-2][1],
            eta_seconds=1,
        )

        # 如果 images 目录不在默认位置，确保它可被前端访问
        default_images = get_task_images_dir(task_id)
        if images_dir and os.path.abspath(images_dir) != os.path.abspath(default_images):
            if not os.path.exists(default_images):
                try:
                    shutil.copytree(images_dir, default_images)
                except Exception:
                    pass

        update_task(
            task,
            status="completed",
            progress=100,
            message="处理完成",
            stage_index=len(stages) - 1,
            stage_label=stages[-1][1],
            eta_seconds=0,
        )
        task["result"] = {
            "layout_pdf": layout_pdf,
            "markdown": result_md,
            "images_dir": images_dir or default_images,
        }

    except FileNotFoundError:
        update_task(task, status="failed", eta_seconds=0)
        task["message"] = (
            "未找到 MinerU Python 模块或运行脚本，请确认当前后端 Python 环境已正确安装 MinerU。"
        )
    except Exception as e:
        update_task(task, status="failed", eta_seconds=0)
        task["message"] = f"处理异常: {type(e).__name__}: {str(e)[:300]}"


@app.get("/progress/{task_id}")
async def get_progress(task_id: str):
    if task_id not in progress_store:
        return JSONResponse(status_code=404, content={"message": "Task not found"})
    return progress_store[task_id]


@app.get("/result/{task_id}/pdf")
async def get_result_pdf(task_id: str):
    # 优先从任务记录中获取 MinerU 实际输出路径
    task = progress_store.get(task_id)
    if task and task.get("result") and task["result"].get("layout_pdf"):
        pdf_path = task["result"]["layout_pdf"]
        if os.path.exists(pdf_path):
            return FileResponse(pdf_path, media_type="application/pdf")
    
    # 如果不在内存中（如重启后），尝试实时扫描输出目录
    output_dir = get_task_output_dir(task_id)
    if os.path.exists(output_dir):
        layout_pdf, _, _ = find_mineru_output_files(output_dir)
        if layout_pdf and os.path.exists(layout_pdf):
            return FileResponse(layout_pdf, media_type="application/pdf")
            
    return JSONResponse(status_code=404, content={"message": "PDF not found for this task"})


@app.get("/result/{task_id}/md")
async def get_result_md(task_id: str):
    md_path = find_task_md_path(task_id)
    if md_path and os.path.exists(md_path):
        return FileResponse(md_path, media_type="text/markdown")

    return JSONResponse(status_code=404, content={"message": "Markdown not found for this task"})


@app.post("/result/{task_id}/annotations")
async def get_result_annotations(task_id: str, body: dict[str, Any] | None = None):
    markdown_text = load_task_markdown(task_id)
    if markdown_text is None:
        return JSONResponse(status_code=404, content={"message": "Markdown not found for this task"})

    rule_ids = []
    if body and isinstance(body.get("rules"), list):
        rule_ids = [str(item) for item in body["rules"]]

    return build_annotation_result(markdown_text, rule_ids)


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


def build_export_content_disposition(file_stem: str) -> str:
    """构建纯 ASCII 的 Content-Disposition，中文文件名走 RFC 5987。

    Starlette 使用 latin-1 编码响应头，直接放中文会抛 UnicodeEncodeError。
    """
    export_name = f"{file_stem}_annotations.jsonl"
    return (
        'attachment; filename="annotations.jsonl"; '
        f"filename*=UTF-8''{quote(export_name)}"
    )


@app.post("/result/{task_id}/export-annotations")
def export_annotations_endpoint(task_id: str, body: dict[str, Any] | None = None):
    # 同步端点：FastAPI 会放入线程池执行，避免 PyTorch 推理阻塞事件循环。
    body = body or {}
    raw_rules = body.get("rules", [])
    if not isinstance(raw_rules, list):
        return JSONResponse(status_code=400, content={"message": "rules 必须是数组"})

    valid_rule_ids = {rule["id"] for rule in ANNOTATION_RULE_OPTIONS}
    rule_ids = [
        str(rule_id) for rule_id in raw_rules if str(rule_id) in valid_rule_ids
    ]
    model_id = str(body.get("model_id") or "").strip()
    if model_id and not _MODEL_ID_PATTERN.fullmatch(model_id):
        return JSONResponse(status_code=400, content={"message": "model_id 格式错误"})
    try:
        threshold = float(body.get("model_conf_threshold") or 0)
    except (TypeError, ValueError):
        threshold = 0.0
    threshold = min(max(threshold, 0.0), 1.0)

    if not rule_ids and not model_id:
        return JSONResponse(
            status_code=400, content={"message": "请至少选择一个标注规则或模型"}
        )

    markdown_text = load_task_markdown(task_id)
    if markdown_text is None:
        return JSONResponse(status_code=404, content={"message": "Markdown not found for this task"})

    try:
        file_name = get_task_file_name(task_id)
        rows = build_annotation_export_rows(
            markdown_text,
            task_id=task_id,
            file_name=file_name,
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
    file_stem = Path(file_name).stem or task_id[:8]
    headers = {"Content-Disposition": build_export_content_disposition(file_stem)}
    return Response(content=content, media_type="application/x-ndjson", headers=headers)


@app.put("/result/{task_id}/md")
async def save_result_md(task_id: str, body: dict[str, Any]):
    md_path = find_task_md_path(task_id)

    if not md_path or not os.path.exists(md_path):
        return JSONResponse(status_code=404, content={"message": "Markdown file not found for this task"})

    content = body.get("content", "")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)

    return {"success": True, "message": "Markdown saved"}


@app.get("/result/{task_id}/images/{image_path:path}")
async def get_result_image(task_id: str, image_path: str):
    # 优先使用任务记录中的 images_dir
    task = progress_store.get(task_id)
    if task and task.get("result") and task["result"].get("images_dir"):
        images_dir = task["result"]["images_dir"]
        full_path = os.path.join(images_dir, image_path)
        if os.path.exists(full_path):
            return FileResponse(full_path)
            
    # 如果不在内存中，尝试实时扫描
    output_dir = get_task_output_dir(task_id)
    if os.path.exists(output_dir):
        _, _, images_dir = find_mineru_output_files(output_dir)
        if images_dir:
            full_path = os.path.join(images_dir, image_path)
            if os.path.exists(full_path):
                return FileResponse(full_path)
                
    return JSONResponse(status_code=404, content={"message": "Image not found"})


# ── 训练数据集库 ──────────────────────────────────────────

@app.post("/datasets/upload")
async def upload_dataset_endpoint(
    file: UploadFile = File(...),
    name: str = Form(""),
):
    raw = await file.read()
    if len(raw) > DATASET_MAX_UPLOAD_BYTES:
        limit_mb = DATASET_MAX_UPLOAD_BYTES // (1024 * 1024)
        return JSONResponse(
            status_code=413,
            content={"message": f"文件过大，最大支持 {limit_mb}MB"},
        )
    try:
        # utf-8-sig 兼容 Windows 保存的带 BOM 文件。
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return JSONResponse(
            status_code=400,
            content={"message": "文件编码错误，请上传 UTF-8 编码的 JSONL 文件"},
        )
    try:
        meta = await run_in_threadpool(save_dataset, content, file.filename or "", name)
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
    raw_dataset_ids = body.get("dataset_ids") or []
    if not isinstance(raw_dataset_ids, list):
        return JSONResponse(status_code=400, content={"message": "dataset_ids 格式错误"})
    dataset_ids = [str(item) for item in raw_dataset_ids if str(item).strip()]
    if not dataset_ids:
        return JSONResponse(status_code=400, content={"message": "请至少选择一个训练数据集"})

    try:
        examples = await run_in_threadpool(load_dataset_examples, dataset_ids)
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


# ── 模型训练：上传 JSONL 数据集 ──────────────────────────────

@app.post("/model/upload-and-train")
async def upload_and_train_endpoint(
    file: UploadFile = File(...),
    model_name: str = Form("未命名模型"),
    epochs: int = Form(0),
    batch_size: int = Form(0),
    lr: float = Form(0),
):
    """上传 Doccano JSONL 训练数据并启动训练（SSE 流返回进度）。"""
    try:
        content = (await file.read()).decode("utf-8")
    except UnicodeDecodeError:
        return JSONResponse(status_code=400, content={"message": "文件编码错误，请上传 UTF-8 编码的 JSONL 文件"})

    examples = parse_jsonl_training_data(content)
    if not examples:
        return JSONResponse(status_code=400, content={"message": "未解析到有效训练数据，请检查 JSONL 格式"})

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


# ── 模型下载 ──────────────────────────────────────────────

@app.get("/model/download/{model_id}")
async def download_model_endpoint(model_id: str):
    """将训练好的模型打包下载为 ZIP 文件。"""
    model_dir = Path(__file__).resolve().parent / "models" / model_id
    if not model_dir.exists():
        return JSONResponse(status_code=404, content={"message": "Model not found"})

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(model_dir):
            for filename in files:
                file_path = os.path.join(root, filename)
                arcname = os.path.relpath(file_path, model_dir)
                zf.write(file_path, arcname)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=model-{model_id}.zip"},
    )


# ── 模型清理 ──────────────────────────────────────────────

@app.delete("/models/{model_id}/clear")
async def clear_model_endpoint(model_id: str):
    """清理指定模型（删除模型目录及缓存）。"""
    try:
        delete_model(model_id)
        return {"message": "ok"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"清理失败: {str(e)}"})


# ── 模型评估 ──────────────────────────────────────────────

@app.post("/model/evaluate")
async def evaluate_model_endpoint(
    model_id: str = Form(...),
    file: UploadFile = File(...),
):
    """上传测试 JSONL 文件，评估指定模型的 NER 性能"""
    try:
        content = (await file.read()).decode("utf-8")
    except UnicodeDecodeError:
        return JSONResponse(status_code=400, content={"message": "文件编码错误，请上传 UTF-8 编码的 JSONL 文件"})

    test_examples = parse_jsonl_training_data(content)
    if not test_examples:
        return JSONResponse(status_code=400, content={"message": "未解析到有效测试数据，请检查 JSONL 格式"})

    try:
        result = evaluate_model(model_id, test_examples)
        return result
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"评估失败: {str(e)}"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8267)

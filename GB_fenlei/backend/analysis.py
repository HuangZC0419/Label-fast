# -*- coding: utf-8 -*-
"""上传文件的体检分析：参照表分类分布、脏数据识别、待分类目录概览。"""

import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from classifier import build_reference
from config import COLUMN_ALIASES
from excel_io import (
    ExcelError,
    group_pending_records,
    pick,
    read_reference_full,
    read_table,
    variant_code_key,
)
from mining import keyword_report, mine_terms
from text import normalize_code, normalize_name


LOGGER = logging.getLogger("aircraft_standard_classifier")


def _used_header(header: Sequence[str], field: str) -> str:
    """返回文件中实际使用的列名，用于导出时沿用原始用词。"""
    for alias in COLUMN_ALIASES[field]:
        if alias in header:
            return alias
    return ""


def _row_numbers(rows: Sequence[Dict[str, Any]]) -> List[int]:
    result: List[int] = []
    for row in rows:
        value = row.get("_row", row.get("row"))
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return result


def _reference_rows(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把参照表原始行整理成体检用的统一结构。"""
    rows: List[Dict[str, Any]] = []
    for record in records:
        code = pick(record, "code")
        name = pick(record, "name")
        profession = pick(record, "profession")
        system = pick(record, "system")
        if not (code or name or profession or system):
            continue
        rows.append({
            "row": record.get("_row", ""),
            "code": code,
            "name": name,
            "profession": profession,
            "system": system,
            "code_key": normalize_code(code),
            "code_family": variant_code_key(code) if code else "",
            "name_key": normalize_name(name),
        })
    return rows


def _conflict_groups(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同标准号 + 同标准名称，但选用专业不一致。

    模型只预测专业，系统差异不构成训练冲突；系统不一致由
    ``_profession_multiple_systems`` 单独提示。
    """
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["code_family"] and row["name_key"]:
            groups[(row["code_family"], row["name_key"])].append(row)

    conflicts: List[Dict[str, Any]] = []
    for group in groups.values():
        professions = {item["profession"] for item in group}
        if len(professions) <= 1:
            continue
        first = group[0]
        conflicts.append({
            "code": first["code"],
            "name": first["name"],
            "count": len(group),
            "rows": _row_numbers(group),
            "professions": sorted(professions),
            "systems": sorted({item["system"] for item in group}),
            "detail": [
                {
                    "row": item.get("row", ""),
                    "profession": item["profession"],
                    "system": item["system"],
                }
                for item in group
            ],
        })
    conflicts.sort(
        key=lambda item: (
            min(item["rows"]) if item["rows"] else 0,
            item["code"],
        )
    )
    return conflicts


def _duplicate_groups(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[str, str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[
            (row["code_key"], row["name_key"], row["profession"], row["system"])
        ].append(row)
    result: List[Dict[str, Any]] = []
    for group in groups.values():
        if len(group) <= 1:
            continue
        first = group[0]
        result.append({
            "code": first["code"],
            "name": first["name"],
            "profession": first["profession"],
            "system": first["system"],
            "count": len(group),
            "rows": _row_numbers(group),
        })
    return result


def _same_name_different_code(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["name_key"]:
            groups[row["name_key"]].append(row)
    result: List[Dict[str, Any]] = []
    for group in groups.values():
        families = {item["code_family"] for item in group if item["code_family"]}
        codes = sorted({item["code"] for item in group if item["code"]})
        if len(families) <= 1:
            continue
        professions = sorted({item["profession"] for item in group if item["profession"]})
        systems = sorted({item["system"] for item in group if item["system"]})
        result.append({
            "name": group[0]["name"],
            "codes": codes,
            "count": len(group),
            "rows": _row_numbers(group),
            "professions": professions,
            "systems": systems,
            "same_profession": len(professions) <= 1,
            "severity": "info" if len(professions) <= 1 else "warning",
        })
    return result


def _same_code_different_name(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["code_family"]:
            groups[row["code_family"]].append(row)
    result: List[Dict[str, Any]] = []
    for group in groups.values():
        names = sorted({item["name"] for item in group if item["name"]})
        if len(names) <= 1:
            continue
        professions = sorted({item["profession"] for item in group if item["profession"]})
        systems = sorted({item["system"] for item in group if item["system"]})
        result.append({
            "code": group[0]["code"],
            "names": names,
            "count": len(group),
            "rows": _row_numbers(group),
            "professions": professions,
            "systems": systems,
            "same_profession": len(professions) <= 1,
            "severity": "info" if len(professions) <= 1 else "warning",
        })
    return result


def _profession_multiple_systems(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    systems: Dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        if row["profession"] and row["system"]:
            systems[row["profession"]][row["system"]] += 1
    result: List[Dict[str, Any]] = []
    for profession, counter in systems.items():
        if len(counter) <= 1:
            continue
        result.append({
            "profession": profession,
            "systems": [
                {"system": system, "count": count}
                for system, count in counter.most_common()
            ],
        })
    return result


def analyze_reference_file(path: Path) -> Dict[str, Any]:
    """分析已分类参照表：分类分布、国标号清单、脏数据与训练排除量。"""
    header, records, _mapping_rows, sheet = read_reference_full(path)
    rows = _reference_rows(records)

    conflicts = _conflict_groups(rows)
    conflict_rows = {row for group in conflicts for row in group["rows"]}

    # 训练集排除：同号同名、同名不同号、同号不同名，只要分类不一致就排除。
    labels_by_name: Dict[str, set] = defaultdict(set)
    labels_by_code: Dict[str, set] = defaultdict(set)
    for row in rows:
        if not row["profession"]:
            continue
        # 只按专业判断冲突：模型预测的是专业，系统差异不构成训练冲突。
        label = row["profession"]
        if row["name_key"]:
            labels_by_name[row["name_key"]].add(label)
        if row["code_family"]:
            labels_by_code[row["code_family"]].add(label)

    training_excluded_rows = set(conflict_rows)
    training_exclusions: List[Dict[str, Any]] = []

    def add_training_exclusion(
        exclusion_type: str,
        group: Sequence[Dict[str, Any]],
        key: str,
    ) -> None:
        professions = sorted({row["profession"] for row in group if row["profession"]})
        if len(professions) <= 1:
            return
        labels = sorted({(row["profession"], row["system"]) for row in group})
        group_rows = _row_numbers(group)
        if not group_rows or set(group_rows).issubset(training_excluded_rows):
            return
        training_excluded_rows.update(group_rows)
        training_exclusions.append({
            "type": exclusion_type,
            "key": key,
            "labels": [
                {"profession": profession, "system": system}
                for profession, system in labels
            ],
            "rows": group_rows,
            "count": len(group_rows),
        })

    for name_key, labels in labels_by_name.items():
        if len(labels) <= 1:
            continue
        group = [row for row in rows if row["name_key"] == name_key]
        add_training_exclusion("同名不同分类", group, group[0]["name"])

    for code_family, labels in labels_by_code.items():
        if len(labels) <= 1:
            continue
        group = [row for row in rows if row["code_family"] == code_family]
        add_training_exclusion("同号不同分类", group, group[0]["code"])

    categories: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        profession = row["profession"] or "（未填写专业）"
        bucket = categories.setdefault(
            profession,
            {
                "profession": profession,
                "count": 0,
                "trainable_count": 0,
                "systems": Counter(),
                "entries": [],
            },
        )
        bucket["count"] += 1
        if row["system"]:
            bucket["systems"][row["system"]] += 1
        is_trainable = bool(
            row["name"]
            and row["profession"]
            and row.get("row") not in training_excluded_rows
        )
        if is_trainable:
            bucket["trainable_count"] += 1
        bucket["entries"].append({
            "row": row.get("row", ""),
            "code": row["code"],
            "name": row["name"],
            "system": row["system"],
            "excluded": row.get("row") in training_excluded_rows,
        })

    category_list: List[Dict[str, Any]] = []
    for bucket in categories.values():
        systems = [
            {"system": system, "count": count}
            for system, count in bucket["systems"].most_common()
        ]
        # 系统名称只取参照表中该专业的多数票；没有记录时留空。
        system_name = systems[0]["system"] if systems else ""
        category_list.append({
            "profession": bucket["profession"],
            "system": system_name,
            "systems": systems,
            "count": bucket["count"],
            "trainable_count": bucket["trainable_count"],
            "excluded_count": bucket["count"] - bucket["trainable_count"],
            "entries": bucket["entries"],
        })
    category_list.sort(key=lambda item: (-item["count"], item["profession"]))

    missing_name = [row for row in rows if not row["name"]]
    missing_profession = [row for row in rows if not row["profession"]]
    missing_system = [row for row in rows if not row["system"]]
    missing_code = [row for row in rows if not row["code"]]

    trainable_rows = [
        row for row in rows
        if row["name"] and row["profession"]
        and row.get("row") not in training_excluded_rows
    ]
    usable_rows = len(trainable_rows)

    quality = {
        "conflicts": conflicts,
        "conflict_group_count": len(conflicts),
        "conflict_row_count": len(conflict_rows),
        "duplicates": _duplicate_groups(rows),
        "same_name_different_code": _same_name_different_code(rows),
        "same_code_different_name": _same_code_different_name(rows),
        "profession_multiple_systems": _profession_multiple_systems(rows),
        "missing": {
            "name": {"count": len(missing_name), "rows": _row_numbers(missing_name)},
            "profession": {
                "count": len(missing_profession),
                "rows": _row_numbers(missing_profession),
            },
            "system": {"count": len(missing_system), "rows": _row_numbers(missing_system)},
            "code": {"count": len(missing_code), "rows": _row_numbers(missing_code)},
        },
        "training_exclusions": training_exclusions,
        "training_excluded_rows": len(training_excluded_rows),
    }

    keyword_rows: List[Dict[str, Any]] = []
    try:
        reference = build_reference(records, _mapping_rows)
        mined = mine_terms(reference.training_examples)
        keyword_rows = keyword_report(
            mined,
            reference.training_examples,
            reference.system_map,
        )
    except ExcelError as exc:
        LOGGER.info("参照表没有可训练数据，分类依据词表为空：%s", exc)
    except Exception:
        LOGGER.warning("参照表分类依据词表生成失败，已降级", exc_info=True)

    return {
        "file": {
            "name": Path(path).name,
            "size": Path(path).stat().st_size,
            "sheet": sheet,
        },
        "columns": {
            "code": _used_header(header, "code"),
            "name": _used_header(header, "name"),
            "system": _used_header(header, "system"),
            "profession": _used_header(header, "profession"),
        },
        "raw_rows": len(rows),
        "usable_rows": usable_rows,
        "training_rows": usable_rows,
        "excluded_rows": len(training_excluded_rows),
        "training_category_count": len(
            [item for item in category_list if item["trainable_count"] > 0]
        ),
        "categories": category_list,
        "quality": quality,
        "keyword_report": keyword_rows,
    }


def analyze_pending_file(path: Path) -> Dict[str, Any]:
    """分析待分类目录：按标准号+名称归并，区分自动分类与人工分类。"""
    header, records, sheet = read_table(
        path, required_fields=("name",), source="待分类目录"
    )
    items, reports, meta = group_pending_records(records)
    if not items:
        raise ExcelError("INVALID_FILE", "待分类目录没有可用的标准名称")

    missing_name_rows = [
        record.get("_row", "")
        for record in records
        if not pick(record, "name")
    ]
    header_row = 1
    if records:
        try:
            header_row = int(
                records[0].get(
                    "_header_row", int(records[0].get("_row", 2)) - 1
                )
            )
        except (TypeError, ValueError):
            header_row = 1

    preview = [
        {
            "index": item["index"],
            "code": item["code"],
            "name": item["name"],
            "units": item["units"],
            "count": item["count"],
            "status": item["status"],
            "reason": item["reason"],
            "needs_confirmation": item["needs_confirmation"],
        }
        for item in items[:80]
    ]

    return {
        "file": {
            "name": Path(path).name,
            "size": Path(path).stat().st_size,
            "sheet": sheet,
            "header_row": header_row,
        },
        "columns": {
            "code": _used_header(header, "code"),
            "name": _used_header(header, "name"),
            "unit": _used_header(header, "unit"),
        },
        "raw_rows": meta["raw_rows"],
        "unique_rows": meta["unique_rows"],
        "group_count": meta["group_count"],
        "auto_count": meta["auto_count"],
        "manual_count": meta["manual_count"],
        "multi_unit_count": meta["multi_unit_count"],
        "exact_duplicate_rows": meta["exact_duplicate_rows"],
        "duplicate_rows": meta["exact_duplicate_rows"],
        "dedup_basis": meta["dedup_basis"],
        "missing_name_count": len(missing_name_rows),
        "missing_name_rows": missing_name_rows,
        "reports": list(reports),
        "items": list(items),
        "preview": preview,
    }

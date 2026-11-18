#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导出混合标注项目的标注明细 Excel（一条知识/一张图表一行）。

扫描 mixed_annotation/backend/data/projects 下的所有项目，只处理
annotations.json 中存在实体（spans）或图表（figures）的文件：

- 每个实体单独一行：类型=知识，内容=span.text，标签=span.label；
- 每张图表单独一行：类型=图表，内容=图表名称，标签=图/表，
  图表完整路径指向 assets/figures 下的本地文件；
- 每行都带项目名称、文件名称、该文件的知识数/图表数、文件地址、
  标注文件路径与最后更新时间；
- 最左侧为连续编号。

用法（Windows）：
    cd /d H:\\Git\\1CF_win11\\数据标注与分类工具
    python export_annotation_summary.py
    python export_annotation_summary.py --projects-dir <目录> --output <xlsx>

依赖：openpyxl。脚本只读数据，不会修改任何标注文件。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    print("[错误] 缺少 openpyxl，请在 CFwin11 环境中运行本脚本。")
    print("       E:\\Anaconda\\envs\\CFwin11\\python.exe export_annotation_summary.py")
    sys.exit(1)


DEFAULT_PROJECTS_DIR = (
    Path(__file__).resolve().parent
    / "mixed_annotation"
    / "backend"
    / "data"
    / "projects"
)

HEADERS = [
    "编号",
    "项目名称",
    "文件名称",
    "类型",
    "内容",
    "标签",
    "文件知识数",
    "文件图表数",
    "文件存储地址",
    "标注文件路径",
    "图表完整路径",
    "最后更新时间",
]

COLUMN_WIDTHS = [6, 16, 40, 8, 58, 12, 10, 10, 55, 65, 65, 20]
SUMMARY_FILL = PatternFill("solid", fgColor="DCE6F1")
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(color="FFFFFF", bold=True)
THIN = Side(style="thin", color="B7C4D4")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(vertical="top", wrap_text=True)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)


def load_json(path: Path) -> Any:
    """读取 UTF-8 JSON；失败返回 None，由调用方跳过该文件。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None


def as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def clean_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def figure_name(figure: Dict[str, Any]) -> str:
    """图表名称：caption → 资产文件名去扩展名 → figure id。"""
    caption = clean_text(figure.get("caption"))
    if caption:
        return caption
    asset_path = clean_text(
        figure.get("assetPath") or figure.get("asset_path")
    ).replace("\\", "/")
    if asset_path:
        name = asset_path.rsplit("/", 1)[-1]
        if name.lower().endswith(".png"):
            name = name[:-4]
        if name:
            return name
    return clean_text(figure.get("id")) or "(未命名图表)"


def figure_asset_abs(file_dir: Path, figure: Dict[str, Any]) -> str:
    """把 assetPath 解析为文件目录下的绝对路径。"""
    raw = clean_text(figure.get("assetPath") or figure.get("asset_path"))
    if not raw:
        return ""
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    if not name:
        return ""
    return str((file_dir / "assets" / "figures" / name).resolve())


def collect_entries(
    projects_dir: Path,
) -> Tuple[List[Dict[str, Any]], Dict[str, int], List[str]]:
    """按条目展开：每个实体/图表一行。"""
    entries: List[Dict[str, Any]] = []
    warnings: List[str] = []
    project_names = set()
    file_keys = set()
    skipped_unannotated = 0
    scanned_files = 0

    for project_dir in sorted(projects_dir.iterdir(), key=lambda p: p.name):
        if not project_dir.is_dir():
            continue
        project_meta = load_json(project_dir / "project.json")
        if not isinstance(project_meta, dict):
            project_meta = {}
        project_name = clean_text(project_meta.get("name")) or project_dir.name

        files_dir = project_dir / "files"
        if not files_dir.is_dir():
            continue

        for file_dir in sorted(files_dir.iterdir(), key=lambda p: p.name):
            if not file_dir.is_dir():
                continue
            meta_path = file_dir / "meta.json"
            if not meta_path.is_file():
                continue
            scanned_files += 1

            meta = load_json(meta_path)
            if not isinstance(meta, dict):
                warnings.append("无法读取文件元数据：%s" % meta_path)
                continue
            file_name = clean_text(meta.get("name")) or file_dir.name

            ann_path = file_dir / "annotations.json"
            if not ann_path.is_file():
                skipped_unannotated += 1
                continue

            annotations = load_json(ann_path)
            if not isinstance(annotations, dict):
                warnings.append("标注文件无法解析：%s" % ann_path)
                continue

            spans = as_list(annotations.get("spans"))
            figures = as_list(annotations.get("figures"))

            # 只输出有知识或图表的文件；关系和段落不单独成行。
            if not spans and not figures:
                skipped_unannotated += 1
                continue

            knowledge_count = len(spans)
            figure_count = len(figures)
            updated_at = (
                clean_text(annotations.get("updated_at"))
                or clean_text(meta.get("updated_at"))
            )
            file_path = str(file_dir.resolve())
            ann_abs = str(ann_path.resolve())
            project_names.add(project_name)
            file_keys.add(str(file_dir.resolve()))

            for span in spans:
                if not isinstance(span, dict):
                    continue
                content = (
                    clean_text(span.get("text"))
                    or clean_text(span.get("label"))
                    or "(空内容)"
                )
                entries.append(
                    {
                        "project": project_name,
                        "file": file_name,
                        "type": "知识",
                        "content": content,
                        "label": clean_text(span.get("label")),
                        "knowledge_count": knowledge_count,
                        "figure_count": figure_count,
                        "file_path": file_path,
                        "annotation_path": ann_abs,
                        "figure_path": "",
                        "updated_at": updated_at,
                    }
                )

            for figure in figures:
                if not isinstance(figure, dict):
                    continue
                kind = clean_text(figure.get("kind")).lower()
                entries.append(
                    {
                        "project": project_name,
                        "file": file_name,
                        "type": "图表",
                        "content": figure_name(figure),
                        "label": "表" if kind == "table" else "图",
                        "knowledge_count": knowledge_count,
                        "figure_count": figure_count,
                        "file_path": file_path,
                        "annotation_path": ann_abs,
                        "figure_path": figure_asset_abs(file_dir, figure),
                        "updated_at": updated_at,
                    }
                )

    entries.sort(key=lambda item: (item["project"], item["file"]))
    stats = {
        "projects": len(project_names),
        "files": len(file_keys),
        "knowledge": sum(1 for item in entries if item["type"] == "知识"),
        "figures": sum(1 for item in entries if item["type"] == "图表"),
        "entries": len(entries),
        "scanned_files": scanned_files,
        "skipped_unannotated": skipped_unannotated,
    }
    return entries, stats, warnings


def content_row_height(content: str) -> float:
    """按内容长度估算行高，避免长实体文本被截断。"""
    length = max(1, len(content))
    lines = max(1, math.ceil(length / 42))
    return min(150, max(30, 15 * lines + 6))


def write_excel(
    entries: List[Dict[str, Any]], stats: Dict[str, int], output: Path
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "标注明细"

    for col_index, header in enumerate(HEADERS, start=1):
        cell = sheet.cell(row=1, column=col_index, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = CENTER
        cell.border = BORDER
        sheet.column_dimensions[get_column_letter(col_index)].width = COLUMN_WIDTHS[
            col_index - 1
        ]

    for row_index, item in enumerate(entries, start=2):
        values = [
            row_index - 1,
            item["project"],
            item["file"],
            item["type"],
            item["content"],
            item["label"],
            item["knowledge_count"],
            item["figure_count"],
            item["file_path"],
            item["annotation_path"],
            item["figure_path"],
            item["updated_at"],
        ]
        for col_index, value in enumerate(values, start=1):
            cell = sheet.cell(row=row_index, column=col_index, value=value)
            cell.border = BORDER
            if col_index in (1, 4, 6, 7, 8):
                cell.alignment = Alignment(horizontal="center", vertical="top")
            else:
                cell.alignment = WRAP
            if col_index in (7, 8):
                cell.number_format = "0"
        sheet.row_dimensions[row_index].height = content_row_height(item["content"])

    summary_row = len(entries) + 2
    summary_values = [
        "合计",
        "%d 个项目" % stats["projects"],
        "%d 个文件" % stats["files"],
        "",
        "知识 %d 条 / 图表 %d 张" % (stats["knowledge"], stats["figures"]),
        "",
        stats["knowledge"],
        stats["figures"],
        "",
        "",
        "",
        "",
    ]
    for col_index, value in enumerate(summary_values, start=1):
        cell = sheet.cell(row=summary_row, column=col_index, value=value)
        cell.font = Font(bold=True)
        cell.fill = SUMMARY_FILL
        cell.border = BORDER
        cell.alignment = (
            Alignment(horizontal="center", vertical="center")
            if col_index in (1, 4, 6, 7, 8)
            else Alignment(vertical="center")
        )

    sheet.freeze_panes = "A2"
    if entries:
        sheet.auto_filter.ref = "A1:L%d" % (len(entries) + 1)
    sheet.sheet_view.zoomScale = 90

    output.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(str(output))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="导出混合标注项目明细 Excel（每个知识/图表单独一行）"
    )
    parser.add_argument(
        "--projects-dir",
        type=Path,
        default=DEFAULT_PROJECTS_DIR,
        help="混合标注 projects 目录（默认：项目内 mixed_annotation/backend/data/projects）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="输出 xlsx 路径（默认：脚本所在目录/混合标注标注明细_时间戳.xlsx）",
    )
    args = parser.parse_args()

    projects_dir = args.projects_dir.expanduser().resolve()
    if not projects_dir.is_dir():
        print("[错误] 找不到项目目录：%s" % projects_dir)
        return 2

    output = args.output
    if output is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = Path(__file__).resolve().parent / ("混合标注标注明细_%s.xlsx" % stamp)
    else:
        output = output.expanduser().resolve()

    entries, stats, warnings = collect_entries(projects_dir)
    write_excel(entries, stats, output)

    print("=" * 68)
    print("混合标注标注明细已生成")
    print("  项目目录：%s" % projects_dir)
    print("  输出文件：%s" % output)
    print(
        "  扫描文件：%d 个；有知识的文件：%d 个；跳过无知识/图表：%d 个"
        % (stats["scanned_files"], stats["files"], stats["skipped_unannotated"])
    )
    print(
        "  明细行：%d 行（知识 %d 条 + 图表 %d 张）；涉及 %d 个项目"
        % (stats["entries"], stats["knowledge"], stats["figures"], stats["projects"])
    )
    if warnings:
        print("  警告（已跳过）：")
        for item in warnings[:10]:
            print("    - %s" % item)
        if len(warnings) > 10:
            print("    ... 其余 %d 条" % (len(warnings) - 10))
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""按所选项目导出「标注明细」Excel 的服务层。

能力等价于仓库根目录的 ``export_annotation_summary.py``，区别只有导出范围：
脚本扫描整个 projects 目录，本服务只导出前端选中的项目（可多选）。列字段、
样式、行高、排序列与汇总行都保持一致，便于两个入口产出同构的工作簿。

设计约束：

- 只通过 ``storage`` 的数据访问函数取数，不直接拼 ``data/projects`` 路径，
  保证目录布局演进（项目目录改名、文件目录按显示名命名）不会影响导出；
- 函数全部同步实现：读标注、读元数据、写 xlsx 都是阻塞 IO，由路由层放到
  线程池执行，避免占用事件循环；
- 不吞异常：``load_annotations`` 对损坏 JSON 抛 500 业务异常，这里不捕获，
  由全局异常处理器统一转成 JSON 错误，前端能明确知道是哪一份数据坏了；
- 无日志噪音：本服务只做纯数据转换，是否需要记录统计由调用方决定。

行序规则：最终按（项目名称, 文件名称）排序；同一文件内知识行在前、图表行
在后（与脚本的追加顺序一致，Python 排序稳定因此不会打乱）。
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from storage import (
    file_dir,
    figure_asset_path,
    get_project,
    has_annotations,
    list_files,
    load_annotations,
)

# 以下常量与 export_annotation_summary.py 逐项对齐，修改时两侧必须同步。
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
# 明细行中需要水平居中的列：编号/类型/文件知识数/文件图表数。
_CENTER_COLUMNS = (1, 4, 6, 7, 8)
_COUNT_COLUMNS = (7, 8)

SHEET_TITLE = "标注明细"

# 行高估算：每行约 42 个字符，行高限制在 30~150 之间。
_CHARS_PER_LINE = 42
_ROW_HEIGHT_MIN = 30
_ROW_HEIGHT_MAX = 150


def _clean(value: Any) -> str:
    """去除首尾空白；``None`` 视为空串，避免单元格出现 "None"。"""

    return str(value).strip() if value is not None else ""


def _unique_ids(project_ids: list[str]) -> list[str]:
    """去空白、去重且保持传入顺序；空串直接丢弃（路由层已校验非空）。"""

    ordered: list[str] = []
    seen: set[str] = set()
    for raw in project_ids:
        value = _clean(raw)
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def figure_name(figure: dict[str, Any]) -> str:
    """图表名称：caption → 资产文件名去扩展名 → figure id → 「(未命名图表)」。"""

    caption = _clean(figure.get("caption"))
    if caption:
        return caption
    # 兼容历史上用 snake_case 写入的记录。
    asset_path = _clean(figure.get("assetPath") or figure.get("asset_path")).replace(
        "\\", "/"
    )
    if asset_path:
        name = asset_path.rsplit("/", 1)[-1]
        if name.lower().endswith(".png"):
            name = name[:-4]
        if name:
            return name
    return _clean(figure.get("id")) or "(未命名图表)"


def _figure_abs_path(meta: dict[str, Any], figure: dict[str, Any]) -> str:
    """图表资产的绝对路径；资产不存在或路径非法时返回空串。

    路径解析统一交给 ``storage.figure_asset_path``，它会拒绝目录穿越与非
    ``assets/figures/<单层文件名>`` 形式，避免导出表里出现越界路径。
    """

    raw = _clean(figure.get("assetPath") or figure.get("asset_path"))
    if not raw:
        return ""
    path = figure_asset_path(meta, raw)
    if path is None or not path.is_file():
        return ""
    return str(path.resolve())


def _file_entries(
    project_name: str,
    meta: dict[str, Any],
    file_name: str,
    knowledge_count: int,
    figure_count: int,
    file_path: str,
    annotation_path: str,
    updated_at: str,
    spans: list[dict[str, Any]],
    figures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """把一个文件展开为「知识行 + 图表行」。"""

    rows: list[dict[str, Any]] = []
    common = {
        "project": project_name,
        "file": file_name,
        "knowledge_count": knowledge_count,
        "figure_count": figure_count,
        "file_path": file_path,
        "annotation_path": annotation_path,
        "updated_at": updated_at,
    }

    for span in spans:
        rows.append(
            {
                **common,
                "type": "知识",
                # 内容兜底顺序：实体文本 → 标签 → 「(空内容)」。
                "content": _clean(span.get("text"))
                or _clean(span.get("label"))
                or "(空内容)",
                "label": _clean(span.get("label")),
                "figure_path": "",
            }
        )

    for figure in figures:
        kind = _clean(figure.get("kind")).lower()
        rows.append(
            {
                **common,
                "type": "图表",
                "content": figure_name(figure),
                "label": "表" if kind == "table" else "图",
                "figure_path": _figure_abs_path(meta, figure),
            }
        )

    return rows


def collect_entries(
    project_ids: list[str],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """按所选项目收集明细行与统计信息。

    - 项目按名称排序（同名时用 id 兜底，保证顺序稳定）；
    - 不存在/非法 id 由 ``get_project`` 抛 ``NotFoundError``（404）；
    - 没有标注、或有标注记录但既无知识又无图表的文件跳过并计入
      ``skipped_unannotated``，与脚本口径一致。
    """

    ids = _unique_ids(project_ids)
    projects = [get_project(project_id) for project_id in ids]
    projects.sort(
        key=lambda item: (_clean(item.get("name")), str(item.get("id") or ""))
    )

    entries: list[dict[str, Any]] = []
    project_names: set[str] = set()
    file_paths: set[str] = set()
    scanned_files = 0
    skipped_unannotated = 0

    for project in projects:
        project_id = str(project.get("id") or "")
        project_name = _clean(project.get("name")) or project_id

        for meta in list_files(project_id):
            if not isinstance(meta, dict):
                continue
            file_id = str(meta.get("id") or "")
            if not file_id:
                continue
            scanned_files += 1

            if not has_annotations(file_id):
                skipped_unannotated += 1
                continue

            annotations = load_annotations(file_id)
            spans = [
                item for item in annotations.get("spans") or [] if isinstance(item, dict)
            ]
            figures = [
                item
                for item in annotations.get("figures") or []
                if isinstance(item, dict)
            ]
            # 关系和段落不单独成行；两者都没有的文件同样跳过。
            if not spans and not figures:
                skipped_unannotated += 1
                continue

            directory = file_dir(meta)
            # 元数据缺少展示名时退化为目录名，与脚本的兜底口径一致。
            file_name = _clean(meta.get("name")) or directory.name
            resolved_dir = directory.resolve()
            annotation_file = (directory / "annotations.json").resolve()
            updated_at = _clean(annotations.get("updated_at")) or _clean(
                meta.get("updated_at")
            )
            project_names.add(project_name)
            file_paths.add(str(resolved_dir))

            entries.extend(
                _file_entries(
                    project_name=project_name,
                    meta=meta,
                    file_name=file_name,
                    knowledge_count=len(spans),
                    figure_count=len(figures),
                    file_path=str(resolved_dir),
                    annotation_path=str(annotation_file),
                    updated_at=updated_at,
                    spans=spans,
                    figures=figures,
                )
            )

    entries.sort(key=lambda item: (item["project"], item["file"]))

    stats = {
        "projects": len(project_names),
        "files": len(file_paths),
        "knowledge": sum(1 for item in entries if item["type"] == "知识"),
        "figures": sum(1 for item in entries if item["type"] == "图表"),
        "entries": len(entries),
        "scanned_files": scanned_files,
        "skipped_unannotated": skipped_unannotated,
    }
    return entries, stats


def content_row_height(content: str) -> float:
    """按内容长度估算行高，避免长实体文本被压成一行看不到。"""

    length = max(1, len(content))
    lines = max(1, math.ceil(length / _CHARS_PER_LINE))
    return min(_ROW_HEIGHT_MAX, max(_ROW_HEIGHT_MIN, 15 * lines + 6))


def write_workbook(
    entries: list[dict[str, Any]], stats: dict[str, int], output: Path
) -> None:
    """写出工作簿：表头 + 明细 + 汇总行，样式与脚本保持一致。"""

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET_TITLE

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
            if col_index in _CENTER_COLUMNS:
                cell.alignment = Alignment(horizontal="center", vertical="top")
            else:
                cell.alignment = WRAP
            if col_index in _COUNT_COLUMNS:
                cell.number_format = "0"
        sheet.row_dimensions[row_index].height = content_row_height(item["content"])

    # 汇总行紧跟在明细之后；无数据时也要输出，行内数值全为 0。
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
            if col_index in _CENTER_COLUMNS
            else Alignment(vertical="center")
        )

    sheet.freeze_panes = "A2"
    if entries:
        sheet.auto_filter.ref = "A1:L%d" % (len(entries) + 1)
    sheet.sheet_view.zoomScale = 90

    output.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(str(output))


def build_excel_export(project_ids: list[str], output: Path) -> dict[str, int]:
    """生成标注明细工作簿并返回统计信息。

    空选择或所选项目都没有可导出标注时仍会生成只有表头 + 汇总行的文件，
    不抛异常：前端多选后可能只命中空项目，报错反而没有意义。
    """

    entries, stats = collect_entries(project_ids)
    write_workbook(entries, stats, Path(output))
    return stats


def suggested_filename() -> str:
    """下载文件名：本地时间戳，避免同名覆盖。"""

    return "混合标注标注明细_%s.xlsx" % datetime.now().strftime("%Y%m%d_%H%M%S")

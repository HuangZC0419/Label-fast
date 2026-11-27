"""项目 ZIP 导出、图谱拉取与多项目 Excel 明细导出路由。"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from schemas import ExcelExportRequest
from services.excel_export_service import build_excel_export, suggested_filename
from services.export_service import (
    _assign_export_stems,
    _load_blocks_safe,
    _normalize_annotation,
    _prepare_figure,
    build_export_zip,
    build_graph_rows,
)
from storage import (
    get_project,
    has_annotations,
    list_files,
    load_annotations,
    read_markdown,
)
from utils import utc_now

router = APIRouter(prefix="/api/projects", tags=["export"])

GRAPH_MEDIA_TYPE = "application/x-ndjson; charset=utf-8"
EXCEL_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _remove_file(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


@router.post("/export-excel")
async def export_projects_excel(payload: ExcelExportRequest) -> FileResponse:
    """按所选项目导出标注明细工作簿。

    路径故意不带 ``{project_id}``：导出范围由请求体里的多选列表决定，
    资源不是单个项目。它声明在动态 GET 路由之前，避免与
    ``/{project_id}/...`` 系列产生匹配歧义。

    生成过程读大量标注 JSON 并写 xlsx，全是阻塞 IO，因此放到线程池；
    失败时先删除 mkstemp 留下的空文件再把业务异常抛给全局处理器。
    """

    fd, temp_name = tempfile.mkstemp(prefix="label-fast-excel-", suffix=".xlsx")
    os.close(fd)
    workbook_path = Path(temp_name)
    try:
        await asyncio.to_thread(
            build_excel_export, payload.project_ids, workbook_path
        )
    except BaseException:
        workbook_path.unlink(missing_ok=True)
        raise
    return FileResponse(
        workbook_path,
        media_type=EXCEL_MEDIA_TYPE,
        filename=suggested_filename(),
        background=BackgroundTask(_remove_file, str(workbook_path)),
    )


@router.get("/{project_id}/export-zip")
async def export_project(project_id: str) -> FileResponse:
    fd, temp_name = tempfile.mkstemp(prefix="label-fast-export-", suffix=".zip")
    os.close(fd)
    archive_path = Path(temp_name)
    try:
        archive_path, download_name = await asyncio.to_thread(
            build_export_zip, project_id, archive_path
        )
    except BaseException:
        archive_path.unlink(missing_ok=True)
        raise
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=download_name,
        background=BackgroundTask(_remove_file, str(archive_path)),
    )


def _collect_graph_rows(project_id: str) -> list[dict[str, Any]]:
    """按 ``build_export_zip`` 的文件收集顺序生成图谱行。

    复用了导出服务中已有的主名分配、blocks 懒构建、标注归一化与图表
    资产路径计算，保证结果与 ZIP 内 ``graph.jsonl`` 一致；区别仅在于
    不写 ZIP、不写临时文件。``blocks.json`` 缺失时会懒构建并落盘，这
    与 ZIP 导出的副作用一致。

    幂等只读语义，可安全放到线程池执行；项目不存在时由
    ``get_project`` 抛出 404 业务异常。
    """

    project = get_project(project_id)
    files = list_files(project_id)
    export_stems = _assign_export_stems(files)
    # 一次请求内共享导出时间，与 build_export_zip 的行为保持一致。
    exported_at = utc_now()

    graph_rows: list[dict[str, Any]] = []
    for meta in files:
        file_id = meta["id"]
        stem = export_stems[file_id]
        markdown_text = read_markdown(file_id)
        blocks = _load_blocks_safe(file_id, markdown_text)

        if has_annotations(file_id):
            record = load_annotations(file_id)
        else:
            record = {
                "text": "",
                "spans": [],
                "relations": [],
                "paragraphs": [],
                "figures": [],
            }

        text, spans, relations = _normalize_annotation(record, markdown_text)

        figure_exports: list[dict[str, Any]] = []
        asset_map: dict[str, str] = {}
        for raw_figure in record.get("figures", []):
            if not isinstance(raw_figure, dict):
                continue
            export_figure, _asset_file, relative, _missing = _prepare_figure(
                meta, raw_figure, stem=stem
            )
            figure_exports.append(export_figure)
            asset_map[str(raw_figure.get("id") or "")] = relative

        graph_rows.extend(
            build_graph_rows(
                project,
                meta,
                blocks,
                {
                    "text": text,
                    "spans": spans,
                    "relations": relations,
                    "paragraphs": record.get("paragraphs", []),
                    "figures": figure_exports,
                },
                asset_map,
                exported_at=exported_at,
            )
        )
    return graph_rows


def _render_graph_ndjson(project_id: str) -> str:
    """把图谱行序列化为 NDJSON 文本（行尾 ``\n``，空项目为空串）。"""

    rows = _collect_graph_rows(project_id)
    if not rows:
        return ""
    return (
        "\n".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":"))
            for row in rows
        )
        + "\n"
    )


@router.get("/{project_id}/graph.jsonl")
async def export_project_graph(project_id: str) -> Response:
    """直接返回与 ZIP 内 ``graph.jsonl`` 等价的 NDJSON，供知识库拉取。"""

    # 文件读取、blocks 懒构建均为阻塞 IO，放线程池避免占用事件循环。
    content = await asyncio.to_thread(_render_graph_ndjson, project_id)
    return Response(content=content, media_type=GRAPH_MEDIA_TYPE)

"""项目导出：原始文件 + Markdown + 图片 + 双文件标注 + 图表资产。

导出 ZIP 同时提供两套标注格式：

- ``annotations.jsonl``：兼容旧知识库导入器的一行一文件格式，新增
  ``paragraphs`` / ``figures`` / ``pages`` / ``meta`` 字段；
- ``graph.jsonl``：面向建图的节点 + 边格式，首行为 ``meta``。

图谱构建逻辑集中在本模块的纯函数 ``build_graph_rows`` 中，便于单元测试，
不依赖真实文件系统。
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from errors import NotFoundError, ServiceError
from services import block_service
from storage import (
    figure_asset_path,
    get_project,
    has_annotations,
    images_dir,
    list_files,
    load_annotations,
    markdown_path,
    read_markdown,
    source_path,
)
from utils import utc_now

EXPORT_VERSION = "labelfast-hybrid/v2"

_INVALID_COMPONENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)},
}
# 国标/行标编号形如 “GBT 4423-2020”“GB 1234—2020”。
_STANDARD_ID_RE = re.compile(r"^([A-Z]{2,}\s*[\d.]+(?:[-—]\d{4})?)")

_EMPTY_BLOCKS: dict[str, Any] = {
    "version": 1,
    "markdown_hash": "",
    "pages": [],
    "sections": [],
    "blocks": [],
}


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


def _safe_component(raw: str, fallback: str, limit: int = 80) -> str:
    text = _INVALID_COMPONENT.sub("_", str(raw or "")).strip().strip(".")
    if not text:
        text = fallback
    if text.split(".")[0].upper() in _WINDOWS_RESERVED:
        text = f"_{text}"
    return text[:limit]


def _file_folder(meta: dict[str, Any]) -> str:
    """导出主名：只使用上传文件名的 stem，不追加内部 id。"""

    name = Path(str(meta.get("name") or "file")).stem
    return _safe_component(name, "file")


def _assign_export_stems(files: list[dict[str, Any]]) -> dict[str, str]:
    """为每个文件分配导出主名，同名时依次追加 ``_2``、``_3``。

    去重状态在同一次导出的所有文件间共享（大小写不敏感，兼容 Windows），
    保证 original / markdown / blocks / assets 使用同一个主名。
    """

    used: set[str] = set()
    stems: dict[str, str] = {}
    for meta in files:
        base = _file_folder(meta)
        stem = base
        suffix = 2
        while stem.casefold() in used:
            stem = f"{base}_{suffix}"
            suffix += 1
        used.add(stem.casefold())
        stems[str(meta.get("id") or "")] = stem
    return stems


def extract_standard_id(file_name: str) -> str:
    """从文件名提取标准编号；无法识别时退化为去扩展名的文件名。"""

    name = str(file_name or "").strip()
    match = _STANDARD_ID_RE.match(name)
    if match:
        return match.group(1).strip()
    return Path(name).stem.strip() if name else ""


def _stringify(value: Any) -> str:
    """图谱 attributes 的值统一转为字符串。"""

    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _number_text(value: Any) -> str:
    """数值转字符串，整数值不带 ``.0`` 尾巴。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return str(number)


def _bbox_text(bbox: Any) -> str:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return ""
    return ",".join(_number_text(item) for item in bbox)


def _short_text(text: Any, limit: int = 80) -> str:
    collapsed = " ".join(str(text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit] + "…"


def _export_pages(pages: Any) -> list[dict[str, Any]]:
    """只保留 annotations.jsonl 需要的页面尺寸字段。"""

    if not isinstance(pages, list):
        return []
    result: list[dict[str, Any]] = []
    for item in pages:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "page": item.get("page", 0),
                "width": item.get("width", 0),
                "height": item.get("height", 0),
            }
        )
    return result


def _markdown_to_text(markdown: str) -> str:
    """无标注时生成可读的纯文本兜底，不作为前端 canonical text 使用。"""

    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"```[^\n]*\n(.*?)```", r"\1", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    lines: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if re.fullmatch(r"\|?[\s:|-]+\|?", stripped) and "-" in stripped:
            continue
        stripped = re.sub(r"^#{1,6}\s*", "", stripped)
        stripped = re.sub(r"^>\s*", "", stripped)
        stripped = re.sub(r"^[-*+]\s+", "", stripped)
        stripped = stripped.replace("|", " ")
        stripped = re.sub(r"\*\*|__", "", stripped)
        stripped = re.sub(r"[ \t]+", " ", stripped).strip()
        lines.append(stripped)
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# 兼容标注行
# ---------------------------------------------------------------------------


def _normalize_annotation(
    record: dict[str, Any], markdown: str | None
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """归一化 text/spans/relations。

    返回的 span 额外携带 ``blockId``，仅供图谱构建使用；写入
    ``annotations.jsonl`` 时会再剥离，保持旧字段语义不变。
    """

    text = record.get("text") if isinstance(record.get("text"), str) else ""
    if not text and markdown:
        text = _markdown_to_text(markdown)

    spans: list[dict[str, Any]] = []
    valid_ids: set[int] = set()
    for raw in record.get("spans", []):
        if not isinstance(raw, dict):
            continue
        try:
            span_id = int(raw["id"])
            start = int(raw["start"])
            end = int(raw["end"])
        except (KeyError, TypeError, ValueError):
            continue
        label = str(raw.get("label") or "").strip()
        if not label or start < 0 or end <= start or end > len(text):
            continue
        snippet = text[start:end]
        spans.append(
            {
                "id": span_id,
                "start": start,
                "end": end,
                "label": label,
                "text": snippet,
                "blockId": str(raw.get("blockId") or "").strip()[:64],
            }
        )
        valid_ids.add(span_id)

    relations: list[dict[str, Any]] = []
    seen_relations: set[tuple[int, int, str]] = set()
    for raw in record.get("relations", []):
        if not isinstance(raw, dict):
            continue
        try:
            from_id = int(raw["fromId"])
            to_id = int(raw["toId"])
        except (KeyError, TypeError, ValueError):
            continue
        relation_type = str(raw.get("type") or "").strip()
        key = (from_id, to_id, relation_type)
        if (
            not relation_type
            or from_id not in valid_ids
            or to_id not in valid_ids
            or key in seen_relations
        ):
            continue
        seen_relations.add(key)
        relations.append(
            {"fromId": from_id, "toId": to_id, "type": relation_type}
        )
    return text, spans, relations


def _legacy_span(span: dict[str, Any]) -> dict[str, Any]:
    """导出到 annotations.jsonl 的旧格式 span（不含新增的 blockId）。"""

    return {
        "id": span["id"],
        "start": span["start"],
        "end": span["end"],
        "label": span["label"],
        "text": span["text"],
    }


def _figure_export_record(figure: dict[str, Any]) -> dict[str, Any]:
    """annotations.jsonl 中图表字段白名单。

    历史数据里的 number/label/paragraphId 与内部 missing 标记一律不输出。
    """

    bbox = figure.get("bbox")
    return {
        "id": str(figure.get("id") or ""),
        "kind": str(figure.get("kind") or "figure"),
        "caption": str(figure.get("caption") or ""),
        "note": str(figure.get("note") or ""),
        "page": figure.get("page", 0),
        "bbox": list(bbox) if isinstance(bbox, (list, tuple)) else [],
        "asset_path": str(figure.get("asset_path") or ""),
    }


def _block_index(blocks: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = blocks.get("blocks")
    if not isinstance(entries, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in entries:
        if isinstance(item, dict) and item.get("id"):
            result[str(item["id"])] = item
    return result


def enrich_paragraphs(
    paragraphs: Any, blocks: dict[str, Any]
) -> list[dict[str, Any]]:
    """用 blocks 回填段落标注的正文、页码与章节信息。"""

    if not isinstance(paragraphs, list):
        return []
    by_id = _block_index(blocks)
    result: list[dict[str, Any]] = []
    for raw in paragraphs:
        if not isinstance(raw, dict):
            continue
        block_id = str(raw.get("blockId") or "").strip()
        block = by_id.get(block_id, {})
        result.append(
            {
                "block_id": block_id,
                "label": str(raw.get("label") or ""),
                "note": str(raw.get("note") or ""),
                "text": str(block.get("text") or ""),
                "page": int(block.get("page") or 0),
                "section_number": str(block.get("sectionNumber") or ""),
                "section_title": str(block.get("sectionTitle") or ""),
            }
        )
    return result


def build_annotation_row(
    project: dict[str, Any],
    meta: dict[str, Any],
    *,
    text: str,
    spans: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    paragraphs: Any,
    figures: list[dict[str, Any]],
    pages: Any,
    blocks: dict[str, Any],
    source_rel: str,
    markdown_rel: str,
    updated_at: str,
) -> dict[str, Any]:
    """构造兼容 annotations.jsonl 的一行记录（纯函数，不读写磁盘）。"""

    paragraphs_out = enrich_paragraphs(paragraphs, blocks)
    figures_out = [
        _figure_export_record(item) for item in figures if isinstance(item, dict)
    ]
    return {
        "project_id": project.get("id", ""),
        "project_name": project.get("name", ""),
        "file_id": meta.get("id", ""),
        "file_name": meta.get("name", ""),
        # source_file / markdown_file 按 API 契约输出标准文件名；
        # 同时附带项目内相对路径，便于多文件 ZIP 精确定位。
        "source_file": Path(source_rel).name if source_rel else "",
        "markdown_file": Path(markdown_rel).name if markdown_rel else "",
        "source_path": source_rel,
        "markdown_path": markdown_rel,
        "text": text,
        "spans": [_legacy_span(span) for span in spans],
        "relations": relations,
        "paragraphs": paragraphs_out,
        "figures": figures_out,
        "pages": _export_pages(pages),
        "meta": {
            "export_version": EXPORT_VERSION,
            "standard_id": extract_standard_id(str(meta.get("name") or "")),
            "block_count": len(blocks.get("blocks") or []),
            "paragraph_count": len(paragraphs_out),
            "figure_count": len(figures_out),
        },
        "updated_at": updated_at,
    }


# ---------------------------------------------------------------------------
# 图谱行（纯函数）
# ---------------------------------------------------------------------------


def _edge_id(source: str, target: str, relation: str) -> str:
    return f"e:{source}|{target}|{relation}"


def build_graph_rows(
    project: dict[str, Any],
    meta: dict[str, Any],
    blocks: dict[str, Any],
    annotations: dict[str, Any],
    asset_map: dict[str, str] | None = None,
    *,
    exported_at: str | None = None,
) -> list[dict[str, Any]]:
    """构造 graph.jsonl 的行：meta 行 + 节点行 + 边行。

    纯函数，不访问文件系统。``annotations`` 需要包含
    ``text/spans/relations/paragraphs/figures``；``spans`` 中的
    ``blockId`` 用于建立“实体出现在段落”的边。

    ``asset_map`` 为 ``figure_id -> ZIP 内相对路径``。
    """

    asset_map = asset_map or {}
    file_id = str(meta.get("id") or "")
    file_name = str(meta.get("name") or "")
    standard_id = extract_standard_id(file_name)

    doc_id = f"doc:{file_id}"
    rows: list[dict[str, Any]] = [
        {
            "record": "meta",
            "format": EXPORT_VERSION,
            "project_id": str(project.get("id") or meta.get("project_id") or ""),
            "file_id": file_id,
            "file_name": file_name,
            "standard_id": standard_id,
            "exported_at": exported_at or utc_now(),
        }
    ]

    # ---- 节点 ----
    rows.append(
        {
            "record": "node",
            "id": doc_id,
            "kind": "document",
            "name": standard_id or Path(file_name).stem or file_id,
            "label": "文件",
            "attributes": {
                "file_id": _stringify(file_id),
                "file_name": _stringify(file_name),
                "standard_id": _stringify(standard_id),
                "project_id": _stringify(
                    project.get("id") or meta.get("project_id")
                ),
                "project_name": _stringify(project.get("name")),
            },
        }
    )

    section_ids: set[str] = set()
    sections = blocks.get("sections")
    for section in sections if isinstance(sections, list) else []:
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("id") or "").strip()
        if not section_id:
            continue
        number = str(section.get("number") or "")
        title = str(section.get("title") or "")
        node_id = f"sec:{file_id}:{section_id}"
        section_ids.add(node_id)
        rows.append(
            {
                "record": "node",
                "id": node_id,
                "kind": "section",
                "name": f"{number} {title}".strip() or section_id,
                "label": "章节",
                "attributes": {
                    "section_id": _stringify(section_id),
                    "number": _stringify(number),
                    "title": _stringify(title),
                    "page": _stringify(section.get("page")),
                },
            }
        )

    by_id = _block_index(blocks)
    paragraph_ids: set[str] = set()
    section_of_paragraph: dict[str, str] = {}
    raw_paragraphs = annotations.get("paragraphs")
    for paragraph in raw_paragraphs if isinstance(raw_paragraphs, list) else []:
        if not isinstance(paragraph, dict):
            continue
        block_id = str(paragraph.get("blockId") or "").strip()
        if not block_id or block_id in paragraph_ids:
            continue
        block = by_id.get(block_id, {})
        node_id = f"par:{file_id}:{block_id}"
        paragraph_ids.add(node_id)
        section_of_paragraph[node_id] = str(block.get("sectionId") or "")
        rows.append(
            {
                "record": "node",
                "id": node_id,
                "kind": "paragraph",
                "name": _short_text(block.get("text")) or block_id,
                "label": _stringify(paragraph.get("label")),
                "attributes": {
                    "block_id": _stringify(block_id),
                    "page": _stringify(block.get("page")),
                    "section": _stringify(block.get("sectionNumber")),
                    "section_title": _stringify(block.get("sectionTitle")),
                    "note": _stringify(paragraph.get("note")),
                    "text": _stringify(block.get("text")),
                },
            }
        )

    figure_ids: set[str] = set()
    raw_figures = annotations.get("figures")
    for figure in raw_figures if isinstance(raw_figures, list) else []:
        if not isinstance(figure, dict):
            continue
        figure_id = str(figure.get("id") or "").strip()
        if not figure_id:
            continue
        node_id = f"fig:{file_id}:{figure_id}"
        figure_ids.add(node_id)
        kind = str(figure.get("kind") or "figure")
        caption = str(figure.get("caption") or "")
        type_label = "表" if kind == "table" else "图"
        rows.append(
            {
                "record": "node",
                "id": node_id,
                "kind": "figure",
                "name": caption or type_label,
                "label": type_label,
                "attributes": {
                    "asset_path": _stringify(
                        asset_map.get(figure_id, figure.get("asset_path"))
                    ),
                    "page": _stringify(figure.get("page")),
                    "bbox": _bbox_text(figure.get("bbox")),
                    "caption": _stringify(caption),
                },
            }
        )

    entity_ids: set[str] = set()
    raw_spans = annotations.get("spans")
    for span in raw_spans if isinstance(raw_spans, list) else []:
        if not isinstance(span, dict):
            continue
        try:
            span_id = int(span.get("id"))
        except (TypeError, ValueError):
            continue
        node_id = f"ent:{file_id}:{span_id}"
        entity_ids.add(node_id)
        block_id = str(span.get("blockId") or "").strip()
        block = by_id.get(block_id, {})
        rows.append(
            {
                "record": "node",
                "id": node_id,
                "kind": "entity",
                "name": str(span.get("text") or ""),
                "label": str(span.get("label") or ""),
                "attributes": {
                    "span_id": _stringify(span_id),
                    "block_id": _stringify(block_id),
                    "page": _stringify(block.get("page")),
                    "start": _stringify(span.get("start")),
                    "end": _stringify(span.get("end")),
                },
            }
        )

    # ---- 边 ----
    seen_edges: set[str] = set()

    def add_edge(
        source: str, target: str, relation: str, kind: str
    ) -> None:
        edge_id = _edge_id(source, target, relation)
        if edge_id in seen_edges:
            return
        seen_edges.add(edge_id)
        rows.append(
            {
                "record": "edge",
                "id": edge_id,
                "source": source,
                "target": target,
                "relation": relation,
                "kind": kind,
            }
        )

    for section_node in sorted(section_ids):
        add_edge(doc_id, section_node, "包含", "hierarchy")

    for paragraph_node in sorted(paragraph_ids):
        section_id = section_of_paragraph.get(paragraph_node, "")
        section_node = f"sec:{file_id}:{section_id}" if section_id else ""
        if section_node and section_node in section_ids:
            add_edge(section_node, paragraph_node, "包含", "hierarchy")

    for figure_node in sorted(figure_ids):
        add_edge(doc_id, figure_node, "包含", "hierarchy")

    for span in raw_spans if isinstance(raw_spans, list) else []:
        if not isinstance(span, dict):
            continue
        block_id = str(span.get("blockId") or "").strip()
        paragraph_node = f"par:{file_id}:{block_id}" if block_id else ""
        entity_node = f"ent:{file_id}:{span.get('id')}"
        if paragraph_node in paragraph_ids and entity_node in entity_ids:
            add_edge(entity_node, paragraph_node, "出现在", "relation")

    raw_relations = annotations.get("relations")
    for relation in raw_relations if isinstance(raw_relations, list) else []:
        if not isinstance(relation, dict):
            continue
        source = f"ent:{file_id}:{relation.get('fromId')}"
        target = f"ent:{file_id}:{relation.get('toId')}"
        relation_type = str(relation.get("type") or "").strip()
        if (
            relation_type
            and source in entity_ids
            and target in entity_ids
        ):
            add_edge(source, target, relation_type, "relation")

    return rows


# ---------------------------------------------------------------------------
# ZIP 写入
# ---------------------------------------------------------------------------


def _write_source(
    archive: zipfile.ZipFile, meta: dict[str, Any], arcname: str
) -> str | None:
    try:
        path = source_path(meta)
    except Exception:
        return None
    if not path.is_file():
        return None
    archive.write(path, arcname)
    return arcname


def _write_markdown_and_images(
    archive: zipfile.ZipFile,
    meta: dict[str, Any],
    *,
    markdown_arc: str,
    images_arc_prefix: str,
) -> str | None:
    md_path = markdown_path(meta)
    if not md_path.is_file():
        return None
    archive.write(md_path, markdown_arc)
    base = images_dir(meta)
    if base.is_dir():
        for image_path in sorted(base.rglob("*")):
            if image_path.is_file():
                relative = image_path.relative_to(base).as_posix()
                archive.write(
                    image_path, f"{images_arc_prefix.rstrip('/')}/{relative}"
                )
    return markdown_arc


def _load_blocks_safe(file_id: str, markdown: str | None) -> dict[str, Any]:
    """读取 blocks；失败时退化为基于当前 Markdown 的即时切块。"""

    try:
        return block_service.load_blocks(file_id)
    except (NotFoundError, ServiceError, OSError, ValueError):
        if markdown is None:
            return {**_EMPTY_BLOCKS}
        try:
            return block_service.parse_blocks(markdown, [])
        except (ValueError, TypeError):
            return {**_EMPTY_BLOCKS}


def _prepare_figure(
    meta: dict[str, Any],
    figure: dict[str, Any],
    *,
    stem: str,
) -> tuple[dict[str, Any], Path | None, str, bool]:
    """生成 annotations.jsonl 的图表记录，并计算 ZIP 内的资产相对路径。

    单文件与多文件布局一致使用 ``assets/<文件主名>/<截图名>``，返回的
    ``missing`` 只供 manifest 使用，不写入标注记录。
    """

    raw_asset = str(figure.get("assetPath") or "")
    name = PurePosixPath(raw_asset.replace("\\", "/")).name
    asset_file = figure_asset_path(meta, raw_asset)
    export = _figure_export_record(
        {
            **figure,
            "asset_path": "",
        }
    )
    if asset_file is not None and name and asset_file.is_file():
        relative = f"assets/{stem}/{name}"
        export["asset_path"] = relative
        return export, asset_file, relative, False
    return export, None, "", True


def build_export_zip(
    project_id: str,
    destination: Path,
) -> tuple[Path, str]:
    """生成导出 ZIP，返回 (临时文件路径, 建议下载名)。"""

    project = get_project(project_id)
    files = list_files(project_id)
    project_folder = _safe_component(project.get("name", ""), "project")
    single_file_layout = len(files) == 1
    export_stems = _assign_export_stems(files)
    exported_at = utc_now()

    rows: list[str] = []
    graph_rows: list[dict[str, Any]] = []
    manifest_files: list[dict[str, Any]] = []
    readme_lines = [
        f"项目名称：{project.get('name', '')}",
        f"项目 ID：{project.get('id', '')}",
        f"导出时间：{exported_at}",
        f"文件数量：{len(files)}",
        "",
        "ZIP 结构：",
        "  original/          原始 PDF / 图片：original/<文件名>.<ext>",
        "  markdown/          OCR 或人工编辑后的 Markdown 与图片",
        "                     单文件：markdown/<文件名>.md + markdown/images/",
        "                     多文件：markdown/<文件名>/<文件名>.md + images/",
        "  assets/            图表截图资产：assets/<文件名>/<截图名>",
        "  blocks/            后端切块结果：blocks/<文件名>.json",
        "  annotations.jsonl  兼容标注记录（含段落/图表/页码/meta）",
        "  graph.jsonl        图谱节点与边（首行为 meta，每行一个对象）",
        "  manifest.json      版本号、文件与资产清单",
        "  README.txt",
        "",
    ]

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(
            destination,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            # 即使没有图表/块文件，也保留目录条目，保证 ZIP 结构稳定。
            archive.writestr(f"{project_folder}/assets/", b"")
            archive.writestr(f"{project_folder}/blocks/", b"")

            for meta in files:
                file_id = meta["id"]
                stem = export_stems[file_id]
                ext = str(meta.get("source_ext") or "bin")
                source_rel = f"original/{stem}.{ext}"
                blocks_rel = f"blocks/{stem}.json"
                if single_file_layout:
                    markdown_rel = f"markdown/{stem}.md"
                    images_prefix = f"{project_folder}/markdown/images"
                else:
                    markdown_rel = f"markdown/{stem}/{stem}.md"
                    images_prefix = f"{project_folder}/markdown/{stem}/images"

                written_source = _write_source(
                    archive, meta, f"{project_folder}/{source_rel}"
                )
                markdown_text = read_markdown(file_id)
                written_markdown = _write_markdown_and_images(
                    archive,
                    meta,
                    markdown_arc=f"{project_folder}/{markdown_rel}",
                    images_arc_prefix=images_prefix,
                )

                blocks = _load_blocks_safe(file_id, markdown_text)
                archive.writestr(
                    f"{project_folder}/{blocks_rel}",
                    (
                        json.dumps(blocks, ensure_ascii=False, indent=2) + "\n"
                    ).encode("utf-8"),
                )

                if has_annotations(file_id):
                    record = load_annotations(file_id)
                    resolved_updated_at = (
                        record.get("updated_at") or meta.get("updated_at") or ""
                    )
                else:
                    record = {
                        "text": "",
                        "spans": [],
                        "relations": [],
                        "paragraphs": [],
                        "figures": [],
                    }
                    resolved_updated_at = meta.get("updated_at") or ""

                text, spans, relations = _normalize_annotation(
                    record, markdown_text
                )

                figure_exports: list[dict[str, Any]] = []
                manifest_figures: list[dict[str, Any]] = []
                asset_map: dict[str, str] = {}
                for raw_figure in record.get("figures", []):
                    if not isinstance(raw_figure, dict):
                        continue
                    export_figure, asset_file, relative, missing = _prepare_figure(
                        meta,
                        raw_figure,
                        stem=stem,
                    )
                    if asset_file is not None and relative:
                        archive.write(
                            asset_file,
                            f"{project_folder}/{relative}",
                        )
                    figure_id = str(raw_figure.get("id") or "")
                    figure_exports.append(export_figure)
                    manifest_figures.append(
                        {
                            "id": raw_figure.get("id", ""),
                            "kind": raw_figure.get("kind", ""),
                            "asset_path": relative,
                            "missing": missing,
                        }
                    )
                    asset_map[figure_id] = relative

                row = build_annotation_row(
                    project,
                    meta,
                    text=text,
                    spans=spans,
                    relations=relations,
                    paragraphs=record.get("paragraphs", []),
                    figures=figure_exports,
                    pages=blocks.get("pages", []),
                    blocks=blocks,
                    source_rel=source_rel if written_source else "",
                    markdown_rel=markdown_rel if written_markdown else "",
                    updated_at=resolved_updated_at,
                )
                rows.append(
                    json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                )

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

                manifest_files.append(
                    {
                        "file_id": file_id,
                        "file_name": meta.get("name", ""),
                        "standard_id": extract_standard_id(
                            str(meta.get("name") or "")
                        ),
                        "source": source_rel if written_source else "",
                        "markdown": markdown_rel if written_markdown else "",
                        "blocks": blocks_rel,
                        "figures": manifest_figures,
                    }
                )
                readme_lines.append(
                    f"- {meta.get('name', file_id)} → "
                    f"{written_source or '（原始文件缺失）'} / "
                    f"{written_markdown or '（Markdown 未生成）'} / "
                    f"{blocks_rel}"
                )

            readme_lines.extend(
                [
                    "",
                    "说明：",
                    "1. annotations.jsonl 保留 file_name/text/spans/relations，"
                    "旧知识库导入器仍可直接读取。",
                    "2. text 是标注坐标系使用的 canonical text；spans 的 "
                    "start/end 为 text 中的字符偏移（左闭右开）。",
                    "3. paragraphs 已用 blocks 回填正文、页码与章节信息；"
                    "figures 的 asset_path 为 ZIP 内相对路径。",
                    "4. graph.jsonl 首行为 meta，随后依次输出 node 与 edge；"
                    "所有 attributes 已字符串化，bbox 格式为 x0,y0,x1,y1。",
                    "5. Markdown 内图片引用使用相对路径 images/...。",
                    "6. 重新 OCR 或修改 Markdown 会使旧段落/实体标注失效，"
                    "图表记录与截图资产会保留；导出前请确认标注数据。",
                    "",
                ]
            )

            archive.writestr(
                f"{project_folder}/README.txt",
                "\n".join(readme_lines),
            )

            jsonl_content = "\n".join(rows)
            if rows:
                jsonl_content += "\n"
            archive.writestr(
                f"{project_folder}/annotations.jsonl",
                jsonl_content.encode("utf-8"),
            )

            graph_content = "\n".join(
                json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                for item in graph_rows
            )
            if graph_rows:
                graph_content += "\n"
            archive.writestr(
                f"{project_folder}/graph.jsonl",
                graph_content.encode("utf-8"),
            )

            manifest = {
                "format": EXPORT_VERSION,
                "version": 2,
                "exported_at": exported_at,
                "project": {
                    "id": project.get("id", ""),
                    "name": project.get("name", ""),
                },
                "files": manifest_files,
            }
            archive.writestr(
                f"{project_folder}/manifest.json",
                (
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
                ).encode("utf-8"),
            )
    except (OSError, zipfile.BadZipFile) as exc:
        destination.unlink(missing_ok=True)
        raise ServiceError(500, f"生成导出 ZIP 失败：{exc}") from exc
    except BaseException:
        destination.unlink(missing_ok=True)
        raise

    download_name = f"{project_folder}.zip"
    return destination, download_name

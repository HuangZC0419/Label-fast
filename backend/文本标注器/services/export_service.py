import os
import json
import zipfile
import io
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import select
from ..storage.db import get_session, init_db
from ..storage.schema import Document, Annotation, Relation, Project
from .record_service import get_project_dir, get_annotation_file_path

def export_project(project_id: int, fmt: str = "jsonl", output_dir: Optional[str] = None, doc_ids: Optional[List[int]] = None) -> str:
    init_db()
    s = get_session()
    try:
        # 提前获取项目信息（用于路径和导出内容）
        p = s.get(Project, project_id)
        proj_name = p.name if p else f"project_{project_id}"

        q_docs = select(Document).where(Document.project_id == project_id)
        if doc_ids:
            q_docs = q_docs.where(Document.id.in_(doc_ids))
        q_docs = q_docs.order_by(Document.id.asc())
        docs = s.execute(q_docs).scalars().all()
        if output_dir is None:
            base_dir = os.path.join(get_project_dir(proj_name), "exports")
        else:
            base_dir = output_dir
        os.makedirs(base_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        if fmt.lower() == "json_v2":
            # New Feature: Structured JSON Export
            path = os.path.join(base_dir, f"project_{project_id}_{ts}.json")

            project_info = {
                "project_name": p.name if p else "Unknown",
                "export_time": datetime.now(timezone.utc).isoformat(),
                "version": "1.0"
            }

            export_docs = []
            for d in docs:
                # Fetch Annotations
                q_anns = select(Annotation).where(Annotation.doc_id == d.id).order_by(Annotation.id.asc())
                anns = s.execute(q_anns).scalars().all()
                
                # Map Ann ID to Export ID
                ann_id_map = {a.id: f"ent_{i+1}" for i, a in enumerate(anns)}
                
                entities = []
                for a in anns:
                    entities.append({
                        "id": ann_id_map[a.id],
                        "start_offset": a.start,
                        "end_offset": a.end,
                        "label": a.label,
                        "text": d.text[a.start:a.end],
                        "confidence": 1.0  # Default
                    })

                # Fetch Relations
                q_rels = select(Relation).where(Relation.doc_id == d.id).order_by(Relation.id.asc())
                rels = s.execute(q_rels).scalars().all()
                
                relations = []
                for i, r in enumerate(rels):
                    if r.from_ann_id in ann_id_map and r.to_ann_id in ann_id_map:
                        relations.append({
                            "id": f"rel_{i+1}",
                            "from_entity_id": ann_id_map[r.from_ann_id],
                            "to_entity_id": ann_id_map[r.to_ann_id],
                            "relation_type": r.relation_type,
                            "confidence": 1.0 # Default
                        })

                doc_obj = {
                    "text_id": f"doc_{d.id}_unit_{d.unit_index or 0}",
                    "original_text": d.text,
                    "annotations": {
                        "entities": entities,
                        "relations": relations
                    },
                    "metadata": {
                        "annotator": "current_user", # Default
                        "annotation_time": d.created_at.isoformat() if d.created_at else None,
                        "status": d.status
                    }
                }
                export_docs.append(doc_obj)

            final_obj = {
                "project_info": project_info,
                "documents": export_docs
            }
            
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(final_obj, indent=2, ensure_ascii=False))
            return path

        if fmt.lower() == "jsonl":
            path = os.path.join(base_dir, f"project_{project_id}_{ts}.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                for d in docs:
                    q_anns = select(Annotation).where(Annotation.doc_id == d.id).order_by(Annotation.start.asc(), Annotation.end.asc())
                    anns = s.execute(q_anns).scalars().all()
                    entities = [{"start": a.start, "end": a.end, "label": a.label} for a in anns]
                    idx = {a.id: i for i, a in enumerate(anns)}
                    q_rels = select(Relation).where(Relation.doc_id == d.id).order_by(Relation.id.asc())
                    rels = s.execute(q_rels).scalars().all()
                    relations = []
                    for r in rels:
                        if r.from_ann_id in idx and r.to_ann_id in idx:
                            relations.append({"from_entity": idx[r.from_ann_id], "to_entity": idx[r.to_ann_id], "relation": r.relation_type})
                    obj = {"text": d.text, "entities": entities, "relations": relations}
                    f.write(json_dumps(obj) + "\n")
            return path
        if fmt.lower() in {"tsv", "csv"}:
            sep = "\t" if fmt.lower() == "tsv" else ","
            path = os.path.join(base_dir, f"project_{project_id}_{ts}.{fmt.lower()}")
            with open(path, "w", encoding="utf-8") as f:
                f.write(sep.join(["doc_id","start","end","label","fragment"]) + "\n")
                for d in docs:
                    q_anns = select(Annotation).where(Annotation.doc_id == d.id).order_by(Annotation.start.asc())
                    anns = s.execute(q_anns).scalars().all()
                    for a in anns:
                        frag = d.text[a.start:a.end]
                        # 转义字段中的分隔符和换行符，避免 CSV/TSV 格式错乱
                        safe_frag = frag.replace("\t", " ").replace("\n", " ").replace("\r", " ")
                        safe_label = a.label.replace("\t", " ").replace("\n", " ").replace("\r", " ")
                        if fmt.lower() == "csv":
                            safe_frag = safe_frag.replace(",", "，")
                            safe_label = safe_label.replace(",", "，")
                        row = sep.join([str(d.id), str(a.start), str(a.end), safe_label, safe_frag])
                        f.write(row + "\n")
            return path
        raise ValueError("unsupported format")
    finally:
        s.close()

def export_project_zip(project_id: int, doc_ids: Optional[List[int]] = None) -> bytes:
    """将项目导出为 ZIP 包 — 从 JSONL 记录文件读取（与"保存并下一篇"数据同源）。"""
    init_db()
    s = get_session()
    try:
        p = s.get(Project, project_id)
        project_name = p.name if p else f"project_{project_id}"
        safe_name = "".join(c for c in project_name if c.isalnum() or c in (' ', '-', '_')).strip() or "export"

        # ---- 1. 读取 JSONL 标注记录（主数据源） ----
        jsonl_file = get_annotation_file_path(project_id, project_name)
        records = []
        if os.path.exists(jsonl_file):
            with open(jsonl_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        # ---- 2. 补充数据库中文档（用于获取完整文本） ----
        db_docs = {}
        if records:
            doc_ids_in_records = {r.get("id") for r in records if r.get("id") and r["id"] > 0}
            if doc_ids_in_records:
                q = select(Document).where(Document.id.in_(doc_ids_in_records))
                for d in s.execute(q).scalars().all():
                    db_docs[d.id] = d.text

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            # ---- JSON (structured) ----
            export_docs = []
            for idx, rec in enumerate(records):
                text = rec.get("text", "")
                spans = rec.get("spans", [])
                relations_data = rec.get("relations", [])

                span_map = {sp["id"]: f"ent_{j+1}" for j, sp in enumerate(spans)}
                entities = []
                for sp in spans:
                    entities.append({
                        "id": span_map[sp["id"]],
                        "start_offset": sp["start"],
                        "end_offset": sp["end"],
                        "label": sp["label"],
                        "text": text[sp["start"]:sp["end"]] if sp["end"] <= len(text) else "",
                        "confidence": 1.0
                    })

                relations = []
                for j, r in enumerate(relations_data):
                    fid = r.get("fromId")
                    tid = r.get("toId")
                    if fid in span_map and tid in span_map:
                        relations.append({
                            "id": f"rel_{j+1}",
                            "from_entity_id": span_map[fid],
                            "to_entity_id": span_map[tid],
                            "relation_type": r.get("type", ""),
                            "confidence": 1.0
                        })

                export_docs.append({
                    "text_id": f"doc_{idx+1}",
                    "original_text": text,
                    "annotations": {"entities": entities, "relations": relations},
                    "metadata": {
                        "annotator": "exported",
                        "annotation_time": rec.get("meta", {}).get("timestamp", ""),
                    }
                })

            zf.writestr(f"{safe_name}/annotations.json", json.dumps({
                "project_info": {
                    "project_name": project_name,
                    "export_time": datetime.now(timezone.utc).isoformat(),
                    "version": "1.0"
                },
                "documents": export_docs
            }, indent=2, ensure_ascii=False))

            # ---- JSONL (逐行) ----
            jsonl_lines = []
            for rec in records:
                spans = rec.get("spans", [])
                relations_data = rec.get("relations", [])
                idx_map = {sp["id"]: i for i, sp in enumerate(spans)}
                entities_out = [{"start": sp["start"], "end": sp["end"], "label": sp["label"]} for sp in spans]
                rels_out = []
                for r in relations_data:
                    fid = r.get("fromId")
                    tid = r.get("toId")
                    if fid in idx_map and tid in idx_map:
                        rels_out.append({"from_entity": idx_map[fid], "to_entity": idx_map[tid], "relation": r.get("type", "")})
                jsonl_lines.append(json.dumps({"text": rec.get("text", ""), "entities": entities_out, "relations": rels_out}, ensure_ascii=False))
            zf.writestr(f"{safe_name}/annotations.jsonl", "\n".join(jsonl_lines) + "\n")

            # ---- CSV ----
            csv_lines = ["doc_id,start,end,label,fragment"]
            for idx, rec in enumerate(records):
                text = rec.get("text", "")
                for sp in rec.get("spans", []):
                    frag = text[sp["start"]:sp["end"]].replace("\t"," ").replace("\n"," ").replace("\r"," ").replace(",","，") if sp["end"] <= len(text) else ""
                    csv_lines.append(f"{idx+1},{sp['start']},{sp['end']},{sp['label'].replace(',','，')},{frag}")
            zf.writestr(f"{safe_name}/annotations.csv", "\n".join(csv_lines) + "\n")

            # ---- README ----
            zf.writestr(f"{safe_name}/README.txt", (
                f"文本标注导出包 — {project_name}\n"
                f"导出时间: {datetime.now(timezone.utc).isoformat()}\n"
                f"标注记录数: {len(records)}\n"
                f"文件: annotations.json / annotations.jsonl / annotations.csv\n"
            ))

        return buf.getvalue()
    finally:
        s.close()


def json_dumps(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)
import os
from datetime import datetime
from typing import Optional
from sqlalchemy import select
from ..storage.db import get_session, init_db
from ..storage.schema import Document, Annotation

def export_project(project_id: int, fmt: str = "jsonl", output_dir: Optional[str] = None) -> str:
    init_db()
    s = get_session()
    try:
        q_docs = select(Document).where(Document.project_id == project_id).order_by(Document.id.asc())
        docs = s.execute(q_docs).scalars().all()
        if output_dir is None:
            base_dir = os.path.join(os.path.dirname(__file__), "..", "exports")
        else:
            base_dir = output_dir
        os.makedirs(base_dir, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        if fmt.lower() == "jsonl":
            path = os.path.join(base_dir, f"project_{project_id}_{ts}.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                for d in docs:
                    q_anns = select(Annotation).where(Annotation.doc_id == d.id).order_by(Annotation.start.asc())
                    anns = s.execute(q_anns).scalars().all()
                    labels = [[a.start, a.end, a.label] for a in anns]
                    obj = {"text": d.text, "labels": labels}
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
                        row = sep.join([str(d.id), str(a.start), str(a.end), a.label, frag.replace("\t"," ").replace("\n"," ")])
                        f.write(row + "\n")
            return path
        raise ValueError("unsupported format")
    finally:
        s.close()

def json_dumps(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)
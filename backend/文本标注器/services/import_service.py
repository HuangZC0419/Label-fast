import os
from typing import List, Optional, Tuple
from ..storage.db import get_session, init_db
from ..storage.schema import Document, Project
from ..models import DocumentModel

def detect_encoding(path: str) -> str:
    try:
        from charset_normalizer import from_path
        res = from_path(path).best()
        if res and res.encoding:
            return res.encoding
    except Exception:
        pass
    return "utf-8"

def read_file_text(path: str, encoding: Optional[str] = None) -> str:
    enc = encoding or detect_encoding(path)
    with open(path, "r", encoding=enc, errors="strict") as f:
        return f.read()

def split_text(text: str, strategy: str, fixed_length: Optional[int] = None) -> List[str]:
    t = text.replace("\r\n", "\n")
    if strategy == "as_is":
        return [t]
    if strategy == "paragraph":
        parts = [p.strip() for p in t.split("\n\n")]
        return [p for p in parts if p]
    if strategy == "sentence":
        import re
        sents: List[str] = []
        cur = []
        for ch in t:
            cur.append(ch)
            if re.match(r"[。．\.！？!?]", ch):
                s = "".join(cur).strip()
                if s:
                    sents.append(s)
                cur = []
        rest = "".join(cur).strip()
        if rest:
            sents.append(rest)
        return sents
    if strategy == "length":
        n = int(fixed_length or 500)
        out: List[str] = []
        i = 0
        while i < len(t):
            out.append(t[i:i+n])
            i += n
        return [p for p in out if p.strip()]
    return [t]

def import_txt_files(project_id: int, file_paths: List[str], strategy: str = "sentence", fixed_length: Optional[int] = None, encoding: Optional[str] = None) -> List[DocumentModel]:
    init_db()
    s = get_session()
    try:
        p = s.get(Project, project_id)
        if not p:
            raise ValueError("project not found")
        docs: List[DocumentModel] = []
        for path in file_paths:
            if not os.path.isfile(path):
                raise ValueError("file not found: " + path)
            text = read_file_text(path, encoding)
            units = split_text(text, strategy, fixed_length)
            for idx, u in enumerate(units):
                d = Document(project_id=project_id, text=u, status="pending", source_file=path, unit_index=idx)
                s.add(d)
        s.commit()
        for path in file_paths:
            pass
        q = s.query(Document).filter(Document.project_id == project_id).order_by(Document.id.asc()).all()
        for d in q:
            docs.append(DocumentModel(id=d.id, project_id=d.project_id, text=d.text, status=d.status, source_file=d.source_file, unit_index=d.unit_index, created_at=d.created_at))
        return docs
    finally:
        s.close()

def update_document_status(doc_id: int, status: str) -> DocumentModel:
    init_db()
    s = get_session()
    try:
        d = s.get(Document, doc_id)
        if not d:
            raise ValueError("document not found")
        d.status = status
        s.commit()
        s.refresh(d)
        return DocumentModel(id=d.id, project_id=d.project_id, text=d.text, status=d.status, source_file=d.source_file, unit_index=d.unit_index, created_at=d.created_at)
    finally:
        s.close()
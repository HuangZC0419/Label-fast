import os
import re
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
        # 以空行（一个或多个换行）作为段落边界
        parts = [p.strip() for p in re.split(r"\n\s*\n", t)]
        return [p for p in parts if p]
    if strategy == "sentence":
        # 句末标点与省略号作为边界，标点保留在上一句；
        # 换行视为硬边界；英文句点仅在后面是空白/结尾且前一个字符不是数字时才算句末，
        # 避免切开小数、版本号以及 "1. xxx" 这类列表序号。
        sents: List[str] = []
        cur: List[str] = []
        n = len(t)

        def flush():
            s = "".join(cur).strip()
            if s:
                sents.append(s)
            cur.clear()

        i = 0
        while i < n:
            ch = t[i]

            if ch == "\n":
                flush()
                i += 1
                continue

            if ch == "…":
                j = i
                while j < n and t[j] == "…":
                    j += 1
                cur.append(t[i:j])
                flush()
                i = j
                continue

            if ch == ".":
                j = i
                while j < n and t[j] == ".":
                    j += 1
                run = j - i
                cur.append("." * run)
                if run >= 3:
                    flush()
                    i = j
                    continue
                nxt = t[j] if j < n else ""
                prev = t[i - 1] if i > 0 else ""
                at_end = nxt == "" or nxt.isspace()
                after_digit = prev.isdigit()
                if run == 1 and at_end and not after_digit:
                    flush()
                i = j
                continue

            cur.append(ch)
            if ch in "。．；！？!?;":
                flush()
            i += 1

        flush()
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
        new_docs: List[Document] = []
        for path in file_paths:
            if not os.path.isfile(path):
                raise ValueError("file not found: " + path)
            text = read_file_text(path, encoding)
            units = split_text(text, strategy, fixed_length)
            for idx, u in enumerate(units):
                d = Document(project_id=project_id, text=u, status="pending", source_file=path, unit_index=idx)
                s.add(d)
                new_docs.append(d)
        s.commit()
        # 刷新以获取数据库生成的 ID 和时间戳
        for d in new_docs:
            s.refresh(d)
        return [DocumentModel(id=d.id, project_id=d.project_id, text=d.text, status=d.status, source_file=d.source_file, unit_index=d.unit_index, created_at=d.created_at) for d in new_docs]
    except Exception:
        s.rollback()
        raise
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
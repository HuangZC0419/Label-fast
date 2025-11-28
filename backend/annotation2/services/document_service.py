import logging
from typing import List
from sqlalchemy import select
from ..storage.db import get_session, init_db
from ..storage.schema import Document, Project
from ..models import DocumentModel

logger = logging.getLogger(__name__)

def import_texts(project_id: int, texts: List[str]) -> List[DocumentModel]:
    init_db()
    s = get_session()
    try:
        p = s.get(Project, project_id)
        if not p:
            raise ValueError("project not found")
        docs = []
        for t in texts:
            d = Document(project_id=project_id, text=t)
            s.add(d)
            docs.append(d)
        s.commit()
        for d in docs:
            s.refresh(d)
        return [DocumentModel(id=d.id, project_id=d.project_id, text=d.text, created_at=d.created_at) for d in docs]
    finally:
        s.close()

def list_documents(project_id: int, limit: int = 50, offset: int = 0) -> List[DocumentModel]:
    init_db()
    s = get_session()
    try:
        q = select(Document).where(Document.project_id == project_id).order_by(Document.id.asc()).limit(limit).offset(offset)
        rows = s.execute(q).scalars().all()
        return [DocumentModel(id=r.id, project_id=r.project_id, text=r.text, created_at=r.created_at) for r in rows]
    finally:
        s.close()

def get_document(doc_id: int) -> DocumentModel:
    init_db()
    s = get_session()
    try:
        d = s.get(Document, doc_id)
        if not d:
            raise ValueError("document not found")
        return DocumentModel(id=d.id, project_id=d.project_id, text=d.text, created_at=d.created_at)
    finally:
        s.close()
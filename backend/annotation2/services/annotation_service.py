import logging
from typing import List
from sqlalchemy import select, delete, update
from ..storage.db import get_session, init_db
from ..storage.schema import Annotation, Document, Project
from ..models import AnnotationModel

logger = logging.getLogger(__name__)

def list_spans(doc_id: int) -> List[AnnotationModel]:
    init_db()
    s = get_session()
    try:
        q = select(Annotation).where(Annotation.doc_id == doc_id).order_by(Annotation.start.asc(), Annotation.end.asc())
        rows = s.execute(q).scalars().all()
        return [AnnotationModel(id=r.id, doc_id=r.doc_id, start=r.start, end=r.end, label=r.label, created_at=r.created_at) for r in rows]
    finally:
        s.close()

def add_span(doc_id: int, start: int, end: int, label: str) -> AnnotationModel:
    init_db()
    s = get_session()
    try:
        d = s.get(Document, doc_id)
        if not d:
            raise ValueError("document not found")
        p = s.get(Project, d.project_id)
        if not p:
            raise ValueError("project not found")
        if label not in p.labels:
            raise ValueError("label not in project")
        if start < 0 or end < 0 or start >= end or end > len(d.text):
            raise ValueError("invalid span")
        if not bool(p.allow_overlap):
            q = select(Annotation).where(Annotation.doc_id == doc_id)
            rows = s.execute(q).scalars().all()
            for r in rows:
                if not (end <= r.start or start >= r.end):
                    raise ValueError("span overlap")
        a = Annotation(doc_id=doc_id, start=start, end=end, label=label)
        s.add(a)
        s.commit()
        s.refresh(a)
        return AnnotationModel(id=a.id, doc_id=a.doc_id, start=a.start, end=a.end, label=a.label, created_at=a.created_at)
    finally:
        s.close()

def update_span(ann_id: int, start: int, end: int, label: str) -> AnnotationModel:
    init_db()
    s = get_session()
    try:
        a0 = s.get(Annotation, ann_id)
        if not a0:
            raise ValueError("annotation not found")
        d = s.get(Document, a0.doc_id)
        if not d:
            raise ValueError("document not found")
        p = s.get(Project, d.project_id)
        if not p:
            raise ValueError("project not found")
        if label not in p.labels:
            raise ValueError("label not in project")
        if start < 0 or end < 0 or start >= end or end > len(d.text):
            raise ValueError("invalid span")
        if not bool(p.allow_overlap):
            q = select(Annotation).where(Annotation.doc_id == d.id, Annotation.id != ann_id)
            rows = s.execute(q).scalars().all()
            for r in rows:
                if not (end <= r.start or start >= r.end):
                    raise ValueError("span overlap")
        s.execute(update(Annotation).where(Annotation.id == ann_id).values(start=start, end=end, label=label).execution_options(synchronize_session="fetch"))
        s.commit()
        a = s.get(Annotation, ann_id)
        return AnnotationModel(id=a.id, doc_id=a.doc_id, start=a.start, end=a.end, label=a.label, created_at=a.created_at)
    finally:
        s.close()

def delete_span(ann_id: int) -> bool:
    init_db()
    s = get_session()
    try:
        q = delete(Annotation).where(Annotation.id == ann_id)
        res = s.execute(q)
        s.commit()
        return res.rowcount > 0
    finally:
        s.close()
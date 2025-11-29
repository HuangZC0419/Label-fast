import logging
from sqlalchemy import select, delete, update
from ..storage.db import get_session, init_db
from ..storage.schema import Relation, Annotation, Document, Project
from ..models import RelationModel

logger = logging.getLogger(__name__)

def list_relations(doc_id: int):
    init_db()
    s = get_session()
    try:
        q = select(Relation).where(Relation.doc_id == doc_id).order_by(Relation.id.asc())
        rows = s.execute(q).scalars().all()
        return [RelationModel(id=r.id, doc_id=r.doc_id, from_ann_id=r.from_ann_id, to_ann_id=r.to_ann_id, relation_type=r.relation_type, created_at=r.created_at) for r in rows]
    finally:
        s.close()

def add_relation(doc_id: int, from_ann_id: int, to_ann_id: int, relation_type: str):
    init_db()
    s = get_session()
    try:
        d = s.get(Document, doc_id)
        if not d:
            raise ValueError("document not found")
        a_from = s.get(Annotation, from_ann_id)
        a_to = s.get(Annotation, to_ann_id)
        if not a_from or not a_to:
            raise ValueError("annotation not found")
        if a_from.doc_id != doc_id or a_to.doc_id != doc_id:
            raise ValueError("annotation not in document")
        p = s.get(Project, d.project_id)
        if not p:
            raise ValueError("project not found")
        if relation_type not in p.relation_types:
            raise ValueError("relation type not in project")
        q = select(Relation).where(Relation.doc_id == doc_id, Relation.from_ann_id == from_ann_id, Relation.to_ann_id == to_ann_id, Relation.relation_type == relation_type)
        if s.execute(q).scalar_one_or_none():
            raise ValueError("relation exists")
        r = Relation(doc_id=doc_id, from_ann_id=from_ann_id, to_ann_id=to_ann_id, relation_type=relation_type)
        s.add(r)
        s.commit()
        s.refresh(r)
        return RelationModel(id=r.id, doc_id=r.doc_id, from_ann_id=r.from_ann_id, to_ann_id=r.to_ann_id, relation_type=r.relation_type, created_at=r.created_at)
    finally:
        s.close()

def update_relation(rel_id: int, relation_type: str):
    init_db()
    s = get_session()
    try:
        r0 = s.get(Relation, rel_id)
        if not r0:
            raise ValueError("relation not found")
        d = s.get(Document, r0.doc_id)
        if not d:
            raise ValueError("document not found")
        p = s.get(Project, d.project_id)
        if not p:
            raise ValueError("project not found")
        if relation_type not in p.relation_types:
            raise ValueError("relation type not in project")
        s.execute(update(Relation).where(Relation.id == rel_id).values(relation_type=relation_type).execution_options(synchronize_session="fetch"))
        s.commit()
        r = s.get(Relation, rel_id)
        return RelationModel(id=r.id, doc_id=r.doc_id, from_ann_id=r.from_ann_id, to_ann_id=r.to_ann_id, relation_type=r.relation_type, created_at=r.created_at)
    finally:
        s.close()

def delete_relation(rel_id: int):
    init_db()
    s = get_session()
    try:
        q = delete(Relation).where(Relation.id == rel_id)
        res = s.execute(q)
        s.commit()
        return res.rowcount > 0
    finally:
        s.close()
from typing import List, Dict, Any, Optional
import os
from sqlalchemy import select, delete
from ..storage.db import get_session, init_db
from ..storage.schema import Project, Document, Annotation, Relation
from .record_service import BASE_DATA_DIR

def get_project_id_by_name(name: str) -> Optional[int]:
    init_db()
    s = get_session()
    try:
        q = select(Project).where(Project.name == name)
        p = s.execute(q).scalars().first()
        return p.id if p else None
    finally:
        s.close()

def create_project(name: str, labels: List[str] = None, relation_types: List[str] = None) -> int:
    init_db()
    s = get_session()
    try:
        # Check if exists
        q = select(Project).where(Project.name == name)
        p = s.execute(q).scalars().first()
        if p:
            return p.id
        
        # Create new
        new_p = Project(
            name=name,
            labels=labels or [],
            relation_types=relation_types or []
        )
        s.add(new_p)
        s.commit()

        # Create project directory
        safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '-', '_')]).strip()
        project_dir = os.path.join(BASE_DATA_DIR, safe_name)
        if not os.path.exists(project_dir):
            os.makedirs(project_dir)

        return new_p.id
    except Exception as e:
        s.rollback()
        raise e
    finally:
        s.close()

def load_project_data(project_id: int) -> Dict[str, Any]:
    init_db()
    s = get_session()
    try:
        p = s.get(Project, project_id)
        if not p:
            return None
            
        q_docs = select(Document).where(Document.project_id == project_id).order_by(Document.id.asc())
        docs = s.execute(q_docs).scalars().all()
        
        doc_list = []
        for d in docs:
            # Fetch annotations
            q_anns = select(Annotation).where(Annotation.doc_id == d.id).order_by(Annotation.id.asc())
            anns = s.execute(q_anns).scalars().all()
            
            spans = []
            ann_id_map = {} 
            
            for a in anns:
                spans.append({
                    "id": a.id,
                    "start": a.start,
                    "end": a.end,
                    "label": a.label
                })
                ann_id_map[a.id] = a.id

            # Fetch relations
            q_rels = select(Relation).where(Relation.doc_id == d.id).order_by(Relation.id.asc())
            rels = s.execute(q_rels).scalars().all()
            
            relations = []
            for r in rels:
                if r.from_ann_id in ann_id_map and r.to_ann_id in ann_id_map:
                    relations.append({
                        "fromId": r.from_ann_id,
                        "toId": r.to_ann_id,
                        "type": r.relation_type
                    })
            
            doc_list.append({
                "id": d.id,
                "text": d.text,
                "status": d.status,
                "spans": spans,
                "relations": relations
            })
            
        return {
            "project": {
                "name": p.name,
                "labels": p.labels,
                "relation_types": p.relation_types
            },
            "documents": doc_list
        }
    finally:
        s.close()

def save_project_data(project_id: int, data: Dict[str, Any]):
    init_db()
    s = get_session()
    try:
        p = s.get(Project, project_id)
        if not p:
            return {"error": "Project not found"}

        # Update project metadata
        if "project" in data:
            pm = data["project"]
            if "name" in pm: p.name = pm["name"]
            if "labels" in pm: p.labels = pm["labels"]
            if "relation_types" in pm: p.relation_types = pm["relation_types"]
            s.add(p)
        
        # Handle documents
        saved_docs = []
        if "documents" in data:
            for d_data in data["documents"]:
                doc_id = d_data.get("id")
                doc = None
                
                if doc_id and doc_id > 0:
                    doc = s.get(Document, doc_id)
                    if doc and doc.project_id == project_id:
                        doc.text = d_data.get("text", doc.text)
                        doc.status = d_data.get("status", doc.status)
                    else:
                        # ID mismatch or not found, create new
                        doc = Document(project_id=project_id, text=d_data["text"], status=d_data.get("status", "pending"))
                        s.add(doc)
                        s.flush()
                else:
                    # Create new
                    doc = Document(project_id=project_id, text=d_data["text"], status=d_data.get("status", "pending"))
                    s.add(doc)
                    s.flush() 
                
                # Replace annotations
                s.execute(delete(Relation).where(Relation.doc_id == doc.id))
                s.execute(delete(Annotation).where(Annotation.doc_id == doc.id))
                
                frontend_id_map = {}
                
                for sp in d_data.get("spans", []):
                    a = Annotation(doc_id=doc.id, start=sp["start"], end=sp["end"], label=sp["label"])
                    s.add(a)
                    s.flush()
                    frontend_id_map[sp["id"]] = a.id
                
                for rel in d_data.get("relations", []):
                    fid = rel.get("fromId")
                    tid = rel.get("toId")
                    if fid in frontend_id_map and tid in frontend_id_map:
                        r = Relation(doc_id=doc.id, from_ann_id=frontend_id_map[fid], to_ann_id=frontend_id_map[tid], relation_type=rel["type"])
                        s.add(r)
                
                saved_docs.append({"id": doc.id, "status": "saved"})

        s.commit()
        return {"status": "ok", "documents": saved_docs}
    except Exception as e:
        s.rollback()
        raise e
    finally:
        s.close()

def clear_project(project_id: int) -> bool:
    init_db()
    s = get_session()
    try:
        p = s.get(Project, project_id)
        if not p:
            return False

        # Delete all documents in project (cascades to annotations/relations usually, but let's be safe)
        # SQLAlchemy cascade might not be set up in schema, so manual delete is safer
        
        # Find all docs
        q = select(Document.id).where(Document.project_id == project_id)
        doc_ids = s.execute(q).scalars().all()
        
        if doc_ids:
            # Delete relations
            s.execute(delete(Relation).where(Relation.doc_id.in_(doc_ids)))
            # Delete annotations
            s.execute(delete(Annotation).where(Annotation.doc_id.in_(doc_ids)))
            # Delete documents
            s.execute(delete(Document).where(Document.id.in_(doc_ids)))

        p.labels = []
        p.relation_types = []
        s.add(p)

        s.commit()
        return True
    finally:
        s.close()

def delete_document(doc_id: int) -> bool:
    init_db()
    s = get_session()
    try:
        s.execute(delete(Relation).where(Relation.doc_id == doc_id))
        s.execute(delete(Annotation).where(Annotation.doc_id == doc_id))
        s.execute(delete(Document).where(Document.id == doc_id))
        s.commit()
        return True
    finally:
        s.close()

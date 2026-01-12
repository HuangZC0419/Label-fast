import logging
import os
import shutil
from typing import List
from sqlalchemy import select, delete, update
from ..storage.db import get_session, init_db
from ..storage.schema import Project, Document, Annotation, Relation
from ..models import ProjectModel
from .record_service import BASE_DATA_DIR

logger = logging.getLogger(__name__)

def create_project(name: str, labels: List[str]) -> ProjectModel:
    init_db()
    s = get_session()
    try:
        q = select(Project).where(Project.name == name)
        if s.execute(q).scalar_one_or_none():
            raise ValueError("project name exists")
        p = Project(name=name, labels=list(labels), relation_types=[], allow_overlap=0)
        s.add(p)
        s.commit()
        s.refresh(p)
        return ProjectModel(id=p.id, name=p.name, labels=p.labels, relation_types=p.relation_types, allow_overlap=bool(p.allow_overlap), created_at=p.created_at)
    finally:
        s.close()

def list_projects() -> List[ProjectModel]:
    init_db()
    s = get_session()
    try:
        q = select(Project).order_by(Project.id.desc())
        rows = s.execute(q).scalars().all()
        return [ProjectModel(id=r.id, name=r.name, labels=r.labels, relation_types=r.relation_types, allow_overlap=bool(r.allow_overlap), created_at=r.created_at) for r in rows]
    finally:
        s.close()

def delete_project(project_id: int) -> bool:
    init_db()
    s = get_session()
    try:
        # Get project info first
        p = s.get(Project, project_id)
        if not p:
            return False
            
        project_name = p.name

        # Delete relations using subquery
        s.execute(delete(Relation).where(Relation.doc_id.in_(
            select(Document.id).where(Document.project_id == project_id)
        )))
        
        # Delete annotations using subquery
        s.execute(delete(Annotation).where(Annotation.doc_id.in_(
            select(Document.id).where(Document.project_id == project_id)
        )))

        # Delete documents
        s.execute(delete(Document).where(Document.project_id == project_id))

        # Delete project
        s.delete(p)
        s.commit()
        
        # Try to delete folder
        if project_name:
            safe_name = "".join([c for c in project_name if c.isalnum() or c in (' ', '-', '_')]).strip()
            project_dir = os.path.join(BASE_DATA_DIR, safe_name)
            if os.path.exists(project_dir):
                try:
                    shutil.rmtree(project_dir, ignore_errors=True)
                except Exception as e:
                    logger.warning(f"Failed to delete project directory {project_dir}: {e}")

        return True
    except Exception as e:
        s.rollback()
        logger.error(f"Error deleting project {project_id}: {e}")
        # Re-raise so the API returns 500 and we see the error
        raise e
    finally:
        s.close()

def update_labels(project_id: int, labels: List[str]) -> ProjectModel:
    init_db()
    s = get_session()
    try:
        q = update(Project).where(Project.id == project_id).values(labels=list(labels)).execution_options(synchronize_session="fetch")
        s.execute(q)
        s.commit()
        p = s.get(Project, project_id)
        if not p:
            raise ValueError("project not found")
        return ProjectModel(id=p.id, name=p.name, labels=p.labels, relation_types=p.relation_types, allow_overlap=bool(p.allow_overlap), created_at=p.created_at)
    finally:
        s.close()

def get_project(project_id: int) -> ProjectModel:
    init_db()
    s = get_session()
    try:
        p = s.get(Project, project_id)
        if not p:
            raise ValueError("project not found")
        return ProjectModel(id=p.id, name=p.name, labels=p.labels, relation_types=p.relation_types, allow_overlap=bool(p.allow_overlap), created_at=p.created_at)
    finally:
        s.close()

def update_allow_overlap(project_id: int, allow: bool) -> ProjectModel:
    init_db()
    s = get_session()
    try:
        s.execute(update(Project).where(Project.id == project_id).values(allow_overlap=1 if allow else 0).execution_options(synchronize_session="fetch"))
        s.commit()
        p = s.get(Project, project_id)
        if not p:
            raise ValueError("project not found")
        return ProjectModel(id=p.id, name=p.name, labels=p.labels, relation_types=p.relation_types, allow_overlap=bool(p.allow_overlap), created_at=p.created_at)
    finally:
        s.close()

def update_relation_types(project_id: int, relation_types: List[str]) -> ProjectModel:
    init_db()
    s = get_session()
    try:
        s.execute(update(Project).where(Project.id == project_id).values(relation_types=list(relation_types)).execution_options(synchronize_session="fetch"))
        s.commit()
        p = s.get(Project, project_id)
        if not p:
            raise ValueError("project not found")
        return ProjectModel(id=p.id, name=p.name, labels=p.labels, relation_types=p.relation_types, allow_overlap=bool(p.allow_overlap), created_at=p.created_at)
    finally:
        s.close()
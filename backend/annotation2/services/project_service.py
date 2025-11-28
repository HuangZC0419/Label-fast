import logging
from typing import List
from sqlalchemy import select, delete, update
from ..storage.db import get_session, init_db
from ..storage.schema import Project
from ..models import ProjectModel

logger = logging.getLogger(__name__)

def create_project(name: str, labels: List[str]) -> ProjectModel:
    init_db()
    s = get_session()
    try:
        q = select(Project).where(Project.name == name)
        if s.execute(q).scalar_one_or_none():
            raise ValueError("project name exists")
        p = Project(name=name, labels=list(labels))
        s.add(p)
        s.commit()
        s.refresh(p)
        return ProjectModel(id=p.id, name=p.name, labels=p.labels, created_at=p.created_at)
    finally:
        s.close()

def list_projects() -> List[ProjectModel]:
    init_db()
    s = get_session()
    try:
        q = select(Project).order_by(Project.id.desc())
        rows = s.execute(q).scalars().all()
        return [ProjectModel(id=r.id, name=r.name, labels=r.labels, created_at=r.created_at) for r in rows]
    finally:
        s.close()

def delete_project(project_id: int) -> bool:
    init_db()
    s = get_session()
    try:
        q = delete(Project).where(Project.id == project_id)
        res = s.execute(q)
        s.commit()
        return res.rowcount > 0
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
        return ProjectModel(id=p.id, name=p.name, labels=p.labels, created_at=p.created_at)
    finally:
        s.close()

def get_project(project_id: int) -> ProjectModel:
    init_db()
    s = get_session()
    try:
        p = s.get(Project, project_id)
        if not p:
            raise ValueError("project not found")
        return ProjectModel(id=p.id, name=p.name, labels=p.labels, created_at=p.created_at)
    finally:
        s.close()
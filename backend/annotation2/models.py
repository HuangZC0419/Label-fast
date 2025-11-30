from pydantic import BaseModel, Field
from typing import List
from datetime import datetime

class ProjectModel(BaseModel):
    id: int
    name: str
    labels: List[str] = Field(default_factory=list)
    relation_types: List[str] = Field(default_factory=list)
    allow_overlap: bool = False
    created_at: datetime

class DocumentModel(BaseModel):
    id: int
    project_id: int
    text: str
    status: str | None = None
    source_file: str | None = None
    unit_index: int | None = None
    created_at: datetime

class AnnotationModel(BaseModel):
    id: int
    doc_id: int
    start: int
    end: int
    label: str
    created_at: datetime

class RelationModel(BaseModel):
    id: int
    doc_id: int
    from_ann_id: int
    to_ann_id: int
    relation_type: str
    created_at: datetime
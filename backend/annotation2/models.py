from pydantic import BaseModel, Field
from typing import List, Optional
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
    status: Optional[str] = None
    source_file: Optional[str] = None
    unit_index: Optional[int] = None
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
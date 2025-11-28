from pydantic import BaseModel, Field
from typing import List
from datetime import datetime

class ProjectModel(BaseModel):
    id: int
    name: str
    labels: List[str] = Field(default_factory=list)
    created_at: datetime

class DocumentModel(BaseModel):
    id: int
    project_id: int
    text: str
    created_at: datetime

class AnnotationModel(BaseModel):
    id: int
    doc_id: int
    start: int
    end: int
    label: str
    created_at: datetime
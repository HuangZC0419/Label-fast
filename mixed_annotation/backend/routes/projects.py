"""项目 CRUD 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from schemas import ProjectCreate, ProjectPatch
from serializers import serialize_file
from storage import (
    create_project,
    delete_project,
    get_project,
    has_annotations_for,
    list_files,
    list_projects,
    update_project,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("")
def get_projects() -> list[dict]:
    return list_projects()


@router.post("", status_code=status.HTTP_201_CREATED)
def post_project(payload: ProjectCreate) -> dict:
    return create_project(payload.name, payload.labels, payload.relation_types)


@router.get("/{project_id}")
def get_project_detail(project_id: str) -> dict:
    project = get_project(project_id)
    # uploading 是上传写入过程中的内部状态：文件尚未校验完成，
    # 对前端不可见，避免暴露半截记录或新增无意义的状态类型。
    files = [
        {**serialize_file(meta), "has_annotations": has_annotations_for(meta)}
        for meta in list_files(project_id)
        if meta.get("status") != "uploading"
    ]
    return {**project, "files": files}


@router.patch("/{project_id}")
def patch_project(project_id: str, payload: ProjectPatch) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    return update_project(project_id, changes)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_project(project_id: str) -> Response:
    delete_project(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

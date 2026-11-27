"""项目 CRUD 路由。

路由层只做「请求参数 → 服务层调用」的翻译：字典合并、引用统计、缺失标签
恢复等业务判定全部在 ``storage`` 内完成，路由不写任何合并逻辑。
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from schemas import ProjectCreate, ProjectPatch, ProjectSplitRequest
from serializers import serialize_file
from storage import (
    create_project,
    delete_project,
    get_project,
    has_annotations_for,
    list_files,
    list_projects,
    project_label_usage_report,
    restore_missing_labels,
    split_project,
    update_project_dictionary,
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
    """增量更新项目：字典只增不减，删除必须显式声明且可能返回 409。"""

    # 旧字段 labels / relation_types 按追加项处理，这是对旧前端包的兜底：
    # 即便它提交整份数组，也不会删掉其他标注员新增的标签。
    return update_project_dictionary(
        project_id,
        name=payload.name,
        labels_add=[*(payload.labels or []), *(payload.labels_add or [])],
        labels_remove=payload.labels_remove or [],
        relation_types_add=[
            *(payload.relation_types or []),
            *(payload.relation_types_add or []),
        ],
        relation_types_remove=payload.relation_types_remove or [],
        shortcuts_set=payload.shortcuts_set or {},
        shortcuts_unset=payload.shortcuts_unset or [],
        force=payload.force,
    )


@router.post("/{project_id}/split")
def post_project_split(project_id: str, payload: ProjectSplitRequest) -> dict:
    """按文件序号区间把项目拆成多个新项目（文件移动，源项目保留）。

    区间语义、文件顺序、继承与回滚全部在 ``storage.split_project`` 内完成；
    这里只把 Pydantic 模型翻译成服务层认识的字典列表。
    """

    return split_project(
        project_id,
        [
            {"name": group.name, "start": group.start, "end": group.end}
            for group in payload.groups
        ],
    )


@router.get("/{project_id}/labels/usage")
def get_project_label_usage(project_id: str) -> dict:
    """只读：实体/段落标签引用计数 + 被引用但字典缺失的标签。"""

    return project_label_usage_report(project_id)


@router.post("/{project_id}/labels/restore")
def post_project_labels_restore(project_id: str) -> dict:
    """把被标注引用但字典缺失的标签全部补回字典（只增不减）。"""

    result = restore_missing_labels(project_id)
    return {**result["project"], "restored": result["restored"]}


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_project(project_id: str) -> Response:
    delete_project(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

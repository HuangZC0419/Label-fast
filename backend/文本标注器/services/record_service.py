import os
import json
from typing import Dict, Any

# 项目数据根目录：backend/文本标注器/projects/
_PROJECTS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "projects"))

def get_project_dir(project_name: str) -> str:
    """获取项目专属文件夹路径（按项目名），不存在则自动创建。"""
    safe_name = "".join([c for c in project_name if c.isalnum() or c in (' ', '-', '_')]).strip()
    if not safe_name:
        safe_name = "default"
    proj_dir = os.path.join(_PROJECTS_ROOT, safe_name)
    os.makedirs(proj_dir, exist_ok=True)
    return proj_dir

def get_annotation_file_path(project_id: int, project_name: str = None) -> str:
    """获取标注记录 JSONL 文件路径。"""
    if project_name:
        proj_dir = get_project_dir(project_name)
        return os.path.join(proj_dir, "annotations.jsonl")

    # Fallback (无项目名时用 ID)
    filename = f"project_{project_id}_annotations.jsonl"
    return os.path.join(_PROJECTS_ROOT, filename)

def _lookup_source(doc_id: Any):
    """按文档 ID 回查来源文件与分段序号，返回 (file_name, file_number)。"""
    try:
        doc_id = int(doc_id)
    except (TypeError, ValueError):
        return None, None
    if doc_id <= 0:
        return None, None

    try:
        from ..storage.db import get_session, init_db
        from ..storage.schema import Document

        init_db()
        s = get_session()
        try:
            d = s.get(Document, doc_id)
            if d is None:
                return None, None
            file_name = os.path.basename(d.source_file) if d.source_file else None
            file_number = (d.unit_index + 1) if d.unit_index is not None else 1
            return file_name, file_number
        finally:
            s.close()
    except Exception:
        return None, None


def _with_source_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """确保记录包含 file_name / file_number，并放在字段最前面。

    - 优先使用记录中已携带的值（前端导入时写入）；
    - 缺失时按文档 ID 回查数据库；
    - 仍然无法确定时不写入该字段，保持旧格式兼容。
    """
    file_name = data.get("file_name")
    file_number = data.get("file_number")

    if not file_name or file_number is None:
        db_name, db_number = _lookup_source(data.get("id"))
        file_name = file_name or db_name
        if file_number is None:
            file_number = db_number

    # 没有文件名时无法判断来源，保持旧格式
    if not file_name:
        return data

    ordered: Dict[str, Any] = {
        "file_name": file_name,
        "file_number": file_number if file_number is not None else 1,
    }
    for key, value in data.items():
        if key not in ("file_name", "file_number"):
            ordered[key] = value
    return ordered


def append_jsonl(project_id: int, data: Dict[str, Any]) -> bool:
    """
    Appends a single record to the project's JSONL file.
    Also saves the raw text content to imports/ directory.
    """
    data = _with_source_fields(data)
    project_name = data.get("meta", {}).get("project_name")
    file_path = get_annotation_file_path(project_id, project_name)

    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        json_line = json.dumps(data, ensure_ascii=False) + "\n"
        with open(file_path, 'a', encoding='utf-8') as f:
            f.write(json_line)

        # 同时保存原始文本到 imports/ 目录
        text = data.get("text", "")
        if text and project_name:
            proj_dir = get_project_dir(project_name)
            texts_dir = os.path.join(proj_dir, "imports")
            os.makedirs(texts_dir, exist_ok=True)
            doc_id = data.get("id", -1)
            # 用文档 ID 或时间戳命名
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:18]
            txt_file = os.path.join(texts_dir, f"doc_{doc_id}_{ts}.txt")
            with open(txt_file, 'w', encoding='utf-8') as tf:
                tf.write(text)

        return True
    except Exception as e:
        print(f"Error appending to JSONL: {e}")
        raise e

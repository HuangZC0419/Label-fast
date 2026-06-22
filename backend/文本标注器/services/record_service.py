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

def append_jsonl(project_id: int, data: Dict[str, Any]) -> bool:
    """
    Appends a single record to the project's JSONL file.
    Also saves the raw text content to imports/ directory.
    """
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

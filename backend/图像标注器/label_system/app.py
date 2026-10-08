import os
import json
import uuid
import zipfile
import io
import shutil
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Body, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional

app = FastAPI()

# Allow CORS just in case, though we serve from same origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Default paths (relative to where the script might be run, assuming root or inside label_system)
# We try to find the project root.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
PROJECTS_FILE = os.path.join(PROJECT_ROOT, "projects.json")

# 离线静态资源（Vue.js / Tailwind CDN 本地副本，用于无互联网环境）
STATIC_DIR = os.path.join(BASE_DIR, "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="minimind_static")

# 默认路径为空 — 进入平台时不应预填任何路径，由用户选择/创建项目后自动生成
DEFAULT_IMAGE_DIR = ""
DEFAULT_JSONL_PATH = ""
DEFAULT_JSONL_FILENAME = "标注结果_qa.jsonl"

def _resolve_path(path: str) -> str:
    """将相对路径转为绝对路径（相对于 PROJECT_ROOT）。已是绝对路径则直接返回。"""
    if os.path.isabs(path):
        return path
    return os.path.join(PROJECT_ROOT, path)

def _ensure_dir(path: str):
    """确保目录存在（先 resolve 路径）。"""
    os.makedirs(_resolve_path(path), exist_ok=True)

class Config(BaseModel):
    image_dir: str
    jsonl_path: str

class Project(BaseModel):
    id: str
    name: str
    project_dir: str = ""
    image_dir: str = ""
    jsonl_path: str = ""
    box_jsonl_path: str = ""
    labels: List[str] = Field(default_factory=list)  # 框选标签列表，按项目独立保存
    last_image: str = ""

# Store current config in memory（启动时为空，等待用户选择/创建项目）
current_config = Config(image_dir="", jsonl_path="")
current_project_name = ""
current_project_id = ""
active_project: Optional[Project] = None

def _normalize_rel_path(path: str) -> str:
    """统一项目内相对路径格式，避免 Windows 反斜杠导致比较失效。"""
    return (path or "").replace("\\", "/").strip("/")

def _sanitize_project_name(project_name: str) -> str:
    safe_name = "".join(c for c in project_name if c.isalnum() or c in (' ', '-', '_')).strip()
    if not safe_name:
        safe_name = "default"
    return safe_name

def _build_project_paths(project_name: str) -> dict:
    safe_name = _sanitize_project_name(project_name)
    project_dir = f"projects/{safe_name}"
    return {
        "project_dir": project_dir,
        "image_dir": f"{project_dir}/images",
        "jsonl_path": f"{project_dir}/{DEFAULT_JSONL_FILENAME}",
        "box_jsonl_path": f"{project_dir}/标注结果_boxes.jsonl",
    }

def _infer_project_dir(raw_project: dict) -> str:
    project_dir = _normalize_rel_path(raw_project.get("project_dir", ""))
    if project_dir:
        return project_dir

    image_dir = _normalize_rel_path(raw_project.get("image_dir", ""))
    if image_dir.endswith("/images"):
        return image_dir[:-len("/images")]

    jsonl_path = _normalize_rel_path(raw_project.get("jsonl_path", ""))
    if jsonl_path.endswith(".jsonl"):
        return os.path.dirname(jsonl_path).replace("\\", "/")
    if jsonl_path:
        return jsonl_path

    return ""

def _normalize_labels(labels: Optional[List[str]]) -> List[str]:
    if not labels:
        return []

    normalized = []
    seen = set()
    for label in labels:
        value = str(label).strip()
        if value and value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized

def _ensure_parent_dir_for_file(path: str):
    parent = os.path.dirname(_resolve_path(path))
    if parent:
        os.makedirs(parent, exist_ok=True)

def _ensure_project_structure(project: Project):
    os.makedirs(_resolve_path(project.project_dir), exist_ok=True)
    os.makedirs(_resolve_path(project.image_dir), exist_ok=True)
    _ensure_parent_dir_for_file(project.jsonl_path)
    _ensure_parent_dir_for_file(project.box_jsonl_path)

def _set_active_project(project: Optional[Project]):
    global active_project, current_config, current_project_name, current_project_id
    active_project = project
    if project is None:
        current_config = Config(image_dir="", jsonl_path="")
        current_project_name = ""
        current_project_id = ""
        return

    current_config = Config(image_dir=project.image_dir, jsonl_path=project.jsonl_path)
    current_project_name = project.name
    current_project_id = project.id

def _load_active_project_from_disk() -> Optional[Project]:
    if not current_project_id:
        return None
    projects = load_projects()
    return next((p for p in projects if p.id == current_project_id), None)

def _require_active_project() -> Project:
    project = active_project or _load_active_project_from_disk()
    if project is None:
        raise HTTPException(status_code=400, detail="请先选择或创建一个项目")
    _set_active_project(project)
    return project

def _reconcile_legacy_project_dir(legacy_project_dir: str, canonical_project_dir: str) -> str:
    legacy_project_dir = _normalize_rel_path(legacy_project_dir)
    canonical_project_dir = _normalize_rel_path(canonical_project_dir)
    if not legacy_project_dir or legacy_project_dir == canonical_project_dir:
        return canonical_project_dir

    legacy_abs = _resolve_path(legacy_project_dir)
    canonical_abs = _resolve_path(canonical_project_dir)

    if os.path.normcase(os.path.abspath(legacy_abs)) == os.path.normcase(os.path.abspath(canonical_abs)):
        return canonical_project_dir

    if os.path.isdir(legacy_abs) and not os.path.exists(canonical_abs):
        os.makedirs(os.path.dirname(canonical_abs), exist_ok=True)
        try:
            shutil.move(legacy_abs, canonical_abs)
            return canonical_project_dir
        except OSError as exc:
            print(f"项目目录迁移失败，保留旧目录 {legacy_project_dir}: {exc}")

    if os.path.isdir(canonical_abs):
        return canonical_project_dir
    if os.path.isdir(legacy_abs):
        return legacy_project_dir
    return canonical_project_dir

def _normalize_project(raw_project: dict) -> Project:
    name = str(raw_project.get("name", "")).strip() or "default"
    canonical_paths = _build_project_paths(name)
    resolved_project_dir = _reconcile_legacy_project_dir(
        _infer_project_dir(raw_project),
        canonical_paths["project_dir"],
    )
    final_paths = _build_project_paths(os.path.basename(resolved_project_dir) or name)
    if _normalize_rel_path(resolved_project_dir) != _normalize_rel_path(canonical_paths["project_dir"]):
        final_paths = {
            "project_dir": resolved_project_dir,
            "image_dir": f"{resolved_project_dir}/images",
            "jsonl_path": f"{resolved_project_dir}/{DEFAULT_JSONL_FILENAME}",
            "box_jsonl_path": f"{resolved_project_dir}/标注结果_boxes.jsonl",
        }
    return Project(
        id=str(raw_project.get("id") or uuid.uuid4()),
        name=name,
        labels=_normalize_labels(raw_project.get("labels", [])),
        last_image=str(raw_project.get("last_image", "") or "").strip(),
        **final_paths,
    )

def _find_project_by_id(projects: List[Project], project_id: str) -> Optional[Project]:
    return next((project for project in projects if project.id == project_id), None)

def _save_single_project(project: Project) -> Project:
    projects = load_projects()
    target = _find_project_by_id(projects, project.id)
    if target is None:
        raise HTTPException(status_code=404, detail="Project not found")

    updated_projects = [project if item.id == project.id else item for item in projects]
    save_projects(updated_projects)
    _set_active_project(project)
    return project

def _delete_single_project(project_id: str) -> None:
    projects = load_projects()
    target = _find_project_by_id(projects, project_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Project not found")

    updated_projects = [item for item in projects if item.id != project_id]
    save_projects(updated_projects)

    project_abs_dir = _resolve_path(target.project_dir)
    if os.path.isdir(project_abs_dir):
        shutil.rmtree(project_abs_dir, ignore_errors=True)

    if current_project_id == project_id:
        _set_active_project(None)

def _read_jsonl_records(path: str) -> List[dict]:
    abs_path = _resolve_path(path)
    if not os.path.exists(abs_path):
        return []

    records = []
    with open(abs_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records

def _write_jsonl_records(path: str, records: List[dict]):
    _ensure_parent_dir_for_file(path)
    abs_path = _resolve_path(path)
    with open(abs_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

def _upsert_annotation_record(path: str, image_name: str, entry: dict):
    records = _read_jsonl_records(path)
    replaced = False
    for idx, record in enumerate(records):
        if record.get("image") == image_name:
            records[idx] = entry
            replaced = True
            break
    if not replaced:
        records.append(entry)
    _write_jsonl_records(path, records)

def _get_labeled_images() -> set:
    """扫描当前项目的标注文件，返回已标注图片的文件名集合。"""
    labeled = set()
    project = active_project or _load_active_project_from_disk()
    if project is None:
        return labeled

    for record in _read_jsonl_records(project.jsonl_path) + _read_jsonl_records(project.box_jsonl_path):
        image_name = record.get("image")
        if image_name:
            labeled.add(image_name)
    return labeled


def _collect_annotation_data() -> dict:
    """收集当前项目所有标注数据，返回 {qa_records: [...], box_records: [...]}。"""
    project = active_project or _load_active_project_from_disk()
    if project is None:
        return {"qa": [], "box": []}

    return {
        "qa": _read_jsonl_records(project.jsonl_path),
        "box": _read_jsonl_records(project.box_jsonl_path),
    }

@app.get("/api/annotations")
async def get_annotations():
    return _collect_annotation_data()

def load_projects() -> List[Project]:
    """加载项目列表，仅以 projects.json 为准，不自动恢复历史目录。"""
    projects_base = _resolve_path("projects")
    os.makedirs(projects_base, exist_ok=True)

    raw_data = []
    existing: List[Project] = []
    if os.path.exists(PROJECTS_FILE):
        try:
            with open(PROJECTS_FILE, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)
                for p in raw_data:
                    try:
                        existing.append(_normalize_project(p))
                    except Exception as pex:
                        print(f"跳过无效项目条目: {pex}")
        except Exception as e:
            print(f"Error loading projects: {e}")

    valid_projects: List[Project] = []
    for p in existing:
        try:
            _ensure_project_structure(p)
            valid_projects.append(p)
        except OSError as e:
            print(f"跳过项目 '{p.name}'：无法创建项目目录 ({p.project_dir}): {e}")

    normalized_json = json.dumps(
        [p.model_dump() for p in valid_projects],
        ensure_ascii=False,
        sort_keys=True,
    )
    raw_json = json.dumps(raw_data, ensure_ascii=False, sort_keys=True)
    if normalized_json != raw_json:
        save_projects(valid_projects)

    return valid_projects

def save_projects(projects: List[Project]):
    with open(PROJECTS_FILE, 'w', encoding='utf-8') as f:
        json.dump([p.model_dump() for p in projects], f, ensure_ascii=False, indent=2)

class LabelData(BaseModel):
    image: str
    user_content: str
    assistant_content: str

class BoxItem(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float
    label: str

class BoxLabelData(BaseModel):
    image: str
    boxes: List[BoxItem]

class SaveCurrentProjectData(BaseModel):
    labels: List[str] = Field(default_factory=list)
    last_image: str = ""
    name: str = ""
    qa_records: Optional[List[LabelData]] = None
    box_records: Optional[List[BoxLabelData]] = None

def _build_qa_entry(image: str, user_content: str, assistant_content: str) -> dict:
    user_text = str(user_content or "").strip()
    if not user_text.endswith("<image>"):
        user_text = f"{user_text}\n<image>"
    return {
        "conversations": [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": str(assistant_content or "")},
        ],
        "image": image,
    }

def _build_box_entry(image: str, boxes: List[BoxItem]) -> dict:
    return {
        "image": image,
        "boxes": [b.model_dump() for b in boxes],
    }

@app.get("/")
async def read_index():
    return FileResponse(os.path.join(BASE_DIR, "templates", "index.html"))

@app.get("/api/config")
async def get_config():
    project = active_project or _load_active_project_from_disk()
    return {
        "image_dir": current_config.image_dir,
        "jsonl_path": current_config.jsonl_path,
        "project_id": current_project_id,
        "project_name": current_project_name,
        "project_dir": project.project_dir if project else "",
        "box_jsonl_path": project.box_jsonl_path if project else "",
        "last_image": project.last_image if project else "",
    }

@app.post("/api/config")
async def update_config(config: Config):
    global current_config
    # Verify paths exist
    # if not os.path.isdir(config.image_dir):
    #     raise HTTPException(status_code=400, detail="Image directory does not exist")
    # We don't enforce jsonl existence, we can create it.
    current_config = config
    return current_config

@app.get("/api/projects")
async def get_projects():
    return load_projects()

@app.post("/api/projects")
async def create_project(project: Project):
    projects = load_projects()
    project_name = project.name.strip()
    if not project_name:
        raise HTTPException(status_code=400, detail="项目名称不能为空")
    if project.id:
        raise HTTPException(status_code=400, detail="该接口只支持新建项目")

    duplicate = next((p for p in projects if p.name == project_name), None)
    if duplicate:
        raise HTTPException(status_code=400, detail="项目名称已存在")

    canonical_paths = _build_project_paths(project_name)
    labels = _normalize_labels(project.labels)
    project = Project(
        id=str(uuid.uuid4()),
        name=project_name,
        labels=labels,
        last_image="",
        **canonical_paths,
    )
    projects.append(project)

    _ensure_project_structure(project)
    save_projects(projects)
    _set_active_project(project)
    return project

@app.post("/api/projects/switch/{project_id}")
async def switch_project(project_id: str):
    projects = load_projects()
    project = next((p for p in projects if p.id == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    _set_active_project(project)
    return {"status": "success", "config": current_config}

@app.post("/api/projects/current")
async def save_current_project(data: SaveCurrentProjectData):
    current = _require_active_project()
    if data.name and data.name.strip() and data.name.strip() != current.name:
        raise HTTPException(status_code=400, detail="不支持修改项目名称")

    updated_project = Project(
        id=current.id,
        name=current.name,
        project_dir=current.project_dir,
        image_dir=current.image_dir,
        jsonl_path=current.jsonl_path,
        box_jsonl_path=current.box_jsonl_path,
        labels=_normalize_labels(data.labels),
        last_image=str(data.last_image or "").strip(),
    )
    saved_project = _save_single_project(updated_project)

    if data.qa_records is not None:
        qa_entries = [
            _build_qa_entry(item.image, item.user_content, item.assistant_content)
            for item in data.qa_records
            if str(item.image or "").strip()
        ]
        _write_jsonl_records(saved_project.jsonl_path, qa_entries)

    if data.box_records is not None:
        box_entries = [
            _build_box_entry(item.image, item.boxes)
            for item in data.box_records
            if str(item.image or "").strip()
        ]
        _write_jsonl_records(saved_project.box_jsonl_path, box_entries)

    return saved_project

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    _delete_single_project(project_id)
    return {"status": "success"}

def _find_images_recursive(base_dir: str) -> list:
    """递归扫描目录中的所有图片文件，返回相对路径列表。"""
    result = []
    if not os.path.isdir(base_dir):
        return result
    for root, dirs, files in os.walk(base_dir):
        for f in files:
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp')):
                # 返回相对于 base_dir 的路径
                rel = os.path.relpath(os.path.join(root, f), base_dir)
                result.append(rel)
    return sorted(result)


@app.get("/api/images")
async def list_images():
    project = active_project or _load_active_project_from_disk()
    if project is None:
        return {"images": [], "labeled": [], "error": "请先选择或创建一个项目。"}

    img_dir = _resolve_path(project.image_dir)
    if not img_dir or not os.path.exists(img_dir):
        return {
            "images": [],
            "labeled": [],
            "error": f"图片目录不存在: {project.image_dir}。请在项目配置中设置正确的图片文件夹路径。"
        }

    try:
        images = _find_images_recursive(img_dir)
        labeled = _get_labeled_images()
        return {"images": images, "labeled": list(labeled)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/image_file/{filename:path}")
async def get_image(filename: str):
    # 在 image_dir 下查找（支持子目录）
    project = _require_active_project()
    img_dir = _resolve_path(project.image_dir)
    direct = os.path.join(img_dir, filename)
    if os.path.isfile(direct):
        return FileResponse(direct)
    # 递归查找
    for root, dirs, files in os.walk(img_dir):
        full = os.path.join(root, os.path.basename(filename))
        if os.path.isfile(full):
            return FileResponse(full)
    raise HTTPException(status_code=404, detail="Image not found")

@app.post("/api/save")
async def save_label(data: LabelData):
    # Automatically append <image> tag if not present (though frontend should strip it, we ensure it's here)
    # User requested format: "content": "text...\n<image>"
    entry = _build_qa_entry(data.image, data.user_content, data.assistant_content)

    project = _require_active_project()
    try:
        _upsert_annotation_record(project.jsonl_path, data.image, entry)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def get_boxes_path() -> str:
    project = _require_active_project()
    return _resolve_path(project.box_jsonl_path)

@app.post("/api/save_boxes")
async def save_boxes(data: BoxLabelData):
    entry = _build_box_entry(data.image, data.boxes)
    project = _require_active_project()
    try:
        _upsert_annotation_record(project.box_jsonl_path, data.image, entry)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/export-zip")
async def export_zip(mode: str = Query("all", description="导出模式: qa | box | all")):
    """一键打包导出 ZIP — 包含标注数据 JSONL + 已标注图片。

    - mode=qa:   仅导出问答标注 + 对应图片
    - mode=box:  仅导出框选标注 + 对应图片
    - mode=all:  同时导出问答 + 框选 + 图片
    """
    buf = io.BytesIO()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    project = _require_active_project()
    safe_name = _sanitize_project_name(project.name or "export")
    download_name = "".join(c for c in safe_name if c.isascii() and (c.isalnum() or c in (" ", "-", "_"))).strip() or "export"

    # 收集标注数据
    data = _collect_annotation_data()
    qa_records = data.get("qa", [])
    box_records = data.get("box", [])
    labeled_images = _get_labeled_images()
    image_dir = _resolve_path(project.image_dir or DEFAULT_IMAGE_DIR)

    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 问答标注
        if mode in ("qa", "all") and qa_records:
            jsonl_content = "\n".join(json.dumps(r, ensure_ascii=False) for r in qa_records) + "\n"
            zf.writestr(f"{safe_name}/{DEFAULT_JSONL_FILENAME}", jsonl_content)

        # 框选标注
        if mode in ("box", "all") and box_records:
            jsonl_content = "\n".join(json.dumps(r, ensure_ascii=False) for r in box_records) + "\n"
            zf.writestr(f"{safe_name}/标注结果_boxes.jsonl", jsonl_content)

        # 包含已标注图片（递归查找子目录）
        img_added = 0
        for img_name in sorted(labeled_images):
            # 先直接查找，再递归扫描子目录
            found = None
            direct = os.path.join(image_dir, img_name)
            if os.path.isfile(direct):
                found = direct
            else:
                for root, dirs, files in os.walk(image_dir):
                    if img_name in files:
                        found = os.path.join(root, img_name)
                        break
            if found:
                zf.write(found, f"{safe_name}/images/{img_name}")
                img_added += 1

        # README
        lines = [
            f"图像标注导出包 — {project.name or '未命名项目'}",
            f"导出时间: {datetime.now(timezone.utc).isoformat()}",
            f"图片目录: {image_dir}",
            f"问答标注记录: {len(qa_records)} 条",
            f"框选标注记录: {len(box_records)} 条",
            f"已标注图片: {img_added} 张",
            f"",
            f"文件结构:",
            f"  {safe_name}/",
        ]
        if qa_records:
            lines.append(f"    ├─ {DEFAULT_JSONL_FILENAME}  ({len(qa_records)} 条)")
        if box_records:
            lines.append(f"    ├─ 标注结果_boxes.jsonl ({len(box_records)} 条)")
        if img_added > 0:
            lines.append(f"    └─ images/              ({img_added} 张图片)")
        zf.writestr(f"{safe_name}/README.txt", "\n".join(lines) + "\n")

    return StreamingResponse(
        io.BytesIO(buf.getvalue()),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{download_name}_{ts}.zip"'}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=8080)

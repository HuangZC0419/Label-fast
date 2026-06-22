import os
import json
import uuid
import zipfile
import io
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Body, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
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

# 默认使用相对路径（相对于 PROJECT_ROOT），跨机器可移植
DEFAULT_IMAGE_DIR = "projects"
DEFAULT_JSONL_PATH = "projects"
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
    image_dir: str
    jsonl_path: str

# Store current config in memory
current_config = Config(image_dir=DEFAULT_IMAGE_DIR, jsonl_path=DEFAULT_JSONL_PATH)
current_project_name = ""

def _make_project_dir(path: str, project_name: str) -> str:
    """在指定目录下创建项目子文件夹并返回绝对路径。"""
    safe_name = "".join(c for c in project_name if c.isalnum() or c in (' ', '-', '_')).strip()
    if not safe_name:
        safe_name = "default"
    proj_dir = os.path.join(_resolve_path(path), safe_name)
    os.makedirs(proj_dir, exist_ok=True)
    return proj_dir

def resolve_jsonl_path(path: str) -> str:
    """获取 JSONL 标注文件路径（绝对路径）。按项目名分子文件夹。"""
    base = _resolve_path(path)
    if os.path.isdir(base) and current_project_name:
        base = _make_project_dir(base, current_project_name)
    if os.path.isdir(base):
        return os.path.join(base, DEFAULT_JSONL_FILENAME)
    return base

def _get_labeled_images() -> set:
    """扫描当前项目的标注文件，返回已标注图片的文件名集合。"""
    labeled = set()
    jsonl_path = resolve_jsonl_path(current_config.jsonl_path)
    boxes_path = get_boxes_path()
    for p in [jsonl_path, boxes_path]:
        if p and os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line: continue
                        data = json.loads(line)
                        if "image" in data:
                            labeled.add(data["image"])
            except: pass
    return labeled


def _collect_annotation_data() -> dict:
    """收集当前项目所有标注数据，返回 {qa_records: [...], box_records: [...]}。"""
    result = {"qa": [], "box": []}
    jsonl_path = resolve_jsonl_path(current_config.jsonl_path)
    boxes_path = get_boxes_path()

    if jsonl_path and os.path.exists(jsonl_path):
        try:
            with open(jsonl_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            result["qa"].append(json.loads(line))
                        except: pass
        except: pass

    if boxes_path and os.path.exists(boxes_path):
        try:
            with open(boxes_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            result["box"].append(json.loads(line))
                        except: pass
        except: pass

    return result

def load_projects() -> List[Project]:
    """加载项目列表，自动过滤掉路径不存在的无效项目。"""
    if not os.path.exists(PROJECTS_FILE):
        return []
    try:
        with open(PROJECTS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            valid_projects = []
            for p in data:
                # 验证项目路径是否有效（非空且目录存在或可创建）
                img_dir = p.get("image_dir", "")
                if img_dir and not os.path.exists(img_dir):
                    # 路径可能是旧的 Docker/其他机器的绝对路径，跳过
                    print(f"跳过项目 '{p.get('name', '?')}'：图片目录不存在 ({img_dir})")
                    continue
                valid_projects.append(Project(**p))
            return valid_projects
    except Exception as e:
        print(f"Error loading projects: {e}")
        return []

def save_projects(projects: List[Project]):
    with open(PROJECTS_FILE, 'w', encoding='utf-8') as f:
        json.dump([p.dict() for p in projects], f, ensure_ascii=False, indent=2)

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

@app.get("/")
async def read_index():
    return FileResponse(os.path.join(BASE_DIR, "templates", "index.html"))

@app.get("/api/config")
async def get_config():
    return current_config

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
async def create_or_update_project(project: Project):
    projects = load_projects()
    existing_idx = next((i for i, p in enumerate(projects) if p.id == project.id), -1)

    # 生成项目专属子目录路径
    safe_name = "".join(c for c in project.name if c.isalnum() or c in (' ', '-', '_')).strip() or "default"
    default_image_dir = f"projects/{safe_name}/images"
    default_jsonl_path = f"projects/{safe_name}"

    # 如果用户没有自定义路径（即用了默认值或空值），自动填写项目专属路径
    if not project.image_dir or project.image_dir.strip() in ("projects", ""):
        project.image_dir = default_image_dir
    if not project.jsonl_path or project.jsonl_path.strip() in ("projects", ""):
        project.jsonl_path = default_jsonl_path

    # 创建项目目录（包括 images 子目录）
    img_abs = _resolve_path(project.image_dir)
    jsonl_abs = _resolve_path(project.jsonl_path)
    os.makedirs(img_abs, exist_ok=True)
    os.makedirs(jsonl_abs, exist_ok=True)

    if existing_idx >= 0:
        projects[existing_idx] = project
    else:
        if any(p.name == project.name for p in projects):
            raise HTTPException(status_code=400, detail="Project name already exists")
        if not project.id:
            project.id = str(uuid.uuid4())
        projects.append(project)

    save_projects(projects)

    global current_config, current_project_name
    current_config = Config(image_dir=project.image_dir, jsonl_path=project.jsonl_path)
    current_project_name = project.name

    return project

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    projects = load_projects()
    projects = [p for p in projects if p.id != project_id]
    save_projects(projects)
    return {"status": "success"}

@app.post("/api/projects/switch/{project_id}")
async def switch_project(project_id: str):
    global current_config, current_project_name
    projects = load_projects()
    project = next((p for p in projects if p.id == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    current_config = Config(image_dir=project.image_dir, jsonl_path=project.jsonl_path)
    current_project_name = project.name
    return {"status": "success", "config": current_config}

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
    img_dir = _resolve_path(current_config.image_dir)
    if not img_dir or not os.path.exists(img_dir):
        return {
            "images": [],
            "labeled": [],
            "error": f"图片目录不存在: {current_config.image_dir}。请在项目配置中设置正确的图片文件夹路径。"
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
    img_dir = _resolve_path(current_config.image_dir)
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
    user_text = data.user_content.strip()
    if not user_text.endswith("<image>"):
        user_text = f"{user_text}\n<image>"
        
    entry = {
        "conversations": [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": data.assistant_content}
        ],
        "image": data.image
    }
    
    try:
        jsonl_path = resolve_jsonl_path(current_config.jsonl_path)
        with open(jsonl_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def get_boxes_path() -> str:
    base = resolve_jsonl_path(current_config.jsonl_path)
    return base.replace("_qa.jsonl", "_boxes.jsonl")

@app.post("/api/save_boxes")
async def save_boxes(data: BoxLabelData):
    entry = {
        "image": data.image,
        "boxes": [b.dict() for b in data.boxes]
    }
    path = get_boxes_path()
    try:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
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
    safe_name = "".join(c for c in (current_project_name or "export") if c.isalnum() or c in (' ', '-', '_')).strip() or "export"

    # 收集标注数据
    data = _collect_annotation_data()
    qa_records = data.get("qa", [])
    box_records = data.get("box", [])
    labeled_images = _get_labeled_images()
    image_dir = _resolve_path(current_config.image_dir or DEFAULT_IMAGE_DIR)

    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 问答标注
        if mode in ("qa", "all") and qa_records:
            jsonl_content = "\n".join(json.dumps(r, ensure_ascii=False) for r in qa_records) + "\n"
            zf.writestr(f"{safe_name}/qa_annotations.jsonl", jsonl_content)

        # 框选标注
        if mode in ("box", "all") and box_records:
            jsonl_content = "\n".join(json.dumps(r, ensure_ascii=False) for r in box_records) + "\n"
            zf.writestr(f"{safe_name}/box_annotations.jsonl", jsonl_content)

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
            f"图像标注导出包 — {current_project_name or '未命名项目'}",
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
            lines.append(f"    ├─ qa_annotations.jsonl  ({len(qa_records)} 条)")
        if box_records:
            lines.append(f"    ├─ box_annotations.jsonl ({len(box_records)} 条)")
        if img_added > 0:
            lines.append(f"    └─ images/              ({img_added} 张图片)")
        zf.writestr(f"{safe_name}/README.txt", "\n".join(lines) + "\n")

    return StreamingResponse(
        io.BytesIO(buf.getvalue()),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_{ts}.zip"'}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=8080)

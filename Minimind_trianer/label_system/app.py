import os
import json
import uuid
import sys
import subprocess
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
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

DEFAULT_IMAGE_DIR = os.path.join(PROJECT_ROOT, "pretrain_images")
DEFAULT_JSONL_PATH = os.path.join(PROJECT_ROOT, "pretrain_data.jsonl")
DEFAULT_JSONL_FILENAME = "pretrain_data.jsonl"

def run_dialog_script(script_code):
    """Run a python script in a subprocess to open a dialog"""
    cmd = [sys.executable, "-c", script_code]
    try:
        # On Windows, we might need shell=True or creationflags to avoid console window popping up if we want to be stealthy,
        # but for now standard subprocess is fine.
        res = subprocess.check_output(cmd, cwd=PROJECT_ROOT).decode('utf-8').strip()
        return res
    except Exception as e:
        print(f"Dialog error: {e}")
        return ""

@app.get("/api/utils/select_folder")
async def select_folder():
    script = "import tkinter as tk; from tkinter import filedialog; root=tk.Tk(); root.withdraw(); root.attributes('-topmost', True); print(filedialog.askdirectory()); root.destroy()"
    path = run_dialog_script(script)
    return {"path": path}

@app.get("/api/utils/select_file_save")
async def select_file_save():
    script = "import tkinter as tk; from tkinter import filedialog; root=tk.Tk(); root.withdraw(); root.attributes('-topmost', True); print(filedialog.askdirectory()); root.destroy()"
    path = run_dialog_script(script)
    return {"path": path}

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

def resolve_jsonl_path(path: str) -> str:
    if os.path.isdir(path):
        return os.path.join(path, DEFAULT_JSONL_FILENAME)
    return path

def load_projects() -> List[Project]:
    if not os.path.exists(PROJECTS_FILE):
        return []
    try:
        with open(PROJECTS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return [Project(**p) for p in data]
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
    # Check if exists
    existing_idx = next((i for i, p in enumerate(projects) if p.id == project.id), -1)
    
    if existing_idx >= 0:
        projects[existing_idx] = project
    else:
        # Check if name exists
        if any(p.name == project.name for p in projects):
             raise HTTPException(status_code=400, detail="Project name already exists")
        if not project.id:
            project.id = str(uuid.uuid4())
        projects.append(project)
    
    save_projects(projects)
    
    # Auto switch to this project
    global current_config
    current_config = Config(image_dir=project.image_dir, jsonl_path=project.jsonl_path)
    
    return project

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    projects = load_projects()
    projects = [p for p in projects if p.id != project_id]
    save_projects(projects)
    return {"status": "success"}

@app.post("/api/projects/switch/{project_id}")
async def switch_project(project_id: str):
    global current_config
    projects = load_projects()
    project = next((p for p in projects if p.id == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    current_config = Config(image_dir=project.image_dir, jsonl_path=project.jsonl_path)
    return {"status": "success", "config": current_config}

@app.get("/api/images")
async def list_images():
    if not os.path.exists(current_config.image_dir):
        return {"images": [], "labeled": []}
    
    try:
        files = os.listdir(current_config.image_dir)
        images = [f for f in files if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp'))]
        images.sort()
        
        # Check labeled images
        labeled = set()
        jsonl_path = resolve_jsonl_path(current_config.jsonl_path)
        if os.path.exists(jsonl_path):
            with open(jsonl_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    try:
                        data = json.loads(line)
                        if "image" in data:
                            labeled.add(data["image"])
                    except:
                        pass
        
        return {"images": images, "labeled": list(labeled)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/image_file/{filename}")
async def get_image(filename: str):
    file_path = os.path.join(current_config.image_dir, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(file_path)

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
    root, ext = os.path.splitext(base)
    return root + "_boxes.jsonl"

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=8080)

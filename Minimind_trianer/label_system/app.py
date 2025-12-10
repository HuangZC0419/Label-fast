import os
import json
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

DEFAULT_IMAGE_DIR = os.path.join(PROJECT_ROOT, "pretrain_images")
DEFAULT_JSONL_PATH = os.path.join(PROJECT_ROOT, "pretrain_data.jsonl")

class Config(BaseModel):
    image_dir: str
    jsonl_path: str

# Store current config in memory
current_config = Config(image_dir=DEFAULT_IMAGE_DIR, jsonl_path=DEFAULT_JSONL_PATH)

class LabelData(BaseModel):
    image: str
    user_content: str
    assistant_content: str

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
    if not os.path.isdir(config.image_dir):
        raise HTTPException(status_code=400, detail="Image directory does not exist")
    # We don't enforce jsonl existence, we can create it.
    current_config = config
    return current_config

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
        if os.path.exists(current_config.jsonl_path):
            with open(current_config.jsonl_path, 'r', encoding='utf-8') as f:
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
        with open(current_config.jsonl_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=8080)

import os
import sys
# Ensure the project root is in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI, HTTPException, Body, Response, Query
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from annotation2.services import export_service, sync_service, record_service
from Minimind_trianer.label_system.app import app as minimind_app
from typing import Dict, Any, List, Optional

app = FastAPI()

# Mount Minimind Image Labeler
app.mount("/minimind", minimind_app)

# Add CORS to allow frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Annotation2 Backend is running. Visit /api/health to check status."}

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

@app.get("/api/health")
def health_check():
    return {"status": "ok"}

@app.get("/api/projects/id-by-name/{name}")
def get_project_id(name: str):
    pid = sync_service.get_project_id_by_name(name)
    if not pid:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"id": pid}

@app.post("/api/projects")
def create_project_api(data: Dict[str, Any] = Body(...)):
    name = data.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Project name required")
    try:
        pid = sync_service.create_project(
            name=name,
            labels=data.get("labels", []),
            relation_types=data.get("relation_types", [])
        )
        return {"id": pid, "name": name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/projects/{project_id}/sync")
def load_project_data(project_id: int):
    data = sync_service.load_project_data(project_id)
    if not data:
        raise HTTPException(status_code=404, detail="Project not found")
    return data

@app.post("/api/projects/{project_id}/sync")
def save_project_data(project_id: int, data: Dict[str, Any] = Body(...)):
    try:
        return sync_service.save_project_data(project_id, data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/projects/{project_id}/record")
def save_record_api(project_id: int, data: Dict[str, Any] = Body(...)):
    try:
        success = record_service.append_jsonl(project_id, data)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to append record")
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/projects/{project_id}/clear")
def clear_project_api(project_id: int):
    try:
        success = sync_service.clear_project(project_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to clear project")
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/documents/{doc_id}")
def delete_document_api(doc_id: int):
    try:
        success = sync_service.delete_document(doc_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete document")
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/projects/{project_id}/export")
def export_project_api(project_id: int, format: str = "json_v2", doc_ids: Optional[List[int]] = Query(None)):
    try:
        # Call the pure service function
        # Note: export_service.export_project returns the absolute file path
        file_path = export_service.export_project(project_id, fmt=format, doc_ids=doc_ids)
        
        if not os.path.exists(file_path):
            raise HTTPException(status_code=500, detail="Export failed to generate file")
            
        filename = os.path.basename(file_path)
        return FileResponse(path=file_path, filename=filename, media_type='application/json')
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    print("Starting Annotation2 Backend...")
    print("Access the API at: http://localhost:8000")
    try:
        uvicorn.run(app, host="0.0.0.0", port=8000)
    except OSError:
        print("Port 8000 is busy, trying 8001...")
        print("Access the API at: http://localhost:8001")
        uvicorn.run(app, host="0.0.0.0", port=8001)

# Server updated with record endpoint

# DESIGN: JSON Export Architecture

## 1. System Architecture
```mermaid
graph TD
    A[Frontend (React)] -->|HTTP GET /export| B[API Layer (FastAPI)]
    B -->|Call| C[Export Service (Pure Python)]
    C -->|Query| D[Database (SQLAlchemy)]
    C -->|Return Dict| B
    B -->|Return File| A
```

## 2. Component Design

### 2.1. Backend Service (`export_service.py`)
- **Function**: `get_project_data(project_id: int, options: dict) -> dict`
- **Logic**:
  - Fetch Project, Documents, Annotations, Relations.
  - Construct the nested JSON structure defined in requirements.
  - Handle defaults: `annotator="user"`, `confidence=1.0`.

### 2.2. API Layer (`server.py`)
- **Framework**: FastAPI
- **Endpoints**:
  - `GET /api/projects/{id}/export`: Streams the JSON file.
  - `GET /api/health`: Health check.

### 2.3. Frontend (`App.tsx`)
- **UI**: Add "Export Project" button to the toolbar.
- **Action**: `window.open('http://localhost:8000/api/projects/{currentId}/export')`

## 3. Data Structure (JSON)
```json
{
  "project_info": { "name": "Demo", "export_time": "..." },
  "documents": [
    {
      "text_id": "doc_1",
      "original_text": "...",
      "annotations": { "entities": [], "relations": [] },
      "metadata": { "status": "pending" }
    }
  ]
}
```

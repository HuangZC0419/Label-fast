# TASK: JSON Export Implementation

## 1. Backend Tasks
- [ ] **Dependencies**: Add `fastapi`, `uvicorn` to `backend/requirements.txt`.
- [ ] **Service**: Update `backend/annotation2/services/export_service.py`:
  - Add `get_export_data_v2(project_id)` function.
  - Implement nested JSON construction logic.
- [ ] **API**: Create `backend/server.py`:
  - Setup FastAPI app.
  - Add CORS middleware (to allow Frontend access).
  - Add `/api/export/{project_id}` route.

## 2. Frontend Tasks
- [ ] **UI**: Edit `annotation2-ui/src/App.tsx`:
  - Add "Export JSON" button to the top bar.
  - Implement click handler to hit `http://localhost:8000/api/export/...`.

## 3. Verification
- [ ] Run `backend/server.py`.
- [ ] Run `frontend`.
- [ ] Click Export -> Check if file downloads and JSON structure is correct.

# CONSENSUS: JSON Export Feature

## 1. Consensus Overview
- **Strategy**: Hybrid Approach.
  - **Backend**: Implement pure Python logic in `export_service.py` (Rule Compliant).
  - **API Layer**: Create a *separate* `server.py` using FastAPI to expose this logic (Satisfies "Backend API" request while keeping service logic pure).
  - **Frontend**: Add "Export" button in `App.tsx` that triggers the backend API download.
- **Data Handling (Scheme B)**: 
  - Missing `annotator` -> default to "current_user".
  - Missing `confidence` -> default to `1.0`.

## 2. Requirements & Boundaries
### Core Requirements
1. **JSON Structure**: Nested format (Project -> Documents -> Annotations/Relations).
2. **Filtering**: Support "All" (Project level) vs "Single" (Document level).
3. **Output**: Downloadable JSON file.

### Technical Constraints
- **Project Rules**: Service logic must be pure. API code must be separate.
- **Dependencies**: Need to add `fastapi` and `uvicorn` to `requirements.txt`.

## 3. Acceptance Criteria
- [ ] Backend service `export_project_json` returns correct dictionary structure.
- [ ] API endpoint `GET /export/{project_id}` returns a JSON file download.
- [ ] Frontend "Export" button triggers the download.
- [ ] JSON output contains all required fields (with defaults for missing ones).

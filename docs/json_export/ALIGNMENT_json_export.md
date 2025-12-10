# ALIGNMENT: JSON Export Feature

## 1. Project Context & Constraints
- **Architecture**: Python Backend (SQLAlchemy/Scripts) + React Frontend (Vite).
- **Current Export**: Basic JSONL/TSV via `export_service.py`.
- **DB Schema**: 
  - `Document`: `id`, `text`, `status`, `source_file`, `created_at`.
  - `Annotation`: `id`, `start`, `end`, `label`.
  - `Relation`: `from`, `to`, `type`.
  - **Constraint**: Schema does *not* currently support `annotator` or `confidence`.

## 2. Requirement Analysis
- **Goal**: Structured JSON export for downstream NLP tasks.
- **Key Features**:
  - Triggers: Project-wide, Single-doc, Batch.
  - Format: Nested JSON with metadata.
  - Options: Filtering, chunking, zip support.
- **Gap Analysis**:
  - Need to implement complex JSON serialization logic.
  - Need to handle "missing" metadata fields (annotator, confidence) gracefully (use defaults).
  - Need frontend UI for "Export Dialog" (Trigger/Options).
  - Need backend support for ZIP generation and Chunking.

## 3. Critical Decisions & Questions
- **Schema vs Defaults**: The requirements ask for `annotator` and `confidence`. 
  - *Decision*: Since modifying the DB schema involves migrations which might be risky/complex for this task scope, we will use **default values** (e.g., `confidence=1.0`, `annotator="current_user"` or `null`) for now.
- **Async vs Sync**: Requirements mention "Async processing".
  - *Decision*: Given the current "script-based" or simple service architecture, we will implement a **Synchronous but Efficient** generation for now. If the dataset is huge, the UI might freeze if we don't have a proper async task queue (Celery).
  - *Strategy*: We will implement the *logic* in `export_service` effectively. For the UI, we will show a "Processing..." state. True async (background jobs) requires infrastructure changes (Redis/Celery) which seems out of scope for a "feature add".
- **API Layer**: The project lacks a visible web server (Flask/FastAPI) in the file list provided (only `demo.py`).
  - *Question*: How does the Frontend talk to the Backend?
  - *Observation*: The user asked for "Commands to run frontend/backend". The backend runs as scripts. The frontend seems to be a standalone SPA currently (mock data or local storage?). 
  - *Correction*: Wait, `App.tsx` has `handleFiles` reading local files. It seems `App.tsx` is currently a **Client-Side Only** demo or lightweight app, OR it talks to a backend I haven't seen running.
  - *Investigation*: `grep fetch` returned nothing. `grep axios` returned nothing.
  - *Conclusion*: **The current Frontend is likely standalone or uses local state.**
  - *Pivot*: If the frontend is standalone, the "Backend Export" might need to be implemented **in TypeScript** on the frontend for the immediate "Download" feature, OR we provide a Python script for the user to run manually.
  - *User Request*: "后端生成JSON文件后...". This implies a backend exists.
  - *Hypothesis*: Maybe I missed the API layer? `demo.py` uses services directly. 
  - *Refined Plan*: I will implement the logic in **Python (Backend)** as requested. I will *also* provide a way to invoke it (e.g., a new script `export_script.py` or extend `demo.py`). If the user wants UI integration, and the UI has no API calls, I might need to add a **Bridge** or acknowledge that the UI export button will likely just download the client-side state *unless* we build a real API.
  - *Actually*: The user's previous prompt asked for "Frontend and Backend commands". This implies they run separately.
  - *Assumption*: The user wants the **Backend Logic** implemented in Python. The **Frontend UI** might just be a visual request, or I should implement the export logic in the Frontend *too* if it's a client-side app.
  - *Better approach*: I will implement the **Python Export Service** fully. I will then ask the user how they want to trigger it from the UI (since there's no obvious API connection). *Wait*, if `App.tsx` has no API calls, it's a standalone app. Implementing a backend service won't help the UI button work unless I add an API.
  - *Strategy*: I will ask the user about the Frontend-Backend connection.

## 4. Proposed Questions for User
1. **Frontend-Backend Connection**: I noticed `App.tsx` doesn't seem to make API calls (`fetch`/`axios` not found). Is the frontend currently standalone? Should I implement the export logic in **TypeScript (Frontend)** for the UI button, or is there a backend server I should connect to?
2. **Metadata Fields**: The database doesn't store `annotator` or `confidence`. Shall I add them to the DB schema (requires migration) or just output default values (e.g., 1.0)?

## 5. Draft Specification
- **Backend**: Update `export_service.py` to support `format="json_v2"`, chunking, zip.
- **Frontend**: Add "Export" Modal. If standalone, implement JSON generation in TS.

<div align="center">

# LabelFast

**A Unified Data Annotation Platform for Text NER, Relation Extraction and Multimodal Image Labeling**

[![Python](https://img.shields.io/badge/Python-3.10-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-6-646CFF?logo=vite&logoColor=white)](https://vitejs.dev/)
[![Docker](https://img.shields.io/badge/Docker-20.10%2B-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

[English](README.md) | [简体中文](README_zh.md)

</div>

---

## Overview

LabelFast is an integrated data annotation platform built for the construction of
high-quality training corpora for natural language processing and multimodal models.
It consolidates two independent annotation workbenches behind a single authenticated
entry point: a **text annotation workbench** supporting named entity recognition and
relation extraction, and an **image annotation workbench** supporting bounding-box
labeling and visual question-answering generation.

The platform can also be deployed and run offline in a local environment.

---

## Features

| Module | Capability | Description |
| --- | --- | --- |
| Text Annotation | Named Entity Recognition | Annotate entities by selecting text spans; entity categories are distinguished by color. |
| Text Annotation | Relation Extraction | Establish directed relations between annotated entities, visualized as Bezier curves. |
| Text Annotation | Overlapping Entities | Configurable per project to permit or prohibit overlapping entity spans. |
| Image Annotation | Bounding Box Labeling | Draw rectangular bounding boxes over images with a multi-label category system. |
| Image Annotation | Visual Question Answering | Author user prompts and assistant responses per image to produce multimodal dialogue data. |
| Project Management | Unified Project Model | Create, switch, configure and delete projects; text and image projects share a consistent lifecycle. |
| Data Export | Multi-format Export | Export annotation results as structured JSON, line-delimited JSONL, CSV/TSV or a bundled ZIP archive. |
| Data Ingestion | Document Import | Import source corpora into projects for subsequent annotation. |
| Security | JWT Authentication | Token-based authentication with account management driven by an administrator-maintained registry. |
| Deployment | Containerization | Multi-stage Docker build supporting both online and fully offline deployment workflows. |
| Deployment | Offline Operation | Image annotation assets are stored locally; no external CDN access is required at runtime. |

---

## Architecture

LabelFast follows a single-origin, three-tier architecture. A FastAPI application acts
as both the API gateway and the static host for the compiled frontend, so that the whole
platform is exposed on one port.

| Layer | Technology | Responsibility |
| --- | --- | --- |
| Frontend (text) | React 18 + TypeScript + Vite | Text annotation workbench, project management, authentication UI |
| Frontend (image) | Vue 3 + Tailwind CSS | Image annotation workbench, served as a mounted sub-application |
| Backend | Python 3.10 + FastAPI | REST API, JWT authentication middleware, SPA hosting |
| Persistence | SQLAlchemy 2.0 + SQLite | Relational storage for text projects, documents, annotations and relations |
| Persistence | JSON / JSONL files | Project configuration and annotation results for image projects |

Request routing is governed by two middlewares registered in `backend/server.py`:

- **JWT authentication middleware** — intercepts every `/api/*` request and validates the
  `Authorization: Bearer <token>` header. Requests to `/api/auth/*` and `/api/health` are exempt.
- **SPA fallback middleware** — serves compiled frontend assets for non-API paths and falls
  back to `index.html` to support client-side routing.

The image annotation workbench is mounted at `/minimind`.

---

## Quick Start

### Prerequisites

| Requirement | Version | Notes |
| --- | --- | --- |
| Python | 3.10 or later | Backend runtime |
| Node.js | 18 or later | Frontend build and development server |
| Docker | 20.10 or later | Optional; required for containerized deployment |

### 1. Start the backend

```bash
cd backend
python -m pip install -r requirements.txt
python -m pip install -r 图像标注器/requirements.txt
python server.py
```

The backend listens on port `3002` by default. If the port is occupied, the server
automatically probes up to 20 subsequent ports. An explicit port may be supplied:

```bash
python server.py --port 8000
```

### 2. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

The development server binds to `0.0.0.0`, allowing access from other machines on the
same network. API requests are proxied to the backend by the Vite development server,
so the browser only needs to reach the frontend port.

### 3. Access the platform

| Entry point | URL |
| --- | --- |
| Text annotation workbench | Frontend root, e.g. `http://localhost:5173` |
| Image annotation workbench | [`/minimind`](http://localhost:5173/minimind) |
| Interactive API documentation | `/docs` on the backend port, e.g. `http://localhost:3002/docs` |

On Windows, both services can be launched from a single script:

```bash
start.bat
```

The script starts the backend on port `8000` and the frontend on port `5173`, each in a
dedicated console window. It expects a Conda environment named `label_v4`.

---

## Deployment

### Containerized deployment

The repository ships a multi-stage `Dockerfile` that compiles the frontend with
Node.js and packages the runtime with a minimal Python image.

```bash
docker build -t label-fast:latest .
docker-compose -f docker-compose.offline.yml up -d
```

The service is then reachable at `http://<host>:3002`.

### Offline deployment

For environments without internet access, the image is transferred as an archive and
loaded on the target host:

```bash
docker load -i label-fast.tar
docker-compose -f docker-compose.offline.yml up -d
```

Common operational commands:

```bash
docker-compose -f docker-compose.offline.yml ps                 # check service status
docker-compose -f docker-compose.offline.yml logs -f label-fast # follow logs
docker-compose -f docker-compose.offline.yml restart            # restart the service
docker-compose -f docker-compose.offline.yml down               # stop the service
```

The reference target platform is RHEL 7.6 on x86_64 with Docker 20.10.9 or later.
Detailed instructions are provided in `部署说明.txt`.

---

## Configuration

### User accounts

Accounts are maintained by an administrator in `backend/users.xlsx`. Self-service
registration is intentionally not provided. The backend must be restarted for changes
to take effect:

```bash
docker-compose -f docker-compose.offline.yml restart
```

### Authentication secret

The JWT signing key is resolved in the following order: the `JWT_SECRET` environment
variable, an existing value in `backend/.env`, or a newly generated key that is
persisted to `backend/.env`. Injecting `JWT_SECRET` as an environment variable is the
recommended approach for production deployments.

### Development proxy

The Vite development server proxies `/api` and `/minimind` to the backend. The target
port is read from the `BACKEND_PORT` environment variable and defaults to `3002`.

### Data persistence

Under containerized deployment, the following paths are mounted as volumes and survive
container replacement:

| Path | Content |
| --- | --- |
| `backend/文本标注器/projects/` | Text annotation project data |
| `backend/文本标注器/storage/` | SQLite database |
| `backend/图像标注器/projects/` | Image annotation project data |
| `backend/图像标注器/projects.json` | Image project index |
| `backend/users.xlsx` | User account registry |

---

## Project Structure

```
LabelFast/
├── backend/                        # FastAPI backend
│   ├── server.py                   # Application entry point and API gateway
│   ├── requirements.txt            # Python dependencies
│   ├── users.xlsx                  # User account registry
│   ├── .env                        # JWT secret (auto-generated on first launch)
│   ├── 文本标注器/                  # Text annotation module
│   │   ├── models.py               # Data models
│   │   ├── services/               # Auth, project, document, annotation, relation, export services
│   │   ├── storage/                # SQLite database
│   │   └── projects/               # Text project data
│   └── 图像标注器/                  # Image annotation module
│       ├── label_system/app.py     # Image annotation service, mounted at /minimind
│       ├── label_system/static/    # Offline frontend assets (Vue 3, Tailwind CSS)
│       ├── projects/               # Image project data and annotation results
│       ├── projects.json           # Image project index
│       └── tests/                  # Module tests
├── frontend/                       # React 18 + TypeScript frontend
│   ├── src/                        # Application source
│   ├── dist/                       # Production build output
│   └── vite.config.ts              # Development server and API proxy configuration
├── docs/                           # Design documentation
├── Dockerfile                      # Multi-stage production image
├── docker-compose.offline.yml      # Offline deployment orchestration
├── docker-entrypoint.sh            # Container initialization script
└── start.bat                       # One-click local startup (Windows)
```

---

## Documentation

| Document | Description |
| --- | --- |
| [`docs/数据集标注平台_软件设计文档.md`](docs/数据集标注平台_软件设计文档.md) | Software design document: architecture, data models, API design, security and deployment |
| `LabelFast_使用说明.html` | End-user operation manual (HTML) |
| `LabelFast_使用说明.pdf` | End-user operation manual (PDF) |
| `操作手册.html` | Annotation workflow handbook |
| `部署说明.txt` | Offline deployment instructions |

Interactive API documentation is generated automatically by FastAPI and is available at
`/docs` (Swagger UI) and `/redoc` on the backend.

---

## Testing

The image annotation module ships with a unit test suite located in
`backend/图像标注器/tests/`. The suite is written against the Python standard library
`unittest` framework and requires no additional dependencies:

```bash
cd backend/图像标注器
python -m unittest discover -s tests -v
```

---

## License

LabelFast is delivered as an internal project and does not include an open-source
license. For licensing or redistribution inquiries, please contact the project
maintainer.

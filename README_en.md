<div align="center">

# Data Annotation & Classification Toolkit

**An offline, all-in-one platform for text, image and document annotation and classification**

Codename: **Label-Fast** · Repository: <https://github.com/HuangZC0419/Label-fast>

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Vue](https://img.shields.io/badge/Vue-3-4FC08D?logo=vue.js&logoColor=white)](https://vuejs.org/)
[![Vite](https://img.shields.io/badge/Vite-6-646CFF?logo=vite&logoColor=white)](https://vitejs.dev/)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?logo=windows&logoColor=white)](#)

[简体中文](README.md) | [English](README_en.md)

</div>

---

## Overview

Label-Fast is a fully offline data-processing platform that unifies six annotation and
classification capabilities behind a single authenticated entry point:

- **Text annotation** — named entity recognition (NER) and entity relation extraction;
- **Image annotation** — bounding-box labeling and visual question-answering (VQA) corpora;
- **LLM QA annotation** — multi-turn question/answer authoring for LLM fine-tuning;
- **Aviation standard classification** — standard-number classification driven by reference
  tables and an ensemble of statistical models;
- **Mixed annotation** — PDF / image conversion to Markdown via OCR, followed by entity,
  relation and structured annotation;
- **Model annotation** — document parsing plus RoBERTa-CRF based NER training, inference,
  evaluation and result annotation.

No external cloud service is involved: OCR runs on a locally deployed MinerU instance and all
model weights and caches stay inside the repository, so the platform works fully air-gapped.
A single `start.bat` launches every service, automatically shifting to the next free port and
printing the addresses actually used.

## Features

| Module | Capability | Description |
| --- | --- | --- |
| Text annotation | Named entity recognition | Span-based entity labeling with per-class colors and per-project overlap policy |
| Text annotation | Relation extraction | Directed relations between annotated entities, rendered as Bézier curves |
| Image annotation | Bounding boxes | Multi-label category system with drag, resize and keyboard shortcuts |
| Image annotation | Visual QA | Author prompt / response pairs per image to produce multimodal dialogue data |
| QA annotation | Dialogue authoring | Project-scoped question-answer editing with import and export |
| Standard classification | Standard-number grouping | Reference-table validation plus keyword / kNN / character n-gram Bayes ensemble, results written back to Excel |
| Mixed annotation | Structured document annotation | PDF / image to Markdown via MinerU OCR, with entity, relation, table and figure annotation and export |
| Model annotation | Document parsing | PDF / image / text upload, layout analysis, OCR, reading-order recovery, formula and table recognition via MinerU |
| Model annotation | NER training & inference | `chinese-roberta-wwm-ext` + CRF with training, continued training, evaluation and multi-model switching |
| Platform | Project management | A unified lifecycle for text, image, QA, mixed and model projects |
| Platform | Data export | JSON, JSONL, CSV / TSV, Doccano and ZIP bundle export |
| Platform | Authentication | JWT tokens kept in sessionStorage, accounts driven by an administrator-maintained registry |
| Platform | Offline operation | All static assets, OCR models and training weights are local; no external CDN required |

## Architecture

The platform runs as one frontend plus four independent backends and one OCR engine.
Every service can be started and debugged on its own; the root `start.bat` orchestrates all of them.

| # | Service | Default port | Responsibility |
| --- | --- | --- | --- |
| 1 | Model annotation backend `model_annotation/backend` | 8267 | Document parsing, NER training / inference / evaluation, dataset library |
| 2 | Main backend `backend` | 3002 | Text / image / QA APIs, SPA hosting and authentication |
| 3 | Standard classification backend `GB_fenlei/backend` | 8000 | Classification pipeline and Excel I/O |
| 4 | MinerU API | 18000 | Resident OCR service (pipeline backend) |
| 5 | Mixed annotation OCR worker `mixed_annotation/ocr_worker` | 8870 | Conversion task scheduling and result storage |
| 6 | Mixed annotation backend `mixed_annotation/backend` | 3200 | Mixed-annotation projects, files, annotation and export |
| 7 | Frontend `frontend` (Vite) | 5175 | Vue 3 SPA, proxying every backend API in dev mode |

The frontend follows a "relative paths only" rule: `API_BASE` is an empty string and the browser
talks exclusively to the frontend port. Vite forwards each prefix locally, so other machines on
the same LAN only need the frontend address.

| Proxy prefix | Target | Notes |
| --- | --- | --- |
| `/api`, `/minimind` | Main backend `BACKEND_PORT` | Text / image / QA APIs |
| `/gb-api` | `GB_BACKEND_PORT` | Prefix stripped before forwarding |
| `/mix-api` | `MIX_BACKEND_PORT` | Prefix stripped before forwarding |
| `/model-api` | `MODEL_BACKEND_PORT` | Prefix stripped before forwarding |

Frontend routes: `/login`, plus `/app/text`, `/app/image`, `/app/qa`, `/app/classify`,
`/app/mixed` and `/app/model`.

## Repository layout

```text
数据标注与分类工具/                # repository root (codename Label-Fast)
├─ start.bat                       one-click launcher for all seven services
├─ backend/                        main backend: text / image / QA annotation, SPA hosting, JWT auth
├─ frontend/                       Vue 3 + TypeScript + Vite 6 single-page application
│  ├─ src/views/                   text / image / QA / login views
│  └─ src/modules/                 gb-fenlei, mixed-annotation and model-annotation frontends
├─ GB_fenlei/                      aviation standard classification module (standalone FastAPI backend)
├─ mixed_annotation/               mixed annotation module (backend + OCR worker + offline models)
├─ model_annotation/               model annotation module (document parsing + NER training / inference)
├─ docs/                           design documents and implementation plans
│  └─ deepseek-harness/            architecture specs and step-by-step plans
├─ 软件示例/                        sample data for every annotation type
├─ export_annotation_summary.py     annotation summary export script
└─ README.md / README_en.md         Chinese and English documentation
```

Module-level documentation lives next to the code:
[GB_fenlei](GB_fenlei/README.md), [mixed_annotation](mixed_annotation/README.md),
[model_annotation](model_annotation/README.md).

## Quick start

### Prerequisites

- Windows 10 / 11 (`cmd` and PowerShell are required by the launcher);
- conda environment `CFwin11` (Python 3.12, see
  [mixed_annotation/environment-cfwin11.yml](mixed_annotation/environment-cfwin11.yml));
- Node.js 18+ for frontend development only;
- GPU optional: MinerU and training use CUDA when available, otherwise set
  `MINERU_DEVICE_MODE=cpu` in `start.bat`.

Install the Python dependencies you need:

```bat
pip install -r backend\requirements.txt
pip install -r GB_fenlei\backend\requirements.txt
pip install -r mixed_annotation\backend\requirements.txt
pip install -r mixed_annotation\ocr_worker\requirements.txt
pip install -r model_annotation\backend\requirements.txt
```

### Launch

Double-click `start.bat` in the repository root. It will:

1. probe the seven ports with a PowerShell `TcpListener` and shift to the next free port instead
   of aborting;
2. open every service as a tab in a new Windows Terminal window, falling back to seven separate
   console windows when `wt.exe` is unavailable;
3. start the model annotation backend first for warm-up, wait for the MinerU health check, then
   bring up the remaining services and the frontend;
4. print the exact addresses in use.

Probe ports only:

```bat
start.bat --check
```

### Access

Open the printed frontend address (default <http://localhost:5175>):

| Service | Address |
| --- | --- |
| Frontend | <http://localhost:5175> |
| Main backend API | <http://localhost:3002> |
| Standard classification Swagger | <http://localhost:8000/docs> |
| Mixed annotation backend | <http://localhost:3200> |
| Model annotation backend | <http://localhost:8267> |
| OCR worker | <http://localhost:8870> |
| MinerU API | <http://localhost:18000> |

Ports shift automatically when occupied — always use the addresses printed by the launcher.

### Manual start

The tail of `start.bat` documents the equivalent manual command (including every environment
variable) for each of the seven services.

## Data and models (not tracked by git)

Large directories and runtime artifacts are excluded through `.gitignore`; copy them alongside the
repository or let the first run regenerate them:

| Directory | Purpose | Size |
| --- | --- | --- |
| `mixed_annotation/models/` | MinerU / Torch offline model cache | ~2.16 GB |
| `mixed_annotation/ocr_worker/models/` | Paddle layout and table models | ~0.25 GB |
| `model_annotation/backend/models/` | RoBERTa backbone and trained models | ~2.36 GB |
| `mixed_annotation/backend/data/` | mixed-annotation runtime project data | grows with use |
| `model_annotation/input/`, `model_annotation/output/` | parsing samples and results | ~14 MB / ~79 MB |
| `frontend/node_modules/`, `frontend/.npm-cache/` | frontend dependencies and cache | — |

## Documentation

| Document | Contents |
| --- | --- |
| [docs/数据集标注平台_软件设计文档.md](docs/数据集标注平台_软件设计文档.md) | Overall platform design: modules, APIs, deployment and frontend conventions |
| [docs/deepseek-harness/specs/](docs/deepseek-harness/specs/) | Design specs for each refactoring phase |
| [docs/deepseek-harness/plans/](docs/deepseek-harness/plans/) | Matching step-by-step implementation plans |
| [mixed_annotation/docs/](mixed_annotation/docs/) | Mixed annotation API and design notes |
| [model_annotation/docs/](model_annotation/docs/) | Model annotation design manual and historical proposals |

## FAQ

**A service window closes immediately, or the port is not the default one.**
The launcher shifts ports when they are occupied; always use the printed addresses and check the
first exception in the failing service window.

**The MinerU health check fails.**
`start.bat` automatically falls back to subprocess mode with a single OCR worker. Functionality is
preserved, conversion is slower. A missing model cache or insufficient VRAM is the usual cause.

**The first launch is slow.**
The model annotation backend loads PyTorch and local weights and needs about 20 seconds before it
starts listening; the launcher starts it first and waits for the other ports before the frontend.

**Can it run without a dedicated GPU?**
Yes — set `MINERU_DEVICE_MODE=cpu` in `start.bat`. OCR and training become noticeably slower.

**How do other machines on the LAN connect?**
The frontend listens on `0.0.0.0`; open `http://<host-ip>:<frontend-port>`. All API traffic is
proxied by Vite on the host, so no backend port has to be exposed.

## Conventions

- Official project name: **数据标注与分类工具** (Data Annotation & Classification Toolkit);
  codename and repository name: **Label-Fast**.
- Development and maintenance are carried out with the **DeepSeek Harness** coding assistant;
  local configuration lives in `.deepseek-harness/`.
- Documentation and code comments are written in Simplified Chinese; commit messages use the
  `feat:` / `fix:` / `docs:` / `chore:` prefixes.

<div align="center">

# LabelFast

**面向文本命名实体识别、关系抽取与多模态图像标注的一体化数据标注平台**

[![Python](https://img.shields.io/badge/Python-3.10-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-6-646CFF?logo=vite&logoColor=white)](https://vitejs.dev/)
[![Docker](https://img.shields.io/badge/Docker-20.10%2B-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

[English](README.md) | [简体中文](README_zh.md)

</div>

---

## 项目简介

LabelFast 是一体化的数据标注平台，用于构建面向自然语言处理与多模态模型的高质量训练语料。
平台将两个相互独立的标注工作台统一在单一认证入口之下：**文本标注工作台**支持命名实体识别与
关系抽取，**图像标注工作台**支持矩形框标注与视觉问答数据生成。

平台同时支持在本地离线部署和运行。

---

## 功能特性

| 模块 | 能力 | 说明 |
| --- | --- | --- |
| 文本标注 | 命名实体识别 | 通过拖选文本片段标注实体，不同实体类别以颜色区分。 |
| 文本标注 | 关系抽取 | 在已标注实体之间建立有向关系，以贝塞尔曲线可视化呈现。 |
| 文本标注 | 重叠实体控制 | 支持按项目配置是否允许实体片段重叠。 |
| 图像标注 | 矩形框标注 | 在图像上拖拽绘制矩形边界框，支持多标签类别体系。 |
| 图像标注 | 视觉问答标注 | 为每张图像编写用户指令与助手回答，生成多模态对话训练数据。 |
| 项目管理 | 统一项目模型 | 支持项目的创建、切换、配置与删除，文本与图像项目采用一致的生命周期。 |
| 数据导出 | 多格式导出 | 支持结构化 JSON、逐行 JSONL、CSV/TSV 表格以及 ZIP 打包导出。 |
| 数据导入 | 语料导入 | 将原始语料导入项目，供后续标注使用。 |
| 安全认证 | JWT 令牌认证 | 基于令牌的认证体系，账号由管理员统一维护。 |
| 部署方式 | 容器化部署 | 多阶段 Docker 构建，同时支持在线与完全离线两种部署模式。 |
| 部署方式 | 离线运行 | 图像标注前端资源本地存储，运行期无需访问外部 CDN。 |

---

## 系统架构

LabelFast 采用单一入口的三层架构。FastAPI 应用同时承担 API 网关与前端静态资源托管的职责，
使整个平台通过单一端口对外提供服务。

| 层次 | 技术选型 | 职责 |
| --- | --- | --- |
| 前端（文本） | React 18 + TypeScript + Vite | 文本标注工作台、项目管理与认证界面 |
| 前端（图像） | Vue 3 + Tailwind CSS | 图像标注工作台，以挂载子应用形式提供 |
| 后端 | Python 3.10 + FastAPI | REST 接口、JWT 认证中间件、单页应用托管 |
| 数据存储 | SQLAlchemy 2.0 + SQLite | 文本项目、文档、标注与关系的结构化存储 |
| 数据存储 | JSON / JSONL 文件 | 图像项目的配置与标注结果 |

请求路由由 `backend/server.py` 中注册的两个中间件共同决定：

- **JWT 认证中间件** —— 拦截全部 `/api/*` 请求并校验 `Authorization: Bearer <token>` 请求头；
  `/api/auth/*` 与 `/api/health` 为免认证路径。
- **单页应用回退中间件** —— 非 API 路径优先返回前端构建产物，未命中时回退至 `index.html`，
  以支持前端客户端路由。

图像标注工作台挂载于 `/minimind` 路径。

---

## 快速开始

### 环境要求

| 依赖 | 版本要求 | 说明 |
| --- | --- | --- |
| Python | 3.10 及以上 | 后端运行时 |
| Node.js | 18 及以上 | 前端构建与开发服务器 |
| Docker | 20.10 及以上 | 可选，容器化部署时必需 |

### 1. 启动后端

```bash
cd backend
python -m pip install -r requirements.txt
python -m pip install -r 图像标注器/requirements.txt
python server.py
```

后端默认监听 `3002` 端口。若端口被占用，服务会自动向后探测最多 20 个端口。也可显式指定端口：

```bash
python server.py --port 8000
```

### 2. 启动前端

```bash
cd frontend
npm install
npm run dev
```

开发服务器绑定 `0.0.0.0`，同一网络中的其他设备可直接访问。接口请求由 Vite 开发服务器
代理至后端，浏览器仅需与前端端口通信。

### 3. 访问系统

| 入口 | 地址 |
| --- | --- |
| 文本标注工作台 | 前端根路径，例如 `http://localhost:5173` |
| 图像标注工作台 | [`/minimind`](http://localhost:5173/minimind) |
| 交互式接口文档 | 后端端口的 `/docs`，例如 `http://localhost:3002/docs` |

在 Windows 环境下，可通过单一脚本同时启动两个服务：

```bash
start.bat
```

该脚本将后端启动于 `8000` 端口、前端启动于 `5173` 端口，各占一个独立控制台窗口，
并依赖名为 `label_v4` 的 Conda 环境。

---

## 部署

### 容器化部署

仓库提供多阶段构建的 `Dockerfile`：前端由 Node.js 阶段完成编译，运行时基于精简的
Python 镜像打包。

```bash
docker build -t label-fast:latest .
docker-compose -f docker-compose.offline.yml up -d
```

服务启动后可通过 `http://<服务器IP>:3002` 访问。

### 离线部署

对于无法访问互联网的环境，以归档包形式传输镜像并在目标主机加载：

```bash
docker load -i label-fast.tar
docker-compose -f docker-compose.offline.yml up -d
```

常用运维命令：

```bash
docker-compose -f docker-compose.offline.yml ps                 # 查看服务状态
docker-compose -f docker-compose.offline.yml logs -f label-fast # 跟踪日志
docker-compose -f docker-compose.offline.yml restart            # 重启服务
docker-compose -f docker-compose.offline.yml down               # 停止服务
```

参考目标环境为 x86_64 架构下的 RHEL 7.6，Docker 版本 20.10.9 及以上。详细步骤参见
`部署说明.txt`。

---

## 配置说明

### 用户账号

账号由管理员在 `backend/users.xlsx` 中统一维护，系统不提供自助注册功能。修改账号表后
需重启后端方可生效：

```bash
docker-compose -f docker-compose.offline.yml restart
```

### 认证密钥

JWT 签名密钥按以下顺序解析：`JWT_SECRET` 环境变量、`backend/.env` 中已存在的值、
以及首次启动时自动生成并写入 `backend/.env` 的新密钥。生产部署建议通过环境变量显式注入
`JWT_SECRET`。

### 开发代理

Vite 开发服务器将 `/api` 与 `/minimind` 代理至后端，目标端口读取自 `BACKEND_PORT`
环境变量，默认值为 `3002`。

### 数据持久化

容器化部署下，以下路径以数据卷方式挂载，容器替换后数据不会丢失：

| 路径 | 内容 |
| --- | --- |
| `backend/文本标注器/projects/` | 文本标注项目数据 |
| `backend/文本标注器/storage/` | SQLite 数据库 |
| `backend/图像标注器/projects/` | 图像标注项目数据 |
| `backend/图像标注器/projects.json` | 图像项目索引 |
| `backend/users.xlsx` | 用户账号表 |

---

## 项目结构

```
LabelFast/
├── backend/                        # FastAPI 后端
│   ├── server.py                   # 应用入口与 API 网关
│   ├── requirements.txt            # Python 依赖清单
│   ├── users.xlsx                  # 用户账号表
│   ├── .env                        # JWT 密钥（首次启动自动生成）
│   ├── 文本标注器/                  # 文本标注模块
│   │   ├── models.py               # 数据模型定义
│   │   ├── services/               # 认证、项目、文档、标注、关系、导出等业务服务
│   │   ├── storage/                # SQLite 数据库
│   │   └── projects/               # 文本项目数据
│   └── 图像标注器/                  # 图像标注模块
│       ├── label_system/app.py     # 图像标注服务，挂载于 /minimind
│       ├── label_system/static/    # 离线前端资源（Vue 3、Tailwind CSS）
│       ├── projects/               # 图像项目数据与标注结果
│       ├── projects.json           # 图像项目索引
│       └── tests/                  # 模块测试
├── frontend/                       # React 18 + TypeScript 前端
│   ├── src/                        # 应用源码
│   ├── dist/                       # 生产构建产物
│   └── vite.config.ts              # 开发服务器与接口代理配置
├── docs/                           # 设计文档
├── Dockerfile                      # 多阶段生产镜像
├── docker-compose.offline.yml      # 离线部署编排文件
├── docker-entrypoint.sh            # 容器初始化脚本
└── start.bat                       # 一键本地启动脚本（Windows）
```

---

## 文档

| 文档 | 说明 |
| --- | --- |
| [`docs/数据集标注平台_软件设计文档.md`](docs/数据集标注平台_软件设计文档.md) | 软件设计文档：架构设计、数据模型、接口设计、安全与部署方案 |
| `LabelFast_使用说明.html` | 最终用户操作手册（HTML） |
| `LabelFast_使用说明.pdf` | 最终用户操作手册（PDF） |
| `操作手册.html` | 标注作业流程手册 |
| `部署说明.txt` | 离线部署说明 |

交互式接口文档由 FastAPI 自动生成，可通过后端的 `/docs`（Swagger UI）与 `/redoc` 访问。

---

## 测试

图像标注模块附带单元测试，位于 `backend/图像标注器/tests/`。测试基于 Python 标准库
`unittest` 编写，无需额外依赖：

```bash
cd backend/图像标注器
python -m unittest discover -s tests -v
```

---

## 许可

LabelFast 为内部交付项目，未附带开源许可证。如需授权或再分发，请联系项目维护者。

<div align="center">

# 数据标注与分类工具

**面向文本 / 图像 / 文档多模态数据的离线标注与分类一体化平台**

网络代号：**Label-Fast** · 仓库：<https://github.com/HuangZC0419/Label-fast>

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Vue](https://img.shields.io/badge/Vue-3-4FC08D?logo=vue.js&logoColor=white)](https://vuejs.org/)
[![Vite](https://img.shields.io/badge/Vite-6-646CFF?logo=vite&logoColor=white)](https://vitejs.dev/)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?logo=windows&logoColor=white)](#)

[简体中文](README.md) | [English](README_en.md)

</div>

---

## 项目简介

数据标注与分类工具（网络代号 **Label-Fast**）是一套**完全离线运行**的数据加工平台，
把六类标注 / 分类能力整合在一个统一入口下：

- **文本标注**：命名实体识别（NER）与实体关系抽取；
- **图像标注**：矩形框标注与图像问答（VQA）语料生成；
- **大模型问答标注**：面向大模型微调的多轮问答数据编写；
- **航空标准分类**：基于参照表与统计集成模型的国标 / 航标标准号归类；
- **混合标注**：PDF / 图片经 OCR 转为 Markdown 后做实体、关系与结构化标注；
- **模型标注**：文档解析 + 基于 RoBERTa-CRF 的 NER 训练、推理、评估与结果标注。

平台不依赖任何外部云服务：OCR 使用本地部署的 MinerU，模型权重与缓存全部落在仓库目录内，
断网环境可直接使用。仓库由 `start.bat` 一键拉起全部服务，端口占用时自动顺延并在窗口打印实际地址。

## 功能一览

| 模块 | 能力 | 说明 |
| --- | --- | --- |
| 文本标注 | 命名实体识别 | 光标选词标注实体，实体类别按颜色区分，支持允许 / 禁止实体重叠的项目级配置 |
| 文本标注 | 关系抽取 | 在已标注实体之间建立有向关系，前端以贝塞尔曲线可视化 |
| 图像标注 | 矩形框标注 | 多标签类别体系，画框、拖拽、缩放与快捷键操作 |
| 图像标注 | 图像问答 | 为每张图片编写提问与回答，产出多模态对话语料 |
| 大模型问答标注 | 问答数据编写 | 按项目维护问答对，支持导入与导出 |
| 航空标准分类 | 标准号归类 | 参照表体检、统计关键词 / kNN / 字符 n-gram 贝叶斯集成决策，结果回写 Excel |
| 混合标注 | 文档结构化标注 | PDF / 图片经 MinerU OCR 转 Markdown，支持实体、关系、表格与图片标注及导出 |
| 模型标注 | 文档解析 | 上传 PDF / 图片 / 文本，调用 MinerU 完成版面分析、OCR、阅读顺序恢复、公式与表格识别 |
| 模型标注 | NER 训练与推理 | `chinese-roberta-wwm-ext` + CRF，支持训练、继续训练、评估、模型管理与多模型切换 |
| 平台能力 | 项目管理 | 文本 / 图像 / 问答 / 混合 / 模型项目统一创建、切换、配置与删除 |
| 平台能力 | 数据导出 | JSON、JSONL、CSV / TSV、Doccano、ZIP 打包等多种导出格式 |
| 平台能力 | 登录鉴权 | JWT Token 鉴权，Token 存放于 sessionStorage，账号由管理员维护的注册表驱动 |
| 平台能力 | 离线运行 | 全部静态资源、OCR 模型与训练权重本地化，无外部 CDN 依赖 |

## 系统架构

平台采用「一个前端 + 四个独立后端 + 一个 OCR 引擎」的多进程结构，各服务互不耦合，
可单独启动调试，也可由根目录 `start.bat` 统一调度。

| 序号 | 服务 | 默认端口 | 职责 |
| --- | --- | --- | --- |
| 1 | 模型标注后端 `model_annotation/backend` | 8267 | 文档解析、NER 训练 / 推理 / 评估、数据集库 |
| 2 | 主后端 `backend` | 3002 | 文本 / 图像 / 问答标注 API，SPA 托管与鉴权 |
| 3 | 国标分类后端 `GB_fenlei/backend` | 8000 | 航空标准分类流水线与 Excel 处理 |
| 4 | MinerU API | 18000 | 常驻 OCR 服务（pipeline 后端） |
| 5 | 混合标注 OCR Worker `mixed_annotation/ocr_worker` | 8870 | 文档转换任务调度与结果落盘 |
| 6 | 混合标注后端 `mixed_annotation/backend` | 3200 | 混合标注项目、文件、标注与导出 |
| 7 | 前端 `frontend`（Vite） | 5175 | Vue 3 单页应用，开发态代理全部后端接口 |

前端遵守「相对路径 + Vite 代理」原则：`API_BASE` 为空字符串，浏览器只与前端端口通信，
接口请求由 Vite 在本地转发，局域网内其他设备访问同一地址即可使用。

| 代理前缀 | 转发目标 | 说明 |
| --- | --- | --- |
| `/api`、`/minimind` | 主后端 `BACKEND_PORT` | 文本 / 图像 / 问答标注接口 |
| `/gb-api` | 国标后端 `GB_BACKEND_PORT` | 前缀剥离后转发 |
| `/mix-api` | 混合标注后端 `MIX_BACKEND_PORT` | 前缀剥离后转发 |
| `/model-api` | 模型标注后端 `MODEL_BACKEND_PORT` | 前缀剥离后转发 |

前端路由：`/login` 登录页；`/app/text`、`/app/image`、`/app/qa`、`/app/classify`、
`/app/mixed`、`/app/model` 六个功能页。

## 目录结构

```text
数据标注与分类工具/                 # 仓库根（网络代号 Label-Fast）
├─ start.bat                       一键启动 7 个服务（新窗口 / Windows Terminal 标签页）
├─ backend/                        主后端：文本 / 图像 / 问答标注 + SPA 托管 + JWT 鉴权
│  ├─ server.py                    应用入口
│  └─ 图像标注器/                   图像标注子应用（label_system）
├─ frontend/                       Vue 3 + TypeScript + Vite 6 单页应用
│  ├─ src/views/                   文本 / 图像 / 问答 / 登录视图
│  ├─ src/modules/gb-fenlei/       航空标准分类前端模块
│  ├─ src/modules/mixed-annotation/ 混合标注前端模块
│  ├─ src/modules/model-annotation/ 模型标注前端模块
│  └─ vite.config.ts               端口与代理配置（全部由环境变量注入）
├─ GB_fenlei/                      航空标准分类模块（独立 FastAPI 后端 + 样例数据）
├─ mixed_annotation/               混合标注模块（后端 + OCR Worker + 离线模型缓存）
├─ model_annotation/               模型标注模块（文档解析 + NER 训练 / 推理）
├─ docs/                           设计文档与实施计划
│  └─ deepseek-harness/            架构规格（specs）与实施计划（plans）
├─ 软件示例/                        各类标注功能的示例数据
├─ export_annotation_summary.py    标注明细汇总导出脚本
└─ README.md / README_en.md        中英文说明
```

各模块的详细目录说明与接口文档见模块内 `README.md`：
[GB_fenlei](GB_fenlei/README.md)、[mixed_annotation](mixed_annotation/README.md)、[model_annotation](model_annotation/README.md)。

## 快速开始

### 1. 环境准备

- 操作系统：Windows 10 / 11（脚本依赖 `cmd` 与 PowerShell）；
- Python 环境：conda 环境 `CFwin11`（Python 3.12，导出见
  [mixed_annotation/environment-cfwin11.yml](mixed_annotation/environment-cfwin11.yml)）；
- Node.js 18+（仅前端开发需要，用于 `npm run dev`）；
- 显卡：可选。有 CUDA 时 MinerU 与训练使用 GPU，否则在 `start.bat` 中把
  `MINERU_DEVICE_MODE` 改为 `cpu`。

安装 Python 依赖（按需安装对应模块）：

```bat
pip install -r backend\requirements.txt
pip install -r GB_fenlei\backend\requirements.txt
pip install -r mixed_annotation\backend\requirements.txt
pip install -r mixed_annotation\ocr_worker\requirements.txt
pip install -r model_annotation\backend\requirements.txt
```

### 2. 一键启动

在仓库根目录**双击 `start.bat`**，脚本会依次完成：

1. 用 PowerShell `TcpListener` 依次探测 7 个端口，被占用时自动 +1 顺延，绝不因端口占用退出；
2. 优先在 Windows Terminal 中以多标签页启动全部服务，无 `wt.exe` 时退回 7 个独立控制台窗口；
3. 先启动模型标注后端并完成预热，再启动其余后端，等待 MinerU 健康检查通过后拉起前端；
4. 在窗口打印本次实际使用的全部地址。

只看端口探测结果：

```bat
start.bat --check
```

### 3. 访问

浏览器打开脚本打印的前端地址（默认 <http://localhost:5175>）：

| 服务 | 地址 |
| --- | --- |
| 前端 | <http://localhost:5175> |
| 主后端 API | <http://localhost:3002> |
| 国标后端 Swagger | <http://localhost:8000/docs> |
| 混合标注后端 | <http://localhost:3200> |
| 模型标注后端 | <http://localhost:8267> |
| OCR Worker | <http://localhost:8870> |
| MinerU API | <http://localhost:18000> |

端口被占用时以上地址均会顺延，**以启动窗口打印的地址为准**。

### 4. 手动启动

`start.bat` 末尾以注释形式给出了 7 个服务等价的手动启动命令（含全部环境变量），
需要逐个调试时可直接照抄执行。

## 数据与模型（不进入 git）

以下目录体积较大或属运行时产物，已在 `.gitignore` 中排除，部署时需随仓库目录一并拷贝或首次运行自动生成：

| 目录 | 说明 | 参考体积 |
| --- | --- | --- |
| `mixed_annotation/models/` | MinerU / Torch 离线模型缓存 | 约 2.16 GB |
| `mixed_annotation/ocr_worker/models/` | Paddle 版面与表格模型缓存 | 约 0.25 GB |
| `model_annotation/backend/models/` | RoBERTa 骨干网络与已训练模型 | 约 2.36 GB |
| `mixed_annotation/backend/data/` | 混合标注运行时项目数据 | 随项目增长 |
| `model_annotation/input/`、`model_annotation/output/` | 文档解析输入样例与解析结果 | 约 14 MB / 79 MB |
| `frontend/node_modules/`、`frontend/.npm-cache/` | 前端依赖与缓存 | — |

## 开发文档

| 文档 | 内容 |
| --- | --- |
| [docs/数据集标注平台_软件设计文档.md](docs/数据集标注平台_软件设计文档.md) | 平台总体设计：模块划分、接口、部署与前端约定 |
| [docs/deepseek-harness/specs/](docs/deepseek-harness/specs/) | 各期改造的设计规格（前端重写、模块集成、布局与交互重构等） |
| [docs/deepseek-harness/plans/](docs/deepseek-harness/plans/) | 对应的分步实施计划（含任务清单与验收步骤） |
| [mixed_annotation/docs/](mixed_annotation/docs/) | 混合标注模块 API 与设计说明 |
| [model_annotation/docs/](model_annotation/docs/) | 模型标注模块设计手册与历史方案 |

## 常见问题

**Q：启动后某个服务窗口一闪而过 / 端口不是默认值？**
A：脚本启动前会探测端口并顺延，请以启动窗口打印的地址访问；服务窗口报错时先看该窗口的首个异常。

**Q：MinerU 健康检查失败怎么办？**
A：`start.bat` 会自动回退到 subprocess 模式并把 OCR 并发降为 1，功能仍可用，只是转换速度变慢。
常驻 API 起不来通常是模型缓存缺失或显存不足，可检查 `mixed_annotation/models/` 是否完整。

**Q：首次启动很慢？**
A：模型标注后端需要加载 PyTorch 与本地权重，约 20 秒后才开始监听；脚本已把它排在第一个启动，
并会等待各端口就绪后再拉起前端。

**Q：没有独立显卡能用吗？**
A：可以。把 `start.bat` 中的 `MINERU_DEVICE_MODE` 改为 `cpu` 即可，OCR 与训练速度会明显下降。

**Q：局域网其他电脑如何访问？**
A：前端以 `server.host: '0.0.0.0'` 启动，同一网段内访问 `http://<本机IP>:<前端端口>` 即可；
所有接口请求由本机 Vite 代理转发，无需额外放通后端端口。

## 约定

- 项目正式名称：**数据标注与分类工具**；网络代号 / 仓库名：**Label-Fast**。
- 本仓库开发与维护过程使用 **DeepSeek Harness** 编码助手，本地配置目录为 `.deepseek-harness/`。
- 文档与代码注释统一使用简体中文；提交信息遵循 `feat:` / `fix:` / `docs:` / `chore:` 前缀。

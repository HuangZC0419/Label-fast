# model_annotation（模型标注模块）

本模块从独立项目「基于模型的标注」迁移而来，提供**文档解析 + NER 训练/推理 + 结果标注**的完整后端能力，
以 FastAPI 服务的形式对外提供 REST 接口，可单独运行，也可作为数据标注与分类工具平台的第七个服务集成运行。

## 功能说明

1. **文档解析**
   - 上传 PDF / 图片 / 文本等文档，调用 MinerU（pipeline / vlm-auto-engine）完成版面分析、OCR、
     阅读顺序恢复、公式与表格识别。
   - 解析结果输出 Markdown、布局 PDF 与图片资源，并维护任务历史、进度轮询与结果下载。
2. **NER 训练与推理**
   - 基于 `chinese-roberta-wwm-ext` 骨干网络 + CRF 的序列标注模型，支持从 JSONL 数据集或
     已上传标注数据训练、继续训练、模型列表/详情/删除/下载。
   - 模型产物保存在 `backend/models/<model_id>/`，支持测试集评估与多模型切换。
3. **标注**
   - 对解析出的 Markdown 文本进行实体标注、标注结果保存与导出（JSONL / Doccano 等格式）。
   - 支持数据集库管理（上传、列表、详情、删除），训练时可直接引用数据集。

## 目录说明

```
model_annotation/
├── backend/                 # FastAPI 后端与模型代码
│   ├── main.py              # 应用入口与全部 HTTP 路由
│   ├── model_service.py     # 骨干网络加载、训练、推理、评估、模型管理
│   ├── dataset_store.py     # 数据集库的落盘与读取
│   ├── ner_crf.py           # CRF 层实现
│   ├── mineru_runner.py     # MinerU 运行包装与质量参数覆盖
│   ├── data_cleaning.py     # 训练数据清洗
│   ├── evaluation.py        # 评估指标
│   ├── generate_hq_data.py  # 高质量训练数据生成脚本
│   ├── generate_edge_cases.py
│   ├── requirements.txt     # 后端依赖
│   ├── models/              # 本地模型（骨干网络 + 已训练模型，约 2.36GB，不入 git）
│   ├── data/                # 训练/测试数据
│   ├── datasets/            # 数据集库（不入 git）
│   ├── test_output/         # 评估输出样例
│   └── tests/               # pytest 测试
├── input/                   # 文档解析输入样例（约 14MB，不入 git）
├── output/                  # 文档解析输出结果（约 70MB，不入 git）
├── docs/                    # 设计手册与历史方案文档
├── samples/                 # 示例文件：NER测试文本.txt、测试文本.png、测试文本_annotations.jsonl
└── README.md
```

## 单独运行

在本机已验证的 conda 环境 `CFwin11` 下执行：

```bat
call conda activate CFwin11
cd /d H:\Git\1CF_win11\Label-fast-main\model_annotation\backend
set PYTHONNOUSERSITE=1
python -m uvicorn main:app --host 127.0.0.1 --port 8267
```

- 服务地址：`http://127.0.0.1:8267`
- 接口文档：`http://127.0.0.1:8267/docs`
- 依赖安装：`pip install -r requirements.txt`（需额外安装 MinerU 才能使用文档解析能力）
- 模型路径为相对 `backend/` 的本地路径，无需联网下载骨干网络。

## 集成运行

根目录 `start.bat` 会启动平台的七个服务（含本模块），本模块默认监听 **8267** 端口，并在端口被占用时自动顺延。
前端不直接访问后端端口，而是通过 Vite dev server 的 `/model-api` 代理转发：

```
浏览器 → 前端端口 → /model-api/* → http://127.0.0.1:<本模块实际端口>/*
```

因此前端只需与前端端口通信；局域网内其他设备访问前端时无需额外开放本模块端口。

## 生产部署

- 仓库现有的 Docker 镜像**不包含本模块**：`Dockerfile` 与 `docker-compose.offline.yml` 仅构建主后端与前端。
- 生产环境需要为本模块**额外启动一个进程**（建议独立容器或 systemd/supervisor 托管 uvicorn，
  设置 `--workers 1`，因为模型常驻显存/内存），并在反向代理（Nginx/Caddy）中配置 `/model-api`
  前缀转发到该进程，同时剥离子路径前缀或使用 `root_path`。
- 模型文件约 2.36GB，建议以挂载卷或镜像外部目录的方式提供，不要打进业务镜像。

## Git 说明

以下内容**不进入 git**（见本目录 `.gitignore`）：

- `backend/models/` —— 骨干网络与已训练模型（约 2.36GB）
- `input/`、`output/` —— 文档解析样例与结果（约 83MB）
- `backend/datasets/` —— 数据集库
- `__pycache__`、`.pytest_cache`、`.model_cache` 等运行时缓存

`backend/data/`、`backend/test_output/`、`backend/tests/` 与 `samples/` 体积较小，正常纳入版本管理。

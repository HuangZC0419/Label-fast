# 航空标准分类（GB_fenlei）模块

本模块从独立的 `GB_fenlei` 项目迁移而来，包含航空标准分类的 FastAPI 后端、设计文档与样例数据，可作为独立服务运行，也可由数据标注与分类工具根目录的启动脚本统一调度。

## 目录说明

```text
GB_fenlei/
├─ backend/                 FastAPI 后端源码
│  ├─ main.py               应用入口（app）
│  ├─ config.py             默认映射、列别名与统计引擎阈值
│  ├─ classifier.py         分类流水线与集成决策
│  ├─ statistical.py        统计关键词、kNN、字符 n-gram 贝叶斯
│  ├─ mining.py             依据词表与相似名称索引
│  ├─ analysis.py           参照表体检与待分类目录概览
│  ├─ text.py               标准号/名称规范化与特征提取
│  ├─ excel_io.py           Excel 读取与去重
│  ├─ export.py             结果 Excel 导出
│  ├─ data/                 内置参照表与样例待分类目录
│  └─ tests/                后端测试
├─ docs/                    设计与计划文档
│  └─ deepseek-harness/
│     ├─ plans/             实施计划
│     └─ specs/             设计规格
├─ samples/                 根目录样例数据
│  ├─ 测试集.xlsx
│  ├─ 待分类目录.xlsx
│  └─ 分类好国标.xlsx
└─ README.md
```

## 单独运行

前置条件：已创建 conda 环境 `CFwin11`，并安装 `backend/requirements.txt` 中的依赖。

```bat
call conda activate CFwin11
cd /d <仓库根>\GB_fenlei\backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

启动后访问：

- Swagger 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/health

若端口 8000 被占用，可自行替换为其他空闲端口。

## 集成运行

在数据标注与分类工具仓库根目录执行 `start.bat` 时，脚本会：

1. 自动探测可用端口，避免端口冲突；
2. 启动本模块的 FastAPI 服务（`GB_fenlei/backend`）；
3. 前端通过 Vite 的 `/gb-api` 前缀代理访问本服务，例如：

```text
/gb-api/api/health
```

前端代码只请求相对路径，不硬编码主机名或端口，具体后端端口由启动脚本通过环境变量传递给 Vite 代理。

## 运行测试

在 `GB_fenlei/backend` 目录下安装测试依赖并执行测试：

```bat
python -m pip install -r requirements-test.txt
python -m pytest tests -q
```

## 生产部署

当前仓库根目录的 `Dockerfile` 只包含 数据标注与分类工具 主后端，不包含国标后端。若使用 Docker 部署，或由 数据标注与分类工具 后端进行前端静态托管（即不使用 Vite dev server），必须额外启动 `GB_fenlei/backend`，并在部署层（Nginx、IIS 或其他反向代理）为 `/gb-api` 配置反向代理，将请求转发到本服务的实际监听端口；否则前端会提示国标服务未连接。示例（Nginx）：

```nginx
location /gb-api/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

注意：`proxy_pass` 末尾的 `/` 会去掉 `/gb-api` 前缀，转发后路径为 `/api/health`，与本服务路由保持一致。

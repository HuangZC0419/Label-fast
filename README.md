# Label Fast

本系统面向文本命名实体识别、关系抽取及图像特征标注，当前仓库已统一整理为清晰的前后端结构：

- `frontend/`: React + Vite 前端
- `backend/`: FastAPI 后端，已内置文本标注与图像标注模块

## 启动后端

```bash
cd h:\Git\Label-fast-main\backend
pip install -r requirements.txt
python server.py
```

后端默认启动在 `http://localhost:8000`。

## 启动前端

```bash
cd h:\Git\Label-fast-main\frontend
npm install
npm run dev
```

前端开发服务器启动后，访问终端输出的本地地址即可。

## 功能入口

- 文本标注平台：前端首页
- 图像标注平台：前端页面右上角按钮，跳转到后端挂载的 `/minimind/`

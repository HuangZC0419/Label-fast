# 模型标注模块集成设计

- 日期：2026-11-05
- 状态：已确认
- 来源项目：`H:\Git\1CF_win11\基于模型的标注`
- 目标项目：`H:\Git\1CF_win11\Label-fast-main`

## 1. 目标

把「基于模型的标注」集成到 数据标注与分类工具 左侧导航，命名为「模型标注」，
保留其文档解析、NER 训练/推理、数据集管理、标注与导出能力；
后端独立进程，前端作为统一前端的一个需要登录的页面，视觉统一为 Ink & Signal。

## 2. 服务拓扑

```text
Vite 前端 :5175
 ├─ /api/*       → 数据标注与分类工具 后端 :3002
 ├─ /gb-api/*    → 国标后端 :8000
 ├─ /mix-api/*   → 混合后端 :3200
 └─ /model-api/* → 模型标注后端 :8267（去前缀）
                     │
                     └─ sys.executable → mineru_runner.py（CFwin11 + MinerU）
```

- 模型标注后端使用 CFwin11（已验证 torch 2.5.1+cu121、CUDA、mineru、transformers、datasets）。
- 后端仅监听 `127.0.0.1`。
- 后端路由为根路径（`/options`、`/models`、`/upload`、`/result/*`），经 `/model-api` 前缀隔离。

## 3. 目录布局

```text
Label-fast-main/
├── model_annotation/
│   ├── backend/          # 代码 + models(2.36GB) + data + datasets + test_output
│   ├── input/            # 样例 PDF/图片
│   ├── output/           # 历史任务结果
│   ├── docs/
│   └── samples/          # NER 测试文本、标注、测试图片
├── frontend/src/modules/model-annotation/
│   ├── views/ModelAnnotationView.vue   # 由 App.vue 拆出的模板 + 脚本
│   └── styles/model-annotation.css     # 由原 <style> 拆出并作用域化
└── start.bat              # 七服务启动
```

不迁移：`MinerU.zip`（10.3GB）、`__pycache__`、`.pytest_cache`、`backend/.model_cache`、
根目录重复 PDF、论文图、`.git`、`node_modules`、`dist`。

`.gitignore` 追加：
- `model_annotation/backend/models/`
- `model_annotation/backend/datasets/`
- `model_annotation/backend/.model_cache/`
- `model_annotation/input/`
- `model_annotation/output/`

## 4. 前端设计

### 4.1 路由与导航

- `/app` 子路由新增：
  - `path: 'model'`
  - `name: 'model-annotation'`
  - `meta.title: '模型标注'`
- 左侧导航第 6 项：标签「模型」，图标为文档 + 实体标记。
- AppHeader 眉题：`Model Annotation`。
- 路由继承 `requiresAuth`。

### 4.2 页面结构

- 页面根节点 `.model-root`，高度 100%，填满 `app-main`。
- 保留模块内部侧栏：历史记录、新建任务、模型管理、版本号；删除「Precisor」品牌块。
- 保留页内头部：面包屑「系统控制台 / 模型管理」、当前任务与状态。
- 保留向导栏与控制台/模型管理两个页面状态。
- `.model-shell`、`.model-sidebar`、`.model-main-wrap`、`.model-main` 改为 100% 高度与内部滚动，
  禁止 `100vh`。
- 删除深色模式：移除切换按钮、`isDarkMode`、系统深色自动切换、`theme-dark` 样式，强制浅色。

### 4.3 样式统一与隔离

- 原样式为蓝紫色 + Inter；映射到 Ink & Signal：
  - `--color-bg → var(--paper)`
  - `--color-bg-alt → var(--paper-deep)`
  - `--color-surface → var(--surface)`
  - `--color-surface-hover → var(--surface-sunken)`
  - `--color-primary → var(--signal)`
  - `--color-primary-hover → var(--signal-deep)`
  - `--color-primary-light → var(--signal-soft)`
  - `--color-accent → var(--warning)`，`--color-accent-light → var(--warning-bg)`
  - `--color-text → var(--ink)`，`--color-text-secondary → var(--ink-3)`，
    `--color-text-muted → var(--ink-4)`
  - `--color-border → var(--line)`，`--color-border-light → #ECE7DD`
  - 成功/警告/危险沿用 数据标注与分类工具 状态色
  - 字体 `Geist`，圆角/阴影使用 数据标注与分类工具 令牌
- 删除 `:root`、`html`、`body` 与全局 `*` 重置。
- 所有选择器限定在 `.model-root` 下；`@media` 内部同样限定；
  `@keyframes` 名称加 `model-` 前缀并同步 `animation` 引用。
- `v-html` 渲染的 Markdown 样式保持全局后代选择器（不加 Vue scoped），
  由 `.model-root .md-content-wrap ...` 命中。
- 冲突类重命名：
  - `app-shell → model-shell`
  - `app-sidebar → model-sidebar`
  - `app-main-wrap → model-main-wrap`
  - `app-main → model-main`
  - `app-header → model-header`
  - `btn-primary → model-btn-primary`
  - `btn-sm → model-btn-sm`
  - `stat-item → model-stat-item`
  - `stat-label → model-stat-label`
  - `status-dot → model-status-dot`
  - `toast → model-toast`
  - `toast-icon → model-toast-icon`
  - `toast-enter-active → model-toast-enter-active`
  - `toast-leave-active → model-toast-leave-active`
  - `toast-move → model-toast-move`

### 4.4 接口

- `resolveApiBase()` 返回 `/model-api`。
- 现有所有 axios/fetch、PDF iframe、图片地址、模型下载链接都经 `API_BASE` 拼接。
- Vite 代理：

```ts
'/model-api': {
  target: `http://127.0.0.1:${process.env.MODEL_BACKEND_PORT || '8267'}`,
  changeOrigin: true,
  rewrite: (path) => path.replace(/^\/model-api/, ''),
}
```

### 4.5 依赖

新增 `axios`、`chart.js`、`marked`、`turndown`、`turndown-plugin-gfm`。
不迁移 `quickTrainShortcuts.test.js`（该模块已不再被 App.vue 引用）。

## 5. 后端与数据

- 后端代码零改动。
- 迁移 `backend/models`（2.36GB）、`backend/data`、`backend/datasets`、
  `backend/test_output`、`input`、`output`。
- `mineru_runner.py` 使用 `sys.executable`，因此后端必须以 CFwin11 运行。
- 复用混合标注已有的 MinerU 模型环境变量（`MODELSCOPE_CACHE` 等）。
- 训练/推理与混合标注 MinerU 共用 GPU，可能互相占用显存。

## 6. 启动脚本

根目录 `start.bat` 扩展为七窗口：

| 窗口 | 默认端口 | 环境 |
| --- | --- | --- |
| 数据标注与分类工具 后端 | 3002 | CFwin11 |
| GB 后端 | 8000 | CFwin11 |
| 混合后端 | 3200 | CFwin11 |
| OCR Worker | 8870 | CFwin11 |
| MinerU API | 18000 | CFwin11 |
| 模型标注后端 | 8267 | CFwin11，`PYTHONNOUSERSITE=1` |
| 前端 | 5175 | Node |

要求：
1. 七个端口用 TcpListener 探测顺延。
2. 模型标注后端仅监听 `127.0.0.1`。
3. 前端窗口传入 `MODEL_BACKEND_PORT`。
4. 打印七个实际地址与手动启动步骤。
5. 文件 ASCII + CRLF。

## 7. 验证

1. `npm install` 后 `npm run build` 通过。
2. 模型标注后端 pytest 全部通过。
3. 启动后端测试端口：`/options`、`/models`、`/history` 返回 200。
4. 通过 Vite 访问 `/model-api/options` 返回 200。
5. 无头 Chrome 截图：模型标注页浅色渲染、无品牌重复、布局正常；
   文本/混合页面样式不受影响。
6. 未登录访问 `/app/model` 跳转登录页。
7. 如时间允许，用已有模型执行一次 `/model/infer`。

## 8. 已知边界

- Docker/生产环境不包含本模块，需要额外进程与 `/model-api` 反向代理。
- 2.36GB 模型、input/output 与 datasets 不进入 git，但迁移到本地目录。
- 训练/推理与混合标注 OCR 共用 GPU。
- 前端单文件较大（约 7418 行），本次只做拆分与作用域化，不重构业务逻辑。

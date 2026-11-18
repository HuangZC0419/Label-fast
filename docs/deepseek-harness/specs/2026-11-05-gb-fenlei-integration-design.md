# 国标分类模块集成设计

- 日期：2026-11-05
- 状态：已确认
- 来源项目：`H:\Git\1CF_win11\GB_fenlei`（航空标准分类）
- 目标项目：`H:\Git\1CF_win11\Label-fast-main`（数据标注与分类工具 标注平台）

## 1. 目标

把 GB_fenlei 的航空标准分类功能集成到 数据标注与分类工具 左侧导航栏，作为一个需要登录的功能模块，
同时保持前后端代码目录独立、可分别修改和单独运行。

## 2. 约束

- 后端必须保持独立进程，不并入 数据标注与分类工具 的 `backend/server.py`。
- 前端必须统一使用 数据标注与分类工具 的 Ink & Signal 设计系统，不使用 iframe。
- GB 前端接口路径 `/api/*` 与 数据标注与分类工具 的 `/api/*` 冲突，必须路径隔离。
- GB 后端使用裸 `import config`，必须以 `GB_fenlei/backend` 为工作目录运行。
- 运行环境统一为 conda 环境 `CFwin11`（注意大小写）。
- 不迁移 `.git`、`node_modules`、`__pycache__`、`.pytest_cache`、`wheels-py37`、打包 zip。

## 3. 目录结构

```text
Label-fast-main/
├── GB_fenlei/
│   ├── backend/                 # 原样迁移：main.py、classifier.py、data/、tests/ 等
│   ├── docs/                    # 原 GB 设计文档
│   ├── samples/                 # 测试集.xlsx、待分类目录.xlsx、分类好国标.xlsx
│   └── README.md                # 模块独立启动说明
├── backend/                     # 数据标注与分类工具 后端，不改业务逻辑
├── frontend/
│   └── src/
│       ├── modules/gb-fenlei/
│       │   ├── views/StandardClassifyView.vue
│       │   ├── components/      # AppSidebar/DataDialog/FileDrop 等 7 个组件
│       │   ├── api.ts
│       │   ├── types.ts
│       │   ├── format.ts
│       │   └── styles.css
│       ├── router/index.ts      # 新增 /app/classify
│       └── components/AppNavRail.vue
└── start.bat                    # 三服务启动，环境 CFwin11
```

## 4. 前端设计

### 4.1 路由与导航

- 在 `/app` 子路由新增：
  - `path: 'classify'`
  - `name: 'standard-classify'`
  - `meta.title: '航空标准分类'`
- 路由继承 `/app` 的 `requiresAuth`，未登录跳转 `/login`。
- 左侧导航新增第 4 项，图标为分层/分类线性图标，标签「国标」。
- AppHeader 眉题新增 `standard-classify` → `Standard Classification`。

### 4.2 页面布局

- 页面外层类名 `.gb-module`，高度 100%，填满 `app-main`。
- 页面内部采用「浅色步骤侧栏 + 内容区」两栏：
  - 侧栏顶部「分类流程」标题，下方四个步骤项；
  - 当前步骤使用 `--signal` 强调，已完成步骤显示对勾，不可达步骤禁用；
  - 侧栏底部显示服务在线状态与版本号；
  - 内容区顶部保留「第 N 步 / 标题 / 说明」和已上传文件上下文标签；
  - 内容区内部滚动，页面不产生第二层整页滚动条。
- 删除 GB 原深色品牌侧栏与深色顶部栏样式，改为 数据标注与分类工具 暖纸浅色面板。

### 4.3 类名与样式隔离

- `styles.css` 中所有选择器限定在 `.gb-module` 下；`@keyframes` 保持全局但名称加
  `gb-` 前缀，`@media` 内部选择器同样加 `.gb-module` 前缀。
- 与 数据标注与分类工具 全局样式已确认冲突的 6 个类名单独重命名：
  - `app-main → gb-main`
  - `btn → gb-btn`
  - `btn-primary → gb-btn-primary`
  - `sidebar → gb-sidebar`
  - `stat-label → gb-stat-label`
  - `input → gb-input`
- 其余类名保持不变，减少迁移改动面；所有 GB 规则因限定在 `.gb-module` 下而不会外泄。
- 删除 GB 的 `:root` 调色板与 `html/body` 全局规则。
- 在 `.gb-module` 下沿用 GB 原有变量名做令牌映射，避免逐个改写声明：
  - `--bg: var(--paper)`
  - `--border: var(--line)`
  - `--text: var(--ink)`
  - `--primary: var(--signal)`
  - `--surface` 等全局同名令牌直接继承，不在模块内重复声明
  - 成功/警告/危险沿用 `--success`、`--warning`、`--danger`
  - 字体使用 `var(--font-sans)`，圆角使用 `--radius-sm` / `--radius`，
    阴影使用 `--shadow-xs`
  - `--radius-lg` 使用字面值 `12px`，避免被模块内 `--radius` 遮蔽后自引用
- 保留 GB 的高密度表格和流程布局，仅替换色彩、字体、圆角、阴影。

### 4.4 接口访问

- `api.ts` 的 `BASE` 固定为 `/gb-api`。
- 请求示例：`/gb-api/api/health`、`/gb-api/api/reference/analyze`。
- `resolveDownloadUrl` 同样拼接 `/gb-api`。
- Vite 代理把 `/gb-api` 前缀去掉后转发到 GB 后端。

## 5. 后端设计

- GB 后端代码零改动，目录整体迁移到 `GB_fenlei/backend`。
- 默认端口 8000，由 `start.bat` 探测并顺延。
- 数据标注与分类工具 的 JWT 中间件不作用于 `/gb-api`（该路径只存在于 Vite 代理层，
  GB 后端本身不校验登录）。
- GB 上传文件、任务缓存、导出 `输出/` 目录均在 GB 后端内部，与 数据标注与分类工具 数据隔离。

## 6. 启动脚本

`start.bat` 修改为：

1. conda 环境使用 `CFwin11`。
2. 探测三个端口：
   - `BACKEND_PORT`：数据标注与分类工具 后端，从 3002 开始；
   - `GB_BACKEND_PORT`：GB 后端，从 8000 开始；
   - `FRONTEND_PORT`：Vite，从 5175 开始。
3. 开三个独立窗口：
   - 数据标注与分类工具 后端：`backend` 目录，`uvicorn server:app`；
   - GB 后端：`GB_fenlei\backend` 目录，`uvicorn main:app`；
   - 前端：`frontend` 目录，传入三个端口环境变量。
4. 打印三套实际地址（前端、Label API、GB API）。

`frontend/vite.config.ts` 增加：

```ts
const gbBackendPort = process.env.GB_BACKEND_PORT || '8000'

proxy: {
  '/api': { target: backendTarget, changeOrigin: true },
  '/minimind': { target: backendTarget, changeOrigin: true },
  '/gb-api': {
    target: `http://127.0.0.1:${gbBackendPort}`,
    changeOrigin: true,
    rewrite: (path) => path.replace(/^\/gb-api/, ''),
  },
}
```

## 7. 验证

1. 在 `frontend` 执行 `npm run typecheck` 通过。
2. 启动三个服务后：
   - `http://127.0.0.1:<前端端口>/` 可打开登录页；
   - 登录后左侧出现「国标」入口；
   - `/app/classify` 页面四步流程可走通；
   - 通过前端端口访问 `/gb-api/api/health` 返回 `{"status":"ok",...}`。
3. 运行 GB 后端测试：`pytest GB_fenlei/backend/tests/test_api.py GB_fenlei/backend/tests/test_workflow.py`。
4. 未登录直接访问 `/app/classify` 会跳转登录页。

## 8. 已知边界

- 当前方案为开发运行方式，依赖 Vite 代理。
- 若 production 由 数据标注与分类工具 后端单独托管前端，需要在部署层为 `/gb-api` 配置反向代理；
  该说明写入 `GB_fenlei/README.md`。
- GB 原 Win7 启动脚本与 wheel 不迁移，Win11 环境不再需要。

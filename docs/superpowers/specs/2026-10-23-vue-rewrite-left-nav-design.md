# LabelFast 前端 Vue 重写与左侧目录导航设计

- 日期：2026-10-23
- 状态：已确认
- 范围：`frontend/` 全部重写为 Vue 3 单页应用；后端接口保持不变

## 1. 目标

1. 前端由 React 整体重写为 Vue 3 + Vite + TypeScript + vue-router。
2. 新增最左侧独立图标目录栏，包含三个入口：
   - 文本标注
   - 图像标注（框选）
   - 大模型问答标注（原图像页内的问答模式）
3. 点击目录项切换到对应页面；删除原有的模块切换按钮与图像页内部的「问答/框选」切换按钮。
4. 保持现有后端 API、数据目录、登录认证、导出格式完全兼容。

## 2. 非目标

- 不修改 FastAPI 接口、JWT 认证逻辑与数据存储格式。
- 不删除旧 `/minimind/` HTML 页面（保留为兼容入口），新 SPA 只使用其 API。
- 不引入 Pinia、Tailwind 或新的 UI 组件库。

## 3. 技术选型

| 项 | 选择 |
|---|---|
| 框架 | Vue 3.5（SFC + `<script setup lang="ts">`） |
| 构建 | Vite 6 + `@vitejs/plugin-vue` |
| 路由 | vue-router 4（history 模式） |
| 类型 | TypeScript |
| 样式 | 复用现有 `App.css` 设计令牌与组件类；图像页样式改写为同款 CSS |
| 状态 | 组合式函数（`useAuth`、`useImageProject`），不引入 Pinia |

## 4. 路由

| 路径 | 页面 | 认证 |
|---|---|---|
| `/` | 根据登录态重定向到 `/app/text` 或 `/login` | - |
| `/login` | 登录页 | 仅未登录 |
| `/app` | 重定向到 `/app/text` | 需要 |
| `/app/text` | 文本标注 | 需要 |
| `/app/image` | 图像标注（框选） | 需要 |
| `/app/qa` | 大模型问答标注 | 需要 |
| `*` | 重定向到 `/` | - |

## 5. 目录结构

```
frontend/src/
├── main.ts
├── App.vue
├── router/index.ts
├── composables/
│   ├── useAuth.ts
│   └── useImageProject.ts
├── layouts/AppLayout.vue
├── components/
│   ├── AppNavRail.vue
│   ├── AppHeader.vue
│   ├── text/HelpModal.vue
│   ├── text/SettingsModal.vue
│   └── image/
│       ├── ProjectSidebar.vue
│       ├── ImageViewer.vue
│       ├── BoxPanel.vue
│       └── QaPanel.vue
├── views/
│   ├── LoginView.vue
│   ├── TextAnnotationView.vue
│   ├── ImageAnnotationView.vue
│   └── QaAnnotationView.vue
└── styles/app.css
```

## 6. 布局

- 最左侧 76px 固定图标导航栏（`AppNavRail`），三项竖排，图标 + 短标签，激活项高亮，悬停显示完整名称。
- 导航栏右侧为页面内容：顶部栏（品牌、当前模块标题、用户名、退出） + 页面主体。
- 文本页保留原「项目配置 / 标签配置 / 待标注对象」侧栏；图像与问答页保留「项目配置 / 图片列表」侧栏。
- 不再出现任何模块切换按钮或问答/框选模式切换按钮。

## 7. 页面职责

### 7.1 文本标注页

迁移 `AnnotatorApp.tsx` 全部行为：

- 项目列表、创建/切换、保存（sync）、清空、删除、ZIP 导出。
- 实体标签与关系类型配置、TXT 配置导入。
- 文本文件拖拽/选择导入，UTF-8/GBK/UTF-16 解码，原文/段落/句子三种切分。
- 字符级高亮覆盖层、关系曲线 SVG、标签选择浮层、关系选择浮层。
- 文档状态（待处理/进行中/已完成）、上/下一篇、跳过、保存、保存并下一篇。
- 快捷键：1-9、Ctrl+1-9、Space、Ctrl+Z、Delete、左右方向键、Esc。
- 显示设置弹窗与切分方式帮助弹窗。

API：`/api/projects`、`/api/projects/:id/sync`、`/api/projects/:id/record`、`/api/projects/:id/clear`、`/api/projects/:id/export-zip`、`/api/documents/:id`。

### 7.2 图像标注页（框选）

基于现有 Vue CDN 页面逻辑迁移：

- 项目列表、创建/切换、保存当前项目、删除项目。
- 图片列表、递归图片扫描、重置刷新、已标注标记。
- 图片查看、上一张/下一张、A/D 快捷键。
- 矩形框绘制（pointer capture）、删除单框、清空当前图片框、标签新增/选择/1-9 快捷键、创建 Box 模式开关。
- 保存框选结果（`/minimind/api/save_boxes`）、ZIP 导出（`mode=box`）。

### 7.3 大模型问答标注页

- 复用项目侧栏与图片查看器。
- 用户指令（默认「详细描述这张图片。」）与助手回答编辑；已有问答自动回填。
- 保存并下一张（助手回答不能为空）、跳过、Ctrl+Enter / Space 保存、A/D 切换。
- 导出问答 ZIP（`mode=qa`）。

### 7.4 共享图像数据层

`useImageProject` 统一处理：

- 项目 CRUD 与激活项目切换。
- 图片列表与已标注集合加载。
- **同时加载问答记录与框选记录**。
- 「保存当前项目」时同时提交 `qa_records` 与 `box_records`，防止任一侧保存时覆盖另一类数据。
- 图片 URL 生成：`/minimind/api/image_file/<encoded>`。

API 基址：`/minimind/api/*`。

## 8. 认证

- token 存于 `sessionStorage.token`，登录调用 `/api/auth/login`。
- 启动时用 `/api/auth/me` 校验 token；失效则清除并跳转 `/login`。
- 路由守卫：未登录访问 `/app/*` 跳转 `/login`；已登录访问 `/login` 跳转 `/app/text`。
- 退出：清除 token，跳转 `/login`。
- 图像 API 不需要 JWT（保持现状）；文本 API 需要 `Authorization: Bearer <token>`。

## 9. 构建与代理

- `vite.config.ts` 保持 `server.host = '0.0.0.0'`，`/api` 与 `/minimind` 代理到 `http://127.0.0.1:<BACKEND_PORT>`（默认 3002）。
- `npm run build` 输出到 `frontend/dist`，由 FastAPI 托管。
- 依赖：`vue`、`vue-router`、`@vitejs/plugin-vue`；移除 React 相关依赖。
- 构建脚本使用 `vite build`（类型检查单独执行，避免阻塞构建）。

## 10. 迁移步骤

1. 安装 Vue 依赖，建立 Vite + Vue 工程骨架与 TypeScript 配置。
2. 迁移设计样式到 `styles/app.css`。
3. 实现认证、路由守卫、AppLayout、AppNavRail、AppHeader。
4. 迁移登录页。
5. 迁移文本标注页与两个弹窗。
6. 实现 `useImageProject`、项目侧栏、图片查看器。
7. 实现框选页与问答页。
8. 删除 React 源码与依赖，更新 `index.html`、`package.json`、`tsconfig.json`。
9. 构建与功能回归。

## 11. 验证清单

- [ ] `npm run build` 成功，产物替换 `frontend/dist`。
- [ ] 登录、退出、刷新保持登录态。
- [ ] 左侧三个目录项可切换，激活态正确；无旧切换按钮。
- [ ] 文本页：导入、切分、实体/关系标注、保存、切换文档、导出正常。
- [ ] 图像页：项目创建/切换、图片列表、框绘制/删除/清空、保存、导出正常。
- [ ] 问答页：问答回填、保存并下一张、导出正常。
- [ ] 在图像页保存后问答数据不丢失，反之亦然。
- [ ] 快捷键（文本页与图像页）正常工作。

## 12. 风险

- 文本标注页逻辑量大，迁移时需逐项对照原实现。
- 图像框坐标换算依赖图片实际渲染尺寸，需在图片加载/窗口缩放后重新计算。
- 后端图像模块使用全局 active project，多个浏览器标签同时操作不同项目会互相影响（既有行为，不在本次范围内）。

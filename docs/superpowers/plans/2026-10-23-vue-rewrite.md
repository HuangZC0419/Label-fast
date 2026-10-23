# LabelFast 前端 Vue 重写实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> 本仓库当前分支为 `main`；除非用户明确要求，否则不要执行 git commit。

**Goal:** 将 `frontend/` 从 React 重写为 Vue 3 单页应用，并新增最左侧图标目录栏，包含文本标注、图像标注、大模型问答标注三个页面。

**Architecture:** Vue 3 + Vite + TypeScript + vue-router；左侧 76px 图标导航栏 + 页面内容；文本标注调用 `/api/*`，图像与问答标注共用 `useImageProject` 并调用 `/minimind/api/*`；后端不改动。

**Tech Stack:** Vue 3.5、Vite 6、TypeScript、vue-router 4、原生 CSS（复用 `App.css` 设计令牌）。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `frontend/package.json` | 依赖改为 Vue；移除 React |
| `frontend/vite.config.ts` | `@vitejs/plugin-vue` + 现有代理 |
| `frontend/tsconfig.json` | Vue/TS 配置 |
| `frontend/index.html` | `#app` + `/src/main.ts` |
| `frontend/src/main.ts` | 创建应用、注册路由 |
| `frontend/src/App.vue` | `<router-view />` |
| `frontend/src/env.d.ts` | Vite 类型声明 |
| `frontend/src/router/index.ts` | 路由表与认证守卫 |
| `frontend/src/composables/useAuth.ts` | 登录态、token、登录/退出/校验 |
| `frontend/src/composables/useImageProject.ts` | 图像项目、图片、问答与框选数据 |
| `frontend/src/layouts/AppLayout.vue` | 导航栏 + 顶部栏 + `<router-view />` |
| `frontend/src/components/AppNavRail.vue` | 76px 图标目录栏 |
| `frontend/src/components/AppHeader.vue` | 品牌、模块标题、用户、退出 |
| `frontend/src/views/LoginView.vue` | 登录页（移植 LoginPage.tsx） |
| `frontend/src/views/TextAnnotationView.vue` | 文本标注页（移植 AnnotatorApp.tsx） |
| `frontend/src/components/text/HelpModal.vue` | 切分说明弹窗（移植 HelpModal.tsx） |
| `frontend/src/components/text/SettingsModal.vue` | 显示设置与快捷键弹窗 |
| `frontend/src/views/ImageAnnotationView.vue` | 框选标注页 |
| `frontend/src/views/QaAnnotationView.vue` | 大模型问答标注页 |
| `frontend/src/components/image/ProjectSidebar.vue` | 项目配置 + 图片列表 |
| `frontend/src/components/image/ImageViewer.vue` | 图片显示、框覆盖层、绘制交互 |
| `frontend/src/components/image/BoxPanel.vue` | 框选右侧面板 |
| `frontend/src/components/image/QaPanel.vue` | 问答右侧面板 |
| `frontend/src/styles/app.css` | 由 `src/App.css` 迁移并补充导航/图像页样式 |

---

### Task 1: Vue 工程骨架

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/tsconfig.json`
- Modify: `frontend/index.html`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/env.d.ts`
- Create: `frontend/src/styles/app.css`（从 `src/App.css` 复制）

- [ ] **Step 1: 更新 package.json**

```json
{
  "name": "label-fast-frontend",
  "version": "0.0.1",
  "private": true,
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "vue": "^3.5.44",
    "vue-router": "^4.5.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.2.4",
    "@types/node": "^22.10.0",
    "typescript": "^5.6.3",
    "vite": "^6.4.2",
    "vue-tsc": "^2.2.0"
  }
}
```

- [ ] **Step 2: 更新 vite.config.ts**

```ts
import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"

const backendPort = process.env.BACKEND_PORT || '3002'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    proxy: {
      '/api': { target: `http://127.0.0.1:${backendPort}`, changeOrigin: true },
      '/minimind': { target: `http://127.0.0.1:${backendPort}`, changeOrigin: true },
    },
  },
})
```

- [ ] **Step 3: 更新 tsconfig.json 与 env.d.ts**

`tsconfig.json`：

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "module": "ESNext",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "skipLibCheck": true,
    "moduleResolution": "Bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "preserve",
    "strict": true,
    "types": ["vite/client", "node"]
  },
  "include": ["src/**/*.ts", "src/**/*.d.ts", "src/**/*.vue"]
}
```

`src/env.d.ts`：

```ts
/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}
```

- [ ] **Step 4: 更新 index.html 与入口**

`index.html`：

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>LabelFast 数据标注平台</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

`src/main.ts`：

```ts
import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './styles/app.css'

createApp(App).use(router).mount('#app')
```

`src/App.vue`：

```vue
<template>
  <router-view />
</template>
```

- [ ] **Step 5: 迁移样式**

将 `frontend/src/App.css` 完整复制为 `frontend/src/styles/app.css`，保留全部类名。后续任务只追加新样式，不删除既有类。

- [ ] **Step 6: 安装依赖并验证构建**

Run: `cd frontend && npm install`
Expected: 安装成功，`node_modules/vue` 存在。

Run: `cd frontend && npm run build`
Expected: 构建成功（此时路由文件尚未创建会失败；本步骤可先临时创建空路由，见 Task 2）。

---

### Task 2: 认证、路由与守卫

**Files:**
- Create: `frontend/src/router/index.ts`
- Create: `frontend/src/composables/useAuth.ts`
- Create: `frontend/src/views/LoginView.vue`
- Create: 三个占位视图 `TextAnnotationView.vue` / `ImageAnnotationView.vue` / `QaAnnotationView.vue`

- [ ] **Step 1: 实现 useAuth.ts**

```ts
import { reactive } from 'vue'

export interface AuthUser { id: number; username: string; role?: string; name?: string }

const state = reactive({
  user: null as AuthUser | null,
  token: sessionStorage.getItem('token'),
  loading: true,
})

let initPromise: Promise<void> | null = null

async function verify() {
  if (!state.token) { state.loading = false; return }
  try {
    const res = await fetch('/api/auth/me', {
      headers: { Authorization: `Bearer ${state.token}` },
    })
    if (res.ok) state.user = await res.json()
    else { sessionStorage.removeItem('token'); state.token = null; state.user = null }
  } catch { /* 网络错误保留 token，等待下次重试 */ }
  finally { state.loading = false }
}

export function ensureAuthReady() {
  if (!initPromise) initPromise = verify()
  return initPromise
}

export function useAuth() {
  return {
    state,
    isAuthenticated: () => !!state.user,
    async login(username: string, password: string) {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || '登录失败')
      }
      const data = await res.json()
      sessionStorage.setItem('token', data.token)
      state.token = data.token
      state.user = data.user
    },
    logout() {
      sessionStorage.removeItem('token')
      state.token = null
      state.user = null
      initPromise = null
    },
  }
}
```

- [ ] **Step 2: 实现路由与守卫**

```ts
import { createRouter, createWebHistory } from 'vue-router'
import { ensureAuthReady, useAuth } from '../composables/useAuth'
import AppLayout from '../layouts/AppLayout.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('../views/LoginView.vue'), meta: { guestOnly: true } },
    {
      path: '/app',
      component: AppLayout,
      meta: { requiresAuth: true },
      children: [
        { path: '', redirect: '/app/text' },
        { path: 'text', component: () => import('../views/TextAnnotationView.vue'), meta: { title: '文本标注' } },
        { path: 'image', component: () => import('../views/ImageAnnotationView.vue'), meta: { title: '图像标注' } },
        { path: 'qa', component: () => import('../views/QaAnnotationView.vue'), meta: { title: '大模型问答标注' } },
      ],
    },
    { path: '/', redirect: () => (useAuth().state.token ? '/app/text' : '/login') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  await ensureAuthReady()
  const { state } = useAuth()
  if (to.meta.requiresAuth && !state.user) return '/login'
  if (to.meta.guestOnly && state.user) return '/app/text'
  return true
})

export default router
```

- [ ] **Step 3: 迁移登录页**

将 `frontend/src/components/LoginPage.tsx` 的结构与文案逐项迁移为 `LoginView.vue`：

- 左侧品牌面板与 SVG 插画（可直接复用原 SVG）。
- 右侧表单：账号、密码、显示/隐藏密码、错误提示、提交中状态。
- 提交调用 `useAuth().login`，成功后 `router.push('/app/text')`。
- 使用既有 `.login-*` 样式类。

- [ ] **Step 4: 创建 AppLayout 与导航组件**

`AppLayout.vue`：

```vue
<template>
  <div class="app-container">
    <div class="app-body">
      <AppNavRail />
      <div class="app-page">
        <AppHeader :title="String(route.meta.title || '')" />
        <router-view />
      </div>
    </div>
  </div>
</template>
```

`AppNavRail.vue`：三个 `router-link`（`/app/text`、`/app/image`、`/app/qa`），使用 SVG 图标与短标签，`router-link-active` 高亮。

`AppHeader.vue`：左侧品牌 Logo + `LabelFast` + 当前模块标题；右侧用户名 + 退出按钮（调用 `logout()` 后 `router.push('/login')`）。

- [ ] **Step 5: 补充导航与布局样式**

在 `styles/app.css` 追加：

```css
.app-body { display: flex; height: 100vh; overflow: hidden; }
.app-page { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.app-nav-rail {
  width: 76px; flex-shrink: 0; background: #0F172A; color: #CBD5E1;
  display: flex; flex-direction: column; align-items: center;
  padding: .75rem .375rem; gap: .375rem; z-index: 30;
}
.app-nav-item {
  width: 100%; display: flex; flex-direction: column; align-items: center; gap: .25rem;
  padding: .625rem .25rem; border-radius: var(--radius-md); color: inherit;
  text-decoration: none; font-size: .6875rem; line-height: 1.2; text-align: center;
  transition: background var(--transition-fast), color var(--transition-fast);
}
.app-nav-item:hover { background: rgba(255,255,255,.08); color: #fff; }
.app-nav-item.router-link-active { background: var(--primary); color: #fff; }
```

- [ ] **Step 6: 构建验证**

Run: `cd frontend && npm run build`
Expected: 成功生成 `dist/index.html` 与 `dist/assets/*`。

---

### Task 3: 文本标注页迁移

**Files:**
- Create: `frontend/src/views/TextAnnotationView.vue`
- Create: `frontend/src/components/text/HelpModal.vue`
- Create: `frontend/src/components/text/SettingsModal.vue`
- Reference: `frontend/src/AnnotatorApp.tsx`、`frontend/src/HelpModal.tsx`、`frontend/src/App.css`

- [ ] **Step 1: 逐项迁移状态与逻辑**

在 `TextAnnotationView.vue` 的 `<script setup lang="ts">` 中实现与 `AnnotatorApp.tsx` 对等的能力：

- 项目：`projectList`、`pid`、`projectName`、`fetchProjects`、`loadProject`、`handleSwitchProject`、`onSave`、`onExportZip`、`onClearAll`、`onDeleteProject`。
- 标签：`labelsInput`、`relationTypesInput`、`labels`、`relationTypes`、`palette`、`relPalette`、配置 TXT 导入。
- 文档：`items`、`docIds`、`itemStatuses`、`currentIndex`、`text`、`spans`、`relations`、`spansByIndex`、`relationsByIndex`。
- 导入：`readFileBuffer`、`tryDecode`（utf-8/gbk/utf-16le/utf-16be）、`splitTextUI`、`handleFiles`、拖拽与文件选择。
- 标注：`onMouseUp`、`addSpan`、`removeSpanById`、`addRelation`、`updateRelationType`、`deleteRelation`、`undo`。
- 覆盖层：`chars`、`charRefs`、`charRects`、`spanSegments`、`boxes`、`overlayHeight`、`measureRectsAndBoxes`（`onMounted`、`watch` 文本/标注/字号/行高、`resize` 监听）。
- 保存：`handleSaveOnly`、`handleSaveAndNext`、`handleSkip`、`onDeleteDoc`。
- 快捷键：与 React 版本一致（1-9、Ctrl+1-9、Space、Ctrl+Z、Delete、左右键、Esc），使用 `window.addEventListener('keydown', handler, { capture: true })`，`onUnmounted` 移除。
- 请求头：`Authorization: Bearer ${token}`。

- [ ] **Step 2: 迁移模板**

按 `AnnotatorApp.tsx` 的 JSX 结构迁移为 Vue 模板，保持类名不变：

- 顶部操作行（上一篇/下一篇/删除当前/跳过/保存/保存并下一篇）。
- 标签与关系快捷区。
- `.annotation-area`：字符 span、绝对定位高亮块、SVG 关系曲线。
- 标签选择浮层、关系选择浮层。
- 设置弹窗、帮助弹窗。

- [ ] **Step 3: 迁移两个弹窗**

`HelpModal.vue`：接收 `open` prop、触发 `close` 事件；内容与 `HelpModal.tsx` 一致。
`SettingsModal.vue`：字大小、行高、关系线宽、虚线、快捷键说明；通过 `v-model` 或 props/emits 与父组件同步。

- [ ] **Step 4: 行为对照检查**

逐项对照原文件确认：无遗漏按钮、无遗漏请求、无遗漏快捷键；`saveCurrent` 在切换文档前调用；状态更新逻辑一致。

- [ ] **Step 5: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功。

---

### Task 4: 图像数据层与共享组件

**Files:**
- Create: `frontend/src/composables/useImageProject.ts`
- Create: `frontend/src/components/image/ProjectSidebar.vue`
- Create: `frontend/src/components/image/ImageViewer.vue`

- [ ] **Step 1: 实现 useImageProject**

参考 `backend/图像标注器/label_system/templates/index.html` 第 444-1234 行。必须包含：

```ts
export interface ImageProject {
  id: string; name: string; project_dir: string; image_dir: string;
  jsonl_path: string; box_jsonl_path: string; labels: string[]; last_image: string;
}
export interface BoxItem { x1: number; y1: number; x2: number; y2: number; label: string }
export interface QaRecord { user_content: string; assistant_content: string }
```

状态：`projects`、`currentProjectId`、`currentProject`、`images`、`labeledSet`、`currentIndex`、`boxes`、`qaRecords`、`imagesError`。
方法：`fetchProjects`、`createProject`、`switchProject`、`persistCurrentProject`、`deleteProject`、`fetchImages(preferred)`、`selectImage`、`prevImage`、`nextImage`、`saveQa`、`saveBoxes`、`exportZip(mode)`。

关键约束：

- `fetchImages` 同时请求 `/minimind/api/images` 与 `/minimind/api/annotations`，把 `box` 与 `qa` 两类记录**全部**装入状态。
- `persistCurrentProject` 提交 `labels`、`last_image`、`qa_records`、`box_records` 四类字段，且两类记录都来自已加载状态，禁止只提交其中一类。
- 所有 API 基址为 `/minimind/api`。
- 图片 URL：`/minimind/api/image_file/${encodeURI(name)}`。

- [ ] **Step 2: 实现 ProjectSidebar**

从原页面左侧栏迁移：

- 历史项目下拉、新建项目输入与按钮。
- 当前项目路径展示（图片目录、项目目录）。
- 「保存当前项目」「删除项目」。
- 图片列表（数量、刷新、当前项高亮、已标注 ✓、错误提示、空状态）。

Props：`projects`、`currentProjectId`、`currentProject`、`images`、`labeledSet`、`currentIndex`、`imagesError`。
Emits：`select-project`、`create-project`、`save-project`、`delete-project`、`refresh-images`、`select-image`。

- [ ] **Step 3: 实现 ImageViewer**

Props：`imageName`、`boxes`、`drawingEnabled`、`currentLabel`。
Emits：`box-created`。

实现：

- 图片容器与 `img`，`object-fit: contain`。
- 覆盖层：每个框按自然像素换算到显示像素，显示彩色边框与四角圆点。
- 绘制：pointerdown/move/up/cancel；只有 `drawingEnabled` 时开始；使用 `setPointerCapture`；小于 3×3 像素的框丢弃；完成后 emit `box-created`。
- 图片加载与窗口 `resize` 后重新计算布局（`layoutVersion`）。
- 上一张/下一张按钮与当前图片名。

- [ ] **Step 4: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功。

---

### Task 5: 图像标注（框选）页

**Files:**
- Create: `frontend/src/views/ImageAnnotationView.vue`
- Create: `frontend/src/components/image/BoxPanel.vue`

- [ ] **Step 1: 页面组装**

`ImageAnnotationView.vue`：

- 使用 `useImageProject()`。
- 左侧 `ProjectSidebar`，中间 `ImageViewer`，右侧 `BoxPanel`。
- 顶部操作区：当前图片名、上一张/下一张、保存框选、导出 ZIP。
- 图片切换前无额外确认（框数据保存在本地状态，未保存的框在切换前应先调用保存或保留在 `boxes` 状态中；与原实现一致）。

- [ ] **Step 2: 实现 BoxPanel**

迁移原右侧面板：

- 标签输入与添加（Enter）。
- 标签列表、当前标签高亮、1-9 选择。
- 「开始框选标注 / 绘制中... 按 ESC 取消」切换按钮。
- 当前图片框列表，支持删除单个框、清空全部框。
- 「保存当前图片框标注」与「打包导出框选标注 (ZIP)」。
- 状态提示（成功/失败）。

- [ ] **Step 3: 快捷键**

- `A` / `D`：上一张 / 下一张（输入框内不触发）。
- `Space`：保存框选。
- `1-9`、`0`：选择第 1-10 个标签并自动进入绘制模式。
- `Escape`：取消绘制并退出绘制模式。
- `Ctrl+Enter`：保存框选（与问答页统一）。

- [ ] **Step 4: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功。

---

### Task 6: 大模型问答标注页

**Files:**
- Create: `frontend/src/views/QaAnnotationView.vue`
- Create: `frontend/src/components/image/QaPanel.vue`

- [ ] **Step 1: 页面组装**

- 复用 `useImageProject()`、`ProjectSidebar`、`ImageViewer`。
- 不启用框绘制（`drawingEnabled=false`）。
- 右侧 `QaPanel`。

- [ ] **Step 2: 实现 QaPanel**

迁移原问答模式：

- 用户指令 textarea（默认「详细描述这张图片。」）。
- 助手回答 textarea。
- 当前图片已有问答题时自动回填；切换图片时保存草稿并在下一张回填。
- 「保存并下一张」：助手回答为空时提示「助手回答不能为空」；成功后标记已标注并跳到下一张。
- 「跳过 (不保存)」。
- 「打包导出问答标注 (ZIP)」→ `/minimind/api/export-zip?mode=qa`。
- 状态提示。

- [ ] **Step 3: 快捷键**

- `Ctrl+Enter`：保存并下一张（textarea 内也生效）。
- `Space`：保存并下一张（非输入状态下）。
- `A` / `D`：上一张 / 下一张（非输入状态下）。

- [ ] **Step 4: 数据不丢失检查**

确认保存问答时 `persistCurrentProject` 同时提交框选记录；可在框选页创建框、保存，再进入问答页保存问答，返回框选页确认框仍在。

- [ ] **Step 5: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功。

---

### Task 7: 清理 React 与样式收尾

**Files:**
- Delete: `frontend/src/App.tsx`、`frontend/src/main.tsx`、`frontend/src/AnnotatorApp.tsx`、`frontend/src/HelpModal.tsx`、`frontend/src/components/LoginPage.tsx`、`frontend/src/contexts/AuthContext.tsx`、`frontend/src/App.css`、`frontend/tsconfig.node.json`（若存在）
- Modify: `frontend/package.json`（移除 React 依赖）
- Modify: `frontend/src/styles/app.css`（补充图像页样式、字典栏微调）

- [ ] **Step 1: 删除 React 源码与依赖**

删除上述文件；从 `package.json` 移除 `react`、`react-dom`、`react-router-dom`、`@types/react`、`@types/react-dom`、`@vitejs/plugin-react`。执行 `npm install` 更新 lockfile。

- [ ] **Step 2: 样式收尾**

- 图像页布局、侧栏、右侧面板、图片容器、状态提示等样式统一到 `styles/app.css`。
- 确保登录页样式完整。
- 导航栏在窄屏（<900px）下保持 76px，不横向滚动页面。

- [ ] **Step 3: 全量构建**

Run: `cd frontend && npm run build`
Expected: 构建成功，无 React 产物。

---

### Task 8: 端到端验证

- [ ] **Step 1: 启动后端**

Run: `cd backend && python server.py --port 3002`
Expected: 输出 `Access the API at: http://localhost:3002`。

- [ ] **Step 2: 启动前端开发服务器**

Run: `cd frontend && npm run dev`
Expected: Vite 启动，输出 Local/Network 地址。

- [ ] **Step 3: 冒烟检查**

逐项确认：

- [ ] 未登录访问 `/app/text` 跳转 `/login`。
- [ ] 登录成功进入文本标注；刷新仍保持登录。
- [ ] 左侧三个图标可切换，激活态正确，无旧切换按钮。
- [ ] 文本页可创建项目、导入文本、实体/关系标注、保存、切换文档、导出。
- [ ] 图像页可创建项目、看到图片列表、绘制/删除框、保存、导出。
- [ ] 问答页可回填已有问答、保存并下一张、导出。
- [ ] 图像页保存后问答数据仍在；问答页保存后框选数据仍在。
- [ ] 退出登录回到 `/login`。

- [ ] **Step 4: 生产构建校验**

Run: `cd frontend && npm run build`
Run: `cd backend && python server.py --port 3002`（若前端已构建，FastAPI 托管 `frontend/dist`）
访问 `http://localhost:3002/login`，确认 SPA 可正常加载。

---

## 备注

- 旧 `/minimind/` HTML 页面保留为兼容入口，但新 UI 不链接它。
- 图像模块的全局 active project 行为保持不变；多标签页同时操作不同项目不在本次修复范围内。
- 所有新代码使用中文注释时遵循项目现有风格。

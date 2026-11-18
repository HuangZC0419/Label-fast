# 混合标注左侧栏与工具栏排版重构 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把混合标注视图的左侧栏收敛为「顶栏管项目 / 侧栏管文件」的单一层级，消除双滚动条，并将工作区工具栏按「模式 / 视图 / 动作 / 主操作」分组。

**Architecture:** 纯前端排版重构。顶栏接管唯一的项目切换入口与新建入口；左侧栏只保留当前项目摘要、导入区和文件列表三段，文件列表独占剩余高度并独自滚动；转换参数收进齿轮弹窗；工具栏用分隔线分成三组。所有 API、上传、轮询、标注、保存、PDF 预览逻辑保持不变。

**Tech Stack:** Vue 3 `<script setup>` + TypeScript、Vite 6、原生 CSS（Ink & Signal 设计令牌）。项目没有单元测试运行器，验收使用 `npm run typecheck` + 浏览器实机检查。

**Spec:** `docs/deepseek-harness/specs/2026-11-09-mixed-annotation-sidebar-design.md`

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `frontend/src/modules/mixed-annotation/components/AppHeader.vue` | 修改 | 顶栏新增「新建项目」图标按钮，发出 `create` 事件 |
| `frontend/src/modules/mixed-annotation/components/project/ProjectPanel.vue` | 修改 | 去掉项目下拉与摘要按钮；只留摘要 + [设置]；暴露 `startCreate` 等入口；删除项目移入表单 |
| `frontend/src/modules/mixed-annotation/views/MixedAnnotationView.vue` | 修改 | 接线顶栏 `create`、ProjectPanel ref、去除 `@select` |
| `frontend/src/modules/mixed-annotation/components/project/ConversionSettingsDialog.vue` | 新建 | 转换参数弹窗（表格 / 公式 / DPI） |
| `frontend/src/modules/mixed-annotation/components/project/UploadPanel.vue` | 修改 | 标题改名；[选择文件][选择文件夹][⚙] 同级；参数移入弹窗；删除长提示 |
| `frontend/src/modules/mixed-annotation/styles/app.css` | 修改 | 左侧栏固定三段 + 单一滚动；项目空态 / 删除按钮 / 顶栏新建按钮样式 |
| `frontend/src/modules/mixed-annotation/components/workspace/MixedWorkspace.vue` | 修改 | 工具栏分三组、分隔线、预览按钮文案随文件类型切换 |

---

### Task 1: 顶栏新建入口 + 项目面板精简

**Files:**
- Modify: `frontend/src/modules/mixed-annotation/components/AppHeader.vue`
- Modify: `frontend/src/modules/mixed-annotation/components/project/ProjectPanel.vue`
- Modify: `frontend/src/modules/mixed-annotation/views/MixedAnnotationView.vue`

- [ ] **Step 1: AppHeader 增加 `create` 事件与「＋」按钮**

在 `AppHeader.vue` 的 emits 中加入 `create`：

```ts
const emit = defineEmits<{
  'select-project': [id: string]
  create: []
  export: []
  'check-health': []
}>()
```

在模板 `<label class="header-project">…</label>` 之后插入：

```html
<button
  type="button"
  class="mx-btn mx-btn-icon header-create"
  title="新建项目"
  aria-label="新建项目"
  :disabled="projectSwitchDisabled"
  @click="emit('create')"
>
  <svg
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    stroke-width="1.5"
    stroke-linecap="round"
    aria-hidden="true"
  >
    <path d="M8 3v10M3 8h10" />
  </svg>
</button>
```

- [ ] **Step 2: ProjectPanel 删除项目下拉，改为摘要 + 设置**

把 `ProjectPanel.vue` 的 `<script setup>` 中与下拉相关的 `selectValue`、`onSelectChange` 删除，并新增 `defineExpose`：

```ts
defineExpose({ startCreate, startEdit, cancelCreate })
```

把 `watch` 中「无项目」分支改为只在确实没有项目时进入新建态：

```ts
watch(
  () => props.currentProject?.id,
  (id, previousId) => {
    if (props.currentProject) {
      mode.value = 'edit'
      fillForm(props.currentProject)
      // 只响应项目切换；后台刷新文件不会覆盖正在编辑的项目配置。
      if (id !== previousId) editing.value = false
      return
    }
    mode.value = 'create'
    editing.value = props.projects.length === 0
    clearForm()
  },
  { immediate: true },
)
```

模板整体替换为以下结构（保留原表单字段与 `submit` 逻辑）：

```html
<template>
  <section class="panel project-panel">
    <header class="panel-head">
      <h2 class="panel-title">项目 <span class="panel-title-cn">Project</span></h2>
      <button
        v-if="currentProject && !editing"
        type="button"
        class="mx-btn btn-ghost mx-btn-sm"
        :disabled="busy"
        @click="startEdit"
      >
        设置
      </button>
    </header>

    <div class="panel-body">
      <div v-if="!editing && currentProject" class="project-summary">
        <div class="project-summary-text">
          <span class="project-summary-name" :title="currentProject.name">
            {{ currentProject.name }}
          </span>
          <span class="project-summary-meta">
            {{ currentProject.labels.length }} 个标签 · {{ currentProject.relation_types.length }} 种关系
          </span>
        </div>
      </div>

      <p v-else-if="!currentProject && !editing" class="project-empty">
        {{ loading ? '正在读取项目…' : '还没有项目。点击顶栏「＋」新建，或在此开始创建。' }}
      </p>

      <form v-if="editing || !currentProject" class="project-form" @submit.prevent="submit">
        <p class="form-caption">
          {{ mode === 'create' ? '新建项目' : '项目配置' }}
          <span v-if="mode === 'edit' && currentProject" class="form-caption-id">
            {{ currentProject.id }}
          </span>
        </p>

        <label class="field">
          <span class="field-label">名称</span>
          <input
            v-model="name"
            class="mx-input"
            type="text"
            maxlength="80"
            placeholder="例如：零件工艺标注"
            :disabled="busy"
          />
        </label>

        <label class="field">
          <span class="field-label">
            实体标签
            <span class="field-meta">{{ labelCount }} 个</span>
          </span>
          <textarea
            v-model="labelsText"
            class="mx-input"
            rows="2"
            placeholder="每行一个，例如：工艺、材料、设备"
            :disabled="busy"
          />
        </label>

        <label class="field">
          <span class="field-label">
            关系类型
            <span class="field-meta">{{ relationCount }} 个</span>
          </span>
          <textarea
            v-model="relationsText"
            class="mx-input"
            rows="2"
            placeholder="每行一个，例如：使用_材料、属于"
            :disabled="busy"
          />
        </label>

        <p class="field-hint">标签与关系支持换行、逗号或顿号分隔，保存时自动去重。</p>

        <div class="form-actions">
          <button type="submit" class="mx-btn mx-btn-primary" :disabled="!canSubmit">
            {{ mode === 'create' ? '创建项目' : '保存配置' }}
          </button>
          <button
            type="button"
            class="mx-btn btn-ghost"
            :disabled="busy"
            @click="cancelCreate"
          >
            {{ mode === 'create' ? '取消' : '收起' }}
          </button>
          <button
            v-if="mode === 'edit' && currentProject"
            type="button"
            class="mx-btn btn-ghost project-delete"
            :disabled="busy"
            @click="emit('remove')"
          >
            删除项目
          </button>
        </div>
      </form>
    </div>
  </section>
</template>
```

同时把 emits 中的 `select` 删除，保留：

```ts
const emit = defineEmits<{
  create: [draft: ProjectDraft]
  save: [draft: ProjectDraft]
  remove: []
}>()
```

- [ ] **Step 3: MixedAnnotationView 接线**

在 `<script setup>` 中加入 ref 类型与实例：

```ts
interface ProjectPanelApi {
  startCreate: () => void
}

const projectPanelRef = ref<ProjectPanelApi | null>(null)
```

AppHeader 增加 `@create`：

```html
<AppHeader
  ...
  @create="projectPanelRef?.startCreate()"
/>
```

ProjectPanel 增加 `ref` 并删除 `@select`：

```html
<ProjectPanel
  ref="projectPanelRef"
  :projects="projects"
  :current-project="currentProject"
  :loading="projectsLoading"
  :busy="savingProject || importing || scanBusy"
  @create="createProject"
  @save="saveProject"
  @remove="deleteProject"
/>
```

- [ ] **Step 4: 补 CSS（项目空态 / 删除按钮 / 顶栏新建按钮）**

在 `styles/app.css` 的「侧栏面板」区块追加：

```css
.mx-root .project-empty {
  margin: 0;
  padding: 10px 12px;
  border: 1px dashed var(--line);
  border-radius: var(--radius);
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--ink-3);
}

.mx-root .form-actions .project-delete {
  margin-left: auto;
  color: var(--danger);
}
```

在「顶部栏」区块追加：

```css
.mx-root .header-create {
  flex: 0 0 auto;
}
```

- [ ] **Step 5: 类型检查**

Run: `cd frontend && npm run typecheck`
Expected: 退出码 0，无 TS 报错。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/modules/mixed-annotation/components/AppHeader.vue \
        frontend/src/modules/mixed-annotation/components/project/ProjectPanel.vue \
        frontend/src/modules/mixed-annotation/views/MixedAnnotationView.vue \
        frontend/src/modules/mixed-annotation/styles/app.css
git commit -m "refactor(mixed): 项目切换收敛到顶栏并精简项目面板"
```

---

### Task 2: 导入区同层级 + 转换参数弹窗

**Files:**
- Create: `frontend/src/modules/mixed-annotation/components/project/ConversionSettingsDialog.vue`
- Modify: `frontend/src/modules/mixed-annotation/components/project/UploadPanel.vue`

- [ ] **Step 1: 新建 ConversionSettingsDialog.vue**

```vue
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ConversionOptions } from '../../types'

const props = defineProps<{
  open: boolean
  options: ConversionOptions
}>()

const emit = defineEmits<{
  'update:open': [open: boolean]
  'update:options': [options: ConversionOptions]
}>()

const DPI_OPTIONS = [150, 200, 250, 300] as const
const draft = ref<ConversionOptions>({ ...props.options })

watch(
  () => props.open,
  (open) => {
    if (open) draft.value = { ...props.options }
  },
)

function close(): void {
  emit('update:open', false)
}

function apply(): void {
  emit('update:options', { ...draft.value })
  close()
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && props.open) close()
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div v-if="open" class="conv-backdrop" @click.self="close">
    <section
      class="conv-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="conv-dialog-title"
    >
      <header class="conv-head">
        <h2 id="conv-dialog-title" class="conv-title">转换参数</h2>
        <button type="button" class="conv-close" aria-label="关闭" @click="close">×</button>
      </header>

      <div class="conv-body">
        <label class="check">
          <input v-model="draft.enable_table" type="checkbox" />
          表格识别
        </label>
        <label class="check">
          <input v-model="draft.enable_formula" type="checkbox" />
          公式识别
        </label>
        <label class="field">
          <span class="field-label">DPI</span>
          <select v-model.number="draft.dpi" class="mx-input">
            <option v-for="dpi in DPI_OPTIONS" :key="dpi" :value="dpi">{{ dpi }}</option>
          </select>
        </label>
        <p class="field-hint">
          公式识别在 CPU 下较慢，可按需开启；DPI 越高越清晰，也更耗时。
        </p>
      </div>

      <footer class="conv-actions">
        <button type="button" class="mx-btn btn-ghost" @click="close">取消</button>
        <button type="button" class="mx-btn mx-btn-primary" @click="apply">应用</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.conv-backdrop {
  position: fixed;
  inset: 0;
  z-index: 120;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(20, 22, 25, 0.36);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  animation: conv-fade 160ms var(--ease-out) both;
}

.conv-dialog {
  width: min(360px, 100%);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: var(--shadow-lg);
  animation: conv-rise 180ms var(--ease-out) both;
}

.conv-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 14px 16px 8px;
}

.conv-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
}

.conv-close {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--ink-4);
  font-size: 17px;
  line-height: 1;
  cursor: pointer;
}

.conv-close:hover {
  background: var(--surface-sunken);
  color: var(--ink-2);
}

.conv-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 16px 14px;
}

.conv-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 16px 14px;
  border-top: 1px solid var(--line);
}

@keyframes conv-fade {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes conv-rise {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: none; }
}

@media (prefers-reduced-motion: reduce) {
  .conv-backdrop,
  .conv-dialog {
    animation: none;
  }
}
</style>
```

- [ ] **Step 2: UploadPanel 引入弹窗与同层级按钮**

在 `<script setup>` 顶部加入：

```ts
import ConversionSettingsDialog from './ConversionSettingsDialog.vue'
```

在 `const dragging = ref(false)` 附近加入：

```ts
const settingsOpen = ref(false)
```

把模板中从 `<button ... class="mx-btn upload-folder-btn" ...>` 到 `</div>`（`upload-options` 结束）以及后面的两段 `field-hint` 整体替换为：

```html
      <div class="upload-actions">
        <button
          type="button"
          class="mx-btn upload-action-btn"
          :disabled="blocked"
          @click="openPicker"
        >
          <svg
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M8 11V3" />
            <path d="m5 6 3-3 3 3" />
            <path d="M3 12.5h10" />
          </svg>
          选择文件
        </button>
        <button
          type="button"
          class="mx-btn upload-action-btn"
          :disabled="blocked"
          @click="openFolderPicker"
        >
          <svg
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path
              d="M2 5.5A1.5 1.5 0 0 1 3.5 4h2.2l1.2 1.5h5.6A1.5 1.5 0 0 1 14 7v5a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 12z"
            />
          </svg>
          {{ importing ? '正在导入…' : '选择文件夹' }}
        </button>
        <button
          type="button"
          class="mx-btn mx-btn-icon upload-settings-btn"
          title="转换参数"
          aria-label="转换参数"
          :disabled="props.disabled"
          @click="settingsOpen = true"
        >
          <svg
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <circle cx="8" cy="8" r="2.4" />
            <path d="M8 2.2v1.4M8 12.4v1.4M2.2 8h1.4M12.4 8h1.4M3.9 3.9l1 1M11.1 11.1l1 1M12.1 3.9l-1 1M4.9 11.1l-1 1" />
          </svg>
        </button>
      </div>
```

在 `</section>` 之前、模板最后加入弹窗：

```html
      <ConversionSettingsDialog
        v-model:open="settingsOpen"
        :options="options"
        @update:options="emit('update:options', $event)"
      />
```

删除已无用的 `DPI_OPTIONS` 常量、`toggleOption` 与 `changeDpi` 函数。

保留一段简短提示（放在进度/统计块之后）：

```html
      <p class="field-hint">文件夹内按相对路径排序；同名文件会自动跳过。</p>
```

- [ ] **Step 3: 更新 UploadPanel scoped 样式**

把 `.upload-folder-btn` 规则替换为：

```css
.upload-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.upload-action-btn {
  flex: 1 1 0;
  min-width: 0;
  height: 32px;
  padding: 0 8px;
  font-size: 11.5px;
}

.upload-settings-btn {
  flex: 0 0 auto;
}
```

- [ ] **Step 4: 面板标题改名**

把模板头部改为：

```html
    <header class="panel-head">
      <h2 class="panel-title">导入 <span class="panel-title-cn">Import</span></h2>
      <span class="panel-count">PDF · PNG · JPG</span>
    </header>
```

- [ ] **Step 5: 类型检查**

Run: `cd frontend && npm run typecheck`
Expected: 退出码 0。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/modules/mixed-annotation/components/project/ConversionSettingsDialog.vue \
        frontend/src/modules/mixed-annotation/components/project/UploadPanel.vue
git commit -m "refactor(mixed): 导入入口同级化并将转换参数收进弹窗"
```

---

### Task 3: 左侧栏单一滚动

**Files:**
- Modify: `frontend/src/modules/mixed-annotation/styles/app.css`

- [ ] **Step 1: 侧栏改为固定三段**

把 `.project-sidebar` 规则改为：

```css
.mx-root .project-sidebar {
  width: 330px;
  flex: 0 0 330px;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--surface);
  border-right: 1px solid var(--line);
}
```

- [ ] **Step 2: 文件面板吃掉剩余高度，文件列表独自滚动**

把 `.file-panel` 与 `.file-scroll` 改为：

```css
.mx-root .file-panel {
  flex: 1 1 auto;
  min-height: 0;
  border-bottom: 0;
}

.mx-root .file-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 2px 8px 10px;
}
```

- [ ] **Step 3: 矮视口回退为整栏滚动**

在 `styles/app.css` 末尾追加：

```css
@media (max-height: 700px) {
  .mx-root .project-sidebar {
    overflow-y: auto;
  }

  .mx-root .file-panel {
    flex: 0 0 auto;
    min-height: 160px;
  }
}
```

- [ ] **Step 4: 保持 ≤900px 移动端回退可用**

确认现有 `@media (max-width: 900px)` 中以下规则仍然存在（不改动，仅核对）：

```css
.mx-root .project-sidebar {
  width: 100%;
  flex: 0 0 auto;
  border-right: 0;
  border-bottom: 1px solid var(--line);
  overflow: visible;
}

.mx-root .file-panel {
  flex: 0 0 auto;
  min-height: 0;
}

.mx-root .file-scroll {
  max-height: 32vh;
}
```

- [ ] **Step 5: 浏览器验证单一滚动**

打开 `http://localhost:5175/app/mixed`，在文件数较多的项目下：
- 页面只出现一条侧栏滚动条（文件列表区域）。
- 文件列表滚到底时，最后一条文件完整可见。
- 缩放窗口宽度 < 900px 时，侧栏恢复整页滚动，无内容被裁剪。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/modules/mixed-annotation/styles/app.css
git commit -m "fix(mixed): 左侧栏改为单一滚动并固定导入区"
```

---

### Task 4: 工具栏三组分区

**Files:**
- Modify: `frontend/src/modules/mixed-annotation/components/workspace/MixedWorkspace.vue`

- [ ] **Step 1: 增加预览文案 computed**

在 `statusHeading` / `statusDescription` 附近加入：

```ts
const previewLabel = computed(() =>
  props.file?.source_type === 'pdf' ? 'PDF 预览' : '原图预览',
)
```

- [ ] **Step 2: 模板分组**

把 `.mw-actions` 内部替换为以下结构（保留原有按钮的事件与禁用条件，仅调整顺序与分组）：

```html
      <div class="mw-actions">
        <div class="mw-mode-switch" role="tablist" aria-label="工作模式">
          <button
            type="button"
            role="tab"
            :aria-selected="mode === 'annotate'"
            class="mw-mode-btn"
            :class="{ active: mode === 'annotate' }"
            :disabled="!completed || !documentReady || busy"
            @click="setMode('annotate')"
          >
            标注
          </button>
          <button
            type="button"
            role="tab"
            :aria-selected="mode === 'edit'"
            class="mw-mode-btn"
            :class="{ active: mode === 'edit' }"
            :disabled="!completed || !documentReady || busy"
            @click="setMode('edit')"
          >
            编辑 Markdown
          </button>
        </div>

        <span class="mw-divider" aria-hidden="true"></span>

        <div class="mw-view-group" role="group" aria-label="视图工具">
          <button
            type="button"
            class="mw-tool"
            :class="{ 'is-active': pdfOpen }"
            :disabled="!completed || !documentReady"
            :aria-pressed="pdfOpen"
            title="显示 / 隐藏原始文件预览"
            @click="togglePdf"
          >
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <path d="M14 2v6h6M8 13h8M8 17h5" />
            </svg>
            {{ previewLabel }}
          </button>

          <button
            type="button"
            class="mw-tool"
            :class="{ 'is-active': syncScroll }"
            :disabled="!completed || !documentReady || file?.source_type !== 'pdf'"
            :aria-pressed="syncScroll"
            title="Markdown 与 PDF 同步上下滚动（仅 PDF）"
            @click="toggleSyncScroll"
          >
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M8 4v16M16 4v16" />
              <path d="M5 7l3-3 3 3M13 17l3 3 3-3" />
            </svg>
            同步滚动
          </button>
        </div>

        <span class="mw-divider" aria-hidden="true"></span>

        <button
          type="button"
          class="mw-tool mw-tool--capture"
          :disabled="!completed || !documentReady"
          title="在原始文件上拖框截取图片或表格，并登记为图表标注"
          @click="startFigureCapture"
        >
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M6 2v14a2 2 0 0 0 2 2h14" />
            <path d="M18 22V8a2 2 0 0 0-2-2H2" />
          </svg>
          图片/表格标注
        </button>

        <button
          type="button"
          class="mw-tool mw-tool--primary"
          :disabled="primarySaveDisabled"
          @click="handlePrimarySave"
        >
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
            <path d="M17 21v-8H7v8M7 3v5h8" />
          </svg>
          {{ primarySaveLabel }}
          <span class="mw-shortcut">Ctrl S</span>
        </button>
      </div>
```

- [ ] **Step 3: 分组样式**

在 `.mw-actions` 规则后追加：

```css
.mw-divider {
  flex: 0 0 auto;
  width: 1px;
  height: 16px;
  background: var(--mw-line);
}

.mw-view-group {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
```

在 `@media (max-width: 760px)` 中追加：

```css
  .mw-divider {
    display: none;
  }
```

- [ ] **Step 4: 类型检查**

Run: `cd frontend && npm run typecheck`
Expected: 退出码 0。

- [ ] **Step 5: 浏览器验证**

打开 `http://localhost:5175/app/mixed`：
- 工具栏呈现「模式 ｜ 视图组 ｜ 动作 ｜ 保存」的层级，组间有 1px 分隔线。
- 选择 PDF 文件时预览按钮显示「PDF 预览」，同步滚动可用。
- 选择图片文件时预览按钮显示「原图预览」，同步滚动禁用。
- 点击「图片/表格标注」仍能打开预览并进入拖框截图。
- 保存按钮仍为唯一实心主按钮。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/modules/mixed-annotation/components/workspace/MixedWorkspace.vue
git commit -m "refactor(mixed): 工具栏按模式/视图/动作/主操作分组"
```

---

### Task 5: 全量验证

**Files:** 无新增

- [ ] **Step 1: 类型检查**

Run: `cd frontend && npm run typecheck`
Expected: 退出码 0。

- [ ] **Step 2: 生产构建**

Run: `cd frontend && npm run build`
Expected: 构建成功，输出 `dist/`，无错误。

- [ ] **Step 3: 逐项验收（对照 spec 第 3 节）**

- [ ] 顶栏与左侧栏合计只有一处项目切换控件。
- [ ] 左侧栏只有一条滚动条，文件列表底部完整可见。
- [ ] 「选择文件」「选择文件夹」视觉同级；DPI/表格/公式只在齿轮弹窗内。
- [ ] 工具栏呈现四级层级，组间有分隔线。
- [ ] 上传、文件夹导入、转换轮询、标注保存、PDF 预览与分栏拖拽行为不变。

- [ ] **Step 4: 若构建产物被版本控制跟踪，同步更新**

`frontend/dist/` 已在仓库中跟踪。如果 `npm run build` 改变了 `frontend/dist/index.html` 与 `assets/`，按现有习惯提交：

```bash
git add frontend/dist
git commit -m "chore: 更新前端构建产物"
```

---

## Self-Review 结论

- Spec 覆盖：2.1 → Task 1 + Task 3；2.2 → Task 2；2.3 → Task 4；验收 → Task 5。
- 无占位符；所有新增/修改代码均给出完整内容。
- 类型一致性：`ConversionOptions`、`ProjectDraft`、`ProjectPanelApi` 均来自现有类型与本次定义；组件事件名 `update:open` / `update:options` / `create` 前后一致。
- 已修正 spec 初稿中「PDF 预览与同步滚动禁用条件一致」的错误：图片文件仍需原图预览，故只让同步滚动对非 PDF 禁用。

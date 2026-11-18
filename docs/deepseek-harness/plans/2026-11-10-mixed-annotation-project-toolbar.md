# 混合标注项目管理与工具栏二次重构 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 项目管理全部收进顶栏「⋯」菜单；项目配置与转换参数合并为一个设置弹窗；左侧只留导入与文件；工具栏四个控制项统一 chip，保存与导出并列；删除顶部重复的截图入口。

**Architecture:** 纯前端。新增 `ProjectSettingsDialog.vue` 与 `ConfirmDialog.vue`，删除 `ProjectPanel.vue` 与 `ConversionSettingsDialog.vue`。父组件 `MixedAnnotationView.vue` 负责所有项目/设置/删除/导出接线；`MixedWorkspace.vue` 只负责工具栏与导出事件。

**Tech Stack:** Vue 3 `<script setup>` + TypeScript、Vite 6、原生 CSS。

**Spec:** `docs/deepseek-harness/specs/2026-11-10-mixed-annotation-project-toolbar-design.md`

---

## 文件分工

| 文件 | 动作 | 负责 |
|---|---|---|
| `components/AppHeader.vue` | 修改 | 顶栏 ＋ 与 ⋯ 菜单，移除导出按钮 |
| `components/project/ProjectSettingsDialog.vue` | 新建 | 项目信息 + 转换参数统一面板 |
| `components/common/ConfirmDialog.vue` | 新建 | 通用危险操作确认弹窗 |
| `views/MixedAnnotationView.vue` | 修改 | 移除 ProjectPanel、接线菜单/弹窗/删除/导出 |
| `types.ts` | 修改 | 新增 `ProjectSettingsPayload` |
| `styles/app.css` | 修改 | 顶栏菜单样式、清理项目卡片死样式 |
| `components/workspace/MixedWorkspace.vue` | 修改 | 四 chip 工具栏、保存/导出并列、移除截图按钮 |
| `components/project/UploadPanel.vue` | 修改 | 移除齿轮与转换参数弹窗 |
| `components/project/ProjectPanel.vue` | 删除 | 不再使用 |
| `components/project/ConversionSettingsDialog.vue` | 删除 | 被统一设置面板取代 |

---

### Task A: 顶栏项目菜单 + 统一设置弹窗 + 删除确认

**Files:**
- Modify: `components/AppHeader.vue`
- Create: `components/project/ProjectSettingsDialog.vue`
- Create: `components/common/ConfirmDialog.vue`
- Modify: `views/MixedAnnotationView.vue`
- Modify: `types.ts`
- Modify: `styles/app.css`
- Delete: `components/project/ProjectPanel.vue`
- Delete: `components/project/ConversionSettingsDialog.vue`

- [ ] **Step A1: types.ts 增加统一提交载荷**

```ts
export interface ProjectSettingsPayload {
  name: string
  labels: string[]
  relation_types: string[]
  options: ConversionOptions
}
```

- [ ] **Step A2: AppHeader 改为 ＋ / ⋯ 菜单**

Props 保留 `projects` / `currentProject` / `selectedFile` / `fileStatusLabel` / `backendStatus` / `projectSwitchDisabled`；删除 `exporting`。
Emits 改为：

```ts
const emit = defineEmits<{
  'select-project': [id: string]
  create: []
  settings: [section: 'rename' | 'project' | 'conversion']
  'delete-project': []
  'export-project': []
  'check-health': []
}>()
```

脚本增加菜单状态与关闭逻辑：

```ts
const menuOpen = ref(false)
const menuRef = ref<HTMLElement | null>(null)

function toggleMenu(): void {
  if (!props.currentProject || props.projectSwitchDisabled) return
  menuOpen.value = !menuOpen.value
}
function closeMenu(): void {
  menuOpen.value = false
}
function choose(action: 'rename' | 'project' | 'conversion' | 'export' | 'delete'): void {
  closeMenu()
  if (action === 'export') emit('export-project')
  else if (action === 'delete') emit('delete-project')
  else emit('settings', action)
}
function onDocumentPointerDown(event: PointerEvent): void {
  if (!menuOpen.value) return
  const target = event.target as Node | null
  if (target && menuRef.value?.contains(target)) return
  closeMenu()
}
function onDocumentKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') closeMenu()
}
onMounted(() => {
  document.addEventListener('pointerdown', onDocumentPointerDown)
  document.addEventListener('keydown', onDocumentKeydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
  document.removeEventListener('keydown', onDocumentKeydown)
})
```

模板在「＋」后加入：

```html
<div ref="menuRef" class="header-menu">
  <button
    type="button"
    class="mx-btn mx-btn-icon header-menu-btn"
    :disabled="!currentProject || projectSwitchDisabled"
    aria-haspopup="menu"
    :aria-expanded="menuOpen"
    title="项目操作"
    aria-label="项目操作"
    @click="toggleMenu"
  >
    <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <circle cx="8" cy="3" r="1.3" />
      <circle cx="8" cy="8" r="1.3" />
      <circle cx="8" cy="13" r="1.3" />
    </svg>
  </button>
  <div v-if="menuOpen" class="header-menu-panel" role="menu">
    <button type="button" role="menuitem" class="header-menu-item" @click="choose('rename')">重命名项目</button>
    <button type="button" role="menuitem" class="header-menu-item" @click="choose('project')">项目配置</button>
    <button type="button" role="menuitem" class="header-menu-item" @click="choose('conversion')">转换参数</button>
    <div class="header-menu-sep" role="separator"></div>
    <button type="button" role="menuitem" class="header-menu-item" @click="choose('export')">导出项目 ZIP</button>
    <div class="header-menu-sep" role="separator"></div>
    <button type="button" role="menuitem" class="header-menu-item is-danger" @click="choose('delete')">删除项目</button>
  </div>
</div>
```

删除模板中的「导出 ZIP」按钮及其 SVG；`header-actions` 只保留健康状态按钮。

- [ ] **Step A3: 新建 ProjectSettingsDialog.vue**

完整组件：两个区块 + 一个提交按钮。核心逻辑：

```ts
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ConversionOptions, Project, ProjectSettingsPayload } from '../../types'

const props = defineProps<{
  open: boolean
  mode: 'create' | 'edit'
  focusSection: 'rename' | 'project' | 'conversion'
  project: Project | null
  options: ConversionOptions
  busy: boolean
}>()

const emit = defineEmits<{
  'update:open': [open: boolean]
  submit: [payload: ProjectSettingsPayload]
}>()

const DPI_OPTIONS = [150, 200, 250, 300] as const

const name = ref('')
const labelsText = ref('')
const relationsText = ref('')
const optionsDraft = ref<ConversionOptions>({ ...props.options })

const dialogRef = ref<HTMLElement | null>(null)
const nameInputRef = ref<HTMLInputElement | null>(null)
const conversionRef = ref<HTMLElement | null>(null)
let restoreFocus: HTMLElement | null = null

function parseList(value: string): string[] {
  const items = value
    .split(/[\n,，、;；]+/)
    .map((item) => item.trim())
    .filter(Boolean)
  return Array.from(new Set(items))
}

const labelCount = computed(() => parseList(labelsText.value).length)
const relationCount = computed(() => parseList(relationsText.value).length)
const canSubmit = computed(() => name.value.trim().length > 0 && !props.busy)
const title = computed(() => (props.mode === 'create' ? '新建项目' : '项目设置'))
const submitLabel = computed(() => (props.mode === 'create' ? '创建项目' : '保存'))

function resetForm(): void {
  name.value = props.project?.name ?? ''
  labelsText.value = props.project?.labels.join('\n') ?? ''
  relationsText.value = props.project?.relation_types.join('\n') ?? ''
  optionsDraft.value = { ...props.options }
}

watch(
  () => props.open,
  async (open) => {
    if (!open) {
      if (restoreFocus) {
        restoreFocus.focus()
        restoreFocus = null
      }
      return
    }
    resetForm()
    restoreFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    if (props.focusSection === 'conversion' && conversionRef.value) {
      conversionRef.value.scrollIntoView({ block: 'nearest' })
      conversionRef.value
        .querySelector<HTMLElement>('input, select, button')
        ?.focus()
      return
    }
    nameInputRef.value?.focus()
    nameInputRef.value?.select()
  },
)

function close(): void {
  if (!props.busy) emit('update:open', false)
}

function submit(): void {
  if (!canSubmit.value) return
  emit('submit', {
    name: name.value.trim(),
    labels: parseList(labelsText.value),
    relation_types: parseList(relationsText.value),
    options: { ...optionsDraft.value },
  })
}
```

模板结构：

```html
<div v-if="open" class="psd-backdrop" @click.self="close">
  <section
    ref="dialogRef"
    class="psd-dialog"
    role="dialog"
    aria-modal="true"
    aria-labelledby="psd-title"
    tabindex="-1"
  >
    <header class="psd-head">
      <h2 id="psd-title" class="psd-title">{{ title }}</h2>
      <button type="button" class="psd-close" aria-label="关闭" @click="close">×</button>
    </header>

    <div class="psd-body">
      <section class="psd-section">
        <h3 class="psd-section-title">项目信息</h3>
        <label class="field">
          <span class="field-label">名称</span>
          <input ref="nameInputRef" v-model="name" class="mx-input" type="text" maxlength="80" placeholder="例如：零件工艺标注" :disabled="busy" />
        </label>
        <label class="field">
          <span class="field-label">实体标签 <span class="field-meta">{{ labelCount }} 个</span></span>
          <textarea v-model="labelsText" class="mx-input" rows="2" placeholder="每行一个，例如：工艺、材料、设备" :disabled="busy" />
        </label>
        <label class="field">
          <span class="field-label">关系类型 <span class="field-meta">{{ relationCount }} 个</span></span>
          <textarea v-model="relationsText" class="mx-input" rows="2" placeholder="每行一个，例如：使用_材料、属于" :disabled="busy" />
        </label>
        <p class="field-hint">标签与关系支持换行、逗号或顿号分隔，保存时自动去重。</p>
      </section>

      <section ref="conversionRef" class="psd-section">
        <h3 class="psd-section-title">转换参数</h3>
        <div class="psd-options">
          <label class="check">
            <input v-model="optionsDraft.enable_table" type="checkbox" :disabled="busy" />
            表格识别
          </label>
          <label class="check">
            <input v-model="optionsDraft.enable_formula" type="checkbox" :disabled="busy" />
            公式识别
          </label>
          <label class="psd-dpi">
            <span>DPI</span>
            <select v-model.number="optionsDraft.dpi" class="mx-input" :disabled="busy">
              <option v-for="dpi in DPI_OPTIONS" :key="dpi" :value="dpi">{{ dpi }}</option>
            </select>
          </label>
        </div>
        <p class="field-hint">公式识别在 CPU 下较慢，可按需开启；DPI 越高越清晰，也更耗时。</p>
      </section>
    </div>

    <footer class="psd-actions">
      <button type="button" class="mx-btn btn-ghost" :disabled="busy" @click="close">取消</button>
      <button type="button" class="mx-btn mx-btn-primary" :disabled="!canSubmit" @click="submit">
        {{ busy ? '保存中…' : submitLabel }}
      </button>
    </footer>
  </section>
</div>
```

样式：fixed 遮罩 + 居中卡片，`z-index: 140`，`width: min(440px, 100%)`，`max-height: 86vh`，`overflow-y: auto`。焦点逻辑与 `ConversionSettingsDialog` 相同：Tab 循环、Esc 关闭、打开期间屏蔽 Ctrl+S（捕获阶段监听）。

- [ ] **Step A4: 新建 ConfirmDialog.vue**

```ts
const props = defineProps<{
  open: boolean
  title: string
  message: string
  confirmLabel?: string
  danger?: boolean
  busy?: boolean
}>()
const emit = defineEmits<{
  'update:open': [open: boolean]
  confirm: []
}>()
```

模板：fixed 遮罩 + 卡片，标题、正文、`[取消] [确认按钮]`。`danger` 时确认按钮用 `.mx-btn-danger`，`busy` 时显示「处理中…」并禁用。Esc 关闭（busy 除外）。焦点恢复到触发元素。

- [ ] **Step A5: MixedAnnotationView 接线**

删除 `ProjectPanel` 导入、`ProjectPanelApi`、`projectPanelRef` 及模板中的 `<ProjectPanel>`。

新增状态：

```ts
const settingsOpen = ref(false)
const settingsMode = ref<'create' | 'edit'>('edit')
const settingsSection = ref<'rename' | 'project' | 'conversion'>('project')
const deleteOpen = ref(false)
```

新增函数：

```ts
function openCreateSettings(): void {
  settingsMode.value = 'create'
  settingsSection.value = 'project'
  settingsOpen.value = true
}
function openProjectSettings(section: 'rename' | 'project' | 'conversion'): void {
  if (!currentProject.value) return
  settingsMode.value = 'edit'
  settingsSection.value = section
  settingsOpen.value = true
}
async function handleSettingsSubmit(payload: ProjectSettingsPayload): Promise<void> {
  const draft = {
    name: payload.name,
    labels: payload.labels,
    relation_types: payload.relation_types,
  }
  const ok =
    settingsMode.value === 'create'
      ? await createProject(draft)
      : await saveProject(draft)
  if (!ok) return
  applyConversionOptions(payload.options)
  settingsOpen.value = false
}
const deleteImpact = computed(() => {
  const project = currentProject.value
  if (!project) return ''
  return `将同时删除 ${files.value.length} 个文件、${project.labels.length} 个标签、${project.relation_types.length} 种关系，以及全部标注记录和图表截图。此操作不可恢复。`
})
function openDeleteDialog(): void {
  if (!currentProject.value) return
  deleteOpen.value = true
}
async function confirmDeleteProject(): Promise<void> {
  const ok = await deleteProject()
  if (ok) deleteOpen.value = false
}
```

把 `createProject` / `saveProject` 改为返回 `Promise<boolean>`（成功 true，失败 false）。`deleteProject` 移除 `window.confirm`，返回 `Promise<boolean>`。

模板：

```html
<AppHeader
  ...
  :project-switch-disabled="importing || scanBusy || savingProject"
  @select-project="selectProject"
  @create="openCreateSettings"
  @settings="openProjectSettings"
  @delete-project="openDeleteDialog"
  @export-project="exportProject"
  @check-health="checkHealth"
/>
```

左侧 aside 只保留 `UploadPanel` 与 `FileList`。

在根级（`</div>` 前）加入：

```html
<ProjectSettingsDialog
  v-model:open="settingsOpen"
  :mode="settingsMode"
  :focus-section="settingsSection"
  :project="currentProject"
  :options="conversionOptions"
  :busy="savingProject"
  @submit="handleSettingsSubmit"
/>

<ConfirmDialog
  v-model:open="deleteOpen"
  :title="`删除项目「${currentProject?.name ?? ''}」？`"
  :message="deleteImpact"
  confirm-label="删除项目"
  danger
  :busy="savingProject"
  @confirm="confirmDeleteProject"
/>
```

同时给 `MixedWorkspace` 增加导出接线：

```html
<MixedWorkspace
  ...
  :exporting="exporting"
  @export="exportProject"
/>
```

- [ ] **Step A6: app.css 顶栏菜单样式与死样式清理**

新增：

```css
.mx-root .header-menu { position: relative; flex: 0 0 auto; }
.mx-root .header-menu-panel {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 40;
  min-width: 184px;
  padding: 5px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface-raised);
  box-shadow: 0 18px 40px -24px rgba(35, 29, 19, .32);
  animation: mx-menu-in 140ms var(--ease-out) both;
}
.mx-root .header-menu-item {
  display: flex;
  width: 100%;
  align-items: center;
  height: 32px;
  padding: 0 10px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--ink-2);
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}
.mx-root .header-menu-item:hover { background: var(--surface-sunken); color: var(--ink); }
.mx-root .header-menu-item.is-danger { color: var(--danger); }
.mx-root .header-menu-item.is-danger:hover { background: var(--danger-bg); }
.mx-root .header-menu-sep { height: 1px; margin: 4px 6px; background: var(--line); }
@keyframes mx-menu-in {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: none; }
}
```

删除已无 DOM 的 `.project-panel`、`.project-summary*`、`.project-delete` 相关规则（`grep` 确认后再删；`.project-form` / `.field` / `.form-actions` 仍被设置弹窗复用，保留）。

- [ ] **Step A7: 删除旧组件**

```bash
rm frontend/src/modules/mixed-annotation/components/project/ProjectPanel.vue
rm frontend/src/modules/mixed-annotation/components/project/ConversionSettingsDialog.vue
```

确认全模块 grep 不再引用这两个组件。

- [ ] **Step A8: 类型检查**

Run: `cd frontend && npm run typecheck`
Expected: 退出码 0。并行 Agent 可能造成瞬时错误，最终必须复跑通过。

---

### Task B: 工具栏四 chip + 保存/导出并列 + 导入区去齿轮

**Files:**
- Modify: `components/workspace/MixedWorkspace.vue`
- Modify: `components/project/UploadPanel.vue`

- [ ] **Step B1: MixedWorkspace props / emits**

```ts
const props = defineProps<{
  project: Project | null
  file: MixedFile | null
  labels: string[]
  relationTypes: string[]
  exporting: boolean
}>()

const emit = defineEmits<{
  saved: []
  refresh: []
  export: []
}>()
```

- [ ] **Step B2: 移除顶部截图入口**

删除 `startFigureCapture` 函数、模板中的「图片/表格标注」按钮，以及 `PdfPreviewApi` 中的 `startCapture` 成员声明（`PdfPreview.vue` 的 `defineExpose` 保持不变）。保留 `captureRegion`。

- [ ] **Step B3: 工具栏四个统一 chip**

替换 `.mw-mode-switch` 区块为：

```html
<div class="mw-controls" role="group" aria-label="工作区控制">
  <button
    type="button"
    class="mw-control"
    :class="{ 'is-mode-active': mode === 'annotate' }"
    :aria-pressed="mode === 'annotate'"
    :disabled="!completed || !documentReady || busy"
    @click="setMode('annotate')"
  >
    <span class="mw-control-dot" aria-hidden="true" />
    标注
  </button>
  <button
    type="button"
    class="mw-control"
    :class="{ 'is-mode-active': mode === 'edit' }"
    :aria-pressed="mode === 'edit'"
    :disabled="!completed || !documentReady || busy"
    @click="setMode('edit')"
  >
    <span class="mw-control-dot" aria-hidden="true" />
    编辑 Markdown
  </button>
  <button
    type="button"
    class="mw-control"
    :class="{ 'is-toggle-active': pdfOpen }"
    :aria-pressed="pdfOpen"
    :disabled="!completed || !documentReady"
    title="显示 / 隐藏原始文件预览"
    @click="togglePdf"
  >
    <span class="mw-control-dot" aria-hidden="true" />
    {{ previewLabel }}
  </button>
  <button
    type="button"
    class="mw-control"
    :class="{ 'is-toggle-active': syncScroll && file?.source_type === 'pdf' }"
    :aria-pressed="syncScroll && file?.source_type === 'pdf'"
    :disabled="!completed || !documentReady || file?.source_type !== 'pdf'"
    title="Markdown 与 PDF 同步上下滚动（仅 PDF）"
    @click="toggleSyncScroll"
  >
    <span class="mw-control-dot" aria-hidden="true" />
    同步滚动
  </button>
</div>
```

- [ ] **Step B4: 保存与导出并列**

把原「保存标注」按钮与新增导出按钮包进 `.mw-publish`：

```html
<div class="mw-publish">
  <button type="button" class="mw-tool mw-tool--primary" :disabled="primarySaveDisabled" @click="handlePrimarySave">
    <!-- 原保存图标 -->
    {{ primarySaveLabel }}
    <span class="mw-shortcut">Ctrl S</span>
  </button>
  <button type="button" class="mw-tool mw-export" :disabled="!project || exporting" @click="emit('export')">
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M12 3v10" />
      <path d="m8 9 4 4 4-4" />
      <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
    </svg>
    {{ exporting ? '导出中…' : '导出 ZIP' }}
  </button>
</div>
```

- [ ] **Step B5: 工具栏样式**

删除 `.mw-mode-switch` / `.mw-mode-btn*` 规则，新增：

```css
.mw-controls {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.mw-control {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 11px;
  border: 1px solid var(--mw-line);
  border-radius: 9px;
  background: var(--mw-surface);
  color: var(--mw-ink-2);
  font-family: inherit;
  font-size: 11.5px;
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 180ms var(--mw-ease), border-color 180ms var(--mw-ease), color 180ms var(--mw-ease);
}
.mw-control:hover:not(:disabled) {
  border-color: var(--mw-line-strong);
  background: var(--mw-raised);
}
.mw-control:disabled { opacity: .42; cursor: not-allowed; }
.mw-control-dot {
  width: 5px;
  height: 5px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--mw-ink-4);
}
.mw-control.is-mode-active {
  border-color: var(--mw-ink);
  background: var(--mw-ink);
  color: #FFFDF9;
  font-weight: 600;
}
.mw-control.is-mode-active .mw-control-dot { background: #FFFDF9; }
.mw-control.is-toggle-active {
  border-color: rgba(228, 87, 46, .34);
  background: var(--mw-signal-soft);
  color: var(--mw-signal-ink);
}
.mw-control.is-toggle-active .mw-control-dot { background: var(--mw-signal); }
.mw-publish { display: inline-flex; align-items: center; gap: 6px; }
.mw-export { border-color: var(--mw-line-strong); }
```

`@media (max-width: 760px)` 中补充：

```css
.mw-controls { width: 100%; }
.mw-control { flex: 1 1 auto; justify-content: center; }
.mw-publish { width: 100%; }
.mw-publish > * { flex: 1 1 0; }
```

- [ ] **Step B6: UploadPanel 移除齿轮**

删除 `ConversionSettingsDialog` 导入、`settingsOpen`、模板中的 `[⚙]` 按钮与 `<ConversionSettingsDialog>`、`.upload-settings-btn` 样式。`[选择文件] [选择文件夹]` 保持同级，各自 `flex: 1 1 0`。

- [ ] **Step B7: 类型检查**

Run: `cd frontend && npm run typecheck`
Expected: 退出码 0。

---

### Task C: 集成验证

- [ ] `cd frontend && npm run typecheck` → 0
- [ ] `cd frontend && npm run build` → 成功
- [ ] 浏览器核对：
  - 顶栏只有项目下拉 + ＋ + ⋯；左侧无项目卡片。
  - ⋯ 菜单五项可用；无文件时可导出项目 ZIP。
  - 设置弹窗同屏含项目信息与转换参数，保存后两处配置同时生效。
  - 删除弹窗显示文件数/标签数/关系数，确认后删除。
  - 工具栏四个控制项同尺寸；当前模式深墨实心，开关开启朱砂浅底。
  - 顶部无「图片/表格标注」；PDF 预览内「截图」可创建图/表。
  - 保存与导出并列且各自有结果提示。
  - 上传、文件夹导入、轮询、Markdown 编辑、同步滚动、分栏拖拽无回归。
- [ ] 代码审查子任务复核。

---

## Self-Review

- Spec 2 → A2；3 → A5/A7/B6；4 → A3；5 → A4/A5；6 → B1-B5；7 → C。
- 无占位符；关键代码均给出。
- 类型一致性：`ProjectSettingsPayload` 在 `types.ts` 定义、弹窗与父组件共同引用；`exporting`/`export` 在 MixedWorkspace 与父组件之间契约固定。
- 已知取舍：导出 ZIP 为整个项目（现有接口），不新增后端。

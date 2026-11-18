<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { Project, ProjectDictionaryPatch } from '../../types'
import { labelColor, relationColor } from '../../composables/useMarkdownAnnotation'

/**
 * 项目字典卡片：在导入面板之上配置「实体标签 / 关系类型」。
 *
 * 职责边界：
 * - 只维护编辑草稿（labels / relation_types），不负责请求；
 * - 每次增删立即 emit 该分区的完整数组，由父组件串行 PATCH 并回写状态；
 * - 保存失败不自行回滚草稿，父组件负责把服务端状态同步回项目对象，
 *   避免“用户正在输入时草稿被覆盖”造成的输入丢失。
 */
const props = defineProps<{
  project: Project
  status: 'idle' | 'saving' | 'saved' | 'error'
}>()

const emit = defineEmits<{
  save: [patch: ProjectDictionaryPatch]
}>()

type DictionarySection = 'labels' | 'relation_types'

interface DuplicateHint {
  section: DictionarySection
  value: string
}

const labels = ref<string[]>([...props.project.labels])
const relations = ref<string[]>([...props.project.relation_types])

/** 同一时间只展开一个分区的编辑态。 */
const activeSection = ref<DictionarySection | null>(null)
/** 两个分区共用同一份输入值（因为只展开一个），切换分区时清空。 */
const inputValue = ref('')
/** 两个分区各持一个模板引用，避免切换时卸载顺序把引用置空。 */
const labelsInputEl = ref<HTMLInputElement | null>(null)
const relationsInputEl = ref<HTMLInputElement | null>(null)
/** 退出编辑后把焦点还给对应分区的「编辑」按钮，避免落到 body。 */
const labelsEditBtn = ref<HTMLButtonElement | null>(null)
const relationsEditBtn = ref<HTMLButtonElement | null>(null)
/** 最近一次发出的增量载荷，供失败后的「重试」原样重发。 */
const lastPatch = ref<ProjectDictionaryPatch | null>(null)

/** 重复项短暂高亮：记录分区 + 值，而不是下标，避免列表变化后错位。 */
const duplicate = ref<DuplicateHint | null>(null)
let duplicateTimer: ReturnType<typeof setTimeout> | null = null

/**
 * 输入法组合状态。仅依赖 event.isComposing 在部分浏览器/输入法的
 * 首次回车并不可靠，因此同时监听 compositionstart / compositionend。
 */
let composing = false

const isEditingLabels = computed(() => activeSection.value === 'labels')
const isEditingRelations = computed(() => activeSection.value === 'relation_types')

const inputPlaceholder = computed(() =>
  isEditingLabels.value ? '输入实体标签，回车添加' : '输入关系类型，回车添加',
)
const inputAriaLabel = computed(() =>
  isEditingLabels.value ? '添加实体标签' : '添加关系类型',
)

/**
 * 重复项的读屏提示。只在当前展开分区的编辑区渲染，
 * 并在 duplicate 计时结束后随 v-if 一起消失。
 */
const duplicateMessage = computed(() => {
  const hint = duplicate.value
  if (!hint || hint.section !== activeSection.value) return ''
  return hint.section === 'labels' ? '已存在同名标签' : '已存在同名关系'
})

function resetFromProject(): void {
  labels.value = [...props.project.labels]
  relations.value = [...props.project.relation_types]
  activeSection.value = null
  inputValue.value = ''
  composing = false
  lastPatch.value = null
  clearDuplicate()
}

// 仅当项目切换时重置，避免父组件回写 project.labels 时打断正在进行的编辑。
watch(() => props.project.id, resetFromProject, { immediate: true })

function emitPatch(patch: ProjectDictionaryPatch): void {
  lastPatch.value = patch
  emit('save', patch)
}

function retrySave(): void {
  if (lastPatch.value) emit('save', lastPatch.value)
}

async function focusInput(): Promise<void> {
  await nextTick()
  const target = isEditingLabels.value ? labelsInputEl.value : relationsInputEl.value
  target?.focus()
}

/** 退出编辑后输入框被卸载，焦点必须显式还给该分区的「编辑」按钮。 */
function focusEditButton(section: DictionarySection): void {
  const target = section === 'labels' ? labelsEditBtn.value : relationsEditBtn.value
  target?.focus()
}

function toggleSection(section: DictionarySection): void {
  if (activeSection.value === section) {
    finishEditing()
    return
  }
  activeSection.value = section
  inputValue.value = ''
  composing = false
  void focusInput()
}

function finishEditing(): void {
  const section = activeSection.value
  activeSection.value = null
  inputValue.value = ''
  composing = false
  if (!section) return
  // 等「完成」按钮文案切回「编辑」后再还焦点，避免与卸载补丁竞争。
  void nextTick(() => focusEditButton(section))
}

function onCompositionStart(): void {
  composing = true
}

function onCompositionEnd(): void {
  composing = false
}

function onInputEnter(event: KeyboardEvent): void {
  // 组合期间回车用于确认候选词，不能提交。
  if (composing || event.isComposing) return
  event.preventDefault()
  commitInput()
}

function onInputEscape(event: KeyboardEvent): void {
  if (composing || event.isComposing) return
  event.stopPropagation()
  event.preventDefault()
  finishEditing()
}

/** 卡片级 Esc：焦点落在删除按钮等位置时也能退出编辑。 */
function onSectionEscape(event: KeyboardEvent): void {
  if (!activeSection.value) return
  if (composing || event.isComposing) return
  event.stopPropagation()
  event.preventDefault()
  finishEditing()
}

/* ------------------------------------------------------------------ */
/* 增删                                                                */
/* ------------------------------------------------------------------ */

function commitInput(): void {
  const section = activeSection.value
  if (!section) return

  const value = inputValue.value.trim()
  if (!value) return

  const list = section === 'labels' ? labels.value : relations.value
  if (list.includes(value)) {
    flashDuplicate(section, value)
    return
  }

  if (section === 'labels') {
    labels.value = [...list, value]
    emitPatch({ labels: [...labels.value] })
  } else {
    relations.value = [...list, value]
    emitPatch({ relation_types: [...relations.value] })
  }

  inputValue.value = ''
  // 点「＋」时焦点会落到按钮上，提交后拉回输入框便于连续录入。
  void focusInput()
}

function removeItem(section: DictionarySection, value: string): void {
  if (section === 'labels') {
    labels.value = labels.value.filter((item) => item !== value)
    emitPatch({ labels: [...labels.value] })
  } else {
    relations.value = relations.value.filter((item) => item !== value)
    emitPatch({ relation_types: [...relations.value] })
  }
  // 删除按钮随列表重渲染消失，把焦点交还输入框便于连续增删。
  if (activeSection.value === section) void focusInput()
}

function flashDuplicate(section: DictionarySection, value: string): void {
  duplicate.value = { section, value }
  if (duplicateTimer) clearTimeout(duplicateTimer)
  duplicateTimer = setTimeout(() => {
    duplicate.value = null
    duplicateTimer = null
  }, 900)
}

function clearDuplicate(): void {
  if (duplicateTimer) {
    clearTimeout(duplicateTimer)
    duplicateTimer = null
  }
  duplicate.value = null
}

function isDuplicate(section: DictionarySection, value: string): boolean {
  return duplicate.value?.section === section && duplicate.value.value === value
}

function chipStyle(section: DictionarySection, value: string): Record<string, string> {
  return {
    background:
      section === 'labels'
        ? labelColor(value, labels.value)
        : relationColor(value, relations.value),
  }
}

onBeforeUnmount(() => {
  clearDuplicate()
})
</script>

<template>
  <section
    class="panel dict-panel"
    aria-label="标签与关系"
    @keydown.esc="onSectionEscape"
  >
    <header class="panel-head">
      <h2 class="panel-title">
        标签与关系
        <span class="panel-title-cn">Dictionary</span>
      </h2>

      <div class="dict-status">
        <!-- live region 只承载状态文本，「重试」是可交互控件，必须放在其外。 -->
        <span class="dict-status-live" role="status" aria-live="polite">
          <span v-if="status === 'saving'" class="dict-status-text is-saving">保存中…</span>
          <span v-else-if="status === 'saved'" class="dict-status-text is-saved">已保存</span>
          <span v-else-if="status === 'error'" class="dict-status-text is-error">保存失败</span>
        </span>
        <button
          v-if="status === 'error' && lastPatch"
          type="button"
          class="dict-retry"
          title="重新提交最近一次修改"
          @click="retrySave"
        >
          重试
        </button>
      </div>
    </header>

    <div class="panel-body">
      <!-- 实体标签 -->
      <section class="dict-section">
        <div class="dict-section-head">
          <div class="dict-section-title">
            <h3 class="dict-section-name">实体标签</h3>
            <span class="dict-count">{{ labels.length }} 个</span>
          </div>
          <button
            ref="labelsEditBtn"
            type="button"
            class="dict-edit-btn"
            :aria-expanded="isEditingLabels"
            aria-controls="dict-labels-chips"
            @click="toggleSection('labels')"
          >
            {{ isEditingLabels ? '完成' : '编辑' }}
          </button>
        </div>

        <div id="dict-labels-chips" class="dict-chip-row">
          <span
            v-for="label in labels"
            :key="label"
            class="dict-chip"
            :class="{ 'is-duplicate': isDuplicate('labels', label) }"
            :style="chipStyle('labels', label)"
            :title="label"
          >
            <span class="dict-chip-text">{{ label }}</span>
            <button
              v-if="isEditingLabels"
              type="button"
              class="dict-chip-remove"
              :aria-label="`删除标签 ${label}`"
              :title="`删除标签 ${label}`"
              @click="removeItem('labels', label)"
            >
              ×
            </button>
          </span>
          <span v-if="labels.length === 0" class="dict-empty">尚未配置实体标签</span>
        </div>

        <div v-if="isEditingLabels" class="dict-add-row">
          <input
            ref="labelsInputEl"
            v-model="inputValue"
            class="mx-input dict-input"
            type="text"
            maxlength="200"
            :placeholder="inputPlaceholder"
            :aria-label="inputAriaLabel"
            :aria-invalid="Boolean(duplicateMessage)"
            :aria-describedby="duplicateMessage ? 'dict-labels-dup' : undefined"
            autocomplete="off"
            @keydown.enter="onInputEnter"
            @keydown.esc="onInputEscape"
            @compositionstart="onCompositionStart"
            @compositionend="onCompositionEnd"
          />
          <button
            type="button"
            class="mx-btn dict-add-btn"
            :aria-label="inputAriaLabel"
            title="添加"
            @click="commitInput"
          >
            ＋
          </button>
        </div>
        <p
          v-if="duplicateMessage"
          id="dict-labels-dup"
          class="dict-duplicate-hint"
          role="status"
        >
          {{ duplicateMessage }}
        </p>
      </section>

      <!-- 关系类型 -->
      <section class="dict-section">
        <div class="dict-section-head">
          <div class="dict-section-title">
            <h3 class="dict-section-name">关系类型</h3>
            <span class="dict-count">{{ relations.length }} 种</span>
          </div>
          <button
            ref="relationsEditBtn"
            type="button"
            class="dict-edit-btn"
            :aria-expanded="isEditingRelations"
            aria-controls="dict-relations-chips"
            @click="toggleSection('relation_types')"
          >
            {{ isEditingRelations ? '完成' : '编辑' }}
          </button>
        </div>

        <div id="dict-relations-chips" class="dict-chip-row">
          <span
            v-for="type in relations"
            :key="type"
            class="dict-chip is-relation"
            :class="{ 'is-duplicate': isDuplicate('relation_types', type) }"
            :style="chipStyle('relation_types', type)"
            :title="type"
          >
            <span class="dict-chip-text">{{ type }}</span>
            <button
              v-if="isEditingRelations"
              type="button"
              class="dict-chip-remove"
              :aria-label="`删除关系 ${type}`"
              :title="`删除关系 ${type}`"
              @click="removeItem('relation_types', type)"
            >
              ×
            </button>
          </span>
          <span v-if="relations.length === 0" class="dict-empty">尚未配置关系类型</span>
        </div>

        <div v-if="isEditingRelations" class="dict-add-row">
          <input
            ref="relationsInputEl"
            v-model="inputValue"
            class="mx-input dict-input"
            type="text"
            maxlength="200"
            :placeholder="inputPlaceholder"
            :aria-label="inputAriaLabel"
            :aria-invalid="Boolean(duplicateMessage)"
            :aria-describedby="duplicateMessage ? 'dict-relations-dup' : undefined"
            autocomplete="off"
            @keydown.enter="onInputEnter"
            @keydown.esc="onInputEscape"
            @compositionstart="onCompositionStart"
            @compositionend="onCompositionEnd"
          />
          <button
            type="button"
            class="mx-btn dict-add-btn"
            :aria-label="inputAriaLabel"
            title="添加"
            @click="commitInput"
          >
            ＋
          </button>
        </div>
        <p
          v-if="duplicateMessage"
          id="dict-relations-dup"
          class="dict-duplicate-hint"
          role="status"
        >
          {{ duplicateMessage }}
        </p>
      </section>
    </div>
  </section>
</template>

<style scoped>
/* ---------- 头部状态 ---------- */
.dict-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  min-height: 16px;
}

/* live region 与「重试」按钮分离，文本区域自身保持行内布局。 */
.dict-status-live {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 16px;
}

.dict-status-text {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  font-weight: 500;
  line-height: 1.2;
  white-space: nowrap;
  color: var(--ink-4);
}

.dict-status-text::before {
  content: '';
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  opacity: .8;
}

.dict-status-text.is-saving {
  color: var(--ink-3);
}

.dict-status-text.is-saved {
  color: var(--success);
}

.dict-status-text.is-error {
  color: var(--danger);
}

.dict-retry {
  flex-shrink: 0;
  height: 18px;
  padding: 0 6px;
  border: 1px solid rgba(181, 64, 58, .28);
  border-radius: 999px;
  background: var(--danger-bg);
  color: var(--danger);
  font-size: 10px;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
  transition:
    background-color 160ms var(--ease-out),
    border-color 160ms var(--ease-out);
}

.dict-retry:hover {
  background: #F5DFDC;
  border-color: rgba(181, 64, 58, .5);
}

/* ---------- 分区 ---------- */
.dict-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.dict-section + .dict-section {
  padding-top: 9px;
  border-top: 1px dashed var(--line);
}

.dict-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.dict-section-title {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}

.dict-section-name {
  margin: 0;
  font-size: 11.5px;
  font-weight: 600;
  line-height: 1.2;
  color: var(--ink-2);
}

.dict-count {
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 400;
  font-variant-numeric: tabular-nums;
  color: var(--ink-4);
  white-space: nowrap;
}

.dict-edit-btn {
  flex-shrink: 0;
  height: 22px;
  padding: 0 7px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--ink-3);
  font-size: 10.5px;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
  transition:
    background-color 160ms var(--ease-out),
    border-color 160ms var(--ease-out),
    color 160ms var(--ease-out);
}

.dict-edit-btn:hover {
  background: var(--surface-sunken);
  border-color: var(--line);
  color: var(--ink);
}

.dict-edit-btn[aria-expanded='true'] {
  background: var(--signal-soft);
  border-color: transparent;
  color: var(--signal-deep);
}

/* ---------- 标签块 ---------- */
/* 标签很多时在分区内部滚动，避免把左侧栏下方的文件区挤出视口。 */
.dict-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  min-width: 0;
  max-height: 112px;
  overflow-y: auto;
  padding-right: 2px;
}

.dict-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  min-height: 23px;
  padding: 3px 7px;
  border: 1px solid rgba(23, 24, 27, .16);
  border-radius: 7px;
  color: var(--ink);
  font-size: 11px;
  font-weight: 500;
  line-height: 1.25;
  transition:
    box-shadow 180ms var(--ease-out),
    border-color 180ms var(--ease-out);
}

.dict-chip.is-relation {
  color: #FFFDF9;
  border-color: rgba(23, 24, 27, .22);
}

.dict-chip.is-duplicate {
  border-color: var(--signal);
  animation: dict-chip-flash 700ms var(--ease-out);
}

@keyframes dict-chip-flash {
  0% { box-shadow: 0 0 0 0 rgba(228, 87, 46, .55); }
  40% { box-shadow: 0 0 0 3px rgba(228, 87, 46, .28); }
  100% { box-shadow: 0 0 0 0 rgba(228, 87, 46, 0); }
}

.dict-chip-text {
  min-width: 0;
  overflow-wrap: anywhere;
}

.dict-chip-remove {
  display: inline-grid;
  place-items: center;
  flex-shrink: 0;
  width: 14px;
  height: 14px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: rgba(255, 255, 255, .55);
  color: var(--ink-2);
  font-size: 11px;
  line-height: 1;
  cursor: pointer;
  transition:
    background-color 160ms var(--ease-out),
    color 160ms var(--ease-out);
}

.dict-chip-remove:hover {
  background: rgba(255, 255, 255, .9);
  color: var(--danger);
}

.dict-chip.is-relation .dict-chip-remove {
  background: rgba(255, 255, 255, .18);
  color: rgba(255, 253, 249, .9);
}

.dict-chip.is-relation .dict-chip-remove:hover {
  background: rgba(255, 255, 255, .35);
  color: #FFFDF9;
}

.dict-empty {
  padding: 2px 0;
  font-size: 10.5px;
  line-height: 1.4;
  color: var(--ink-4);
}

/* ---------- 添加行 ---------- */
.dict-add-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.dict-add-row .dict-input {
  flex: 1 1 auto;
  width: auto;
  min-width: 0;
  height: 28px;
  padding: 0 8px;
  font-size: 11.5px;
}

.dict-add-row .dict-add-btn {
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  padding: 0;
  border-radius: var(--radius-sm);
  font-size: 15px;
  line-height: 1;
}

/* 重复项被拦截时同步输入框边框与读屏提示，避免只靠颜色闪烁传达。 */
.dict-add-row .dict-input[aria-invalid='true'] {
  border-color: var(--warning);
}

.dict-duplicate-hint {
  margin: 0;
  font-size: 10.5px;
  line-height: 1.4;
  color: var(--warning);
}

@media (prefers-reduced-motion: reduce) {
  .dict-chip.is-duplicate {
    animation: none;
    box-shadow: 0 0 0 2px rgba(228, 87, 46, .28);
  }
}
</style>

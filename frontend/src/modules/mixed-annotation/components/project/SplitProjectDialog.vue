<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { MixedFile, SplitGroup } from '../../types'

/**
 * 项目拆分弹窗：按左侧文件列表的顺序（1 基）把文件**移动**到若干新项目。
 *
 * 职责边界：
 * - 组件只维护区间草稿（起始 / 结束 / 新项目名称），不发起请求；
 * - 所有校验都在本地实时完成，与后端规则一一对应（越界、起止颠倒、行间重叠、
 *   名称为空或重复、区间含 `converting` 文件），避免用户提交后才看到 400/409；
 * - 提交由父组件执行，失败时通过 `error` 回传，在弹窗内就地展示后端中文 detail。
 *
 * 刻意不使用 `<Teleport>`：`.mx-modal` / `.mx-input` / `.mx-btn` 都依赖
 * `.mx-root` 祖先作用域，就地渲染可继承主题令牌与弹窗动效。
 */
const props = defineProps<{
  open: boolean
  /** 源项目名称，用于生成默认的新项目名（`项目名-1`）。 */
  projectName: string
  /** 当前项目文件列表，顺序与左侧文件列表完全一致。 */
  files: MixedFile[]
  /** 父组件正在提交拆分；期间锁定一切交互。 */
  busy: boolean
  /** 后端失败原因（中文 detail），弹窗内就地展示。 */
  error?: string
}>()

const emit = defineEmits<{
  'update:open': [open: boolean]
  submit: [groups: SplitGroup[]]
}>()

/** 与后端一致的上限：一次最多 50 组。 */
const MAX_GROUPS = 50
/** 新项目名称长度上限（后端校验一致）。 */
const MAX_NAME_LENGTH = 120

interface GroupRow {
  /** 稳定的行 key：输入过程中数组重排或删除都不会串行。 */
  id: number
  /** 数字输入框的原始文本：保留用户输入过程，避免 `''` 与 `0` 混淆。 */
  start: string
  end: string
  name: string
}

interface RowIssue {
  start: string
  end: string
  name: string
  /** 跨行问题（区间重叠），显示在整行下方。 */
  range: string
}

const dialogRef = ref<HTMLElement | null>(null)
const cancelRef = ref<HTMLButtonElement | null>(null)
const firstInputRef = ref<HTMLInputElement | null>(null)
let restoreFocus: HTMLElement | null = null
let rowSeed = 0

const rows = ref<GroupRow[]>([])

const FOCUSABLE =
  'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'

/** 文件总数：区间上界。 */
const total = computed(() => props.files.length)

function defaultGroupName(index: number): string {
  const base = props.projectName.trim() || '项目'
  return `${base}-${index + 1}`
}

/** 打开时重置为单行默认值：`1 .. N` → `项目名-1`。 */
function resetRows(): void {
  rowSeed += 1
  rows.value =
    total.value > 0
      ? [{ id: rowSeed, start: '1', end: String(total.value), name: defaultGroupName(0) }]
      : []
}

/** 解析数字输入：空串/非整数一律视为「未填写」，避免 `Number('') === 0` 的陷阱。 */
function parseBound(raw: string): number | null {
  const text = String(raw ?? '').trim()
  if (!text) return null
  const value = Number(text)
  return Number.isInteger(value) ? value : null
}

/** 单行的合法区间（用于计数与覆盖统计）；非法时返回 null。 */
function validRange(row: GroupRow): { start: number; end: number } | null {
  const n = total.value
  const start = parseBound(row.start)
  const end = parseBound(row.end)
  if (start === null || end === null) return null
  if (start < 1 || end < 1 || start > n || end > n || start > end) return null
  return { start, end }
}

/** 逐行校验：字段错误就地提示，跨行错误（重叠）落在 `range`。 */
const rowIssues = computed<RowIssue[]>(() => {
  const n = total.value
  const issues: RowIssue[] = rows.value.map(() => ({
    start: '',
    end: '',
    name: '',
    range: '',
  }))

  rows.value.forEach((row, index) => {
    const issue = issues[index]
    const start = parseBound(row.start)
    const end = parseBound(row.end)

    if (start === null) issue.start = '请填写整数'
    else if (start < 1) issue.start = '不能小于 1'
    else if (start > n) issue.start = `不能大于 ${n}`

    if (end === null) issue.end = '请填写整数'
    else if (end < 1) issue.end = '不能小于 1'
    else if (end > n) issue.end = `不能大于 ${n}`

    if (start !== null && end !== null && start > end && end >= 1) {
      issue.end = '结束不能小于起始'
    }

    const name = row.name.trim()
    if (!name) issue.name = '请填写新项目名称'
    else if (name.length > MAX_NAME_LENGTH) {
      issue.name = `名称不能超过 ${MAX_NAME_LENGTH} 字`
    }
  })

  // 名称重复：两行都标红，避免用户只改其中一行仍被拦截。
  const nameIndex = new Map<string, number>()
  rows.value.forEach((row, index) => {
    const name = row.name.trim()
    if (!name) return
    const first = nameIndex.get(name)
    if (first === undefined) {
      nameIndex.set(name, index)
      return
    }
    if (!issues[index].name) issues[index].name = `与第 ${first + 1} 组重名`
    if (!issues[first].name) issues[first].name = `与第 ${index + 1} 组重名`
  })

  // 区间重叠：端点相同也算重叠（与后端一致）。
  for (let left = 0; left < rows.value.length; left += 1) {
    const leftRange = validRange(rows.value[left])
    if (!leftRange) continue
    for (let right = left + 1; right < rows.value.length; right += 1) {
      const rightRange = validRange(rows.value[right])
      if (!rightRange) continue
      if (leftRange.start <= rightRange.end && rightRange.start <= leftRange.end) {
        if (!issues[left].range) issues[left].range = `与第 ${right + 1} 组区间重叠`
        if (!issues[right].range) issues[right].range = `与第 ${left + 1} 组区间重叠`
      }
    }
  }

  return issues
})

const hasRowIssue = computed(() =>
  rowIssues.value.some(
    (issue) => Boolean(issue.start || issue.end || issue.name || issue.range),
  ),
)

/** 已被合法区间覆盖的文件序号（1 基）。 */
const coveredIndexes = computed<Set<number>>(() => {
  const covered = new Set<number>()
  for (const row of rows.value) {
    const range = validRange(row)
    if (!range) continue
    for (let index = range.start; index <= range.end; index += 1) covered.add(index)
  }
  return covered
})

const assignedCount = computed(() => coveredIndexes.value.size)
const unassignedCount = computed(() => Math.max(0, total.value - assignedCount.value))
const coversAll = computed(() => total.value > 0 && unassignedCount.value === 0)

/** 选中区间内正在转换的文件名：转换中移动目录会损坏产物，必须拦截。 */
const convertingFiles = computed<string[]>(() => {
  const names: string[] = []
  const seen = new Set<string>()
  for (const index of coveredIndexes.value) {
    const file = props.files[index - 1]
    if (!file || file.status !== 'converting') continue
    if (seen.has(file.name)) continue
    seen.add(file.name)
    names.push(file.name)
  }
  return names
})

const canSubmit = computed(
  () =>
    !props.busy &&
    rows.value.length > 0 &&
    !hasRowIssue.value &&
    convertingFiles.value.length === 0,
)

function rowFileCount(index: number): number {
  const row = rows.value[index]
  if (!row) return 0
  const range = validRange(row)
  return range ? range.end - range.start + 1 : 0
}

/** 区间首尾文件名预览：让用户确认序号确实对应左侧列表里的文件。 */
function rowPreview(index: number): string {
  const row = rows.value[index]
  if (!row) return ''
  const range = validRange(row)
  if (!range) return ''
  const first = props.files[range.start - 1]?.name ?? ''
  const last = props.files[range.end - 1]?.name ?? ''
  if (range.start === range.end) return `第 ${range.start} 个：${first}`
  return `第 ${range.start} 个：${first} … 第 ${range.end} 个：${last}`
}

/** 只把第一行的起始输入框记作打开弹窗后的初始焦点。 */
function setRowStartRef(index: number, el: unknown): void {
  if (index === 0) firstInputRef.value = (el as HTMLInputElement | null) ?? null
}

function rowIssueMessage(index: number): string {
  const issue = rowIssues.value[index]
  if (!issue) return ''
  return [issue.start ?? '', issue.end ?? '', issue.name ?? '', issue.range ?? '']
    .map((text) => text.trim())
    .filter(Boolean)
    .join('；')
}

/* ------------------------------------------------------------------ */
/* 行增删                                                              */
/* ------------------------------------------------------------------ */

/**
 * 新行的默认区间：取第一段尚未被覆盖的文件。
 * 这样「添加一组」不会立刻制造重叠错误，用户只需按需改结束位置。
 */
function nextUncoveredRange(): { start: number; end: number } {
  const n = total.value
  const covered = coveredIndexes.value
  let start = 1
  while (start <= n && covered.has(start)) start += 1
  if (start > n) return { start: 1, end: Math.max(1, n) }

  let end = start
  while (end + 1 <= n && !covered.has(end + 1)) end += 1
  return { start, end }
}

function addRow(): void {
  if (props.busy || rows.value.length >= MAX_GROUPS) return
  const { start, end } = nextUncoveredRange()
  rowSeed += 1
  rows.value = [
    ...rows.value,
    {
      id: rowSeed,
      start: String(start),
      end: String(end),
      name: defaultGroupName(rows.value.length),
    },
  ]
}

function removeRow(index: number): void {
  if (props.busy) return
  rows.value = rows.value.filter((_, position) => position !== index)
}

function close(): void {
  if (props.busy) return
  emit('update:open', false)
}

function submit(): void {
  if (!canSubmit.value) return
  // 覆盖全部文件意味着源项目会被清空，属于不可逆的移动操作，提交前再确认一次。
  if (
    coversAll.value &&
    !window.confirm(
      '当前区间覆盖全部文件，拆分后源项目将不再包含任何文件。\n\n文件会被移动到新项目，是否继续？',
    )
  ) {
    return
  }
  const groups: SplitGroup[] = []
  for (const row of rows.value) {
    const range = validRange(row)
    const name = row.name.trim()
    if (!range || !name) return
    groups.push({ name, start: range.start, end: range.end })
  }
  if (groups.length === 0) return
  emit('submit', groups)
}

/* ------------------------------------------------------------------ */
/* 弹窗交互：打开重置、焦点归还、Esc 关闭、Tab 陷阱                     */
/* ------------------------------------------------------------------ */

watch(
  () => props.open,
  async (open) => {
    if (!open) {
      if (restoreFocus?.isConnected) restoreFocus.focus()
      restoreFocus = null
      return
    }
    resetRows()
    restoreFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    firstInputRef.value?.focus()
    firstInputRef.value?.select()
  },
)

function onKeydown(event: KeyboardEvent): void {
  if (!props.open) return

  if (event.key === 'Escape') {
    close()
    return
  }

  // 弹窗打开期间屏蔽全局 Ctrl+S，避免在背景触发标注保存。
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault()
    return
  }

  if (event.key !== 'Tab' || !dialogRef.value) return
  const focusable = dialogRef.value.querySelectorAll<HTMLElement>(FOCUSABLE)
  if (focusable.length === 0) {
    event.preventDefault()
    dialogRef.value.focus()
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

// 捕获阶段监听：不依赖与工作区全局快捷键的注册顺序。
onMounted(() => window.addEventListener('keydown', onKeydown, true))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown, true))
</script>

<template>
  <div v-if="open" class="mx-modal-backdrop" @click.self="close">
    <section
      ref="dialogRef"
      class="mx-modal spd-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="spd-title"
      aria-describedby="spd-desc"
      tabindex="-1"
    >
      <header class="spd-head">
        <div class="spd-head-text">
          <h2 id="spd-title" class="spd-title">拆分项目</h2>
          <p id="spd-desc" class="spd-desc">
            按左侧文件列表的顺序划分区间，把文件移动到新项目；序号从 1 开始，未分配的文件留在源项目。
          </p>
        </div>
        <button
          type="button"
          class="spd-close"
          aria-label="关闭"
          :disabled="busy"
          @click="close"
        >
          ×
        </button>
      </header>

      <div class="spd-body">
        <div class="spd-summary" role="status" aria-live="polite">
          <span class="spd-summary-item">
            项目「{{ projectName }}」共 <strong>{{ total }}</strong> 个文件
          </span>
          <span class="spd-summary-item">
            已分配 <strong>{{ assignedCount }}</strong> · 未分配
            <strong>{{ unassignedCount }}</strong>
          </span>
        </div>

        <div class="spd-rows">
          <div v-for="(row, index) in rows" :key="row.id" class="spd-row">
            <div class="spd-row-head">
              <span class="spd-row-index">第 {{ index + 1 }} 组</span>
              <span class="spd-row-count">{{ rowFileCount(index) }} 个文件</span>
              <button
                type="button"
                class="spd-row-remove"
                :disabled="busy"
                :aria-label="`删除第 ${index + 1} 组`"
                @click="removeRow(index)"
              >
                删除
              </button>
            </div>

            <div class="spd-row-fields">
              <label class="spd-field spd-field--num">
                <span class="spd-field-label">起始</span>
                <input
                  :ref="(el) => setRowStartRef(index, el)"
                  v-model="row.start"
                  class="mx-input"
                  type="number"
                  min="1"
                  :max="total"
                  step="1"
                  :disabled="busy"
                  :aria-invalid="Boolean(rowIssues[index]?.start)"
                />
              </label>
              <label class="spd-field spd-field--num">
                <span class="spd-field-label">结束</span>
                <input
                  v-model="row.end"
                  class="mx-input"
                  type="number"
                  min="1"
                  :max="total"
                  step="1"
                  :disabled="busy"
                  :aria-invalid="Boolean(rowIssues[index]?.end)"
                />
              </label>
              <label class="spd-field spd-field--name">
                <span class="spd-field-label">新项目名称</span>
                <input
                  v-model="row.name"
                  class="mx-input"
                  type="text"
                  :maxlength="MAX_NAME_LENGTH"
                  placeholder="例如：国标3-A"
                  :disabled="busy"
                  :aria-invalid="Boolean(rowIssues[index]?.name)"
                />
              </label>
            </div>

            <p v-if="rowPreview(index)" class="spd-row-preview">
              {{ rowPreview(index) }}
            </p>

            <p v-if="rowIssueMessage(index)" class="spd-row-error" role="alert">
              {{ rowIssueMessage(index) }}
            </p>
          </div>
        </div>

        <button
          type="button"
          class="spd-add"
          :disabled="busy || rows.length >= MAX_GROUPS"
          @click="addRow"
        >
          ＋ 添加一组
        </button>

        <p v-if="coversAll" class="spd-warning" role="status">
          区间覆盖全部文件，拆分后源项目将不再包含任何文件。
        </p>
        <p v-if="convertingFiles.length > 0" class="spd-inline-error" role="alert">
          所选区间含正在转换的文件：{{ convertingFiles.join('、') }}。请等待转换完成或调整区间。
        </p>
      </div>

      <p v-if="error" class="spd-error" role="alert">{{ error }}</p>

      <footer class="spd-actions">
        <span class="spd-actions-hint">文件为移动而非复制，源项目会保留</span>
        <button
          ref="cancelRef"
          type="button"
          class="mx-btn btn-ghost"
          :disabled="busy"
          @click="close"
        >
          取消
        </button>
        <button
          type="button"
          class="mx-btn mx-btn-primary"
          :disabled="!canSubmit"
          @click="submit"
        >
          {{ busy ? '拆分中…' : `开始拆分（${rows.length} 组）` }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.spd-dialog {
  width: min(620px, 100%);
}

.spd-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  padding: 16px 18px 10px;
}

.spd-head-text {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}

.spd-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink);
}

.spd-desc {
  margin: 0;
  font-size: 11px;
  line-height: 1.6;
  color: var(--ink-4);
}

.spd-close {
  display: grid;
  place-items: center;
  flex-shrink: 0;
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

.spd-close:hover:not(:disabled) {
  background: var(--surface-sunken);
  color: var(--ink-2);
}

.spd-close:disabled {
  opacity: .45;
  cursor: not-allowed;
}

.spd-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 2px 18px 16px;
  min-width: 0;
}

/* 汇总条：始终可见的文件总数与分配情况 */
.spd-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface-sunken);
  font-size: 11px;
  color: var(--ink-3);
}

.spd-summary-item {
  min-width: 0;
}

.spd-summary strong {
  font-family: var(--font-mono);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--ink);
}

.spd-rows {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 320px;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 2px;
}

.spd-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 9px 10px 10px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface-raised);
}

.spd-row-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.spd-row-index {
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-2);
}

.spd-row-count {
  font-family: var(--font-mono);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  color: var(--ink-4);
}

.spd-row-remove {
  height: 22px;
  margin-left: auto;
  padding: 0 7px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--ink-4);
  font-size: 10.5px;
  cursor: pointer;
  transition:
    background-color 160ms var(--ease-out),
    border-color 160ms var(--ease-out),
    color 160ms var(--ease-out);
}

.spd-row-remove:hover:not(:disabled) {
  border-color: rgba(181, 64, 58, .28);
  background: var(--danger-bg);
  color: var(--danger);
}

.spd-row-remove:disabled {
  opacity: .45;
  cursor: not-allowed;
}

/* 起始/结束窄列 + 名称弹性列：窄屏自动换行，不做横向滚动 */
.spd-row-fields {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}

.spd-field {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.spd-field--num {
  flex: 0 0 84px;
}

.spd-field--name {
  flex: 1 1 160px;
}

.spd-field-label {
  font-size: 10px;
  font-weight: 500;
  color: var(--ink-4);
}

.spd-field .mx-input {
  height: 30px;
  font-size: 12px;
}

.spd-field .mx-input[aria-invalid='true'] {
  border-color: var(--warning);
}

.spd-row-preview {
  margin: 0;
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--ink-4);
  overflow-wrap: anywhere;
}

.spd-row-error {
  margin: 0;
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--warning);
}

.spd-add {
  align-self: flex-start;
  height: 28px;
  padding: 0 10px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius);
  background: transparent;
  color: var(--ink-3);
  font-size: 11.5px;
  cursor: pointer;
  transition:
    border-color 160ms var(--ease-out),
    color 160ms var(--ease-out);
}

.spd-add:hover:not(:disabled) {
  border-color: var(--signal);
  color: var(--signal-deep);
}

.spd-add:disabled {
  opacity: .45;
  cursor: not-allowed;
}

.spd-warning {
  margin: 0;
  padding: 7px 10px;
  border: 1px solid rgba(169, 118, 30, .3);
  border-radius: var(--radius);
  background: var(--warning-bg, #FAF2E1);
  color: var(--warning);
  font-size: 11px;
  line-height: 1.5;
}

.spd-inline-error {
  margin: 0;
  padding: 7px 10px;
  border: 1px solid rgba(181, 64, 58, .22);
  border-radius: var(--radius);
  background: var(--danger-bg);
  color: var(--danger);
  font-size: 11px;
  line-height: 1.5;
}

.spd-error {
  margin: 0;
  padding: 8px 18px;
  border-top: 1px solid rgba(181, 64, 58, .2);
  background: var(--danger-bg);
  color: var(--danger);
  font-size: 11.5px;
  line-height: 1.5;
}

.spd-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 18px 16px;
  border-top: 1px solid var(--line);
}

.spd-actions-hint {
  flex: 1 1 auto;
  min-width: 0;
  font-size: 10.5px;
  color: var(--ink-4);
}

@media (max-width: 560px) {
  .spd-row-fields {
    flex-direction: column;
  }

  .spd-field--num,
  .spd-field--name {
    flex: 1 1 auto;
  }
}
</style>

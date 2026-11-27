<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ProjectShortcutsPatch } from '../../types'
import {
  DEFAULT_SHORTCUT_COUNT,
  comboFromKeyboardEvent,
  effectiveShortcuts,
  findShortcutConflict,
  formatShortcut,
  isReservedShortcut,
  isSupportedShortcut,
  normalizeShortcut,
} from '../../utils/shortcuts'

/**
 * 项目级快捷键设置弹窗。
 *
 * 职责边界：
 * - 只维护**覆盖项草稿**（`{标签: 组合键}`）与录制态，不发起请求；
 * - 有效快捷键、来源（默认/自定义/无）与冲突都由 `utils/shortcuts` 的纯函数推导，
 *   与标注画布、字典卡片共用同一套规则，避免显示与实际生效不一致；
 * - 保留键与重复占用在录制当场就地拒绝并提示；清除覆盖后可能重新产生的冲突
 *   （例如别的标签显式占用了它的默认数字）会在行内标出并禁用保存；
 * - 提交由父组件执行：`shortcuts_set` 为全部自定义覆盖，`shortcuts_unset`
 *   为被清除的标签，服务端按增量合并，不会覆盖他人的修改。
 */
const props = defineProps<{
  open: boolean
  /** 当前项目字典里的全部标签（顺序决定默认 1–9 的分配）。 */
  labels: string[]
  /** 项目里已保存的快捷键覆盖项（只含显式设置过的标签）。 */
  shortcuts: Record<string, string>
  busy: boolean
  /** 后端失败原因（中文 detail），弹窗内就地展示。 */
  error?: string
}>()

const emit = defineEmits<{
  'update:open': [open: boolean]
  save: [payload: ProjectShortcutsPatch]
}>()

type ShortcutSource = 'default' | 'custom' | 'none'

interface ShortcutRow {
  label: string
  index: number
  combo: string
  source: ShortcutSource
}

const dialogRef = ref<HTMLElement | null>(null)
const cancelRef = ref<HTMLButtonElement | null>(null)
let restoreFocus: HTMLElement | null = null

const FOCUSABLE =
  'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'

/** 覆盖项草稿：录制/清除都只改这里，保存时才提交。 */
const draft = ref<Record<string, string>>({})
/** 正在录制快捷键的标签；非空时全局按键都被录制流程接管。 */
const recordingLabel = ref<string | null>(null)
/** 录制过程中被拒绝的原因（保留键 / 已占用），按标签就地展示。 */
const recordErrors = ref<Record<string, string>>({})

/** 弹窗打开时的原始覆盖项：用于计算增量与「是否有改动」。 */
const original = computed<Record<string, string>>(() => {
  const result: Record<string, string> = {}
  for (const label of props.labels) {
    const combo = normalizeShortcut(props.shortcuts?.[label])
    // 保留键（如固定给「图片／表格标注」的 F3）不再作为标签快捷键展示。
    if (combo && !isReservedShortcut(combo)) result[label] = combo
  }
  return result
})

/** 合并默认规则与覆盖项后的有效快捷键。 */
const effective = computed(() => effectiveShortcuts(props.labels, draft.value))

/** 有效快捷键中的重复占用（同一组合键被多个标签使用）。 */
const conflicts = computed(() => findShortcutConflict(effective.value))

/** 标签 → 冲突描述，供行内提示。 */
const conflictMessages = computed<Record<string, string>>(() => {
  const map: Record<string, string> = {}
  for (const conflict of conflicts.value) {
    const text = `「${formatShortcut(conflict.combo)}」被 ${conflict.labels
      .map((label) => `「${label}」`)
      .join('、')} 同时占用`
    for (const label of conflict.labels) map[label] = text
  }
  return map
})

const rows = computed<ShortcutRow[]>(() =>
  props.labels.map((label, index) => {
    const combo = effective.value[label] ?? ''
    const source: ShortcutSource = draft.value[label]
      ? 'custom'
      : combo
        ? 'default'
        : 'none'
    return { label, index, combo, source }
  }),
)

const hasConflict = computed(() => conflicts.value.length > 0)
/**
 * 录制被拒绝（保留键 / 已占用）只做就地提示，不会写进草稿，
 * 因此不阻断保存；真正阻断保存的是「清除覆盖项后重新产生的冲突」。
 * 没有任何改动时也禁用保存，避免发出空 PATCH。
 */
const canSave = computed(
  () => !props.busy && !hasConflict.value && changeCount.value > 0,
)

/** 本次提交的增量：只包含真正变化的覆盖项。 */
const pending = computed<{ set: Record<string, string>; unset: string[] }>(() => {
  const set: Record<string, string> = {}
  for (const [label, raw] of Object.entries(draft.value)) {
    const combo = normalizeShortcut(raw)
    if (!combo) continue
    if (original.value[label] === combo) continue
    set[label] = combo
  }

  const unset: string[] = []
  const known = new Set(props.labels)
  for (const label of Object.keys(original.value)) {
    if (!known.has(label)) continue
    if (!normalizeShortcut(draft.value[label])) unset.push(label)
  }
  return { set, unset }
})

const changeCount = computed(
  () => Object.keys(pending.value.set).length + pending.value.unset.length,
)

/* ------------------------------------------------------------------ */
/* 草稿重置                                                            */
/* ------------------------------------------------------------------ */

function resetDraft(): void {
  draft.value = { ...original.value }
  recordingLabel.value = null
  recordErrors.value = {}
}

watch(
  () => props.open,
  async (open) => {
    if (!open) {
      recordingLabel.value = null
      if (restoreFocus?.isConnected) restoreFocus.focus()
      restoreFocus = null
      return
    }
    resetDraft()
    restoreFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    // 没有可录制的标签时，焦点落到「取消」而不是弹窗本体。
    ;(dialogRef.value?.querySelector<HTMLElement>('.ssd-record') ?? cancelRef.value)?.focus()
  },
)

/* ------------------------------------------------------------------ */
/* 录制                                                                */
/* ------------------------------------------------------------------ */

function setRecordError(label: string, message: string): void {
  recordErrors.value = { ...recordErrors.value, [label]: message }
}

function clearRecordError(label: string): void {
  if (!recordErrors.value[label]) return
  const next = { ...recordErrors.value }
  delete next[label]
  recordErrors.value = next
}

function startRecording(label: string): void {
  if (props.busy) return
  recordingLabel.value = label
  clearRecordError(label)
}

function stopRecording(): void {
  const label = recordingLabel.value
  recordingLabel.value = null
  // 取消录制时清掉上一次被拒绝的提示：草稿没有变化，提示不应继续常驻。
  if (label) clearRecordError(label)
}

/** 录制态下的按键处理：下一次按键立即绑定，Esc 取消。 */
function handleRecordingKey(event: KeyboardEvent): void {
  const label = recordingLabel.value
  if (!label) return

  // 录制期间吞掉一切按键，避免触发背景的标注快捷键或弹窗自身的 Esc/Tab 逻辑。
  // stopImmediatePropagation 同时挡住同一节点上更晚注册的全局监听器。
  event.preventDefault()
  event.stopPropagation()
  event.stopImmediatePropagation()

  if (event.isComposing) return
  if (event.key === 'Escape') {
    stopRecording()
    return
  }

  const combo = comboFromKeyboardEvent(event)
  // 纯修饰键（Ctrl/Shift/…）不构成组合，继续等待真正的主键。
  if (!combo) return

  if (isReservedShortcut(combo)) {
    setRecordError(
      label,
      normalizeShortcut(combo) === 'F3'
        ? '「F3」已固定为右侧「图片／表格标注」的快捷键，已被占用，请换一个组合'
        : `「${formatShortcut(combo)}」是系统保留快捷键（撤销/保存/删除/关系等），请换一个组合`,
    )
    return
  }

  // 后端只接受单字符（字母/数字/标点）、F1–F24 与常见具名键；
  // 其余按键（Insert、多媒体键、非 ASCII）在录制阶段就拒绝，避免保存时才 400。
  if (!isSupportedShortcut(combo)) {
    setRecordError(
      label,
      `「${formatShortcut(combo)}」不支持，可用字母、数字、标点、F1–F24 或 Ctrl/Alt/Shift 组合`,
    )
    return
  }

  // 与其它标签的有效快捷键重复：当场拒绝，避免保存时才看到 409。
  const nextDraft = { ...draft.value, [label]: combo }
  const nextEffective = effectiveShortcuts(props.labels, nextDraft)
  const holder = Object.keys(nextEffective).find(
    (other) => other !== label && nextEffective[other] === combo,
  )
  if (holder) {
    setRecordError(
      label,
      `「${formatShortcut(combo)}」已被「${holder}」占用，请换一个组合`,
    )
    return
  }

  clearRecordError(label)
  draft.value = nextDraft
  recordingLabel.value = null
}

/* ------------------------------------------------------------------ */
/* 清除 / 恢复默认                                                     */
/* ------------------------------------------------------------------ */

function hasOverride(label: string): boolean {
  return Boolean(normalizeShortcut(draft.value[label]))
}

/** 标签是否本来就有默认数字快捷键（前 9 个）。 */
function hasDefaultShortcut(row: ShortcutRow): boolean {
  return row.index < DEFAULT_SHORTCUT_COUNT
}

/**
 * 删除覆盖项，回落到默认规则或「无快捷键」。
 * 对自带默认值的标签按钮文案是「恢复默认」，对第 10 个及之后的标签是「清除」。
 */
function clearOverride(label: string): void {
  if (props.busy) return
  const next = { ...draft.value }
  delete next[label]
  draft.value = next
  clearRecordError(label)
  if (recordingLabel.value === label) recordingLabel.value = null
}

/* ------------------------------------------------------------------ */
/* 提交与关闭                                                          */
/* ------------------------------------------------------------------ */

function close(): void {
  if (props.busy) return
  recordingLabel.value = null
  emit('update:open', false)
}

function submit(): void {
  if (!canSave.value || recordingLabel.value) return
  emit('save', {
    shortcuts_set: { ...pending.value.set },
    shortcuts_unset: [...pending.value.unset],
  })
}

function rowMessage(row: ShortcutRow): string {
  return recordErrors.value[row.label] || conflictMessages.value[row.label] || ''
}

function sourceLabel(row: ShortcutRow): string {
  if (row.source === 'custom') return '自定义'
  if (row.source === 'default') return '默认'
  return '无'
}

/* ------------------------------------------------------------------ */
/* 键盘与焦点                                                          */
/* ------------------------------------------------------------------ */

function onKeydown(event: KeyboardEvent): void {
  if (!props.open) return

  // 录制态优先：所有按键都交给录制流程，Esc 由它负责取消录制。
  if (recordingLabel.value) {
    handleRecordingKey(event)
    return
  }

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

// 捕获阶段监听：录制态必须早于工作区与其它弹窗的全局快捷键执行。
onMounted(() => window.addEventListener('keydown', onKeydown, true))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown, true))
</script>

<template>
  <div v-if="open" class="mx-modal-backdrop" @click.self="close">
    <section
      ref="dialogRef"
      class="mx-modal ssd-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ssd-title"
      aria-describedby="ssd-desc"
      tabindex="-1"
    >
      <header class="ssd-head">
        <div class="ssd-head-text">
          <h2 id="ssd-title" class="ssd-title">快捷键设置</h2>
          <p id="ssd-desc" class="ssd-desc">
            默认前 {{ DEFAULT_SHORTCUT_COUNT }} 个标签使用数字 1–9；自定义项优先，可覆盖任意标签（包括第
            {{ DEFAULT_SHORTCUT_COUNT + 1 }} 个之后的标签）。
          </p>
        </div>
        <button
          type="button"
          class="ssd-close"
          aria-label="关闭"
          :disabled="busy"
          @click="close"
        >
          ×
        </button>
      </header>

      <div class="ssd-body">
        <p class="ssd-tip">
          点击「录制」后直接按下目标组合（如 <kbd>q</kbd> 或 <kbd>Ctrl</kbd> + <kbd>K</kbd>），按
          <kbd>Esc</kbd> 取消录制。选中正文后按该组合即可应用标签。
          注意 <kbd>F3</kbd> 已被右侧「图片／表格标注」占用，不能设置为标签快捷键。
        </p>

        <div v-if="labels.length > 0" class="ssd-list">
          <div
            v-for="row in rows"
            :key="row.label"
            class="ssd-row"
            :class="{
              'is-recording': recordingLabel === row.label,
              'is-conflict': Boolean(conflictMessages[row.label]),
            }"
          >
            <span class="ssd-row-index" aria-hidden="true">{{ row.index + 1 }}</span>
            <span class="ssd-row-label" :title="row.label">{{ row.label }}</span>

            <span class="ssd-row-combo">
              <template v-if="recordingLabel === row.label">
                <span class="ssd-recording">
                  <span class="ssd-recording-dot" aria-hidden="true" />
                  请按下快捷键…
                </span>
              </template>
              <template v-else-if="row.combo">
                <kbd class="ssd-combo">{{ formatShortcut(row.combo) }}</kbd>
                <span class="ssd-source" :class="`is-${row.source}`">{{ sourceLabel(row) }}</span>
              </template>
              <span v-else class="ssd-source is-none">无</span>
            </span>

            <span class="ssd-row-actions">
              <button
                type="button"
                class="ssd-record"
                :class="{ 'is-active': recordingLabel === row.label }"
                :disabled="busy"
                :aria-label="`录制「${row.label}」的快捷键`"
                @click="recordingLabel === row.label ? stopRecording() : startRecording(row.label)"
              >
                {{ recordingLabel === row.label ? '取消' : '录制' }}
              </button>
              <button
                v-if="hasOverride(row.label)"
                type="button"
                class="ssd-clear"
                :disabled="busy"
                @click="clearOverride(row.label)"
              >
                {{ hasDefaultShortcut(row) ? '恢复默认' : '清除' }}
              </button>
            </span>

            <p v-if="rowMessage(row)" class="ssd-row-error" role="alert">
              {{ rowMessage(row) }}
            </p>
          </div>
        </div>
        <p v-else class="ssd-empty">项目还没有配置实体标签，先在上方字典卡片中添加标签。</p>
      </div>

      <p v-if="hasConflict" class="ssd-error" role="alert">
        有多个标签使用了同一个快捷键，请先解决冲突再保存。
      </p>
      <p v-if="error" class="ssd-error" role="alert">{{ error }}</p>

      <footer class="ssd-actions">
        <span class="ssd-actions-hint">
          {{ changeCount > 0 ? `${changeCount} 项改动待保存` : '尚未修改快捷键' }}
        </span>
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
          :disabled="!canSave || Boolean(recordingLabel)"
          @click="submit"
        >
          {{ busy ? '保存中…' : '保存快捷键' }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.ssd-dialog {
  width: min(560px, 100%);
}

.ssd-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  padding: 16px 18px 10px;
}

.ssd-head-text {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}

.ssd-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink);
}

.ssd-desc {
  margin: 0;
  font-size: 11px;
  line-height: 1.6;
  color: var(--ink-4);
}

.ssd-close {
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

.ssd-close:hover:not(:disabled) {
  background: var(--surface-sunken);
  color: var(--ink-2);
}

.ssd-close:disabled {
  opacity: .45;
  cursor: not-allowed;
}

.ssd-body {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 2px 18px 16px;
  min-width: 0;
}

.ssd-tip {
  margin: 0;
  font-size: 10.5px;
  line-height: 1.7;
  color: var(--ink-4);
}

.ssd-tip kbd {
  padding: 0 4px;
  border: 1px solid var(--line-strong);
  border-radius: 4px;
  background: var(--surface-raised);
  color: var(--ink-2);
  font-family: var(--font-mono);
  font-size: 9px;
}

/* 标签多时内部滚动，弹窗整体不撑破视口 */
.ssd-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 360px;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 2px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface-raised);
}

.ssd-row {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  transition: background-color 160ms var(--ease-out);
}

.ssd-row:hover {
  background: var(--surface-sunken);
}

.ssd-row.is-recording {
  background: var(--signal-soft);
  box-shadow: inset 0 0 0 1px rgba(228, 87, 46, .35);
}

.ssd-row.is-conflict {
  background: var(--danger-bg);
}

.ssd-row-index {
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-variant-numeric: tabular-nums;
  color: var(--ink-4);
  text-align: right;
}

.ssd-row-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--ink-2);
}

.ssd-row-combo {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.ssd-combo {
  max-width: 168px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 1px 6px;
  border: 1px solid var(--line-strong);
  border-radius: 5px;
  background: var(--surface);
  color: var(--ink-2);
  font-family: var(--font-mono);
  font-size: 9.5px;
  line-height: 1.6;
}

.ssd-source {
  flex-shrink: 0;
  padding: 0 5px;
  border-radius: 999px;
  background: rgba(23, 24, 27, .05);
  color: var(--ink-4);
  font-size: 9px;
  line-height: 1.6;
  white-space: nowrap;
}

.ssd-source.is-custom {
  background: var(--signal-soft);
  color: var(--signal-ink);
}

.ssd-source.is-default {
  background: rgba(47, 125, 91, .1);
  color: var(--success);
}

.ssd-recording {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 10.5px;
  font-weight: 600;
  color: var(--signal-ink);
  white-space: nowrap;
}

.ssd-recording-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--signal);
  animation: ssd-pulse 1s ease-in-out infinite;
}

@keyframes ssd-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: .25; }
}

.ssd-row-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.ssd-record,
.ssd-clear {
  height: 22px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface);
  color: var(--ink-3);
  font-size: 10.5px;
  line-height: 1;
  cursor: pointer;
  transition:
    background-color 160ms var(--ease-out),
    border-color 160ms var(--ease-out),
    color 160ms var(--ease-out);
}

.ssd-record:hover:not(:disabled),
.ssd-clear:hover:not(:disabled) {
  border-color: var(--line-strong);
  color: var(--ink);
}

.ssd-record.is-active {
  border-color: transparent;
  background: var(--signal);
  color: #FFFDF9;
}

.ssd-record:disabled,
.ssd-clear:disabled {
  opacity: .45;
  cursor: not-allowed;
}

/* 行内错误跨满整行：不挤压标签名与操作按钮 */
.ssd-row-error {
  grid-column: 2 / -1;
  margin: 0;
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--danger);
}

.ssd-empty {
  margin: 0;
  padding: 22px 10px;
  border: 1px dashed var(--line);
  border-radius: var(--radius);
  text-align: center;
  font-size: 11.5px;
  color: var(--ink-4);
}

.ssd-error {
  margin: 0;
  padding: 8px 18px;
  border-top: 1px solid rgba(181, 64, 58, .2);
  background: var(--danger-bg);
  color: var(--danger);
  font-size: 11.5px;
  line-height: 1.5;
}

.ssd-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 18px 16px;
  border-top: 1px solid var(--line);
}

.ssd-actions-hint {
  flex: 1 1 auto;
  min-width: 0;
  font-size: 10.5px;
  color: var(--ink-4);
}

@media (max-width: 560px) {
  .ssd-row {
    grid-template-columns: 16px minmax(0, 1fr);
  }

  .ssd-row-combo,
  .ssd-row-actions {
    grid-column: 2 / -1;
    justify-self: start;
  }
}

@media (prefers-reduced-motion: reduce) {
  .ssd-recording-dot {
    animation: none;
  }
}
</style>

<script setup lang="ts">
import { ref, watch } from 'vue'

/**
 * 显示设置与快捷键弹窗。
 * 数值输入使用本地草稿，允许用户输入“1.”等中间态，仅在合法时同步给父组件。
 */

const props = defineProps<{
  open: boolean
  fontSize: number
  lineHeight: number
  relStrokeWidth: number
  relDashed: boolean
}>()

const emit = defineEmits<{
  close: []
  'update:fontSize': [value: number]
  'update:lineHeight': [value: number]
  'update:relStrokeWidth': [value: number]
  'update:relDashed': [value: boolean]
}>()

const fontSizeDraft = ref('18')
const lineHeightDraft = ref('1.8')
const strokeWidthDraft = ref('2')

function syncDrafts(): void {
  fontSizeDraft.value = String(props.fontSize)
  lineHeightDraft.value = String(props.lineHeight)
  strokeWidthDraft.value = String(props.relStrokeWidth)
}

watch(
  () => props.open,
  (open) => {
    if (open) syncDrafts()
  },
  { immediate: true },
)

/** 从输入框读取正数，非法值不提交 */
function readPositiveNumber(raw: string): number | null {
  if (raw.trim() === '') return null
  const value = Number(raw)
  return Number.isFinite(value) && value > 0 ? value : null
}

function handleFontSizeInput(event: Event): void {
  const raw = (event.target as HTMLInputElement).value
  fontSizeDraft.value = raw
  const value = readPositiveNumber(raw)
  if (value !== null) emit('update:fontSize', value)
}

function handleLineHeightInput(event: Event): void {
  const raw = (event.target as HTMLInputElement).value
  lineHeightDraft.value = raw
  const value = readPositiveNumber(raw)
  if (value !== null) emit('update:lineHeight', value)
}

function handleStrokeWidthInput(event: Event): void {
  const raw = (event.target as HTMLInputElement).value
  strokeWidthDraft.value = raw
  const value = readPositiveNumber(raw)
  if (value !== null) emit('update:relStrokeWidth', value)
}

function resetFontSize(): void {
  if (readPositiveNumber(fontSizeDraft.value) === null) fontSizeDraft.value = String(props.fontSize)
}

function resetLineHeight(): void {
  if (readPositiveNumber(lineHeightDraft.value) === null) {
    lineHeightDraft.value = String(props.lineHeight)
  }
}

function resetStrokeWidth(): void {
  if (readPositiveNumber(strokeWidthDraft.value) === null) {
    strokeWidthDraft.value = String(props.relStrokeWidth)
  }
}

function handleDashedChange(event: Event): void {
  emit('update:relDashed', (event.target as HTMLInputElement).checked)
}

const shortcuts = [
  { action: '选择实体标签', key: '1 - 9' },
  { action: '选择关系类型', key: 'Ctrl + 1-9' },
  { action: '确认 / 下一篇', key: 'Space' },
  { action: '撤销操作', key: 'Ctrl + Z' },
  { action: '删除选中标注', key: 'Delete' },
  { action: '切换文档', key: '← / →' },
]
</script>

<template>
  <div v-if="open" class="modal-overlay" @click="emit('close')">
    <div
      class="modal-content settings-modal"
      role="dialog"
      aria-modal="true"
      aria-label="显示设置与快捷键"
      @click.stop
    >
      <div class="modal-header">
        <div class="modal-heading">
          <span class="modal-eyebrow">Display / Shortcuts</span>
          <h3 class="modal-title">显示设置与快捷键</h3>
        </div>
        <button type="button" class="modal-close-btn" aria-label="关闭" @click="emit('close')">
          ×
        </button>
      </div>

      <div class="settings-grid">
        <section class="settings-group" aria-label="显示设置">
          <h4 class="settings-group-title">显示设置</h4>

          <label class="settings-row">
            <span class="settings-label">字体大小 <span class="settings-unit">px</span></span>
            <input
              type="number"
              class="input settings-number"
              min="8"
              :value="fontSizeDraft"
              @input="handleFontSizeInput"
              @blur="resetFontSize"
            />
          </label>

          <label class="settings-row">
            <span class="settings-label">行高 <span class="settings-unit">倍数</span></span>
            <input
              type="number"
              class="input settings-number"
              min="1"
              step="0.1"
              :value="lineHeightDraft"
              @input="handleLineHeightInput"
              @blur="resetLineHeight"
            />
          </label>

          <label class="settings-row">
            <span class="settings-label">关系线宽 <span class="settings-unit">px</span></span>
            <input
              type="number"
              class="input settings-number"
              min="1"
              :value="strokeWidthDraft"
              @input="handleStrokeWidthInput"
              @blur="resetStrokeWidth"
            />
          </label>

          <label class="settings-checkbox">
            <input type="checkbox" :checked="relDashed" @change="handleDashedChange" />
            <span>虚线关系连线</span>
          </label>
        </section>

        <section class="settings-shortcuts" aria-label="快捷键说明">
          <h4 class="settings-group-title">快捷键说明</h4>
          <div class="shortcut-list">
            <div v-for="shortcut in shortcuts" :key="shortcut.action" class="shortcut-item">
              <span class="shortcut-action">{{ shortcut.action }}</span>
              <kbd class="shortcut-key">{{ shortcut.key }}</kbd>
            </div>
          </div>
        </section>
      </div>

      <div class="settings-actions">
        <button type="button" class="btn btn-primary" @click="emit('close')">关闭</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ============================================================
   Ink & Signal — 显示设置弹窗
   ============================================================ */
.modal-overlay {
  --tf-raised: var(--surface-raised, #FFFFFF);
  --tf-sunken: var(--surface-sunken, #F2EEE6);
  --tf-ink: var(--ink, #17181B);
  --tf-ink-2: var(--ink-2, #3E4147);
  --tf-ink-3: var(--ink-3, #6E727A);
  --tf-ink-4: var(--ink-4, #9A9DA3);
  --tf-line: var(--line, #E2DCCF);
  --tf-signal: var(--signal, #E4572E);
  --tf-signal-deep: var(--signal-deep, #C44722);
  --tf-signal-ink: var(--signal-ink, #8E2F14);
  --tf-signal-soft: var(--signal-soft, #FBE8E1);
  --tf-mono: var(--font-mono, 'JetBrains Mono', 'Fira Code', monospace);
  --tf-display: var(--font-display, 'Instrument Serif', Georgia, serif);
  --tf-ease: var(--ease-out, cubic-bezier(.22,.61,.36,1));
  --tf-shadow-lg: var(--shadow-lg, 0 32px 80px -32px rgba(23,24,27,.3));

  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(20, 22, 25, .38);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  animation: st-fade 180ms var(--tf-ease) both;
}

.settings-modal {
  width: min(620px, 100%);
  max-width: 620px;
  max-height: calc(100vh - 48px);
  padding: 0;
  overflow-y: auto;
  border: 1px solid var(--tf-line);
  border-radius: 22px;
  background: var(--tf-raised);
  box-shadow: var(--tf-shadow-lg);
  animation: st-pop 200ms var(--tf-ease) both;
  scrollbar-width: thin;
}

/* 头部：中文标题 + Instrument Serif 英文小字 */
.modal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 22px 24px 16px;
  margin-bottom: 0;
  border-bottom: 1px solid var(--tf-line);
  background: var(--tf-raised);
}
.modal-heading {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.modal-eyebrow {
  font-family: var(--tf-display);
  font-style: italic;
  font-size: 13px;
  line-height: 1.2;
  color: var(--tf-ink-3);
  letter-spacing: .01em;
}
.modal-title {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  letter-spacing: .01em;
  color: var(--tf-ink);
}

.modal-close-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  border-radius: 9px;
  border: 1px solid var(--tf-line);
  background: transparent;
  color: var(--tf-ink-3);
  font-family: var(--font-sans, 'Geist', 'Inter', system-ui, sans-serif);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  transition:
    background-color 180ms var(--tf-ease),
    color 180ms var(--tf-ease),
    border-color 180ms var(--tf-ease);
}
.modal-close-btn:hover {
  background: var(--tf-sunken);
  border-color: var(--tf-line);
  color: var(--tf-ink);
}

/* 两列：设置 | 快捷键，中间 1px 细线 */
.settings-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}
.settings-group,
.settings-shortcuts {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 18px 24px 22px;
}
.settings-shortcuts {
  border-left: 1px solid var(--tf-line);
}
.settings-group-title {
  margin: 0 0 8px;
  font-family: var(--tf-mono);
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: var(--tf-ink-3);
}

.settings-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 9px 0;
  border-bottom: 1px solid var(--tf-line);
}
.settings-label {
  font-size: 12px;
  font-weight: 400;
  color: var(--tf-ink-2);
  white-space: nowrap;
}
.settings-unit {
  margin-left: 3px;
  font-size: 10px;
  color: var(--tf-ink-3);
}

.settings-number {
  width: 82px;
  height: 30px;
  flex-shrink: 0;
  padding: 0 8px;
  border-radius: 8px;
  border: 1px solid var(--tf-line);
  background: var(--tf-sunken);
  color: var(--tf-ink);
  font-family: var(--tf-mono);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  text-align: right;
  transition:
    border-color 180ms var(--tf-ease),
    box-shadow 180ms var(--tf-ease);
}
.settings-number:focus {
  outline: none;
  border-color: var(--tf-signal);
  box-shadow: 0 0 0 3px var(--tf-signal-soft);
}

.settings-checkbox {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 12px 0 2px;
  font-size: 12px;
  color: var(--tf-ink-2);
  cursor: pointer;
}
.settings-checkbox input[type='checkbox'] {
  width: 15px;
  height: 15px;
  margin: 0;
  accent-color: var(--tf-signal-deep);
  cursor: pointer;
}

/* 快捷键：细线行 + 等宽小胶囊 */
.shortcut-list {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.shortcut-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid var(--tf-line);
}
.shortcut-item:last-child { border-bottom: none; }
.shortcut-action {
  font-size: 12px;
  color: var(--tf-ink-2);
  min-width: 0;
}
.shortcut-key {
  flex-shrink: 0;
  padding: 2px 7px;
  border: 1px solid var(--tf-line);
  border-radius: 5px;
  background: var(--tf-sunken);
  box-shadow: inset 0 -1px 0 rgba(23,24,27,.06);
  color: var(--tf-ink-3);
  font-family: var(--tf-mono);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: .02em;
  line-height: 1.5;
  white-space: nowrap;
}

.settings-actions {
  display: flex;
  justify-content: flex-end;
  padding: 14px 24px;
  border-top: 1px solid var(--tf-line);
  background: var(--tf-raised);
}

/* 按钮：与文本页保持一致 */
.settings-modal .btn {
  height: 32px;
  padding: 0 14px;
  border-radius: 9px;
  border: 1px solid var(--tf-line);
  background: var(--tf-raised);
  color: var(--tf-ink-2);
  font-family: var(--font-sans, 'Geist', 'Inter', system-ui, sans-serif);
  font-size: 12.5px;
  font-weight: 500;
  box-shadow: none;
  cursor: pointer;
  transition:
    transform 180ms var(--tf-ease),
    background-color 180ms var(--tf-ease),
    border-color 180ms var(--tf-ease);
}
.settings-modal .btn:hover { transform: translateY(-1px); }
.settings-modal .btn:active { transform: scale(.985); }
.settings-modal .btn-primary {
  background: var(--tf-signal-deep);
  border-color: transparent;
  color: #FFFDF9;
  font-weight: 600;
}
.settings-modal .btn-primary:hover { background: var(--tf-signal-ink); }
.settings-modal :focus-visible {
  outline: 2px solid var(--tf-signal);
  outline-offset: 2px;
}

@keyframes st-fade {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes st-pop {
  from { opacity: 0; transform: scale(.985); }
  to { opacity: 1; transform: scale(1); }
}

@media (max-width: 560px) {
  .settings-grid { grid-template-columns: minmax(0, 1fr); }
  .settings-shortcuts {
    border-left: none;
    border-top: 1px solid var(--tf-line);
  }
  .modal-header { padding: 18px 18px 14px; }
  .settings-group,
  .settings-shortcuts { padding-left: 18px; padding-right: 18px; }
  .settings-actions { padding: 12px 18px; }
}

@media (prefers-reduced-motion: reduce) {
  .modal-overlay,
  .settings-modal,
  .settings-modal * {
    animation-duration: .001ms !important;
    transition-duration: .001ms !important;
  }
}
</style>

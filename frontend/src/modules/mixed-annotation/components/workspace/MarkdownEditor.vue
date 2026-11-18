<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'

/**
 * Markdown 源码编辑器。
 *
 * 编辑态由父组件持有（v-model）；编辑模式下右侧由工作区直接展示 PDF，
 * 因此这里只保留源码面板，并提供 0..1 滚动比例用于与 PDF 双向同步。
 */

const props = withDefaults(
  defineProps<{
    modelValue: string
    savedMarkdown: string
    fileId: string
    busy?: boolean
  }>(),
  {
    busy: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  apply: [markdown: string]
  /** 源码面板滚动比例，用于与 PDF 预览同步。 */
  'scroll-state': [ratio: number]
}>()

const sourceRef = ref<HTMLTextAreaElement | null>(null)
const isDirty = computed(() => props.modelValue !== props.savedMarkdown)
const characterCount = computed(() => props.modelValue.length)

let suppressScroll = false
let suppressRaf = 0

function clampRatio(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.min(1, Math.max(0, value))
}

function getScrollRatio(): number {
  const el = sourceRef.value
  if (!el) return 0
  const max = el.scrollHeight - el.clientHeight
  return max > 0 ? clampRatio(el.scrollTop / max) : 0
}

/** 由 PDF 驱动源码滚动；抑制本次滚动回传，避免双向同步互相打架。 */
function setScrollRatio(ratio: number): void {
  const el = sourceRef.value
  if (!el) return
  const max = el.scrollHeight - el.clientHeight
  if (max <= 0) return
  suppressScroll = true
  el.scrollTop = clampRatio(ratio) * max
  cancelAnimationFrame(suppressRaf)
  suppressRaf = requestAnimationFrame(() => {
    suppressScroll = false
  })
}

function handleSourceScroll(): void {
  if (suppressScroll) return
  emit('scroll-state', getScrollRatio())
}

function handleInput(event: Event): void {
  emit('update:modelValue', (event.target as HTMLTextAreaElement).value)
}

function handleReset(): void {
  if (props.busy) return
  emit('update:modelValue', props.savedMarkdown)
}

function requestApply(): void {
  if (props.busy || !isDirty.value) return
  emit('apply', props.modelValue)
}

function handleRootKeydown(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault()
    requestApply()
  }
}

function handleTextareaKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Tab' || event.shiftKey) return
  event.preventDefault()
  const textarea = event.target as HTMLTextAreaElement
  const start = textarea.selectionStart
  const end = textarea.selectionEnd
  textarea.setRangeText('  ', start, end, 'end')
  emit('update:modelValue', textarea.value)
}

onBeforeUnmount(() => {
  cancelAnimationFrame(suppressRaf)
  suppressRaf = 0
})

defineExpose({ getScrollRatio, setScrollRatio })
</script>

<template>
  <div class="markdown-editor" @keydown="handleRootKeydown">
    <section class="editor-card" aria-label="Markdown 编辑">
      <header class="editor-head">
        <div class="editor-heading">
          <span class="editor-eyebrow">Markdown · Source</span>
          <h2 class="editor-title">编辑与预览</h2>
        </div>

        <div class="editor-meta">
          <slot name="save-status" />
          <span class="meta-count">{{ characterCount }} 字符</span>
        </div>

        <div class="editor-actions">
          <button
            type="button"
            class="mx-btn btn-quiet"
            :disabled="busy || !isDirty"
            @click="handleReset"
          >
            还原
          </button>
        </div>
      </header>

      <div class="editor-panes">
        <section class="editor-pane editor-pane--source" aria-label="Markdown 源码">
          <div class="pane-head">
            <span class="pane-title">源码</span>
            <span class="pane-meta">支持表格、图片与代码块</span>
          </div>
          <textarea
            ref="sourceRef"
            class="markdown-input"
            :value="modelValue"
            spellcheck="false"
            autocomplete="off"
            autocapitalize="off"
            wrap="off"
            aria-label="Markdown 源码"
            placeholder="在此输入或粘贴 Markdown…"
            @input="handleInput"
            @scroll="handleSourceScroll"
            @keydown="handleTextareaKeydown"
          ></textarea>
        </section>
      </div>

      <footer class="editor-foot">
        <span class="foot-dot" aria-hidden="true"></span>
        <span>
          自动保存会重新生成 canonical text；若文件中已有标注，会先清空标注再保存 Markdown。
        </span>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.markdown-editor {
  --me-surface: var(--surface, #fffdf9);
  --me-raised: var(--surface-raised, #fff);
  --me-sunken: var(--surface-sunken, #f2eee6);
  --me-paper-deep: var(--paper-deep, #efebe2);
  --me-ink: var(--ink, #17181b);
  --me-ink-2: var(--ink-2, #3e4147);
  --me-ink-3: var(--ink-3, #6e727a);
  --me-ink-4: var(--ink-4, #9a9da3);
  --me-line: var(--line, #e2dccf);
  --me-line-strong: var(--line-strong, #d2caba);
  --me-signal: var(--signal, #e4572e);
  --me-signal-deep: var(--signal-deep, #c44722);
  --me-signal-soft: var(--signal-soft, #fbe8e1);
  --me-success: var(--success, #2f7d5b);
  --me-danger: var(--danger, #b5403a);
  --me-warning: var(--warning, #a9761e);
  --me-mono: var(--font-mono, 'Geist Mono', ui-monospace, Consolas, monospace);
  --me-sans: var(--font-sans, 'Geist Variable', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif);
  --me-display: var(--font-display, 'Instrument Serif', Georgia, serif);
  --me-ease: var(--ease-out, cubic-bezier(0.22, 1, 0.36, 1));
  --me-shadow-xs: var(--shadow-xs, 0 1px 2px rgba(35, 29, 19, 0.05));
  --me-shadow: var(--shadow, 0 18px 44px -28px rgba(35, 29, 19, 0.22));

  display: flex;
  flex: 1;
  min-width: 0;
  min-height: 0;
}

.editor-card {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--me-line);
  border-radius: 22px;
  background: var(--me-surface);
  box-shadow: var(--me-shadow);
  animation: me-in 280ms var(--me-ease) both;
}

.editor-head {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  padding: 14px 20px;
  border-bottom: 1px solid var(--me-line);
  background: var(--me-surface);
}

.editor-heading {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.editor-eyebrow {
  font-family: var(--me-mono);
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--me-ink-3);
}

.editor-title {
  margin: 0;
  font-family: var(--me-display);
  font-size: 22px;
  font-weight: 400;
  line-height: 1.1;
  letter-spacing: -0.01em;
  color: var(--me-ink);
}

.editor-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-left: auto;
}

.meta-count {
  font-family: var(--me-mono);
  font-size: 10px;
  color: var(--me-ink-4);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.editor-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
}

.mx-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 30px;
  padding: 0 11px;
  border: 1px solid var(--me-line);
  border-radius: 8px;
  background: var(--me-surface);
  color: var(--me-ink-2);
  font-family: inherit;
  font-size: 11.5px;
  font-weight: 500;
  line-height: 1;
  cursor: pointer;
  transition:
    background-color 180ms var(--me-ease),
    border-color 180ms var(--me-ease),
    color 180ms var(--me-ease),
    transform 180ms var(--me-ease);
}

.mx-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  border-color: var(--me-line-strong);
  background: var(--me-raised);
}

.mx-btn:active:not(:disabled) {
  transform: scale(0.985);
}

.mx-btn:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}

.btn-quiet {
  border-color: transparent;
  background: transparent;
  color: var(--me-ink-3);
}

.btn-quiet:hover:not(:disabled) {
  border-color: transparent;
  background: var(--me-paper-deep);
  color: var(--me-ink);
}

.editor-panes {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
}

.editor-pane {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.editor-pane--source {
  border-right: 0;
  background: var(--me-raised);
}

.pane-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-shrink: 0;
  padding: 9px 14px;
  border-bottom: 1px solid var(--me-line);
  background: var(--me-sunken);
}

.pane-title {
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--me-ink-2);
}

.pane-meta {
  overflow: hidden;
  font-family: var(--me-mono);
  font-size: 9px;
  color: var(--me-ink-4);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.markdown-input {
  flex: 1;
  width: 100%;
  min-height: 0;
  padding: 18px 20px 28px;
  overflow: auto;
  border: none;
  outline: none;
  resize: none;
  background: var(--me-raised);
  color: var(--me-ink-2);
  caret-color: var(--me-signal);
  font-family: var(--me-sans);
  font-size: 14px;
  line-height: 1.78;
  letter-spacing: .01em;
  tab-size: 2;
  white-space: pre;
  scrollbar-width: thin;
}

.markdown-input::placeholder {
  color: var(--me-ink-4);
}

.markdown-input::selection {
  background: rgba(228, 87, 46, 0.2);
}

.preview-state {
  display: flex;
  min-height: 100%;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 32px;
  text-align: center;
  color: var(--me-ink-3);
  font-size: 12px;
  line-height: 1.6;
}

.preview-state strong {
  font-family: var(--me-display);
  font-size: 21px;
  font-weight: 400;
  color: var(--me-ink-2);
}

.preview-state--error {
  color: var(--me-danger);
}

.preview-state--error strong {
  color: var(--me-danger);
}

.editor-foot {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  flex-shrink: 0;
  padding: 9px 20px 11px;
  border-top: 1px solid var(--me-line);
  background: var(--me-sunken);
  color: var(--me-ink-3);
  font-size: 10.5px;
  line-height: 1.55;
}

.foot-dot {
  width: 5px;
  height: 5px;
  flex-shrink: 0;
  margin-top: 5px;
  border-radius: 50%;
  background: var(--me-signal);
}

@keyframes me-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

@media (max-width: 900px) {
  .markdown-editor {
    display: block;
    overflow-y: auto;
    padding-bottom: 8px;
  }

  .editor-card {
    min-height: 78vh;
    overflow: visible;
    border-radius: 18px;
  }

  .editor-head {
    align-items: flex-start;
    padding: 14px 16px;
  }

  .editor-meta {
    margin-left: 0;
  }

  .editor-actions {
    width: 100%;
    justify-content: space-between;
  }

  .editor-panes {
    display: flex;
    flex-direction: column;
  }

  .markdown-input {
    min-height: 260px;
  }

  .editor-foot {
    padding: 10px 16px 12px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .editor-card {
    animation: none;
  }

  .mx-btn {
    transition: none;
  }
}
</style>

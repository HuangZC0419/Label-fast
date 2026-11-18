<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { FigureAnnotation, FigureDraftPayload } from '../../types'
import { figureAssetUrl } from '../../api/client'

/**
 * 图表（截图）元数据弹窗。
 *
 * 职责边界：
 * - 只负责表单与预览，不直接发请求；提交/删除由 MixedWorkspace 编排，
 *   这样上传失败时弹窗可以保留输入并展示后端 detail。
 * - 表单在打开时初始化一次；父组件重试期间不重建，避免丢失用户输入。
 */

const props = withDefaults(
  defineProps<{
    mode: 'create' | 'edit'
    fileId: string
    figure?: FigureAnnotation | null
    page: number
    bbox: number[]
    previewUrl?: string
    submitting?: boolean
    serverError?: string
  }>(),
  {
    figure: null,
    previewUrl: undefined,
    submitting: false,
    serverError: '',
  },
)

const emit = defineEmits<{
  close: []
  submit: [payload: FigureDraftPayload]
  remove: [figureId: string]
}>()

/* ============================================================
   表单初始值
   ============================================================ */

const editable = computed(() => props.mode === 'edit')
const kind = ref<FigureAnnotation['kind']>(props.figure?.kind ?? 'figure')
const caption = ref(props.figure?.caption ?? '')
const note = ref(props.figure?.note ?? '')

const localError = ref('')
const previewFailed = ref(false)
const captionInputRef = ref<HTMLInputElement | null>(null)

/* ============================================================
   展示数据
   ============================================================ */

const bboxText = computed(() =>
  props.bbox
    .map((value) => {
      const number = Number(value)
      return Number.isFinite(number) ? String(Math.round(number * 100) / 100) : '0'
    })
    .join(', '),
)

const previewSource = computed(() => {
  if (props.previewUrl) return props.previewUrl
  if (props.figure?.assetPath) {
    return figureAssetUrl(props.fileId, props.figure.assetPath) ?? ''
  }
  return ''
})

const displayError = computed(() => localError.value || props.serverError || '')
const kindText = computed(() => (kind.value === 'table' ? '表' : '图'))
const dialogTitle = computed(() =>
  editable.value ? '编辑图表标注' : '新建图表标注',
)

watch(previewSource, () => {
  previewFailed.value = false
})

/* ============================================================
   交互
   ============================================================ */

function chooseKind(next: FigureAnnotation['kind']): void {
  if (editable.value || props.submitting || kind.value === next) return
  kind.value = next
}

function handleSubmit(): void {
  if (props.submitting) return
  localError.value = ''

  if (!(Number(props.page) >= 1)) {
    localError.value = '页码不合法，无法创建图表。'
    return
  }
  if (!Array.isArray(props.bbox) || props.bbox.length !== 4) {
    localError.value = '截图范围不合法，请重新拖框。'
    return
  }

  emit('submit', {
    kind: kind.value,
    caption: caption.value.trim(),
    note: note.value.trim(),
  })
}

function requestClose(): void {
  if (props.submitting) return
  emit('close')
}

function handleBackdrop(): void {
  requestClose()
}

function requestDelete(): void {
  if (!props.figure || props.submitting) return
  emit('remove', props.figure.id)
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    requestClose()
  }
}

/* ============================================================
   生命周期
   ============================================================ */

let previousBodyOverflow = ''

onMounted(() => {
  previousBodyOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  window.addEventListener('keydown', handleKeydown)
  void nextTick(() => captionInputRef.value?.focus())
})

onBeforeUnmount(() => {
  document.body.style.overflow = previousBodyOverflow
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <Teleport to="body">
    <div class="fd-backdrop" @mousedown.self="handleBackdrop">
      <section
        class="fd-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="figure-dialog-title"
      >
        <form class="fd-form" @submit.prevent="handleSubmit">
          <header class="fd-head">
            <div class="fd-head-copy">
              <span class="fd-eyebrow">{{ editable ? 'Edit Figure' : 'New Figure' }}</span>
              <h2 id="figure-dialog-title" class="fd-title">{{ dialogTitle }}</h2>
            </div>
            <button
              type="button"
              class="fd-close"
              aria-label="关闭"
              :disabled="submitting"
              @click="requestClose"
            >
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </header>

          <div class="fd-body">
            <div class="fd-preview">
              <div class="fd-preview-frame" :class="{ 'is-missing': !previewSource || previewFailed }">
                <img
                  v-if="previewSource && !previewFailed"
                  :src="previewSource"
                  alt="截图预览"
                  @error="previewFailed = true"
                />
                <div v-else class="fd-preview-empty">
                  <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <rect x="3" y="4" width="18" height="16" rx="2" />
                    <circle cx="8.5" cy="9.5" r="1.5" />
                    <path d="m21 16-5-5L5 21" />
                  </svg>
                  <span>{{ previewFailed ? '截图资产缺失' : '暂无截图预览' }}</span>
                </div>
              </div>
              <p class="fd-preview-meta">
                第 {{ page }} 页 · bbox {{ bboxText }}
              </p>
            </div>

            <div class="fd-fields">
              <fieldset class="fd-kind" :disabled="editable || submitting">
                <legend>类型</legend>
                <div class="fd-kind-options">
                  <button
                    type="button"
                    class="fd-kind-btn"
                    :class="{ 'is-active': kind === 'figure' }"
                    :aria-pressed="kind === 'figure'"
                    @click="chooseKind('figure')"
                  >
                    图
                  </button>
                  <button
                    type="button"
                    class="fd-kind-btn"
                    :class="{ 'is-active': kind === 'table' }"
                    :aria-pressed="kind === 'table'"
                    @click="chooseKind('table')"
                  >
                    表
                  </button>
                </div>
                <span class="fd-kind-note">类型创建后不可修改</span>
              </fieldset>

              <label class="fd-field">
                <span class="fd-field-label">标题</span>
                <input
                  ref="captionInputRef"
                  v-model="caption"
                  type="text"
                  maxlength="500"
                  placeholder="例如：OD·JZ型端子结构"
                  :disabled="submitting"
                />
              </label>

              <label class="fd-field">
                <span class="fd-field-label">备注</span>
                <textarea
                  v-model="note"
                  rows="3"
                  maxlength="2000"
                  placeholder="可选，用于说明图表内容或来源"
                  :disabled="submitting"
                ></textarea>
              </label>
            </div>
          </div>

          <p v-if="displayError" class="fd-error" role="alert">{{ displayError }}</p>

          <footer class="fd-foot">
            <button
              v-if="editable"
              type="button"
              class="fd-btn fd-btn--danger"
              :disabled="submitting"
              @click="requestDelete"
            >
              删除
            </button>
            <span class="fd-spacer"></span>
            <button
              type="button"
              class="fd-btn"
              :disabled="submitting"
              @click="requestClose"
            >
              取消
            </button>
            <button
              type="submit"
              class="fd-btn fd-btn--primary"
              :disabled="submitting"
            >
              {{ submitting ? '保存中…' : `确定${kindText}` }}
            </button>
          </footer>
        </form>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.fd-backdrop {
  --fd-surface: var(--surface, #fffdf9);
  --fd-raised: var(--surface-raised, #fff);
  --fd-sunken: var(--surface-sunken, #f2eee6);
  --fd-paper: var(--paper, #f6f3ec);
  --fd-ink: var(--ink, #17181b);
  --fd-ink-2: var(--ink-2, #3e4147);
  --fd-ink-3: var(--ink-3, #6e727a);
  --fd-ink-4: var(--ink-4, #9a9da3);
  --fd-line: var(--line, #e2dccf);
  --fd-line-strong: var(--line-strong, #d2caba);
  --fd-signal: var(--signal, #e4572e);
  --fd-signal-deep: var(--signal-deep, #c44722);
  --fd-signal-soft: var(--signal-soft, #fbe8e1);
  --fd-signal-ink: var(--signal-ink, #8e2f14);
  --fd-danger: var(--danger, #b5403a);
  --fd-danger-bg: var(--danger-bg, #faecea);
  --fd-mono: var(--font-mono, 'Geist Mono', ui-monospace, Consolas, monospace);
  --fd-display: var(--font-display, 'Instrument Serif', Georgia, serif);
  --fd-ease: var(--ease-out, cubic-bezier(0.22, 1, 0.36, 1));

  position: fixed;
  inset: 0;
  z-index: 120;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(20, 22, 25, 0.42);
  backdrop-filter: blur(5px);
  -webkit-backdrop-filter: blur(5px);
  animation: fd-fade 160ms var(--fd-ease) both;
}

.fd-dialog {
  width: min(880px, 100%);
  max-height: min(90vh, 760px);
  overflow: hidden;
  border: 1px solid var(--fd-line);
  border-radius: 20px;
  background: var(--fd-surface);
  box-shadow: var(--shadow-lg, 0 28px 60px -24px rgba(35, 29, 19, 0.28));
  animation: fd-rise 200ms var(--fd-ease) both;
}

.fd-form {
  display: flex;
  flex-direction: column;
  max-height: inherit;
}

.fd-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-shrink: 0;
  padding: 16px 20px 13px;
  border-bottom: 1px solid var(--fd-line);
}

.fd-head-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.fd-eyebrow {
  font-family: var(--fd-mono);
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--fd-ink-3);
}

.fd-title {
  margin: 0;
  font-family: var(--fd-display);
  font-size: 25px;
  font-weight: 400;
  line-height: 1.15;
  color: var(--fd-ink);
}

.fd-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  padding: 0;
  border: 1px solid var(--fd-line);
  border-radius: 7px;
  background: var(--fd-surface);
  color: var(--fd-ink-3);
  cursor: pointer;
}

.fd-close:hover:not(:disabled) {
  border-color: var(--fd-line-strong);
  background: var(--fd-raised);
  color: var(--fd-ink);
}

.fd-close:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.fd-body {
  display: grid;
  grid-template-columns: minmax(0, 300px) minmax(0, 1fr);
  gap: 20px;
  min-height: 0;
  padding: 18px 20px;
  overflow: auto;
}

.fd-preview {
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-width: 0;
}

.fd-preview-frame {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 180px;
  max-height: 360px;
  overflow: hidden;
  border: 1px solid var(--fd-line);
  border-radius: 12px;
  background-color: var(--fd-sunken);
  background-image: radial-gradient(rgba(23, 24, 27, 0.045) 1px, transparent 1px);
  background-size: 12px 12px;
}

.fd-preview-frame img {
  display: block;
  max-width: 100%;
  max-height: 360px;
  object-fit: contain;
  background: #fff;
}

.fd-preview-frame.is-missing {
  border-style: dashed;
  background-image: none;
}

.fd-preview-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 24px;
  color: var(--fd-ink-4);
  font-size: 11px;
  text-align: center;
}

.fd-preview-meta {
  margin: 0;
  font-family: var(--fd-mono);
  font-size: 9.5px;
  color: var(--fd-ink-3);
  word-break: break-all;
}

.fd-fields {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.fd-kind {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0;
  padding: 0;
  border: none;
}

.fd-kind legend {
  float: left;
  margin-right: 2px;
  padding: 0;
  font-size: 11px;
  font-weight: 600;
  color: var(--fd-ink-2);
}

.fd-kind-options {
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  border-radius: 9px;
  background: var(--fd-sunken);
}

.fd-kind-btn {
  min-width: 48px;
  height: 25px;
  padding: 0 12px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--fd-ink-3);
  font-family: inherit;
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
}

.fd-kind-btn:hover:not(:disabled) {
  color: var(--fd-ink);
}

.fd-kind-btn.is-active {
  background: var(--fd-raised);
  color: var(--fd-signal-ink);
  font-weight: 600;
  box-shadow: var(--shadow-xs, 0 1px 2px rgba(35, 29, 19, 0.05));
}

.fd-kind-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.fd-kind-note {
  font-size: 9.5px;
  color: var(--fd-ink-4);
}

.fd-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.fd-field-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--fd-ink-2);
}

.fd-field input,
.fd-field textarea {
  width: 100%;
  min-width: 0;
  padding: 7px 9px;
  border: 1px solid var(--fd-line);
  border-radius: 8px;
  background: var(--fd-raised);
  color: var(--fd-ink);
  font-family: inherit;
  font-size: 12px;
  line-height: 1.5;
  outline: none;
  transition:
    border-color 160ms var(--fd-ease),
    box-shadow 160ms var(--fd-ease);
}

.fd-field textarea {
  min-height: 64px;
  resize: vertical;
}

.fd-field input:focus,
.fd-field textarea:focus {
  border-color: var(--fd-signal);
  box-shadow: 0 0 0 2px var(--fd-signal-soft);
}

.fd-field input:disabled,
.fd-field textarea:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.fd-error {
  margin: 0 20px 12px;
  padding: 8px 10px;
  border: 1px solid rgba(181, 64, 58, 0.24);
  border-radius: 8px;
  background: var(--fd-danger-bg);
  color: var(--fd-danger);
  font-size: 11.5px;
  line-height: 1.55;
}

.fd-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  padding: 13px 20px;
  border-top: 1px solid var(--fd-line);
  background: var(--fd-paper);
}

.fd-spacer {
  flex: 1;
}

.fd-btn {
  height: 32px;
  padding: 0 14px;
  border: 1px solid var(--fd-line);
  border-radius: 9px;
  background: var(--fd-surface);
  color: var(--fd-ink-2);
  font-family: inherit;
  font-size: 11.5px;
  font-weight: 500;
  line-height: 1;
  cursor: pointer;
  transition:
    background-color 160ms var(--fd-ease),
    border-color 160ms var(--fd-ease),
    color 160ms var(--fd-ease);
}

.fd-btn:hover:not(:disabled) {
  border-color: var(--fd-line-strong);
  background: var(--fd-raised);
  color: var(--fd-ink);
}

.fd-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.fd-btn--primary {
  border-color: transparent;
  background: var(--fd-signal-deep);
  color: #fffdf9;
  font-weight: 600;
}

.fd-btn--primary:hover:not(:disabled) {
  border-color: transparent;
  background: var(--fd-signal);
  color: #fffdf9;
}

.fd-btn--danger {
  border-color: rgba(181, 64, 58, 0.26);
  background: transparent;
  color: var(--fd-danger);
}

.fd-btn--danger:hover:not(:disabled) {
  border-color: rgba(181, 64, 58, 0.4);
  background: var(--fd-danger-bg);
  color: var(--fd-danger);
}

@keyframes fd-fade {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@keyframes fd-rise {
  from {
    opacity: 0;
    transform: translateY(10px) scale(0.99);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

@media (max-width: 720px) {
  .fd-backdrop {
    padding: 10px;
  }

  .fd-dialog {
    max-height: 94vh;
    border-radius: 16px;
  }

  .fd-body {
    grid-template-columns: minmax(0, 1fr);
    gap: 14px;
    padding: 14px;
  }

  .fd-preview-frame {
    min-height: 140px;
    max-height: 220px;
  }

  .fd-preview-frame img {
    max-height: 220px;
  }

  .fd-head,
  .fd-foot {
    padding-left: 14px;
    padding-right: 14px;
  }

  .fd-error {
    margin-left: 14px;
    margin-right: 14px;
  }

  .fd-kind {
    flex-wrap: wrap;
  }
}

@media (prefers-reduced-motion: reduce) {
  .fd-backdrop,
  .fd-dialog {
    animation: none;
  }

  .fd-close,
  .fd-kind-btn,
  .fd-field input,
  .fd-field textarea,
  .fd-btn {
    transition: none;
  }
}
</style>

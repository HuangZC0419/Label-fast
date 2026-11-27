<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { FigureAnnotation, FigureDraftPayload } from '../../types'
import { figureAssetUrl, recognizeFigureCaption } from '../../api/client'

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
/** 用户是否手动选过「图/表」；选过之后自动识别不再改类型。 */
const kindTouched = ref(false)

const localError = ref('')
const previewFailed = ref(false)
const previewZoomed = ref(false)
/** 放大预览图片的原始尺寸；加载完成后按视口计算显示尺寸。 */
const zoomNatural = ref<{ width: number; height: number } | null>(null)
const captionInputRef = ref<HTMLInputElement | null>(null)

/* ============================================================
   标题自动识别（截图小图 OCR）
   ============================================================ */

const ocrLoading = ref(false)
/** OCR 给出的标题建议；没有命中时为空串。 */
const ocrSuggestion = ref('')
/** 识别结果的说明文案（空 = 不展示）。 */
const ocrHint = ref('')
/** 用户是否手动改过标题；改过之后自动识别不再覆盖。 */
const captionTouched = ref(false)
let ocrToken = 0

/**
 * 把截图预览的 data URL 转成 Blob 再上传。
 * 预览本身就是 PNG data URL，不额外触发一次离屏截图。
 */
async function dataUrlToBlob(url: string): Promise<Blob> {
  const response = await fetch(url)
  return response.blob()
}

/** 发起一次小图 OCR；失败只提示手动填写，不阻塞创建。 */
async function runCaptionOcr(): Promise<void> {
  if (editable.value || props.submitting) return
  const url = props.previewUrl
  if (!url || !url.startsWith('data:image/')) return

  const token = ++ocrToken
  ocrLoading.value = true
  ocrHint.value = ''
  ocrSuggestion.value = ''

  try {
    const blob = await dataUrlToBlob(url)
    const result = await recognizeFigureCaption(props.fileId, blob)
    if (token !== ocrToken) return

    const suggestion = (result.caption || '').trim()
    if (!suggestion) {
      ocrHint.value = result.text.trim()
        ? '图中未识别到「图 X … / 表 X …」样式的标题，可手动填写'
        : '图中没有识别到文字，请手动填写'
      return
    }

    ocrSuggestion.value = suggestion
    if (!captionTouched.value && !caption.value.trim()) {
      caption.value = suggestion
      ocrHint.value = `已自动填入「${suggestion}」，可直接修改`
    } else {
      ocrHint.value = `识别到标题「${suggestion}」，可一键填入`
    }
  } catch {
    if (token === ocrToken) ocrHint.value = '自动识别暂不可用，请手动填写'
  } finally {
    if (token === ocrToken) ocrLoading.value = false
  }
}

/** 用户手动点了「填入」：覆盖当前标题。 */
function applyOcrSuggestion(): void {
  if (!ocrSuggestion.value) return
  caption.value = ocrSuggestion.value
  captionTouched.value = true
  ocrHint.value = `已填入「${ocrSuggestion.value}」，可直接修改`
}

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
  kindTouched.value = true
  kind.value = next
}

/*
 * 标题以「图」「表」开头时自动切换类型：
 * - OCR 自动填的标题（如「表1 公称尺寸范围」）会让类型直接落到「表」；
 * - 用户手动输入/粘贴的标题同理；
 * - 用户手动点过类型后（kindTouched）不再覆盖，避免抢操作。
 */
watch(caption, (value) => {
  if (editable.value || kindTouched.value) return
  const text = String(value ?? '').trim()
  if (!text) return
  if (text.startsWith('表')) kind.value = 'table'
  else if (text.startsWith('图')) kind.value = 'figure'
})

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
  // 放大预览时 Esc 先关预览，不要直接关掉整个图表弹窗。
  if (event.key === 'Escape' && previewZoomed.value) {
    event.preventDefault()
    previewZoomed.value = false
    return
  }
  if (event.key === 'Escape') {
    event.preventDefault()
    requestClose()
  }
}

function openPreviewZoom(): void {
  if (!previewSource.value || previewFailed.value) return
  zoomNatural.value = null
  previewZoomed.value = true
}

function closePreviewZoom(): void {
  previewZoomed.value = false
}

/** 加载完成后按「视口 92% 宽 / 86% 高」等比放大，小截图也能看清细节。 */
function handleZoomImageLoad(event: Event): void {
  const image = event.target as HTMLImageElement | null
  if (!image || !image.naturalWidth || !image.naturalHeight) return
  zoomNatural.value = { width: image.naturalWidth, height: image.naturalHeight }
}

const zoomImageStyle = computed<Record<string, string>>(() => {
  const natural = zoomNatural.value
  if (!natural) return {}
  const maxWidth = window.innerWidth * 0.92
  const maxHeight = window.innerHeight * 0.86
  // 最多放大 4 倍，避免把很小的截图糊成色块。
  const scale = Math.min(maxWidth / natural.width, maxHeight / natural.height, 4)
  const width = Math.max(160, Math.round(natural.width * scale))
  const style: Record<string, string> = {
    width: `${width}px`,
    height: `${Math.round((width * natural.height) / natural.width)}px`,
  }
  return style
})

/* ============================================================
   生命周期
   ============================================================ */

let previousBodyOverflow = ''

onMounted(() => {
  previousBodyOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  window.addEventListener('keydown', handleKeydown)
  void nextTick(() => captionInputRef.value?.focus())
  // 新建图表时自动识别截图里的「图 3 XXXX」标题；编辑模式不覆盖已有标题。
  if (!editable.value && props.previewUrl) void runCaptionOcr()
})

onBeforeUnmount(() => {
  ocrToken += 1
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
              <div
                class="fd-preview-frame"
                :class="{
                  'is-missing': !previewSource || previewFailed,
                  'is-zoomable': Boolean(previewSource) && !previewFailed,
                }"
                :role="previewSource && !previewFailed ? 'button' : undefined"
                :tabindex="previewSource && !previewFailed ? 0 : undefined"
                :aria-label="previewSource && !previewFailed ? '放大查看截图' : undefined"
                @click="openPreviewZoom"
                @keydown.enter.prevent="openPreviewZoom"
                @keydown.space.prevent="openPreviewZoom"
              >
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
                <span v-if="previewSource && !previewFailed" class="fd-preview-zoom">
                  点击放大
                </span>
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
                  @input="captionTouched = true"
                />
              </label>

              <!--
                截图标题自动预填：新建图表时对截图像素跑一次小图 OCR，
                命中「图 3 XXXX / 表 2 XXXX」就直接填进标题；识别失败不影响提交。
              -->
              <div
                v-if="!editable && previewUrl"
                class="fd-ocr"
                role="status"
                aria-live="polite"
              >
                <span v-if="ocrLoading" class="fd-ocr-state is-loading">
                  <span class="fd-ocr-dot" aria-hidden="true"></span>
                  正在识别截图中的标题…
                </span>
                <template v-else>
                  <span class="fd-ocr-state">{{ ocrHint }}</span>
                  <button
                    v-if="ocrSuggestion && caption !== ocrSuggestion"
                    type="button"
                    class="fd-ocr-action"
                    @click="applyOcrSuggestion"
                  >
                    填入
                  </button>
                  <button
                    v-if="ocrHint"
                    type="button"
                    class="fd-ocr-action"
                    :disabled="submitting"
                    @click="runCaptionOcr"
                  >
                    重新识别
                  </button>
                </template>
              </div>

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

      <!-- 截图放大预览：点击左侧图片打开，Esc / 点空白处 / 右上角关闭。 -->
      <div v-if="previewZoomed" class="fd-zoom" @click="closePreviewZoom">
        <div class="fd-zoom-stage">
          <img
            :src="previewSource"
            alt="截图放大预览"
            :style="zoomImageStyle"
            @load="handleZoomImageLoad"
          />
        </div>
        <button
          type="button"
          class="fd-zoom-close"
          aria-label="关闭放大预览"
          @click.stop="closePreviewZoom"
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
        <span class="fd-zoom-tip">点击任意处或按 Esc 关闭</span>
      </div>
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
  position: relative;
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

.fd-preview-frame.is-zoomable {
  cursor: zoom-in;
  transition:
    border-color 160ms var(--fd-ease),
    box-shadow 160ms var(--fd-ease);
}

.fd-preview-frame.is-zoomable:hover,
.fd-preview-frame.is-zoomable:focus-visible {
  outline: none;
  border-color: var(--fd-signal);
  box-shadow: 0 0 0 2px var(--fd-signal-soft);
}

/* 右下角的放大提示：让用户知道这张缩略图能点开。 */
.fd-preview-zoom {
  position: absolute;
  right: 8px;
  bottom: 8px;
  padding: 2px 7px;
  border-radius: 999px;
  background: rgba(23, 24, 27, 0.62);
  color: #fffdf9;
  font-size: 9.5px;
  letter-spacing: 0.02em;
  pointer-events: none;
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

/* ------------------------------------------------------------
   截图放大预览
   ------------------------------------------------------------ */
.fd-zoom {
  position: fixed;
  inset: 0;
  z-index: 160;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 28px;
  background: rgba(12, 14, 17, 0.82);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  cursor: zoom-out;
  animation: fd-fade 140ms var(--fd-ease) both;
}

.fd-zoom-stage {
  display: flex;
  align-items: center;
  justify-content: center;
  max-width: 94vw;
  max-height: 88vh;
}

.fd-zoom img {
  display: block;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 30px 80px -30px rgba(0, 0, 0, 0.72);
  cursor: zoom-out;
}

.fd-zoom-close {
  position: absolute;
  top: 18px;
  right: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border: 1px solid rgba(255, 253, 249, 0.28);
  border-radius: 50%;
  background: rgba(255, 253, 249, 0.12);
  color: #fffdf9;
  cursor: pointer;
  transition:
    background-color 160ms var(--fd-ease),
    border-color 160ms var(--fd-ease);
}

.fd-zoom-close:hover {
  border-color: rgba(255, 253, 249, 0.55);
  background: rgba(255, 253, 249, 0.22);
}

.fd-zoom-tip {
  position: absolute;
  left: 50%;
  bottom: 22px;
  transform: translateX(-50%);
  color: rgba(255, 253, 249, 0.72);
  font-size: 11px;
  letter-spacing: 0.02em;
  pointer-events: none;
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

/* 标题自动识别的状态行：弱提示 + 两个文字按钮，不抢表单主体的注意力。 */
.fd-ocr {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 10px;
  margin-top: -2px;
  padding-left: 1px;
  min-height: 16px;
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--fd-ink-3);
}

.fd-ocr-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.fd-ocr-state.is-loading {
  color: var(--fd-ink-2);
}

.fd-ocr-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--fd-signal);
  animation: fd-ocr-pulse 1.1s ease-in-out infinite;
}

@keyframes fd-ocr-pulse {
  0%,
  100% {
    opacity: 0.35;
    transform: scale(0.85);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
}

.fd-ocr-action {
  padding: 0;
  border: none;
  background: transparent;
  color: var(--fd-signal-ink);
  font-family: inherit;
  font-size: 10.5px;
  font-weight: 600;
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
}

.fd-ocr-action:hover:not(:disabled) {
  color: var(--fd-signal);
}

.fd-ocr-action:disabled {
  opacity: 0.5;
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

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type {
  AnnotationRecord,
  BlockInfo,
  FigureAnnotation,
  FigureCreatePayload,
  FigureDraftPayload,
  FigureRegionSelection,
  MixedFile,
  Project,
} from '../../types'
import type { AnnotationPayload } from '../../composables/useMarkdownAnnotation'
import {
  ApiError,
  apiFetch,
  createFigure,
  deleteFigure,
  fetchBlocks,
  fetchFigures,
  updateFigure,
} from '../../api/client'
import { normalizeBlocks } from '../../utils/blocks'
import FigureDialog from './FigureDialog.vue'
import MarkdownAnnotator from './MarkdownAnnotator.vue'
import MarkdownEditor from './MarkdownEditor.vue'
import ModeToggle from './ModeToggle.vue'
import PdfPreview from './PdfPreview.vue'
import SaveStatus from './SaveStatus.vue'
import ConfirmDialog from '../common/ConfirmDialog.vue'

/**
 * 混合标注工作区编排层。
 *
 * 单一职责：
 * - 负责“文件生命周期”（加载/转换状态/保存）；
 * - 标注画布与编辑器各自维护局部 UI 状态，互不直接依赖；
 * - PDF 只作为可折叠的原始依据，不参与 Markdown 标注数据流。
 */

interface AnnotatorApi {
  getPayload: () => AnnotationPayload
  getCanonicalText: () => string
  hasAnnotations: () => boolean
  clearAnnotations: () => void
  refreshLayout: () => Promise<void>
  /** 按 0..1 比例设置滚动位置（同步滚动用）。 */
  setScrollRatio: (ratio: number) => void
  getScrollRatio: () => number
}

/** PdfPreview 通过 defineExpose 暴露的方法。 */
interface PdfPreviewApi {
  /** bbox 为目标页坐标，page 为 1 基页码；图片模式固定传 1。 */
  captureRegion: (bbox: number[], page: number) => Promise<Blob>
  setScrollRatio: (ratio: number) => void
  getScrollRatio: () => number
}

/** MarkdownEditor 通过 defineExpose 暴露的方法。 */
interface MarkdownEditorApi {
  setScrollRatio: (ratio: number) => void
  getScrollRatio: () => number
}

interface MarkdownResponse {
  markdown?: string
  page_count?: number
}

type WorkspaceMode = 'annotate' | 'edit'

type SaveState = 'saved' | 'saving' | 'pending' | 'error'

type FigureDialogState =
  | { mode: 'create'; page: number; bbox: number[]; previewUrl?: string }
  | { mode: 'edit'; figure: FigureAnnotation }

const props = defineProps<{
  project: Project | null
  file: MixedFile | null
  labels: string[]
  relationTypes: string[]
}>()

const emit = defineEmits<{
  saved: []
  refresh: []
}>()

const mode = ref<WorkspaceMode>('annotate')
const pdfOpen = ref(false)
const isNarrow = ref(false)

const loading = ref(false)
const documentReady = ref(false)
const loadError = ref('')
const loadWarning = ref('')
const actionError = ref('')
const savedNotice = ref('')

const applying = ref(false)

/* ============================================================
   自动保存状态机
   ============================================================ */

const AUTO_SAVE_DELAY = 1200
const AUTO_SAVE_RETRY_DELAY = 5000
const AUTO_SAVE_MAX_RETRIES = 3
/** 保存请求硬超时：后端挂起时不能永久锁住切换。 */
const SAVE_TIMEOUT = 20_000

const saveState = ref<SaveState>('saved')
const saveError = ref('')
const editConsentOpen = ref(false)

let autoSaveTimer: ReturnType<typeof setTimeout> | null = null
let autoSaveRetryTimer: ReturnType<typeof setTimeout> | null = null
let autoSaveRetries = 0
/** 串行化写入：同一时刻只允许一个保存请求在途。 */
let autoSaveInFlight: Promise<void> | null = null
/** 在途期间又有新变更时置位，落盘完成后补跑一次。 */
let autoSaveQueued = false
/** 模式切换期间抑制“内容变更”误判。 */
let suppressModeSave = false
/** 标注页是否存在尚未落盘的变更。 */
let annotationDirty = false
/** 标注内容的单调修订号：用于识别“请求在途期间又发生了新标注”。 */
let annotationRevision = 0
/** 文件代际：切换文件后旧请求的 finally 不得清理新文件的在途状态。 */
let saveGeneration = 0
/** 当前保存请求的取消控制器与超时计时器。 */
let saveAbort: AbortController | null = null
let saveAbortTimer: number | null = null
/** 防止模式切换过程中的重复点击（ref 以便驱动按钮禁用态）。 */
const modeSwitching = ref(false)

const markdownSource = ref('')
const editorDraft = ref('')
const blocks = ref<BlockInfo[]>([])
const annotationRecord = ref<AnnotationRecord | null>(null)
/**
 * 图表单独保存一份引用。
 * 图表由独立接口维护，更新它时不能替换 annotationRecord，
 * 否则 MarkdownAnnotator 会重新加载标注并丢弃用户尚未保存的编辑。
 */
const figures = ref<FigureAnnotation[]>([])

const figureDialog = ref<FigureDialogState | null>(null)
const figureSubmitting = ref(false)
const figureError = ref('')

const annotatorRef = ref<AnnotatorApi | null>(null)
const editorRef = ref<MarkdownEditorApi | null>(null)
const pdfPreviewRef = ref<PdfPreviewApi | null>(null)

let loadToken = 0
let noticeTimer: ReturnType<typeof setTimeout> | null = null
let mediaQuery: MediaQueryList | null = null

const completed = computed(() => props.file?.status === 'completed')
const draftDirty = computed(() => editorDraft.value !== markdownSource.value)
const modeToggleDisabled = computed(
  () =>
    !completed.value ||
    !documentReady.value ||
    applying.value ||
    modeSwitching.value,
)
const pdfAsDrawer = computed(() => isNarrow.value)

/* ============================================================
   同步滚动（Markdown ↔ PDF）
   ============================================================ */

const SYNC_SCROLL_STORAGE_KEY = 'labelfast.syncScroll'
/** PDF.js 读取页面尺寸需要时间，打开预览后短延时再对齐一次。 */
const SYNC_ALIGN_RETRY_DELAY = 400

const syncScroll = ref(true)
/** 最近一次 Markdown 滚动比例；PDF 未挂载或页面高度未就绪时用于补偿。 */
const lastMarkdownRatio = ref(0)
let syncAlignTimer: ReturnType<typeof setTimeout> | null = null

/**
 * 仅在“并排显示 PDF”时联动。
 * 抽屉（窄屏）与关闭预览时两个视口不同时可见，联动没有意义；
 * 图片文件没有可类比的文档纵向结构，也不参与联动。
 */
const scrollSyncActive = computed(
  () =>
    syncScroll.value &&
    pdfOpen.value &&
    !pdfAsDrawer.value &&
    documentReady.value &&
    props.file?.source_type === 'pdf',
)

/* ============================================================
   Markdown / PDF 分栏宽度
   ============================================================ */

const PDF_PANEL_STORAGE_KEY = 'labelfast.pdfPanelWidth'
const PDF_PANEL_DEFAULT = 36
const PDF_PANEL_MIN = 22
const PDF_PANEL_MAX = 70

/** 百分比宽度：相对 .mw-body 的内容宽度，随窗口尺寸自动等比缩放。 */
const pdfPanelWidth = ref(PDF_PANEL_DEFAULT)
const resizingPdf = ref(false)
const bodyRef = ref<HTMLElement | null>(null)
const splitterRef = ref<HTMLElement | null>(null)

interface SplitDragState {
  pointerId: number
  startX: number
  startPercent: number
  contentWidth: number
}

let splitDrag: SplitDragState | null = null

/** 只有“并排显示”时才需要分隔条；抽屉模式沿用原逻辑。 */
const pdfInlineVisible = computed(
  () => pdfOpen.value && !pdfAsDrawer.value && documentReady.value,
)

const progressPercent = computed(() => {
  const value = Number(props.file?.progress ?? 0)
  return Math.max(0, Math.min(100, Math.round(value)))
})
const previewLabel = computed(() =>
  props.file?.source_type === 'pdf' ? 'PDF 预览' : '原图预览',
)
const statusHeading = computed(() => {
  if (!props.file) return ''
  if (props.file.status === 'failed') return '转换失败'
  if (props.file.status === 'converting') return '正在转换'
  return '等待转换'
})
const statusDescription = computed(() => {
  const file = props.file
  if (!file) return ''
  if (file.status === 'failed') {
    return file.error || '转换失败，请检查主应用与 OCR Worker 日志后重试。'
  }
  if (file.status === 'converting') {
    return [file.stage, file.message].filter(Boolean).join(' · ') || 'OCR 正在识别版面与文字，请稍候。'
  }
  return '文件已上传，转换尚未开始。刷新状态可查看最新进度。'
})

const dialogFigure = computed(() =>
  figureDialog.value?.mode === 'edit' ? figureDialog.value.figure : null,
)
const dialogPage = computed(() =>
  figureDialog.value?.mode === 'edit'
    ? figureDialog.value.figure.page
    : figureDialog.value?.page ?? 0,
)
const dialogBbox = computed(() =>
  figureDialog.value?.mode === 'edit'
    ? figureDialog.value.figure.bbox
    : figureDialog.value?.bbox ?? [],
)
const dialogPreviewUrl = computed(() =>
  figureDialog.value?.mode === 'create' ? figureDialog.value.previewUrl : undefined,
)
const dialogKey = computed(() => {
  const dialog = figureDialog.value
  if (!dialog) return ''
  return dialog.mode === 'edit'
    ? `edit:${dialog.figure.id}`
    : `create:${dialog.page}:${dialog.bbox.join(',')}`
})

/* ============================================================
   加载文件
   ============================================================ */

function emptyAnnotationRecord(): AnnotationRecord {
  return { text: '', spans: [], relations: [], paragraphs: [], figures: [] }
}

function normalizeAnnotationRecord(record: AnnotationRecord | null): AnnotationRecord {
  if (!record) return emptyAnnotationRecord()
  return {
    text: typeof record.text === 'string' ? record.text : '',
    spans: Array.isArray(record.spans) ? record.spans : [],
    relations: Array.isArray(record.relations) ? record.relations : [],
    paragraphs: Array.isArray(record.paragraphs)
      ? record.paragraphs.filter(
          (paragraph) =>
            paragraph &&
            typeof paragraph.blockId === 'string' &&
            paragraph.blockId.trim().length > 0 &&
            typeof paragraph.label === 'string' &&
            paragraph.label.trim().length > 0,
        )
      : [],
    figures: Array.isArray(record.figures) ? record.figures : [],
  }
}

/**
 * 清空文本标注（实体/关系，以及兼容后端的历史段落字段），
 * 但保留图表记录（图表由独立接口维护）。
 */
function clearedAnnotationRecord(figures: FigureAnnotation[]): AnnotationRecord {
  return { ...emptyAnnotationRecord(), figures }
}

function resetDocumentState(): void {
  documentReady.value = false
  loading.value = false
  markdownSource.value = ''
  editorDraft.value = ''
  blocks.value = []
  annotationRecord.value = null
  figures.value = []
  figureDialog.value = null
  figureSubmitting.value = false
  figureError.value = ''
  loadError.value = ''
  loadWarning.value = ''
  actionError.value = ''

  // 清空自动保存状态：中止上一文件的在途请求，避免其 finally 污染新文件状态。
  saveGeneration += 1
  abortSaveRequest()
  clearAutoSaveTimers()
  autoSaveInFlight = null
  autoSaveRetries = 0
  autoSaveQueued = false
  annotationDirty = false
  annotationRevision = 0
  saveError.value = ''
  saveState.value = 'saved'
  editConsentOpen.value = false

  clearSavedNotice()
}

function appendLoadWarning(message: string): void {
  loadWarning.value = loadWarning.value ? `${loadWarning.value} ${message}` : message
}

async function loadDocument(): Promise<void> {
  const token = ++loadToken
  resetDocumentState()

  const file = props.file
  if (!file || file.status !== 'completed') return

  loading.value = true
  const fileId = encodeURIComponent(file.id)

  try {
    // 三个请求互不依赖：并行加载可避免“先 Markdown 再标注”的串行等待。
    const [markdownResult, blocksResult, annotationsResult] = await Promise.allSettled([
      apiFetch<MarkdownResponse>(`/api/files/${fileId}/markdown`),
      fetchBlocks(file.id),
      apiFetch<AnnotationRecord>(`/api/files/${fileId}/annotations`),
    ])
    if (token !== loadToken) return

    if (markdownResult.status === 'rejected') throw markdownResult.reason
    const markdownResponse = markdownResult.value
    if (!markdownResponse || typeof markdownResponse !== 'object') {
      throw new Error('Markdown 接口返回了无效数据')
    }

    const source =
      typeof markdownResponse.markdown === 'string' ? markdownResponse.markdown : ''
    markdownSource.value = source
    editorDraft.value = source

    if (blocksResult.status === 'fulfilled') {
      blocks.value = normalizeBlocks(blocksResult.value)
    } else {
      blocks.value = []
      const notFound =
        blocksResult.reason instanceof ApiError && blocksResult.reason.status === 404
      if (!notFound) {
        appendLoadWarning('段落切块加载失败，已回退为整篇渲染。')
      }
    }

    let record: AnnotationRecord | null = null
    if (annotationsResult.status === 'fulfilled') {
      record = annotationsResult.value
    } else {
      const notFound =
        annotationsResult.reason instanceof ApiError &&
        annotationsResult.reason.status === 404
      if (!notFound) {
        appendLoadWarning('标注读取失败，已按未标注状态打开；保存前请确认当前文件没有既有标注。')
      }
    }

    const normalized = normalizeAnnotationRecord(record)
    annotationRecord.value = normalized
    figures.value = normalized.figures ?? []
    documentReady.value = true
    await nextTick()
    if (token !== loadToken) return
    annotatorRef.value?.refreshLayout()
  } catch (error) {
    if (token === loadToken) {
      loadError.value = formatError(error)
    }
  } finally {
    if (token === loadToken) loading.value = false
  }
}

watch(
  () => `${props.file?.id ?? ''}:${props.file?.status ?? ''}`,
  () => {
    mode.value = 'annotate'
    if (isNarrow.value) pdfOpen.value = false
    void loadDocument()
  },
  { immediate: true },
)

/* ============================================================
   模式与预览
   ============================================================ */

/** 纯模式切换：只改 UI 状态，不做保存与确认。 */
function applyMode(next: WorkspaceMode): void {
  suppressModeSave = true
  mode.value = next
  if (next === 'edit') {
    // 编辑模式用 PDF 取代渲染预览：桌面端直接并排打开，窄屏留给抽屉。
    pdfOpen.value = !isNarrow.value
  }
  void nextTick().then(() => {
    suppressModeSave = false
    if (mode.value === 'annotate') annotatorRef.value?.refreshLayout()
    else requestPdfAlignment()
  })
}

async function setMode(next: WorkspaceMode): Promise<void> {
  if (
    next === mode.value ||
    !completed.value ||
    !documentReady.value ||
    applying.value ||
    modeSwitching.value
  ) {
    return
  }

  modeSwitching.value = true
  try {
    // 切换模式前先落盘；失败时留在当前模式，避免在失败状态下丢草稿。
    const saved = await flushAutoSave()
    if (!saved) return
    if (next === mode.value) return

    if (next === 'edit' && annotatorRef.value?.hasAnnotations()) {
      // 只在有标注时确认一次；进入编辑后的自动保存使用 skipConfirm。
      editConsentOpen.value = true
      return
    }

    applyMode(next)
  } finally {
    modeSwitching.value = false
  }
}

/** ConfirmDialog 确认：用户接受“清空实体/关系标注”后进入编辑模式。 */
function confirmEditMode(): void {
  editConsentOpen.value = false
  if (mode.value !== 'edit') applyMode('edit')
}

/** 两种模式共用的切换入口，避免模板里重复条件表达式。 */
function toggleMode(): void {
  void setMode(mode.value === 'annotate' ? 'edit' : 'annotate')
}

function togglePdf(): void {
  if (!completed.value || !documentReady.value) return
  pdfOpen.value = !pdfOpen.value
}

function handleMediaChange(event: MediaQueryListEvent): void {
  isNarrow.value = event.matches
  if (event.matches) pdfOpen.value = false
}

/* ============================================================
   同步滚动实现
   ============================================================ */

function readStoredSyncScroll(): boolean {
  try {
    const raw = window.localStorage.getItem(SYNC_SCROLL_STORAGE_KEY)
    return raw === null ? true : raw === '1'
  } catch {
    // 隐私模式或禁用存储时退回默认开启。
    return true
  }
}

function persistSyncScroll(): void {
  try {
    window.localStorage.setItem(SYNC_SCROLL_STORAGE_KEY, syncScroll.value ? '1' : '0')
  } catch {
    // 持久化失败只影响下次打开，不阻断本次会话。
  }
}

function toggleSyncScroll(): void {
  syncScroll.value = !syncScroll.value
  persistSyncScroll()
}

function clearSyncAlignTimer(): void {
  if (syncAlignTimer) clearTimeout(syncAlignTimer)
  syncAlignTimer = null
}

/** 用 Markdown 当前比例对齐 PDF；高度未就绪时由组件内部安全跳过。 */
async function alignPdfToMarkdown(): Promise<void> {
  if (!scrollSyncActive.value) return
  await nextTick()
  if (!scrollSyncActive.value) return
  const ratio =
    mode.value === 'edit'
      ? editorRef.value?.getScrollRatio() ?? lastMarkdownRatio.value
      : annotatorRef.value?.getScrollRatio() ?? lastMarkdownRatio.value
  lastMarkdownRatio.value = ratio
  pdfPreviewRef.value?.setScrollRatio(ratio)
}

/**
 * 打开 PDF 或重新开启同步时先对齐一次，再在短延时后重试一次。
 * PDF.js 读取页面尺寸是异步的，首次调用时滚动容器可能还不够高。
 */
function requestPdfAlignment(): void {
  if (!scrollSyncActive.value) return
  clearSyncAlignTimer()
  void alignPdfToMarkdown()
  syncAlignTimer = setTimeout(() => {
    syncAlignTimer = null
    void alignPdfToMarkdown()
  }, SYNC_ALIGN_RETRY_DELAY)
}

function handleMarkdownScroll(ratio: number): void {
  // 无论是否联动都记录比例：用户关闭同步后滚动 Markdown，再开启时仍能对齐。
  lastMarkdownRatio.value = ratio
  if (!scrollSyncActive.value) return
  pdfPreviewRef.value?.setScrollRatio(ratio)
}

function handlePdfScroll(ratio: number): void {
  if (!scrollSyncActive.value) return
  if (mode.value === 'edit') editorRef.value?.setScrollRatio(ratio)
  else annotatorRef.value?.setScrollRatio(ratio)
}

watch(
  () => [
    pdfOpen.value,
    pdfAsDrawer.value,
    syncScroll.value,
    documentReady.value,
    mode.value,
  ] as const,
  () => {
    // flush: post 保证预览已挂载；PDF 页高未就绪的情况由 requestPdfAlignment 的重试兜底。
    if (scrollSyncActive.value) requestPdfAlignment()
  },
  { flush: 'post' },
)

/* ============================================================
   分栏拖动
   ============================================================ */

function clampPdfPanelWidth(value: number): number {
  if (!Number.isFinite(value)) return PDF_PANEL_DEFAULT
  return Math.min(PDF_PANEL_MAX, Math.max(PDF_PANEL_MIN, value))
}

function readStoredPdfPanelWidth(): number {
  try {
    const raw = window.localStorage.getItem(PDF_PANEL_STORAGE_KEY)
    if (!raw) return PDF_PANEL_DEFAULT
    return clampPdfPanelWidth(Number.parseFloat(raw))
  } catch {
    // 隐私模式或禁用存储时退回默认值。
    return PDF_PANEL_DEFAULT
  }
}

function persistPdfPanelWidth(): void {
  try {
    window.localStorage.setItem(
      PDF_PANEL_STORAGE_KEY,
      pdfPanelWidth.value.toFixed(2),
    )
  } catch {
    // 写入失败不影响本次会话内的宽度。
  }
}

/** 拖动的可用宽度：扣除 .mw-body 的左右内边距，与 flex-basis 百分比基准一致。 */
function measureBodyContentWidth(): number {
  const element = bodyRef.value
  if (!element) return 0
  const style = window.getComputedStyle(element)
  const padding =
    (Number.parseFloat(style.paddingLeft) || 0) +
    (Number.parseFloat(style.paddingRight) || 0)
  return Math.max(0, element.clientWidth - padding)
}

function handleSplitterPointerDown(event: PointerEvent): void {
  if (event.button !== 0 || !pdfInlineVisible.value) return
  const contentWidth = measureBodyContentWidth()
  if (!(contentWidth > 0)) return

  event.preventDefault()
  splitDrag = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startPercent: pdfPanelWidth.value,
    contentWidth,
  }
  resizingPdf.value = true
  splitterRef.value?.setPointerCapture(event.pointerId)
}

function handleSplitterPointerMove(event: PointerEvent): void {
  const drag = splitDrag
  if (!drag || event.pointerId !== drag.pointerId) return
  // 向左拖动 => 分隔条左移 => PDF 变宽。
  const deltaPercent = ((drag.startX - event.clientX) / drag.contentWidth) * 100
  pdfPanelWidth.value = clampPdfPanelWidth(drag.startPercent + deltaPercent)
}

function endSplitterDrag(event: PointerEvent): void {
  const drag = splitDrag
  if (!drag || event.pointerId !== drag.pointerId) return
  splitDrag = null
  resizingPdf.value = false
  if (splitterRef.value?.hasPointerCapture(event.pointerId)) {
    splitterRef.value.releasePointerCapture(event.pointerId)
  }
  persistPdfPanelWidth()
}

/** 捕获意外丢失（例如组件重渲染）时也必须结束拖动并保存。 */
function handleSplitterLostCapture(): void {
  if (!splitDrag) return
  splitDrag = null
  resizingPdf.value = false
  persistPdfPanelWidth()
}

function handleSplitterKeydown(event: KeyboardEvent): void {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  event.preventDefault()
  const step = event.shiftKey ? 6 : 2
  // 左箭头 = 分隔条左移 = PDF 变宽。
  const direction = event.key === 'ArrowLeft' ? step : -step
  pdfPanelWidth.value = clampPdfPanelWidth(pdfPanelWidth.value + direction)
  persistPdfPanelWidth()
}

function resetPdfPanelWidth(): void {
  pdfPanelWidth.value = PDF_PANEL_DEFAULT
  persistPdfPanelWidth()
}

/* ============================================================
   自动保存：定时器、重试与串行写入
   ============================================================ */

function clearAutoSaveTimer(): void {
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  autoSaveTimer = null
}

function clearAutoSaveRetryTimer(): void {
  if (autoSaveRetryTimer) clearTimeout(autoSaveRetryTimer)
  autoSaveRetryTimer = null
}

function clearAutoSaveTimers(): void {
  clearAutoSaveTimer()
  clearAutoSaveRetryTimer()
}

interface SaveRequest {
  signal: AbortSignal
  finish: () => void
}

/**
 * 为一次保存创建可取消、可超时的请求。
 * 切换文件时由 resetDocumentState 中止旧请求；超时后由调用方进入失败/重试流程。
 */
function beginSaveRequest(): SaveRequest {
  saveAbort?.abort()
  if (saveAbortTimer) clearTimeout(saveAbortTimer)
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), SAVE_TIMEOUT)
  saveAbort = controller
  saveAbortTimer = timer
  return {
    signal: controller.signal,
    finish: () => {
      window.clearTimeout(timer)
      if (saveAbort === controller) {
        saveAbort = null
        saveAbortTimer = null
      }
    },
  }
}

function abortSaveRequest(): void {
  saveAbort?.abort()
  saveAbort = null
  if (saveAbortTimer) {
    window.clearTimeout(saveAbortTimer)
    saveAbortTimer = null
  }
}

/** 内容变更：重置重试计数，重新开始 1.2 秒空闲倒计时。 */
function scheduleAutoSave(): void {
  clearAutoSaveTimers()
  autoSaveRetries = 0
  saveState.value = 'pending'
  saveError.value = ''
  autoSaveTimer = setTimeout(() => {
    autoSaveTimer = null
    void flushAutoSave()
  }, AUTO_SAVE_DELAY)
}

/**
 * 保存失败后 5 秒自动重试，最多 3 次。
 * `retry` 固定为失败的那次保存，避免用户切回标注模式后把 Markdown 重试成标注保存。
 */
function scheduleAutoSaveRetry(retry: () => Promise<void>): void {
  if (autoSaveRetries >= AUTO_SAVE_MAX_RETRIES) return
  clearAutoSaveRetryTimer()
  autoSaveRetryTimer = setTimeout(() => {
    autoSaveRetryTimer = null
    if (saveState.value !== 'error') return
    autoSaveRetries += 1
    saveState.value = 'pending'
    void retry()
  }, AUTO_SAVE_RETRY_DELAY)
}

/**
 * 统一串行入口：同一时刻只允许一个写入请求。
 * 在途期间的新请求合并为一次补跑，避免并发写入互相覆盖。
 */
function runAutoSave(task: () => Promise<void>): Promise<void> {
  if (autoSaveInFlight) {
    autoSaveQueued = true
    return autoSaveInFlight
  }
  const generation = saveGeneration
  const promise = (async () => {
    try {
      await task()
    } finally {
      // 文件已切换：旧请求不得清理新文件的在途状态。
      if (generation !== saveGeneration) return
      autoSaveInFlight = null
      if (autoSaveQueued) {
        autoSaveQueued = false
        // 失败态下不立即补跑，交给已有的 5 秒重试，避免连续失败时反复打后端。
        if (saveState.value !== 'error') {
          // 把补跑链进当前 Promise，flushAutoSave 的调用方才能真正等到全部落盘。
          await flushAutoSave()
        }
      }
    }
  })()
  autoSaveInFlight = promise
  return promise
}

/**
 * 立即落盘当前模式的内容（切换模式 / 切换文件 / Ctrl+S / 卸载前）。
 * 无变更时不发请求；返回是否处于可安全切换的状态（失败时阻止切换，避免丢草稿）。
 */
async function flushAutoSave(): Promise<boolean> {
  // 只取消空闲防抖，保留失败后的 5 秒自动重试；否则一次切换会清掉重试机会。
  clearAutoSaveTimer()
  if (!props.file || !completed.value || !documentReady.value) {
    saveState.value = 'saved'
    return true
  }
  if (autoSaveInFlight) {
    autoSaveQueued = true
    await autoSaveInFlight
  }
  const isDirty = (): boolean =>
    mode.value === 'edit' ? draftDirty.value : annotationDirty
  // 循环补跑：用户在保存在途期间继续输入/标注时，直到最新内容落盘才允许切换。
  for (let attempt = 0; attempt < 5 && isDirty(); attempt += 1) {
    if (mode.value === 'edit') await autoSaveMarkdown()
    else await autoSaveAnnotations()
    if (saveState.value === 'error') break
  }
  // 只有确实没有未落盘内容才允许切换；错误态但无 dirty 时不应阻断。
  return !isDirty()
}

async function autoSaveAnnotations(manual = false): Promise<void> {
  const file = props.file
  const annotator = annotatorRef.value
  if (!file || file.status !== 'completed' || !documentReady.value || !annotator) {
    saveState.value = 'saved'
    return
  }
  if (!manual && !annotationDirty) {
    saveState.value = 'saved'
    return
  }

  const targetFileId = file.id
  const revision = annotationRevision
  const generation = saveGeneration
  await runAutoSave(async () => {
    const request = beginSaveRequest()
    saveState.value = 'saving'
    saveError.value = ''
    actionError.value = ''
    try {
      const payload = annotator.getPayload()
      await apiFetch<unknown>(
        `/api/files/${encodeURIComponent(targetFileId)}/annotations`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
          signal: request.signal,
        },
      )

      // 请求期间切换了文件/重新加载：本次结果属于旧文档，不能污染当前状态。
      if (generation !== saveGeneration || props.file?.id !== targetFileId) return

      // 请求在途期间又产生了新标注：本快照已过期，保留 dirty 并重新排期，
      // 不能清掉 dirty 造成新标注静默丢失。
      if (annotationRevision !== revision) {
        annotationDirty = true
        saveState.value = 'pending'
        scheduleAutoSave()
        return
      }

      annotationDirty = false
      autoSaveRetries = 0
      saveError.value = ''
      saveState.value = 'saved'
      // 自动保存只更新保存状态；手动 Ctrl+S 才额外闪一次顶栏提示。
      if (manual) showSavedNotice('标注已保存')
      // 只发 saved：父级据此更新“已标注”徽标，再发 refresh 会造成重复请求。
      emit('saved')
    } catch (error) {
      const message = formatError(error)
      if (generation !== saveGeneration || props.file?.id !== targetFileId) return
      saveError.value = message
      saveState.value = 'error'
      actionError.value = `保存标注失败：${message}`
      scheduleAutoSaveRetry(() => autoSaveAnnotations())
    } finally {
      request.finish()
    }
  })
}

async function autoSaveMarkdown(manual = false): Promise<void> {
  const file = props.file
  if (!file || file.status !== 'completed' || !documentReady.value) {
    saveState.value = 'saved'
    return
  }
  if (!draftDirty.value) {
    saveState.value = 'saved'
    return
  }
  if (applying.value || autoSaveInFlight) {
    autoSaveQueued = true
    return
  }

  const targetFileId = file.id
  saveState.value = 'saving'
  saveError.value = ''

  let ok = false
  await runAutoSave(async () => {
    ok = await applyMarkdown(editorDraft.value, {
      skipConfirm: true,
      silent: !manual,
    })
  })

  // 文件已切换：只结束本次请求，不再改动新文件的保存状态。
  if (props.file?.id !== targetFileId) return

  if (ok) {
    autoSaveRetries = 0
    saveError.value = ''
    if (draftDirty.value) {
      // 保存期间用户继续输入：保留新草稿，重新排期下一次自动保存。
      scheduleAutoSave()
    } else {
      saveState.value = 'saved'
    }
  } else if (actionError.value) {
    saveError.value = actionError.value
    saveState.value = 'error'
    scheduleAutoSaveRetry(() => autoSaveMarkdown())
  } else {
    // 被重入/取消等非错误路径拦下：保留草稿，重新排期，避免停在「保存中」。
    scheduleAutoSave()
  }
}

/* ============================================================
   应用 Markdown
   ============================================================ */

async function applyMarkdown(
  nextMarkdown: string,
  options: { skipConfirm?: boolean; silent?: boolean } = {},
): Promise<boolean> {
  const file = props.file
  if (!file || file.status !== 'completed' || applying.value) return false

  // 记录目标文件与代际：请求期间切换文件或重新加载，返回后都不得回写本地状态。
  const targetFileId = file.id
  const generation = saveGeneration
  const sameFile = (): boolean =>
    props.file?.id === targetFileId && generation === saveGeneration

  const annotated =
    annotatorRef.value?.hasAnnotations() ??
    Boolean(
      (annotationRecord.value?.spans.length ?? 0) > 0 ||
        (annotationRecord.value?.relations.length ?? 0) > 0 ||
        (annotationRecord.value?.paragraphs?.length ?? 0) > 0,
    )

  if (annotated && !options.skipConfirm) {
    const confirmed = window.confirm(
      '实体与关系标注将失效（图表记录保留）。\n\n确认后将先清空已有的实体与关系标注，再保存新的 Markdown。是否继续？',
    )
    if (!confirmed) return false
  }

  applying.value = true
  actionError.value = ''
  clearSavedNotice()
  const request = beginSaveRequest()
  let annotationsCleared = false
  // 图表由独立接口维护，本地清空文本标注时必须保留，避免误导用户丢失截图。
  const preservedFigures: FigureAnnotation[] = [...figures.value]
  closeFigureDialog(true)

  try {
    const fileId = encodeURIComponent(targetFileId)

    if (annotated) {
      await apiFetch<unknown>(`/api/files/${fileId}/annotations`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: '', spans: [], relations: [], paragraphs: [] }),
        signal: request.signal,
      })
      annotationsCleared = true
      if (sameFile()) {
        annotationRecord.value = clearedAnnotationRecord(preservedFigures)
        annotatorRef.value?.clearAnnotations()
      }
    }

    await apiFetch<unknown>(`/api/files/${fileId}/markdown`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ markdown: nextMarkdown }),
      signal: request.signal,
    })

    // 文件已切换：请求属于旧文件，不回写任何当前文档状态。
    if (!sameFile()) return true

    markdownSource.value = nextMarkdown
    // 请求期间用户可能继续输入：只有草稿未被改动时才回写，否则保留新输入。
    if (editorDraft.value === nextMarkdown) {
      editorDraft.value = nextMarkdown
    }
    annotationRecord.value = clearedAnnotationRecord(preservedFigures)
    annotationDirty = false

    // Markdown 变化后后端会重建 blocks；必须重新拉取，否则逐块渲染仍是旧内容。
    try {
      const nextBlocks = normalizeBlocks(await fetchBlocks(targetFileId))
      if (sameFile()) blocks.value = nextBlocks
    } catch (blockError) {
      if (sameFile()) {
        blocks.value = []
        appendLoadWarning('Markdown 已保存，但段落切块重建失败，已回退为整篇渲染。')
      }
      console.warn('重新加载 blocks 失败', blockError)
    }

    if (!sameFile()) return true

    if (!options.silent) {
      showSavedNotice(
        annotated
          ? 'Markdown 已保存，实体与关系标注已清空'
          : 'Markdown 已保存',
      )
    }
    emit('saved')

    await nextTick()
    if (sameFile()) annotatorRef.value?.refreshLayout()
    return true
  } catch (error) {
    if (sameFile()) {
      actionError.value = `保存 Markdown 失败：${formatError(error)}`
      if (annotationsCleared) {
        // 标注已在服务端清空，本地必须保持一致，即便 Markdown 保存失败。
        annotationRecord.value = clearedAnnotationRecord(preservedFigures)
        annotatorRef.value?.clearAnnotations()
      }
    }
    return false
  } finally {
    request.finish()
    applying.value = false
  }
}

/* ============================================================
   保存入口（Ctrl+S / 编辑器应用）
   ============================================================ */

function handlePrimarySave(): void {
  if (!completed.value || !documentReady.value) return
  if (mode.value === 'edit') {
    void autoSaveMarkdown(true)
  } else {
    void autoSaveAnnotations(true)
  }
}

function handleEditorApply(): void {
  void autoSaveMarkdown(true)
}

function handleAnnotationChange(): void {
  if (suppressModeSave || mode.value !== 'annotate') return
  annotationRevision += 1
  annotationDirty = true
  scheduleAutoSave()
}

function handleDraftUpdate(value: string): void {
  editorDraft.value = value
  if (suppressModeSave || mode.value !== 'edit') return
  if (value === markdownSource.value) {
    // 草稿被还原成已保存版本：取消防抖与重试，状态与错误一起归位。
    clearAutoSaveTimers()
    saveError.value = ''
    actionError.value = ''
    saveState.value = 'saved'
    return
  }
  scheduleAutoSave()
}

/* ============================================================
   图表（拖框截图）
   ============================================================ */

/**
 * 更新图表引用时同步 annotationRecord 里的 figures 字段。
 * 只写嵌套字段、不替换 annotationRecord 本身，避免触发标注重新加载。
 */
function setFigures(next: FigureAnnotation[]): void {
  figures.value = next
  if (annotationRecord.value) annotationRecord.value.figures = next
}

/** 以服务端为准刷新图表；失败时保留本地乐观结果。 */
async function refreshFiguresFromServer(): Promise<void> {
  const file = props.file
  if (!file) return
  try {
    setFigures(await fetchFigures(file.id))
  } catch (error) {
    console.warn('刷新图表列表失败，保留本地状态', error)
  }
}

function handleRegionSelected(selection: FigureRegionSelection): void {
  if (!props.file || props.file.status !== 'completed' || figureSubmitting.value) return
  figureError.value = ''
  figureDialog.value = {
    mode: 'create',
    page: selection.page,
    bbox: [...selection.bbox],
    previewUrl: selection.previewUrl,
  }
}

function handleFigureSelected(figure: FigureAnnotation): void {
  if (figureSubmitting.value) return
  figureError.value = ''
  figureDialog.value = { mode: 'edit', figure }
}

function closeFigureDialog(force = false): void {
  if (figureSubmitting.value && !force) return
  figureDialog.value = null
  figureError.value = ''
}

async function handleFigureSubmit(payload: FigureDraftPayload): Promise<void> {
  const dialog = figureDialog.value
  const file = props.file
  if (!dialog || !file || figureSubmitting.value) return

  figureSubmitting.value = true
  figureError.value = ''

  try {
    if (dialog.mode === 'create') {
      const preview = pdfPreviewRef.value
      if (!preview) throw new Error('预览面板已关闭，无法生成截图，请重新打开 PDF 预览后再试。')
      const blob = await preview.captureRegion(dialog.bbox, dialog.page)
      const meta: FigureCreatePayload = {
        ...payload,
        page: dialog.page,
        bbox: dialog.bbox,
      }
      const created = await createFigure(file.id, blob, meta)
      setFigures([...figures.value, created])
      await refreshFiguresFromServer()
      showSavedNotice('图表已创建')
    } else {
      const updated = await updateFigure(file.id, dialog.figure.id, payload)
      setFigures(
        figures.value.map((item) => (item.id === updated.id ? updated : item)),
      )
      await refreshFiguresFromServer()
      showSavedNotice('图表已更新')
    }

    closeFigureDialog(true)
    emit('saved')
  } catch (error) {
    // 上传失败时保持弹窗打开，用户输入与预览都不丢失。
    figureError.value = `${dialog.mode === 'create' ? '创建' : '保存'}图表失败：${formatError(error)}`
  } finally {
    figureSubmitting.value = false
  }
}

async function handleFigureDelete(): Promise<void> {
  const dialog = figureDialog.value
  const file = props.file
  if (!dialog || dialog.mode !== 'edit' || !file || figureSubmitting.value) return

  const figureId = dialog.figure.id
  const fallback = dialog.figure.kind === 'table' ? '表' : '图'
  const title = String(dialog.figure.caption ?? '').trim() || fallback
  if (!window.confirm(`确定删除「${title}」吗？截图资产会一并删除，且不可恢复。`)) {
    return
  }

  figureSubmitting.value = true
  figureError.value = ''

  try {
    await deleteFigure(file.id, figureId)
    setFigures(figures.value.filter((item) => item.id !== figureId))
    await refreshFiguresFromServer()
    closeFigureDialog(true)
    showSavedNotice('图表已删除')
    emit('saved')
  } catch (error) {
    figureError.value = `删除图表失败：${formatError(error)}`
  } finally {
    figureSubmitting.value = false
  }
}

/* ============================================================
   提示与错误
   ============================================================ */

function showSavedNotice(message: string): void {
  savedNotice.value = message
  clearSavedNoticeTimer()
  noticeTimer = setTimeout(() => {
    savedNotice.value = ''
    noticeTimer = null
  }, 2800)
}

function clearSavedNotice(): void {
  savedNotice.value = ''
  clearSavedNoticeTimer()
}

function clearSavedNoticeTimer(): void {
  if (noticeTimer) clearTimeout(noticeTimer)
  noticeTimer = null
}

function formatError(cause: unknown): string {
  if (cause instanceof Error && cause.message) return cause.message
  if (cause && typeof cause === 'object') {
    const value = cause as { detail?: unknown; message?: unknown }
    if (typeof value.detail === 'string') return value.detail
    if (typeof value.message === 'string') return value.message
  }
  return String(cause)
}

function retryLoad(): void {
  emit('refresh')
  void loadDocument()
}

function refreshStatus(): void {
  emit('refresh')
}

function handleGlobalKeydown(event: KeyboardEvent): void {
  if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 's') return
  if (
    event.defaultPrevented ||
    !documentReady.value ||
    figureDialog.value ||
    editConsentOpen.value
  ) {
    return
  }
  event.preventDefault()
  handlePrimarySave()
}

/** 页面隐藏/关闭前尽力落盘；刷新时若仍有未保存内容则提示用户。 */
function handleVisibilityChange(): void {
  if (document.visibilityState === 'hidden' && saveState.value !== 'saved') {
    void flushAutoSave()
  }
}

function handleBeforeUnload(event: BeforeUnloadEvent): void {
  if (saveState.value === 'saved') return
  void flushAutoSave()
  event.preventDefault()
  event.returnValue = ''
}

/* ============================================================
   生命周期
   ============================================================ */

onMounted(() => {
  mediaQuery = window.matchMedia('(max-width: 1180px)')
  isNarrow.value = mediaQuery.matches
  pdfOpen.value = !mediaQuery.matches
  pdfPanelWidth.value = readStoredPdfPanelWidth()
  syncScroll.value = readStoredSyncScroll()
  mediaQuery.addEventListener('change', handleMediaChange)
  window.addEventListener('keydown', handleGlobalKeydown)
  document.addEventListener('visibilitychange', handleVisibilityChange)
  window.addEventListener('beforeunload', handleBeforeUnload)
})

onBeforeUnmount(() => {
  loadToken += 1
  clearSavedNoticeTimer()
  clearSyncAlignTimer()
  clearAutoSaveTimers()
  // 卸载前尝试把未落盘的变更写完；请求异步进行，不阻塞卸载。
  void flushAutoSave()
  mediaQuery?.removeEventListener('change', handleMediaChange)
  mediaQuery = null
  window.removeEventListener('keydown', handleGlobalKeydown)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  window.removeEventListener('beforeunload', handleBeforeUnload)
})

// 父组件在切换文件/项目前调用，确保 1.2 秒防抖窗口内的变更不丢失。
defineExpose({
  flushSave: () => flushAutoSave(),
})
</script>

<template>
  <section
    class="mixed-workspace"
    :class="{ 'is-resizing': resizingPdf }"
    aria-label="混合标注工作区"
  >
    <header class="mw-toolbar">
      <div class="mw-identity">
        <div class="mw-eyebrow">
          <span class="mw-project" :title="project?.name ?? '未选择项目'">
            {{ project?.name || '未选择项目' }}
          </span>
          <span class="mw-slash" aria-hidden="true">/</span>
          <span>Mixed Annotation</span>
        </div>
        <div class="mw-title-row">
          <h1 class="mw-title" :title="file?.name">
            {{ file?.name || '混合标注' }}
          </h1>
          <span
            v-if="file"
            class="mw-status-dot"
            :class="`is-${file.status}`"
            :title="file.status"
            aria-hidden="true"
          ></span>
          <span v-if="savedNotice" class="mw-saved-pill" role="status" aria-live="polite">
            {{ savedNotice }}
          </span>
        </div>
      </div>

      <div class="mw-actions">
        <div class="mw-controls" role="group" aria-label="工作区控制">
          <ModeToggle
            :mode="mode"
            :disabled="modeToggleDisabled"
            @toggle="toggleMode"
          />
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
      </div>
    </header>

    <div v-if="actionError || loadWarning" class="mw-banners">
      <div v-if="actionError" class="mw-banner mw-banner--error" role="alert">
        <span>{{ actionError }}</span>
        <button type="button" class="mw-banner-close" aria-label="关闭错误提示" @click="actionError = ''">
          ×
        </button>
      </div>
      <div v-if="loadWarning" class="mw-banner mw-banner--warning" role="status">
        <span>{{ loadWarning }}</span>
        <button type="button" class="mw-banner-close" aria-label="关闭提示" @click="loadWarning = ''">
          ×
        </button>
      </div>
    </div>

    <div v-if="!file" class="mw-empty">
      <span class="mw-empty-glyph" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="34" height="34" fill="none" stroke="currentColor" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <path d="M14 2v6h6M8 13h8M8 17h5" />
        </svg>
      </span>
      <p class="mw-empty-en">No document selected</p>
      <p class="mw-empty-zh">从左侧选择一个已完成转换的文件</p>
      <p class="mw-empty-hint">转换完成后即可查看 Markdown、原始 PDF，并开始实体与关系标注。</p>
    </div>

    <div v-else-if="file.status !== 'completed'" class="mw-status-wrap">
      <section class="mw-status-card" :class="`is-${file.status}`">
        <span class="mw-status-glyph" aria-hidden="true">
          <svg v-if="file.status === 'failed'" viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 8v5M12 16h.01" />
          </svg>
          <svg v-else viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" />
          </svg>
        </span>

        <span class="mw-status-eyebrow">{{ statusHeading }}</span>
        <h2 class="mw-status-title">{{ file.name }}</h2>
        <p class="mw-status-desc">{{ statusDescription }}</p>

        <div v-if="file.status === 'converting'" class="mw-progress" role="progressbar" :aria-valuenow="progressPercent" aria-valuemin="0" aria-valuemax="100">
          <span class="mw-progress-bar" :style="{ width: `${progressPercent}%` }"></span>
        </div>
        <div v-if="file.status === 'converting'" class="mw-progress-meta">
          <span>{{ progressPercent }}%</span>
          <span>{{ file.stage || 'OCR' }}</span>
        </div>

        <div class="mw-status-actions">
          <button type="button" class="mw-tool" @click="refreshStatus">刷新状态</button>
          <span v-if="file.status === 'converting'" class="mw-status-note">转换在后台进行，可稍后回来查看</span>
          <span v-else-if="file.status === 'failed'" class="mw-status-note mw-status-note--danger">
            可让左侧文件面板重新转换后再刷新
          </span>
          <span v-else class="mw-status-note">文件已上传，等待转换任务开始</span>
        </div>
      </section>
    </div>

    <div
      v-else
      ref="bodyRef"
      class="mw-body"
      :class="{ 'has-inline-pdf': pdfInlineVisible }"
      :style="{ '--pdf-panel-width': `${pdfPanelWidth}%` }"
    >
      <main class="mw-main">
        <div v-if="loading || (!documentReady && !loadError)" class="mw-state">
          <span class="mw-spinner" aria-hidden="true"></span>
          <strong>正在加载文件</strong>
          <span>读取 Markdown 与已有标注…</span>
        </div>

        <div v-else-if="loadError" class="mw-state mw-state--error">
          <strong>无法打开文件</strong>
          <span>{{ loadError }}</span>
          <div class="mw-state-actions">
            <button type="button" class="mw-tool" @click="retryLoad">重试</button>
            <button type="button" class="mw-tool mw-tool--quiet" @click="refreshStatus">刷新状态</button>
          </div>
        </div>

        <template v-else-if="documentReady">
          <div v-show="mode === 'annotate'" class="mw-pane">
            <MarkdownAnnotator
              :key="file.id"
              ref="annotatorRef"
              :file-id="file.id"
              :markdown="markdownSource"
              :blocks="blocks"
              :labels="labels"
              :relation-types="relationTypes"
              :annotations="annotationRecord"
              :active="mode === 'annotate'"
              @scroll-state="handleMarkdownScroll"
              @change="handleAnnotationChange"
            >
              <template #save-status>
                <SaveStatus :state="saveState" :error="saveError" />
              </template>
            </MarkdownAnnotator>
          </div>

          <MarkdownEditor
            v-if="mode === 'edit'"
            ref="editorRef"
            :key="file.id"
            :model-value="editorDraft"
            :saved-markdown="markdownSource"
            :file-id="file.id"
            :busy="applying"
            @update:model-value="handleDraftUpdate"
            @apply="handleEditorApply"
            @scroll-state="handleMarkdownScroll"
          >
            <template #save-status>
              <SaveStatus :state="saveState" :error="saveError" />
            </template>
          </MarkdownEditor>
        </template>
      </main>

      <div
        v-if="pdfInlineVisible"
        ref="splitterRef"
        class="mw-splitter"
        :class="{ 'is-active': resizingPdf }"
        role="separator"
        tabindex="0"
        aria-orientation="vertical"
        aria-label="调整 Markdown 与原始预览的宽度"
        :aria-valuenow="Math.round(pdfPanelWidth)"
        :aria-valuemin="PDF_PANEL_MIN"
        :aria-valuemax="PDF_PANEL_MAX"
        title="拖动调整预览宽度，双击恢复默认"
        @pointerdown="handleSplitterPointerDown"
        @pointermove="handleSplitterPointerMove"
        @pointerup="endSplitterDrag"
        @pointercancel="endSplitterDrag"
        @lostpointercapture="handleSplitterLostCapture"
        @keydown="handleSplitterKeydown"
        @dblclick="resetPdfPanelWidth"
      >
        <span class="mw-splitter-grip" aria-hidden="true"></span>
      </div>

      <div
        v-if="pdfOpen && pdfAsDrawer && documentReady"
        class="mw-drawer-backdrop"
        aria-hidden="true"
        @click="pdfOpen = false"
      ></div>

      <aside
        v-if="pdfOpen && documentReady"
        class="mw-pdf"
        :class="{ 'mw-pdf--drawer': pdfAsDrawer }"
        aria-label="原始文件预览面板"
      >
        <PdfPreview
          :key="file.id"
          ref="pdfPreviewRef"
          :file="file"
          :figures="figures"
          @close="pdfOpen = false"
          @region-selected="handleRegionSelected"
          @figure-selected="handleFigureSelected"
          @scroll-state="handlePdfScroll"
        />
      </aside>
    </div>

    <FigureDialog
      v-if="figureDialog && file"
      :key="dialogKey"
      :mode="figureDialog.mode"
      :file-id="file.id"
      :figure="dialogFigure"
      :page="dialogPage"
      :bbox="dialogBbox"
      :preview-url="dialogPreviewUrl"
      :submitting="figureSubmitting"
      :server-error="figureError"
      @close="closeFigureDialog()"
      @submit="handleFigureSubmit"
      @remove="handleFigureDelete"
    />

    <ConfirmDialog
      v-model:open="editConsentOpen"
      title="进入编辑模式？"
      message="进入编辑模式并自动保存 Markdown 会清空已有的实体/关系标注。图表记录与截图会保留。是否继续？"
      confirm-label="继续"
      danger
      :busy="applying"
      @confirm="confirmEditMode"
    />
  </section>
</template>

<style scoped>
.mixed-workspace {
  --mw-paper: var(--paper, #f6f3ec);
  --mw-paper-deep: var(--paper-deep, #efebe2);
  --mw-surface: var(--surface, #fffdf9);
  --mw-raised: var(--surface-raised, #fff);
  --mw-sunken: var(--surface-sunken, #f2eee6);
  --mw-ink: var(--ink, #17181b);
  --mw-ink-2: var(--ink-2, #3e4147);
  --mw-ink-3: var(--ink-3, #6e727a);
  --mw-ink-4: var(--ink-4, #9a9da3);
  --mw-line: var(--line, #e2dccf);
  --mw-line-strong: var(--line-strong, #d2caba);
  --mw-signal: var(--signal, #e4572e);
  --mw-signal-deep: var(--signal-deep, #c44722);
  --mw-signal-soft: var(--signal-soft, #fbe8e1);
  --mw-signal-ink: var(--signal-ink, #8e2f14);
  --mw-success: var(--success, #2f7d5b);
  --mw-warning: var(--warning, #a9761e);
  --mw-warning-bg: var(--warning-bg, #faf2e1);
  --mw-danger: var(--danger, #b5403a);
  --mw-danger-bg: var(--danger-bg, #faecea);
  --mw-mono: var(--font-mono, 'Geist Mono', ui-monospace, Consolas, monospace);
  --mw-display: var(--font-display, 'Instrument Serif', Georgia, serif);
  --mw-ease: var(--ease-out, cubic-bezier(0.22, 1, 0.36, 1));
  --mw-shadow-xs: var(--shadow-xs, 0 1px 2px rgba(35, 29, 19, 0.05));
  --mw-shadow: var(--shadow, 0 18px 44px -28px rgba(35, 29, 19, 0.22));

  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  color: var(--mw-ink);
}

/* ------------------------------------------------------------
   工具栏
   ------------------------------------------------------------ */
.mw-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  flex-shrink: 0;
  min-height: 66px;
  padding: 11px 20px;
  border-bottom: 1px solid var(--mw-line);
  /* Chrome 109 不支持 color-mix，保留暖纸底色作为回退。 */
  background: var(--mw-paper);
  background: color-mix(in srgb, var(--mw-paper) 90%, transparent);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  animation: mw-fade 260ms var(--mw-ease) both;
}

.mw-identity {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.mw-eyebrow {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
  overflow: hidden;
  font-family: var(--mw-mono);
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--mw-ink-3);
  white-space: nowrap;
}

.mw-project {
  max-width: 220px;
  overflow: hidden;
  color: var(--mw-signal-deep);
  text-overflow: ellipsis;
}

.mw-slash {
  color: var(--mw-line-strong);
}

.mw-title-row {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
}

.mw-title {
  margin: 0;
  overflow: hidden;
  font-family: var(--mw-display);
  font-size: clamp(20px, 1.9vw, 26px);
  font-weight: 400;
  line-height: 1.14;
  letter-spacing: -0.012em;
  color: var(--mw-ink);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mw-status-dot {
  width: 7px;
  height: 7px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--mw-ink-4);
}

.mw-status-dot.is-completed {
  background: var(--mw-success);
  box-shadow: 0 0 0 3px rgba(47, 125, 91, 0.13);
}

.mw-status-dot.is-converting {
  background: var(--mw-warning);
  box-shadow: 0 0 0 3px rgba(169, 118, 30, 0.14);
  animation: mw-pulse 1.6s ease-in-out infinite;
}

.mw-status-dot.is-failed {
  background: var(--mw-danger);
}

.mw-saved-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--success-bg, #eaf4ee);
  color: var(--mw-success);
  font-size: 9.5px;
  font-weight: 500;
  white-space: nowrap;
  animation: mw-fade 180ms var(--mw-ease) both;
}

.mw-actions {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}

/* 视图控制项共用一套尺寸与状态色：
   开关开启 = 朱砂浅底；未激活 = 白底细边。 */
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
  transition:
    background-color 180ms var(--mw-ease),
    border-color 180ms var(--mw-ease),
    color 180ms var(--mw-ease);
}

.mw-control:hover:not(:disabled) {
  border-color: var(--mw-line-strong);
  background: var(--mw-raised);
}

.mw-control:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}

.mw-control-dot {
  width: 5px;
  height: 5px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--mw-ink-4);
}

.mw-control.is-toggle-active {
  border-color: rgba(228, 87, 46, 0.34);
  background: var(--mw-signal-soft);
  color: var(--mw-signal-ink);
}

.mw-control.is-toggle-active .mw-control-dot {
  background: var(--mw-signal);
}

.mw-tool {
  display: inline-flex;
  align-items: center;
  justify-content: center;
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
  transition:
    background-color 180ms var(--mw-ease),
    border-color 180ms var(--mw-ease),
    color 180ms var(--mw-ease),
    transform 180ms var(--mw-ease);
}

.mw-tool:hover:not(:disabled) {
  transform: translateY(-1px);
  border-color: var(--mw-line-strong);
  background: var(--mw-raised);
}

.mw-tool:active:not(:disabled) {
  transform: scale(0.985);
}

.mw-tool:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}

.mw-tool--quiet {
  border-color: transparent;
  background: transparent;
  color: var(--mw-ink-3);
}

/* ------------------------------------------------------------
   提示条
   ------------------------------------------------------------ */
.mw-banners {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-shrink: 0;
  padding: 8px 20px 0;
}

.mw-banner {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 10px 8px 12px;
  border: 1px solid var(--mw-line);
  border-radius: 9px;
  font-size: 11.5px;
  line-height: 1.55;
}

.mw-banner > span {
  flex: 1;
  min-width: 0;
}

.mw-banner--error {
  border-color: rgba(181, 64, 58, 0.24);
  background: var(--danger-bg, #faecea);
  color: var(--mw-danger);
}

.mw-banner--warning {
  border-color: rgba(169, 118, 30, 0.24);
  background: var(--mw-warning-bg);
  color: var(--mw-warning);
}

.mw-banner-close {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: currentColor;
  font-family: inherit;
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
  opacity: 0.65;
}

.mw-banner-close:hover {
  background: rgba(23, 24, 27, 0.06);
  opacity: 1;
}

/* ------------------------------------------------------------
   空状态 / 转换状态
   ------------------------------------------------------------ */
.mw-empty,
.mw-status-wrap {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 28px;
}

.mw-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  text-align: center;
  color: var(--mw-ink-3);
}

.mw-empty-glyph {
  display: grid;
  place-items: center;
  width: 56px;
  height: 56px;
  margin-bottom: 8px;
  border: 1px solid var(--mw-line);
  border-radius: 50%;
  color: var(--mw-ink-4);
}

.mw-empty-en {
  margin: 0;
  font-family: var(--mw-display);
  font-style: italic;
  font-size: 27px;
  line-height: 1.15;
  color: var(--mw-ink-3);
}

.mw-empty-zh {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.035em;
  color: var(--mw-ink-2);
}

.mw-empty-hint {
  max-width: 430px;
  margin: 2px 0 0;
  font-size: 11.5px;
  line-height: 1.65;
  color: var(--mw-ink-3);
}

.mw-status-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
}

.mw-status-card {
  width: min(540px, 100%);
  padding: 30px 30px 24px;
  border: 1px solid var(--mw-line);
  border-radius: 22px;
  background: var(--mw-surface);
  box-shadow: var(--mw-shadow);
  text-align: center;
  animation: mw-rise 300ms var(--mw-ease) both;
}

.mw-status-glyph {
  display: grid;
  place-items: center;
  width: 54px;
  height: 54px;
  margin: 0 auto 13px;
  border: 1px solid var(--mw-line);
  border-radius: 50%;
  color: var(--mw-ink-3);
}

.mw-status-card.is-converting .mw-status-glyph {
  color: var(--mw-warning);
  animation: mw-rotate 5s linear infinite;
}

.mw-status-card.is-failed .mw-status-glyph {
  border-color: rgba(181, 64, 58, 0.25);
  color: var(--mw-danger);
}

.mw-status-eyebrow {
  display: block;
  margin-bottom: 5px;
  font-family: var(--mw-mono);
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--mw-ink-3);
}

.mw-status-title {
  margin: 0 0 8px;
  overflow: hidden;
  font-family: var(--mw-display);
  font-size: 27px;
  font-weight: 400;
  line-height: 1.2;
  color: var(--mw-ink);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mw-status-desc {
  margin: 0 auto 18px;
  max-width: 390px;
  color: var(--mw-ink-3);
  font-size: 12px;
  line-height: 1.65;
}

.mw-progress {
  height: 4px;
  margin: 0 auto 6px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--mw-line);
}

.mw-progress-bar {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--mw-signal);
  transition: width 240ms var(--mw-ease);
}

.mw-progress-meta {
  display: flex;
  justify-content: space-between;
  margin-bottom: 16px;
  font-family: var(--mw-mono);
  font-size: 9.5px;
  color: var(--mw-ink-3);
  font-variant-numeric: tabular-nums;
}

.mw-status-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  flex-wrap: wrap;
}

.mw-status-note {
  font-size: 10.5px;
  color: var(--mw-ink-3);
}

.mw-status-note--danger {
  color: var(--mw-danger);
}

/* ------------------------------------------------------------
   主体
   ------------------------------------------------------------ */
.mw-body {
  display: flex;
  flex: 1;
  gap: 12px;
  min-width: 0;
  min-height: 0;
  padding: 12px 16px 16px;
}

/* 并排模式由分隔条提供间距，避免 gap 与抓手叠加造成过宽空白。 */
.mw-body.has-inline-pdf {
  gap: 0;
}

.mw-main {
  display: flex;
  flex: 1;
  min-width: 0;
  min-height: 0;
}

.mw-pane {
  display: flex;
  flex: 1;
  min-width: 0;
  min-height: 0;
}

.mw-pdf {
  flex: 0 0 var(--pdf-panel-width, 36%);
  width: auto;
  min-width: 0;
  min-height: 0;
}

/* ------------------------------------------------------------
   可拖动分隔条
   ------------------------------------------------------------ */
.mw-splitter {
  position: relative;
  z-index: 1;
  flex: 0 0 14px;
  align-self: stretch;
  padding: 0;
  border: none;
  background: transparent;
  cursor: col-resize;
  touch-action: none;
  outline: none;
  -webkit-user-select: none;
  user-select: none;
}

.mw-splitter::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 1px;
  transform: translateX(-50%);
  background: var(--mw-line);
  transition:
    width 160ms var(--mw-ease),
    background-color 160ms var(--mw-ease);
}

.mw-splitter-grip {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 5px;
  height: 40px;
  transform: translate(-50%, -50%);
  border-radius: 999px;
  background: var(--mw-line-strong);
  transition:
    height 160ms var(--mw-ease),
    background-color 160ms var(--mw-ease),
    box-shadow 160ms var(--mw-ease);
}

.mw-splitter:hover::before,
.mw-splitter:focus-visible::before,
.mw-splitter.is-active::before {
  width: 2px;
  background: var(--mw-signal);
}

.mw-splitter:hover .mw-splitter-grip,
.mw-splitter:focus-visible .mw-splitter-grip,
.mw-splitter.is-active .mw-splitter-grip {
  height: 52px;
  background: var(--mw-signal);
  box-shadow: 0 0 0 3px var(--mw-signal-soft);
}

.mw-splitter:focus-visible {
  border-radius: 6px;
}

/* 拖动期间禁止选中文本，并让整页光标保持 col-resize。 */
.mixed-workspace.is-resizing {
  cursor: col-resize;
  -webkit-user-select: none;
  user-select: none;
}

.mixed-workspace.is-resizing :deep(*) {
  cursor: col-resize !important;
  -webkit-user-select: none !important;
  user-select: none !important;
}

.mw-state {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 0;
  padding: 32px;
  border: 1px solid var(--mw-line);
  border-radius: 20px;
  background: var(--mw-surface);
  box-shadow: var(--mw-shadow-xs);
  text-align: center;
  color: var(--mw-ink-3);
  font-size: 12px;
  line-height: 1.6;
}

.mw-state strong {
  margin-top: 5px;
  font-family: var(--mw-display);
  font-size: 24px;
  font-weight: 400;
  line-height: 1.2;
  color: var(--mw-ink-2);
}

.mw-state--error {
  border-color: rgba(181, 64, 58, 0.22);
}

.mw-state--error strong {
  color: var(--mw-danger);
}

.mw-spinner {
  width: 26px;
  height: 26px;
  border: 2px solid var(--mw-line);
  border-top-color: var(--mw-signal);
  border-radius: 50%;
  animation: mw-rotate 0.75s linear infinite;
}

.mw-state-actions {
  display: flex;
  gap: 7px;
  margin-top: 8px;
}

/* PDF 抽屉（窄屏或编辑模式） */
.mw-drawer-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  background: rgba(20, 22, 25, 0.36);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  animation: mw-fade 180ms var(--mw-ease) both;
}

.mw-pdf--drawer {
  position: fixed;
  inset: 0 0 0 auto;
  z-index: 60;
  flex: none;
  width: min(560px, 94vw);
  padding: 12px;
  background: var(--mw-paper);
  border-left: 1px solid var(--mw-line);
  box-shadow: var(--shadow-lg, 0 28px 60px -24px rgba(35, 29, 19, 0.28));
  animation: mw-drawer-in 220ms var(--mw-ease) both;
}

/* ------------------------------------------------------------
   动效
   ------------------------------------------------------------ */
@keyframes mw-fade {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@keyframes mw-rise {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

@keyframes mw-drawer-in {
  from {
    opacity: 0;
    transform: translateX(20px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

@keyframes mw-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.4;
  }
}

@keyframes mw-rotate {
  to {
    transform: rotate(360deg);
  }
}

/* ------------------------------------------------------------
   响应式
   ------------------------------------------------------------ */
@media (max-width: 1180px) {
  .mw-pdf {
    width: 100%;
  }
}

@media (max-width: 760px) {
  .mw-toolbar {
    align-items: flex-start;
    padding: 10px 12px;
    gap: 10px;
  }

  .mw-actions {
    width: 100%;
  }

  .mw-controls {
    width: 100%;
  }

  .mw-control {
    flex: 1 1 auto;
    justify-content: center;
  }

  .mw-tool {
    height: 30px;
    padding: 0 9px;
    font-size: 10.5px;
  }

  .mw-saved-pill {
    display: none;
  }

  .mw-banners {
    padding: 7px 12px 0;
  }

  .mw-body {
    padding: 8px 8px 10px;
  }

  .mw-empty,
  .mw-status-wrap {
    padding: 18px 12px;
  }

  .mw-status-card {
    padding: 25px 18px 20px;
    border-radius: 18px;
  }

  .mw-status-title {
    font-size: 23px;
  }

  .mw-pdf--drawer {
    width: 96vw;
    padding: 8px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .mw-toolbar,
  .mw-status-card,
  .mw-status-card.is-converting .mw-status-glyph,
  .mw-status-dot.is-converting,
  .mw-spinner,
  .mw-drawer-backdrop,
  .mw-pdf--drawer,
  .mw-saved-pill {
    animation: none;
  }

  .mw-tool,
  .mw-control,
  .mw-banner-close,
  .mw-progress-bar,
  .mw-splitter::before,
  .mw-splitter-grip {
    transition: none;
  }
}
</style>

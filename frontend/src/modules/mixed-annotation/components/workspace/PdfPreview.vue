<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type {
  PDFDocumentLoadingTask,
  PDFDocumentProxy,
  PDFPageProxy,
  RenderTask,
} from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type {
  FigureAnnotation,
  FigureRegionSelection,
  MixedFile,
} from '../../types'
import { apiUrl } from '../../api/client'

/**
 * 原始 PDF / 图片预览。
 *
 * 性能策略：
 * - 组件只在面板打开时挂载；
 * - PDF.js 按需动态加载，图片文件不会下载 PDF 运行时；
 * - PDF 采用纵向连续滚动，所有页只创建一个占位节点；
 *   canvas 交给 IntersectionObserver 按视口懒渲染，离开视口不销毁、可复用；
 * - 缩放 / 容器尺寸变化时先保留滚动锚点，再防抖重渲染已渲染页；
 * - 截图只在用户确认后按 200 DPI 离屏渲染目标页，预览本身不参与导出。
 *
 * 坐标约定：
 * - 对外暴露的 bbox 统一为 [x0, y0, x1, y1]、左上原点；
 * - PDF 使用目标页 viewport scale=1 的页面坐标（单位 pt）；
 * - 图片使用 naturalWidth / naturalHeight 像素坐标。
 */

const props = withDefaults(
  defineProps<{
    file: MixedFile
    figures?: FigureAnnotation[]
  }>(),
  {
    figures: () => [],
  },
)

const emit = defineEmits<{
  close: []
  'region-selected': [selection: FigureRegionSelection]
  'figure-selected': [figure: FigureAnnotation]
  /** 用户滚动 PDF 时上报 0..1 的纵向滚动比例，用于与 Markdown 联动。 */
  'scroll-state': [ratio: number]
}>()

type PdfjsModule = typeof import('pdfjs-dist')

let pdfjsLoader: Promise<PdfjsModule> | null = null

function loadPdfjs(): Promise<PdfjsModule> {
  if (!pdfjsLoader) {
    pdfjsLoader = import('pdfjs-dist').then((module) => {
      module.GlobalWorkerOptions.workerSrc = workerUrl
      return module
    })
  }
  return pdfjsLoader
}

/* ============================================================
   响应式状态
   ============================================================ */

const scrollRef = ref<HTMLDivElement | null>(null)
const imageRef = ref<HTMLImageElement | null>(null)

const loading = ref(false)
const error = ref('')
const pageCount = ref(props.file.page_count || 0)
/** 当前滚动位置对应的页码（仅用于工具栏指示与跳转）。 */
const activePage = ref(1)
const zoom = ref(1)
/** PDF 页面可用宽度（滚动容器宽度减去内边距），随容器尺寸变化。 */
const containerWidth = ref(640)
/** PDF 文档是否已加载且页面尺寸就绪；不等待具体页面的 canvas 渲染。 */
const pdfReady = ref(false)

const imageLoading = ref(true)
const imageError = ref('')
/** 图片原始像素尺寸：用于把 bbox 映射到显示区域。 */
const imageNaturalWidth = ref(0)
const imageNaturalHeight = ref(0)

interface PdfPageEntry {
  page: number
  /** viewport scale=1 的页面宽度（pt）。 */
  widthPt: number
  /** viewport scale=1 的页面高度（pt）。 */
  heightPt: number
  rendered: boolean
  renderedScale: number
  visible: boolean
  renderError: string
}

/** 每个 PDF 页的尺寸占位；canvas 内容按需填充。 */
const pages = ref<PdfPageEntry[]>([])
const figureLookup = computed(() => props.figures)

const captureMode = ref(false)
const selection = ref<{ page: number; rect: SelectionRect } | null>(null)
/**
 * 外部请求进入截图模式时，PDF/图片可能仍在加载；
 * 记录请求，待 canCapture 变为 true 后自动进入。
 */
const pendingCapture = ref(false)

/* ============================================================
   非响应式运行时句柄
   ============================================================ */

let loadingTask: PDFDocumentLoadingTask | null = null
let pdfDocument: PDFDocumentProxy | null = null
/** PDFPageProxy 体量大且不应被 Vue 深度代理，单独用原生 Map 持有。 */
const pageProxies = new Map<number, PDFPageProxy>()
const pageElements = new Map<number, HTMLElement>()
const canvasElements = new Map<number, HTMLCanvasElement>()
const renderTasks = new Map<number, RenderTask>()
/** 每页渲染代次：取消或缩放后用来丢弃过期结果。 */
const renderTokens = new Map<number, number>()
/** 已排队等待 canvas 挂载的页码，避免同一页重复排队。 */
const queuedPages = new Set<number>()

let pageObserver: IntersectionObserver | null = null
let loadToken = 0
let layoutTimer: ReturnType<typeof setTimeout> | null = null
let rerenderTimer: ReturnType<typeof setTimeout> | null = null
let scrollRaf = 0
let resizeObserver: ResizeObserver | null = null
/** 程序化滚动的抑制标志：setScrollRatio 后的下一帧前不再上报自身滚动。 */
let ignoringScroll = false
let suppressRaf = 0

interface SelectionRect {
  left: number
  top: number
  width: number
  height: number
}

interface FigureOverlayItem {
  figure: FigureAnnotation
  label: string
  title: string
  kindClass: string
  style: Record<string, string>
}

/** 截图输出目标分辨率；canvas 尺寸过大时按上限自动降采样。 */
const CAPTURE_DPI = 200
const MAX_CAPTURE_EDGE = 8192
const MAX_CAPTURE_AREA = 32_000_000
const PREVIEW_MAX_EDGE = 720
const MIN_SELECTION_PX = 6
const PAGE_GAP = 18
const SCROLL_ANCHOR_OFFSET = 12

const isPdf = computed(() => props.file.source_type === 'pdf')
const sourceLabel = computed(() => (isPdf.value ? 'PDF Source' : 'Image Source'))
const sourceUrl = computed(() => {
  const id = encodeURIComponent(props.file.id)
  const version = encodeURIComponent(props.file.updated_at || '')
  return apiUrl(`/api/files/${id}/source${version ? `?v=${version}` : ''}`)
})
const zoomPercent = computed(() => `${Math.round(zoom.value * 100)}%`)

/**
 * PDF 只要求“文档已加载且无错误”。
 * 某一页还在离屏渲染不应阻塞截图：截图会按目标页重新离屏渲染。
 */
const canCapture = computed(() =>
  isPdf.value
    ? pdfReady.value && !error.value
    : Boolean(imageNaturalWidth.value) && !imageError.value,
)

/* ============================================================
   图表叠加层
   ============================================================ */

function buildFigureOverlay(
  figure: FigureAnnotation,
  baseWidth: number,
  baseHeight: number,
): FigureOverlayItem | null {
  const bbox = Array.isArray(figure.bbox) ? figure.bbox : []
  if (bbox.length < 4) return null
  const [x0, y0, x1, y1] = bbox.map(Number)
  if (![x0, y0, x1, y1].every(Number.isFinite)) return null
  const left = clamp(Math.min(x0, x1), 0, baseWidth)
  const top = clamp(Math.min(y0, y1), 0, baseHeight)
  const right = clamp(Math.max(x0, x1), 0, baseWidth)
  const bottom = clamp(Math.max(y0, y1), 0, baseHeight)
  if (right - left < 0.5 || bottom - top < 0.5) return null

  // 图表不再有编号/标签字段：叠加层固定展示“图/表”，标题只用 caption。
  const label = figure.kind === 'table' ? '表' : '图'
  const caption = typeof figure.caption === 'string' ? figure.caption.trim() : ''
  return {
    figure,
    label,
    title: caption || label,
    kindClass: figure.kind === 'table' ? 'is-table' : 'is-figure',
    style: {
      left: `${((left / baseWidth) * 100).toFixed(4)}%`,
      top: `${((top / baseHeight) * 100).toFixed(4)}%`,
      width: `${(((right - left) / baseWidth) * 100).toFixed(4)}%`,
      height: `${(((bottom - top) / baseHeight) * 100).toFixed(4)}%`,
    },
  }
}

/** 图片是单页文件，直接展示全部图表记录。 */
const imageFigureOverlays = computed<FigureOverlayItem[]>(() => {
  const baseWidth = imageNaturalWidth.value
  const baseHeight = imageNaturalHeight.value
  if (!(baseWidth > 0) || !(baseHeight > 0)) return []
  return figureLookup.value.flatMap((figure) => {
    const item = buildFigureOverlay(figure, baseWidth, baseHeight)
    return item ? [item] : []
  })
})

/**
 * PDF 图表按页分组：每组使用该页自己的 widthPt / heightPt 计算百分比，
 * 因此不同页面尺寸（横向页 / 竖向页）不会互相串位。
 */
const figuresByPage = computed<Map<number, FigureOverlayItem[]>>(() => {
  const map = new Map<number, FigureOverlayItem[]>()
  if (!isPdf.value) return map
  const dimensions = new Map(
    pages.value.map((entry) => [
      entry.page,
      { width: entry.widthPt, height: entry.heightPt },
    ]),
  )
  for (const figure of figureLookup.value) {
    const page = Number(figure.page) || 1
    const size = dimensions.get(page)
    if (!size) continue
    const item = buildFigureOverlay(figure, size.width, size.height)
    if (!item) continue
    const bucket = map.get(page)
    if (bucket) bucket.push(item)
    else map.set(page, [item])
  }
  return map
})

const selectionBoxStyle = computed<Record<string, string>>(() => {
  const current = selection.value
  if (!current) return {} as Record<string, string>
  const { rect } = current
  return {
    left: `${rect.left}px`,
    top: `${rect.top}px`,
    width: `${rect.width}px`,
    height: `${rect.height}px`,
  }
})

/* ============================================================
   加载与销毁
   ============================================================ */

async function loadSource(): Promise<void> {
  const token = ++loadToken
  await teardownDocument()
  if (token !== loadToken) return

  error.value = ''
  imageError.value = ''
  imageLoading.value = true
  loading.value = false
  captureMode.value = false
  selection.value = null
  imageNaturalWidth.value = 0
  imageNaturalHeight.value = 0
  pageCount.value = props.file.page_count || 0
  activePage.value = 1
  zoom.value = 1
  // 注意：这里绝不能清空 pendingCapture。
  // 主工具栏可能在 PDF 仍处于加载中时调用 startCapture，
  // 该请求必须保留到 canCapture 变为 true 后再消费。

  if (!isPdf.value) return

  loading.value = true
  try {
    const pdfjs = await loadPdfjs()
    if (token !== loadToken) return

    containerWidth.value = measureContainerWidth()

    const task = pdfjs.getDocument({
      url: sourceUrl.value,
      isEvalSupported: false,
    })
    loadingTask = task
    const document = await task.promise
    if (token !== loadToken) {
      await document.destroy()
      return
    }

    pdfDocument = document
    pageCount.value = document.numPages
    await buildPageEntries(document, token)
    if (token !== loadToken) return

    pdfReady.value = true
    await nextTick()
    if (token !== loadToken) return
    setupPageObserver()
    updateActivePage()
  } catch (cause) {
    if (token === loadToken && !isCancellation(cause)) {
      error.value = formatError(cause)
      pendingCapture.value = false
    }
  } finally {
    if (token === loadToken) loading.value = false
  }
}

/** 读取所有页的 scale=1 尺寸，生成连续滚动所需的占位条目。 */
async function buildPageEntries(
  document: PDFDocumentProxy,
  token: number,
): Promise<void> {
  const entries: PdfPageEntry[] = []
  for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
    const proxy = await document.getPage(pageNumber)
    if (token !== loadToken) return
    const viewport = proxy.getViewport({ scale: 1 })
    pageProxies.set(pageNumber, proxy)
    entries.push({
      page: pageNumber,
      widthPt: viewport.width,
      heightPt: viewport.height,
      rendered: false,
      renderedScale: 0,
      visible: false,
      renderError: '',
    })
  }
  pages.value = entries
}

async function teardownDocument(): Promise<void> {
  disconnectPageObserver()

  if (rerenderTimer) {
    clearTimeout(rerenderTimer)
    rerenderTimer = null
  }
  for (const task of renderTasks.values()) {
    try {
      task.cancel()
    } catch {
      // 渲染任务已经结束时 cancel 会抛错，忽略即可。
    }
  }
  renderTasks.clear()
  renderTokens.clear()
  queuedPages.clear()
  pageProxies.clear()
  pageElements.clear()
  canvasElements.clear()
  pages.value = []
  pdfReady.value = false

  if (pdfDocument) {
    const document = pdfDocument
    pdfDocument = null
    loadingTask = null
    try {
      await document.destroy()
    } catch {
      // 页面卸载阶段允许销毁失败。
    }
    return
  }

  if (loadingTask) {
    const task = loadingTask
    loadingTask = null
    try {
      await task.destroy()
    } catch {
      // 同上。
    }
  }
}

/* ============================================================
   页面尺寸与渲染
   ============================================================ */

function measureContainerWidth(): number {
  const width = scrollRef.value?.clientWidth ?? 640
  return Math.max(220, width - 32)
}

/** 页面在屏幕上的渲染比例：以“容器宽度适配”为基准再乘以用户缩放。 */
function pageScale(entry: PdfPageEntry): number {
  const width = entry.widthPt > 0 ? entry.widthPt : 1
  return clamp((containerWidth.value / width) * zoom.value, 0.15, 4)
}

function pageStageStyle(entry: PdfPageEntry): Record<string, string> {
  const scale = pageScale(entry)
  return {
    width: `${Math.max(1, Math.floor(entry.widthPt * scale))}px`,
    height: `${Math.max(1, Math.floor(entry.heightPt * scale))}px`,
  }
}

async function renderPage(entry: PdfPageEntry): Promise<void> {
  const document = pdfDocument
  if (!document || !isPdf.value || !entry.visible) return

  const canvas = canvasElements.get(entry.page)
  if (!canvas) return

  const scale = pageScale(entry)
  if (entry.rendered && Math.abs(entry.renderedScale - scale) < 0.001) return

  const page = pageProxies.get(entry.page)
  if (!page) return

  const token = (renderTokens.get(entry.page) ?? 0) + 1
  renderTokens.set(entry.page, token)

  const previous = renderTasks.get(entry.page)
  if (previous) {
    try {
      previous.cancel()
    } catch {
      // 已结束的任务忽略。
    }
    renderTasks.delete(entry.page)
  }

  const viewport = page.getViewport({ scale })
  const context = canvas.getContext('2d', { alpha: false })
  if (!context) {
    entry.renderError = '当前浏览器无法创建画布上下文'
    return
  }

  const ratio = Math.min(window.devicePixelRatio || 1, 2)
  canvas.width = Math.max(1, Math.floor(viewport.width * ratio))
  canvas.height = Math.max(1, Math.floor(viewport.height * ratio))

  context.save()
  context.fillStyle = '#ffffff'
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.restore()

  const task = page.render({
    canvasContext: context,
    viewport,
    transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined,
  })
  renderTasks.set(entry.page, task)

  try {
    await task.promise
    if (renderTokens.get(entry.page) !== token) return
    entry.rendered = true
    entry.renderedScale = scale
    entry.renderError = ''
  } catch (cause) {
    if (renderTokens.get(entry.page) === token && !isCancellation(cause)) {
      entry.renderError = formatError(cause)
    }
  } finally {
    if (renderTasks.get(entry.page) === task) renderTasks.delete(entry.page)
  }
}

function setPageElement(page: number, element: unknown): void {
  if (element instanceof HTMLElement) pageElements.set(page, element)
  else pageElements.delete(page)
}

function setCanvasElement(page: number, element: unknown): void {
  if (element instanceof HTMLCanvasElement) canvasElements.set(page, element)
  else canvasElements.delete(page)
}

/**
 * 懒渲染调度：canvas 通过 v-if 只在页面进入视口附近或已经渲染过时创建，
 * 因此首次看到某页时要等 DOM 挂载后才能拿到 canvas。
 */
function queuePageRender(entry: PdfPageEntry): void {
  if (!entry.visible) return
  if (queuedPages.has(entry.page)) return
  queuedPages.add(entry.page)
  void nextTick(() => {
    queuedPages.delete(entry.page)
    if (entry.visible) void renderPage(entry)
  })
}

/* ============================================================
   IntersectionObserver 懒渲染
   ============================================================ */

function disconnectPageObserver(): void {
  pageObserver?.disconnect()
  pageObserver = null
}

function setupPageObserver(): void {
  disconnectPageObserver()
  const root = scrollRef.value
  if (!root) return

  if (typeof IntersectionObserver === 'undefined') {
    // 极旧环境退化为渲染首屏两页，至少保证可截图。
    pages.value.slice(0, 2).forEach((entry) => {
      entry.visible = true
      queuePageRender(entry)
    })
    return
  }

  pageObserver = new IntersectionObserver(
    (records) => {
      for (const record of records) {
        const target = record.target as HTMLElement
        const page = Number(target.dataset.page)
        if (!Number.isFinite(page)) continue
        const entry = pages.value[page - 1]
        if (!entry) continue
        entry.visible = record.isIntersecting
        if (record.isIntersecting) queuePageRender(entry)
      }
    },
    {
      root,
      rootMargin: '300px 0px',
      threshold: 0,
    },
  )

  for (const entry of pages.value) {
    const element = pageElements.get(entry.page)
    if (element) pageObserver.observe(element)
  }
}

/* ============================================================
   缩放 / 容器尺寸
   ============================================================ */

interface ScrollAnchor {
  page: number
  ratio: number
}

/** 记录“视口顶部落在哪一页的百分比位置”，用于布局变化后恢复滚动。 */
function captureScrollAnchor(): ScrollAnchor | null {
  const root = scrollRef.value
  if (!root || !pages.value.length) return null
  const rootRect = root.getBoundingClientRect()
  let fallback: ScrollAnchor | null = null

  for (const entry of pages.value) {
    const element = pageElements.get(entry.page)
    if (!element) continue
    const rect = element.getBoundingClientRect()
    fallback = {
      page: entry.page,
      ratio: clamp((rootRect.top - rect.top) / Math.max(1, rect.height), 0, 1),
    }
    if (rect.bottom > rootRect.top + 1) {
      return {
        page: entry.page,
        ratio: clamp((rootRect.top - rect.top) / Math.max(1, rect.height), 0, 1),
      }
    }
  }

  return fallback
}

function restoreScrollAnchor(anchor: ScrollAnchor | null): void {
  if (!anchor) return
  const root = scrollRef.value
  const element = pageElements.get(anchor.page)
  if (!root || !element) return

  const rootRect = root.getBoundingClientRect()
  const rect = element.getBoundingClientRect()
  // 页面内容偏移与当前滚动无关：rect.top - rootRect.top + scrollTop。
  const contentTop = rect.top - rootRect.top + root.scrollTop
  // 缩放 / 容器尺寸变化属于布局维护，不应反向驱动 Markdown 滚动。
  suppressOwnScroll()
  root.scrollTop = Math.max(0, contentTop + anchor.ratio * rect.height)
}

async function setZoom(next: number): Promise<void> {
  const value = clamp(Math.round(next * 100) / 100, 0.5, 2.5)
  if (value === zoom.value) return

  const anchor = captureScrollAnchor()
  zoom.value = value
  await nextTick()
  restoreScrollAnchor(anchor)
  updateActivePage()
  scheduleVisibleRerender()
}

function changeZoom(delta: number): void {
  void setZoom(zoom.value + delta)
}

function fitWidth(): void {
  void setZoom(1)
}

/** 缩放 / 尺寸变化后，只重渲染当前可见的已渲染页；其余页进入视口时自行补齐。 */
function scheduleVisibleRerender(delay = 120): void {
  if (rerenderTimer) clearTimeout(rerenderTimer)
  rerenderTimer = setTimeout(() => {
    rerenderTimer = null
    if (!isPdf.value) return
    for (const entry of pages.value) {
      if (entry.visible) queuePageRender(entry)
    }
  }, delay)
}

function scheduleLayoutUpdate(): void {
  if (layoutTimer) clearTimeout(layoutTimer)
  layoutTimer = setTimeout(() => {
    layoutTimer = null
    void applyLayoutUpdate()
  }, 180)
}

async function applyLayoutUpdate(): Promise<void> {
  if (!isPdf.value || !pdfReady.value) return
  const width = measureContainerWidth()
  if (Math.abs(width - containerWidth.value) < 0.5) return

  const anchor = captureScrollAnchor()
  containerWidth.value = width
  await nextTick()
  restoreScrollAnchor(anchor)
  scheduleVisibleRerender()
}

/* ============================================================
   滚动位置
   ============================================================ */

function clampRatio(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.min(1, Math.max(0, value))
}

function scrollRatioOf(element: HTMLElement): number {
  // 分母至少为 1，避免不可滚动时除以 0。
  return clampRatio(element.scrollTop / Math.max(1, element.scrollHeight - element.clientHeight))
}

/**
 * 程序化滚动后屏蔽自身 scroll 事件。
 *
 * 标志在下一帧的 rAF 回调里清除；scroll 事件在同一帧的渲染步骤中先于
 * rAF 回调派发，因此事件处理器读取到的仍是 true，可可靠跳过回传，
 * 避免 PDF ↔ Markdown 的 A→B→A 回环。
 */
function suppressOwnScroll(): void {
  ignoringScroll = true
  if (suppressRaf) cancelAnimationFrame(suppressRaf)
  suppressRaf = requestAnimationFrame(() => {
    suppressRaf = 0
    ignoringScroll = false
  })
}

function handleScroll(): void {
  const root = scrollRef.value
  if (!root) return
  // 程序化滚动的 scroll 事件在事件阶段跳过上报；页码指示仍需更新。
  const programmatic = ignoringScroll
  if (scrollRaf) return
  scrollRaf = requestAnimationFrame(() => {
    scrollRaf = 0
    updateActivePage()
    if (programmatic) return
    emit('scroll-state', scrollRatioOf(root))
  })
}

/** 外部（MixedWorkspace）按比例设置滚动位置；图片模式不参与同步。 */
function setScrollRatio(ratio: number): void {
  const root = scrollRef.value
  if (!root || !isPdf.value) return
  const max = root.scrollHeight - root.clientHeight
  if (max <= 0) return
  const target = clampRatio(ratio) * max
  if (Math.abs(target - root.scrollTop) < 1) return
  suppressOwnScroll()
  root.scrollTop = target
}

function getScrollRatio(): number {
  const root = scrollRef.value
  if (!root || !isPdf.value) return 0
  return scrollRatioOf(root)
}

function updateActivePage(): void {
  const root = scrollRef.value
  if (!root || !pages.value.length) return
  // 用视口上方 1/4 处作为“当前页”判定线，更贴近视觉感受。
  // offsetTop / offsetHeight 相对滚动容器，滚动期间读取不会反复触发布局，
  // 对上百页文档也比逐页 getBoundingClientRect 便宜得多。
  const line = root.scrollTop + Math.min(72, root.clientHeight * 0.25)
  let current = 1

  for (const entry of pages.value) {
    const element = pageElements.get(entry.page)
    if (!element) continue
    current = entry.page
    if (element.offsetTop + element.offsetHeight > line) break
  }

  if (activePage.value !== current) activePage.value = current
}

function jumpToPage(page: number): void {
  const total = pageCount.value || pages.value.length
  if (!total) return
  const next = clamp(Math.round(page), 1, total)
  activePage.value = next

  const root = scrollRef.value
  const element = pageElements.get(next)
  if (!root || !element) return
  const rootRect = root.getBoundingClientRect()
  const target =
    element.getBoundingClientRect().top -
    rootRect.top +
    root.scrollTop -
    SCROLL_ANCHOR_OFFSET

  root.scrollTo({ top: Math.max(0, target), behavior: 'smooth' })
}

function handlePageInput(event: Event): void {
  const input = event.target as HTMLInputElement
  const value = Number(input.value)
  if (Number.isFinite(value)) jumpToPage(value)
  input.value = String(activePage.value)
}

/* ============================================================
   图片加载
   ============================================================ */

function handleImageLoaded(event: Event): void {
  const image = event.target as HTMLImageElement
  imageNaturalWidth.value = image.naturalWidth || 0
  imageNaturalHeight.value = image.naturalHeight || 0
  imageLoading.value = false
}

function handleImageError(): void {
  imageLoading.value = false
  imageError.value = '原图加载失败，请检查文件是否仍然存在。'
  pendingCapture.value = false
}

/* ============================================================
   拖框截图
   ============================================================ */

function toggleCaptureMode(): void {
  if (!canCapture.value) return
  captureMode.value = !captureMode.value
  selection.value = null
}

function exitCaptureMode(): void {
  captureMode.value = false
  selection.value = null
  pendingCapture.value = false
}

/**
 * 外部入口：进入拖框截图模式。
 * 若当前还不能截图（PDF 仍在加载、图片未加载完成），先记下请求，
 * 由 canCapture 的 watch 在就绪后自动进入，避免主工具栏按钮点了没反应。
 */
function startCapture(): void {
  if (canCapture.value) {
    pendingCapture.value = false
    if (!captureMode.value) {
      captureMode.value = true
      selection.value = null
    }
    return
  }
  if (error.value || imageError.value) return
  pendingCapture.value = true
}

function selectFigure(figure: FigureAnnotation): void {
  if (captureMode.value) return
  emit('figure-selected', figure)
}

let dragPointerId: number | null = null
let dragPage: number | null = null
let dragOrigin: { x: number; y: number } | null = null

interface PageBaseSize {
  width: number
  height: number
}

function pageBaseSize(page: number): PageBaseSize | null {
  if (!isPdf.value) {
    if (!(imageNaturalWidth.value > 0) || !(imageNaturalHeight.value > 0)) return null
    return { width: imageNaturalWidth.value, height: imageNaturalHeight.value }
  }
  const entry = pages.value[page - 1]
  if (!entry || !(entry.widthPt > 0) || !(entry.heightPt > 0)) return null
  return { width: entry.widthPt, height: entry.heightPt }
}

function handleSelectionPointerDown(event: PointerEvent, page: number): void {
  if (!captureMode.value || event.button !== 0) return
  const layer = event.currentTarget as HTMLElement | null
  if (!layer) return

  const bounds = layer.getBoundingClientRect()
  if (bounds.width <= 0 || bounds.height <= 0) return
  if (!pageBaseSize(page)) return

  const point = clampPointToLayer(event, bounds)
  dragPointerId = event.pointerId
  dragPage = page
  dragOrigin = point
  selection.value = {
    page,
    rect: { left: point.x, top: point.y, width: 0, height: 0 },
  }
  try {
    layer.setPointerCapture(event.pointerId)
  } catch {
    // 合成事件等场景下 pointerId 可能未激活，拖框本身不依赖指针捕获。
  }
  event.preventDefault()
}

function handleSelectionPointerMove(event: PointerEvent, page: number): void {
  if (dragPointerId !== event.pointerId || dragPage !== page || !dragOrigin) return
  const layer = event.currentTarget as HTMLElement | null
  if (!layer) return
  const bounds = layer.getBoundingClientRect()
  const point = clampPointToLayer(event, bounds)
  selection.value = { page, rect: normalizeRect(dragOrigin, point) }
  event.preventDefault()
}

function handleSelectionPointerUp(event: PointerEvent, page: number): void {
  if (dragPointerId !== event.pointerId || dragPage !== page) return
  const layer = event.currentTarget as HTMLElement | null
  dragPointerId = null
  dragPage = null
  dragOrigin = null
  try {
    layer?.releasePointerCapture?.(event.pointerId)
  } catch {
    // 指针捕获可能从未建立（合成事件），忽略即可。
  }

  const current = selection.value
  const rect = current && current.page === page ? current.rect : null
  if (!layer || !rect || rect.width < MIN_SELECTION_PX || rect.height < MIN_SELECTION_PX) {
    selection.value = null
    return
  }

  const bounds = layer.getBoundingClientRect()
  const base = pageBaseSize(page)
  if (!base || bounds.width <= 0 || bounds.height <= 0) {
    selection.value = null
    return
  }

  const scaleX = base.width / bounds.width
  const scaleY = base.height / bounds.height
  const x0 = clamp(rect.left * scaleX, 0, base.width)
  const y0 = clamp(rect.top * scaleY, 0, base.height)
  const x1 = clamp((rect.left + rect.width) * scaleX, 0, base.width)
  const y1 = clamp((rect.top + rect.height) * scaleY, 0, base.height)
  if (x1 - x0 < 0.5 || y1 - y0 < 0.5) {
    selection.value = null
    return
  }

  const previewUrl = buildSelectionPreview(page, rect, bounds)
  selection.value = null
  captureMode.value = false

  emit('region-selected', {
    page: isPdf.value ? page : 1,
    bbox: [round2(x0), round2(y0), round2(x1), round2(y1)],
    previewUrl,
  })
}

function handleSelectionPointerCancel(event: PointerEvent): void {
  if (dragPointerId !== event.pointerId) return
  dragPointerId = null
  dragPage = null
  dragOrigin = null
  selection.value = null
}

function clampPointToLayer(
  event: PointerEvent,
  bounds: DOMRect,
): { x: number; y: number } {
  return {
    x: clamp(event.clientX - bounds.left, 0, bounds.width),
    y: clamp(event.clientY - bounds.top, 0, bounds.height),
  }
}

function normalizeRect(
  origin: { x: number; y: number },
  point: { x: number; y: number },
): SelectionRect {
  return {
    left: Math.min(origin.x, point.x),
    top: Math.min(origin.y, point.y),
    width: Math.abs(point.x - origin.x),
    height: Math.abs(point.y - origin.y),
  }
}

/** 用目标页当前屏幕画面快速生成弹窗预览，不触发任何离屏重渲染。 */
function buildSelectionPreview(
  page: number,
  rect: SelectionRect,
  bounds: DOMRect,
): string | undefined {
  try {
    const canvas = document.createElement('canvas')
    let source: CanvasImageSource | null = null
    let sourceWidth = 0
    let sourceHeight = 0

    if (isPdf.value) {
      const screenCanvas = canvasElements.get(page)
      if (!screenCanvas || !screenCanvas.width || !screenCanvas.height) {
        return undefined
      }
      source = screenCanvas
      sourceWidth = screenCanvas.width
      sourceHeight = screenCanvas.height
    } else {
      const image = imageRef.value
      if (!image || !image.complete) return undefined
      source = image
      sourceWidth = image.naturalWidth
      sourceHeight = image.naturalHeight
    }

    if (!(sourceWidth > 0) || !(sourceHeight > 0)) return undefined

    const scaleX = sourceWidth / bounds.width
    const scaleY = sourceHeight / bounds.height
    const cropX = clamp(rect.left * scaleX, 0, sourceWidth)
    const cropY = clamp(rect.top * scaleY, 0, sourceHeight)
    const cropW = clamp(rect.width * scaleX, 1, sourceWidth - cropX)
    const cropH = clamp(rect.height * scaleY, 1, sourceHeight - cropY)
    if (cropW <= 0 || cropH <= 0) return undefined

    const shrink = Math.min(1, PREVIEW_MAX_EDGE / Math.max(cropW, cropH))
    canvas.width = Math.max(1, Math.round(cropW * shrink))
    canvas.height = Math.max(1, Math.round(cropH * shrink))
    const context = canvas.getContext('2d', { alpha: false })
    if (!context) return undefined
    context.fillStyle = '#ffffff'
    context.fillRect(0, 0, canvas.width, canvas.height)
    context.imageSmoothingQuality = 'high'
    context.drawImage(
      source,
      cropX,
      cropY,
      cropW,
      cropH,
      0,
      0,
      canvas.width,
      canvas.height,
    )
    return canvas.toDataURL('image/png')
  } catch {
    // 预览只是锦上添花，失败时不影响正式截图流程。
    return undefined
  }
}

/* ============================================================
   高清截图
   ============================================================ */

/**
 * 按 bbox 生成高清 PNG。
 * - PDF：离屏重新渲染 page 指定的那一页（200 DPI），只绘制选区；
 * - 图片：单图模式，page 恒为 1，按原始像素裁剪。
 */
async function captureRegion(bbox: number[], page = 1): Promise<Blob> {
  const values = Array.isArray(bbox) ? bbox.slice(0, 4).map(Number) : []
  if (values.length !== 4 || !values.every(Number.isFinite)) {
    throw new Error('截图范围不合法')
  }
  const [x0, y0, x1, y1] = values
  if (x1 <= x0 || y1 <= y0) throw new Error('截图范围不合法')

  return isPdf.value
    ? capturePdfRegion(page, x0, y0, x1, y1)
    : captureImageRegion(x0, y0, x1, y1)
}

async function capturePdfRegion(
  pageNumber: number,
  x0: number,
  y0: number,
  x1: number,
  y1: number,
): Promise<Blob> {
  const pdf = pdfDocument
  if (!pdf) throw new Error('PDF 尚未加载完成，无法截图')

  const total = pageCount.value || pdf.numPages || 1
  const target = clamp(Math.round(pageNumber) || 1, 1, total)
  const page = await pdf.getPage(target)
  const baseViewport = page.getViewport({ scale: 1 })
  const baseWidth = baseViewport.width
  const baseHeight = baseViewport.height
  if (!(baseWidth > 0) || !(baseHeight > 0)) throw new Error('页面尺寸无效')

  const left = clamp(x0, 0, baseWidth)
  const top = clamp(y0, 0, baseHeight)
  const right = clamp(x1, 0, baseWidth)
  const bottom = clamp(y1, 0, baseHeight)
  if (right - left < 0.5 || bottom - top < 0.5) throw new Error('截图范围过小')

  const scale = limitCaptureScale(CAPTURE_DPI / 72, baseWidth, baseHeight)
  const viewport = page.getViewport({ scale })
  const cropX = Math.floor(left * scale)
  const cropY = Math.floor(top * scale)
  const cropWidth = Math.max(1, Math.ceil((right - left) * scale))
  const cropHeight = Math.max(1, Math.ceil((bottom - top) * scale))

  // 使用 transform 把页面平移到选区原点，避免先渲染整页再二次裁剪。
  const canvas = document.createElement('canvas')
  canvas.width = cropWidth
  canvas.height = cropHeight
  const context = canvas.getContext('2d', { alpha: false })
  if (!context) throw new Error('当前浏览器无法创建画布上下文')

  context.fillStyle = '#ffffff'
  context.fillRect(0, 0, cropWidth, cropHeight)

  const task = page.render({
    canvasContext: context,
    viewport,
    transform: [1, 0, 0, 1, -cropX, -cropY],
  })
  await task.promise

  return canvasToPngBlob(canvas)
}

async function captureImageRegion(
  x0: number,
  y0: number,
  x1: number,
  y1: number,
): Promise<Blob> {
  const image = await loadCaptureImage()
  const naturalWidth = image.naturalWidth
  const naturalHeight = image.naturalHeight
  if (!(naturalWidth > 0) || !(naturalHeight > 0)) {
    throw new Error('原图尺寸无效')
  }

  const left = clamp(x0, 0, naturalWidth)
  const top = clamp(y0, 0, naturalHeight)
  const right = clamp(x1, 0, naturalWidth)
  const bottom = clamp(y1, 0, naturalHeight)
  const cropWidth = right - left
  const cropHeight = bottom - top
  if (cropWidth < 0.5 || cropHeight < 0.5) throw new Error('截图范围过小')

  const scale = Math.min(
    1,
    MAX_CAPTURE_EDGE / cropWidth,
    MAX_CAPTURE_EDGE / cropHeight,
    Math.sqrt(MAX_CAPTURE_AREA / (cropWidth * cropHeight)),
  )
  const outputWidth = Math.max(1, Math.round(cropWidth * scale))
  const outputHeight = Math.max(1, Math.round(cropHeight * scale))

  const canvas = document.createElement('canvas')
  canvas.width = outputWidth
  canvas.height = outputHeight
  const context = canvas.getContext('2d', { alpha: false })
  if (!context) throw new Error('当前浏览器无法创建画布上下文')

  context.fillStyle = '#ffffff'
  context.fillRect(0, 0, outputWidth, outputHeight)
  context.imageSmoothingQuality = 'high'
  context.drawImage(
    image,
    left,
    top,
    cropWidth,
    cropHeight,
    0,
    0,
    outputWidth,
    outputHeight,
  )
  return canvasToPngBlob(canvas)
}

/** 优先使用已加载的 <img>；尚未完成时重新加载并等待 decode。 */
async function loadCaptureImage(): Promise<HTMLImageElement> {
  const existing = imageRef.value
  if (existing && existing.complete && existing.naturalWidth > 0) return existing

  const image = new Image()
  image.decoding = 'async'
  image.src = sourceUrl.value
  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve()
    image.onerror = () => reject(new Error('原图加载失败，无法截图'))
  })
  return image
}

/** 限制离屏 canvas 边长与总面积，规避浏览器 canvas 上限导致 toBlob 失败。 */
function limitCaptureScale(
  preferred: number,
  pageWidth: number,
  pageHeight: number,
): number {
  if (!(pageWidth > 0) || !(pageHeight > 0)) return preferred
  const edgeLimit = Math.min(
    MAX_CAPTURE_EDGE / pageWidth,
    MAX_CAPTURE_EDGE / pageHeight,
  )
  const areaLimit = Math.sqrt(MAX_CAPTURE_AREA / (pageWidth * pageHeight))
  return Math.max(0.05, Math.min(preferred, edgeLimit, areaLimit))
}

function canvasToPngBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    try {
      canvas.toBlob((blob) => {
        if (blob) resolve(blob)
        else reject(new Error('截图生成失败，请重试'))
      }, 'image/png')
    } catch (cause) {
      reject(cause instanceof Error ? cause : new Error('截图生成失败，请重试'))
    }
  })
}

/* ============================================================
   工具函数
   ============================================================ */

function round2(value: number): number {
  return Math.round(value * 100) / 100
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function isCancellation(cause: unknown): boolean {
  if (!cause || typeof cause !== 'object') return false
  return (cause as { name?: string }).name === 'RenderingCancelledException'
}

function formatError(cause: unknown): string {
  if (cause instanceof Error && cause.message) return cause.message
  return String(cause)
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && captureMode.value) {
    event.preventDefault()
    exitCaptureMode()
  }
}

// 延迟请求：资源就绪后自动进入截图模式。
watch(canCapture, (ready) => {
  if (!ready || !pendingCapture.value) return
  pendingCapture.value = false
  if (!captureMode.value) {
    captureMode.value = true
    selection.value = null
  }
})

/**
 * 供 MixedWorkspace 使用：
 * - startCapture：外部触发截图模式（预览头部按钮仍是主要入口）；
 * - captureRegion：弹窗确认后按 bbox + 页码生成高清截图；
 * - setScrollRatio / getScrollRatio：与 Markdown 画布同步滚动。
 */
defineExpose({ captureRegion, startCapture, setScrollRatio, getScrollRatio })

/* ============================================================
   生命周期
   ============================================================ */

watch(
  () => props.file.id,
  () => {
    // 只有文件真正切换时才丢弃旧的截图请求；加载过程本身必须保留。
    pendingCapture.value = false
    void loadSource()
  },
  { immediate: true },
)

onMounted(() => {
  window.addEventListener('resize', scheduleLayoutUpdate)
  window.addEventListener('keydown', handleKeydown)
  if (typeof ResizeObserver !== 'undefined' && scrollRef.value) {
    resizeObserver = new ResizeObserver(scheduleLayoutUpdate)
    resizeObserver.observe(scrollRef.value)
  }
})

onBeforeUnmount(() => {
  loadToken += 1
  pendingCapture.value = false
  if (layoutTimer) clearTimeout(layoutTimer)
  layoutTimer = null
  if (rerenderTimer) clearTimeout(rerenderTimer)
  rerenderTimer = null
  if (scrollRaf) cancelAnimationFrame(scrollRaf)
  scrollRaf = 0
  if (suppressRaf) cancelAnimationFrame(suppressRaf)
  suppressRaf = 0
  ignoringScroll = false
  resizeObserver?.disconnect()
  resizeObserver = null
  window.removeEventListener('resize', scheduleLayoutUpdate)
  window.removeEventListener('keydown', handleKeydown)
  void teardownDocument()
})
</script>

<template>
  <aside class="pdf-preview" aria-label="原始文件预览">
    <header class="pdf-head">
      <div class="pdf-head-copy">
        <span class="pdf-eyebrow">{{ sourceLabel }}</span>
        <h2 class="pdf-title" :title="file.name">{{ file.name }}</h2>
      </div>
      <div class="pdf-head-actions">
        <button
          type="button"
          class="head-capture"
          :class="{ 'is-active': captureMode }"
          :disabled="!canCapture"
          :aria-pressed="captureMode"
          :title="captureMode ? '退出图片／表格标注（Esc）' : '拖拽框选区域并标注为图片或表格'"
          @click="toggleCaptureMode"
        >
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M6 2v14a2 2 0 0 0 2 2h14" />
            <path d="M18 22V8a2 2 0 0 0-2-2H2" />
          </svg>
          {{ captureMode ? '退出标注' : '图片／表格标注' }}
        </button>
        <span class="pdf-type">{{ isPdf ? 'PDF' : 'IMG' }}</span>
        <button type="button" class="icon-btn" title="关闭预览" aria-label="关闭预览" @click="emit('close')">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>
    </header>

    <div v-if="captureMode" class="capture-banner" role="status">
      拖拽框选要标注为图片或表格的区域（任意页均可），按 Esc 退出标注模式
    </div>
    <div v-else-if="pendingCapture" class="capture-notice" role="status">
      正在等待预览加载完成，就绪后将自动进入图片／表格标注模式…
    </div>

    <template v-if="!isPdf">
      <div class="image-stage">
        <div v-if="!imageError" class="image-frame">
          <img
            ref="imageRef"
            class="source-image"
            :src="sourceUrl"
            :alt="file.name"
            @load="handleImageLoaded"
            @error="handleImageError"
          />
          <div class="figure-layer" aria-label="已有图表区域">
            <button
              v-for="item in imageFigureOverlays"
              :key="item.figure.id"
              type="button"
              class="figure-box"
              :class="item.kindClass"
              :style="item.style"
              :title="item.title"
              :aria-label="item.title"
              @click.stop="selectFigure(item.figure)"
            >
              <span class="figure-box-label">{{ item.label }}</span>
            </button>
          </div>
          <div
            v-if="captureMode"
            class="selection-layer"
            @pointerdown="handleSelectionPointerDown($event, 1)"
            @pointermove="handleSelectionPointerMove($event, 1)"
            @pointerup="handleSelectionPointerUp($event, 1)"
            @pointercancel="handleSelectionPointerCancel"
          >
            <div
              v-if="selection && selection.page === 1"
              class="selection-box"
              :style="selectionBoxStyle"
            ></div>
          </div>
        </div>
        <div v-if="imageLoading && !imageError" class="image-state">
          <span class="loading-bar" aria-hidden="true"></span>
          <span>正在加载原图…</span>
        </div>
        <div v-if="imageError" class="image-state image-state--error">
          <strong>预览不可用</strong>
          <span>{{ imageError }}</span>
        </div>
      </div>
    </template>

    <template v-else>
      <div class="pdf-toolbar">
        <div class="pager" role="group" aria-label="PDF 页码">
          <span class="page-readout">
            第
            <input
              class="page-input"
              type="number"
              min="1"
              :max="pageCount || 1"
              :value="activePage"
              aria-label="跳转页码"
              @change="handlePageInput"
            />
            / {{ pageCount || '—' }} 页
          </span>
        </div>

        <div class="zoomer" role="group" aria-label="PDF 缩放">
          <button type="button" class="icon-btn icon-btn--text" :disabled="zoom <= 0.5" title="缩小" aria-label="缩小" @click="changeZoom(-0.15)">
            −
          </button>
          <button type="button" class="zoom-readout" title="恢复适应宽度" @click="fitWidth">
            {{ zoomPercent }}
          </button>
          <button type="button" class="icon-btn icon-btn--text" :disabled="zoom >= 2.5" title="放大" aria-label="放大" @click="changeZoom(0.15)">
            +
          </button>
        </div>
      </div>

      <div ref="scrollRef" class="pdf-scroll" @scroll.passive="handleScroll">
        <div v-if="error" class="pdf-status pdf-status--error" role="alert">
          <strong>PDF 预览失败</strong>
          <span>{{ error }}</span>
        </div>
        <div v-else-if="loading && !pages.length" class="pdf-status pdf-status--loading" aria-live="polite">
          <span class="loading-bar" aria-hidden="true"></span>
          <span>正在打开 PDF…</span>
        </div>
        <div v-else-if="!pages.length" class="pdf-status">
          <span>PDF 没有可预览的页面。</span>
        </div>
        <div v-else class="pdf-pages" :style="{ gap: `${PAGE_GAP}px` }">
          <div
            v-for="entry in pages"
            :key="entry.page"
            class="pdf-page"
            :data-page="entry.page"
            :ref="(element) => setPageElement(entry.page, element)"
          >
            <div class="page-stage" :style="pageStageStyle(entry)">
              <canvas
                v-if="entry.visible || entry.rendered"
                :ref="(element) => setCanvasElement(entry.page, element)"
                class="pdf-canvas"
                :aria-label="`第 ${entry.page} 页`"
              ></canvas>

              <div class="figure-layer" aria-label="已有图表区域">
                <button
                  v-for="item in figuresByPage.get(entry.page) ?? []"
                  :key="item.figure.id"
                  type="button"
                  class="figure-box"
                  :class="item.kindClass"
                  :style="item.style"
                  :title="item.title"
                  :aria-label="item.title"
                  @click.stop="selectFigure(item.figure)"
                >
                  <span class="figure-box-label">{{ item.label }}</span>
                </button>
              </div>

              <div
                v-if="captureMode"
                class="selection-layer"
                @pointerdown="handleSelectionPointerDown($event, entry.page)"
                @pointermove="handleSelectionPointerMove($event, entry.page)"
                @pointerup="handleSelectionPointerUp($event, entry.page)"
                @pointercancel="handleSelectionPointerCancel"
              >
                <div
                  v-if="selection && selection.page === entry.page"
                  class="selection-box"
                  :style="selectionBoxStyle"
                ></div>
              </div>

              <div v-if="entry.renderError" class="page-note page-note--error">
                第 {{ entry.page }} 页渲染失败：{{ entry.renderError }}
              </div>
              <div v-else-if="entry.visible && !entry.rendered" class="page-note">
                正在渲染第 {{ entry.page }} 页…
              </div>
            </div>
            <span class="page-label">{{ entry.page }}</span>
          </div>
        </div>
      </div>
    </template>
  </aside>
</template>

<style scoped>
.pdf-preview {
  --pp-surface: var(--surface, #fffdf9);
  --pp-raised: var(--surface-raised, #fff);
  --pp-sunken: var(--surface-sunken, #f2eee6);
  --pp-paper: var(--paper, #f6f3ec);
  --pp-ink: var(--ink, #17181b);
  --pp-ink-2: var(--ink-2, #3e4147);
  --pp-ink-3: var(--ink-3, #6e727a);
  --pp-ink-4: var(--ink-4, #9a9da3);
  --pp-line: var(--line, #e2dccf);
  --pp-line-strong: var(--line-strong, #d2caba);
  --pp-signal: var(--signal, #e4572e);
  --pp-signal-soft: var(--signal-soft, #fbe8e1);
  --pp-signal-ink: var(--signal-ink, #8e2f14);
  --pp-danger: var(--danger, #b5403a);
  --pp-mono: var(--font-mono, 'Geist Mono', ui-monospace, Consolas, monospace);
  --pp-display: var(--font-display, 'Instrument Serif', Georgia, serif);
  --pp-ease: var(--ease-out, cubic-bezier(0.22, 1, 0.36, 1));
  --pp-shadow: var(--shadow, 0 18px 44px -28px rgba(35, 29, 19, 0.22));

  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--pp-line);
  border-radius: 18px;
  background: var(--pp-surface);
  box-shadow: var(--pp-shadow);
  animation: pp-in 220ms var(--pp-ease) both;
}

.pdf-head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
  padding: 12px 14px;
  border-bottom: 1px solid var(--pp-line);
}

.pdf-head-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.pdf-eyebrow {
  font-family: var(--pp-mono);
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--pp-ink-3);
}

.pdf-title {
  margin: 0;
  overflow: hidden;
  color: var(--pp-ink);
  font-size: 12.5px;
  font-weight: 600;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pdf-head-actions {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-shrink: 0;
}

.pdf-type {
  padding: 2px 6px;
  border: 1px solid var(--pp-line);
  border-radius: 5px;
  background: var(--pp-sunken);
  color: var(--pp-ink-3);
  font-family: var(--pp-mono);
  font-size: 8.5px;
  font-weight: 500;
  letter-spacing: 0.08em;
}

.head-capture {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 9px;
  border: 1px solid var(--pp-line);
  border-radius: 7px;
  background: var(--pp-surface);
  color: var(--pp-ink-2);
  font-family: inherit;
  font-size: 11px;
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
  transition:
    background-color 180ms var(--pp-ease),
    border-color 180ms var(--pp-ease),
    color 180ms var(--pp-ease);
}

.head-capture:hover:not(:disabled) {
  border-color: var(--pp-line-strong);
  background: var(--pp-raised);
  color: var(--pp-ink);
}

.head-capture:disabled {
  opacity: 0.36;
  cursor: not-allowed;
}

.head-capture.is-active {
  border-color: rgba(228, 87, 46, 0.32);
  background: var(--pp-signal-soft);
  color: var(--pp-signal-ink);
  font-weight: 600;
}

.capture-banner,
.capture-notice {
  flex-shrink: 0;
  padding: 6px 14px;
  border-bottom: 1px solid var(--pp-line);
  font-size: 10.5px;
  font-weight: 500;
  letter-spacing: 0.01em;
}

.capture-banner {
  background: var(--pp-signal-soft);
  color: var(--pp-signal-ink);
}

.capture-notice {
  background: var(--pp-sunken);
  color: var(--pp-ink-3);
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid var(--pp-line);
  border-radius: 7px;
  background: var(--pp-surface);
  color: var(--pp-ink-3);
  font-family: inherit;
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
  transition:
    background-color 180ms var(--pp-ease),
    border-color 180ms var(--pp-ease),
    color 180ms var(--pp-ease);
}

.icon-btn:hover:not(:disabled) {
  border-color: var(--pp-line-strong);
  background: var(--pp-raised);
  color: var(--pp-ink);
}

.icon-btn:disabled {
  opacity: 0.36;
  cursor: not-allowed;
}

.icon-btn--text {
  font-family: var(--pp-mono);
  font-size: 15px;
}

.pdf-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-shrink: 0;
  padding: 8px 12px;
  border-bottom: 1px solid var(--pp-line);
  background: var(--pp-sunken);
}

.pager,
.zoomer {
  display: flex;
  align-items: center;
  gap: 4px;
}

.page-readout {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0 2px;
  font-family: var(--pp-mono);
  font-size: 10.5px;
  color: var(--pp-ink-3);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.page-input {
  width: 38px;
  height: 25px;
  padding: 0 3px;
  border: 1px solid var(--pp-line);
  border-radius: 5px;
  background: var(--pp-raised);
  color: var(--pp-ink);
  font-family: inherit;
  font-size: 10.5px;
  text-align: center;
  outline: none;
}

.page-input:focus {
  border-color: var(--pp-signal);
  box-shadow: 0 0 0 2px var(--pp-signal-soft);
}

.page-input::-webkit-outer-spin-button,
.page-input::-webkit-inner-spin-button {
  margin: 0;
  appearance: none;
}

.zoom-readout {
  min-width: 48px;
  height: 25px;
  padding: 0 6px;
  border: 1px solid transparent;
  border-radius: 5px;
  background: transparent;
  color: var(--pp-ink-2);
  font-family: var(--pp-mono);
  font-size: 10px;
  cursor: pointer;
  font-variant-numeric: tabular-nums;
}

.zoom-readout:hover {
  background: var(--pp-raised);
  border-color: var(--pp-line);
}

.pdf-scroll {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 16px;
  background-color: var(--pp-sunken);
  background-image: radial-gradient(rgba(23, 24, 27, 0.045) 1px, transparent 1px);
  background-size: 14px 14px;
  scrollbar-width: thin;
}

.pdf-pages {
  display: flex;
  flex-direction: column;
  align-items: center;
  align-items: safe center;
  width: max-content;
  min-width: 100%;
}

.pdf-page {
  display: flex;
  flex: 0 0 auto;
  flex-direction: column;
  align-items: center;
  gap: 5px;
}

.page-stage {
  position: relative;
  display: block;
  flex: 0 0 auto;
  overflow: hidden;
  border-radius: 3px;
  background: #fff;
  box-shadow:
    0 1px 2px rgba(35, 29, 19, 0.08),
    0 18px 40px -24px rgba(35, 29, 19, 0.3);
}

.pdf-canvas {
  display: block;
  width: 100%;
  height: 100%;
  background: #fff;
}

.page-label {
  font-family: var(--pp-mono);
  font-size: 9px;
  line-height: 1;
  color: var(--pp-ink-4);
  font-variant-numeric: tabular-nums;
}

.page-note {
  position: absolute;
  inset: 0;
  z-index: 3;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: rgba(255, 253, 249, 0.55);
  color: var(--pp-ink-4);
  font-size: 11px;
  text-align: center;
  pointer-events: none;
}

.page-note--error {
  background: rgba(250, 236, 234, 0.85);
  color: var(--pp-danger);
}

/* 图表矩形与拖框层：百分比定位随画布缩放自动适配。 */
.figure-layer {
  position: absolute;
  inset: 0;
  z-index: 2;
  pointer-events: none;
}

.figure-box {
  position: absolute;
  margin: 0;
  padding: 0;
  border: 1.5px solid var(--pp-signal);
  border-radius: 3px;
  background: rgba(228, 87, 46, 0.1);
  color: var(--pp-signal-ink);
  cursor: pointer;
  pointer-events: auto;
  transition:
    background-color 160ms var(--pp-ease),
    box-shadow 160ms var(--pp-ease);
}

.figure-box:hover {
  background: rgba(228, 87, 46, 0.2);
  box-shadow: 0 0 0 2px rgba(228, 87, 46, 0.22);
}

.figure-box.is-table {
  border-color: var(--info, #3b6e8f);
  background: rgba(59, 110, 143, 0.1);
  color: var(--info, #3b6e8f);
}

.figure-box.is-table:hover {
  background: rgba(59, 110, 143, 0.2);
  box-shadow: 0 0 0 2px rgba(59, 110, 143, 0.22);
}

.figure-box-label {
  position: absolute;
  top: 3px;
  left: 3px;
  max-width: calc(100% - 6px);
  padding: 1px 5px;
  overflow: hidden;
  border-radius: 4px;
  background: rgba(255, 253, 249, 0.92);
  color: inherit;
  font-family: var(--pp-mono);
  font-size: 9px;
  font-weight: 600;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selection-layer {
  position: absolute;
  inset: 0;
  z-index: 4;
  cursor: crosshair;
  touch-action: none;
  user-select: none;
}

.selection-box {
  position: absolute;
  border: 1.5px dashed var(--pp-signal);
  border-radius: 2px;
  background: rgba(228, 87, 46, 0.16);
  box-shadow: inset 0 0 0 1px rgba(255, 253, 249, 0.65);
  pointer-events: none;
}

.pdf-status {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 260px;
  padding: 24px;
  border-radius: 8px;
  background: rgba(255, 253, 249, 0.9);
  color: var(--pp-ink-3);
  font-size: 11.5px;
  text-align: center;
}

.pdf-status strong {
  font-family: var(--pp-display);
  font-size: 20px;
  font-weight: 400;
  color: var(--pp-ink-2);
}

.pdf-status--loading {
  flex-direction: row;
  gap: 8px;
}

.pdf-status--error {
  color: var(--pp-danger);
  background: rgba(250, 236, 234, 0.94);
}

.pdf-status--error strong {
  color: var(--pp-danger);
}

.loading-bar {
  width: 18px;
  height: 2px;
  overflow: hidden;
  border-radius: 999px;
  background: linear-gradient(90deg, transparent, var(--pp-signal), transparent);
  animation: pp-loading 1.1s ease-in-out infinite;
}

/* 图片模式 */
.image-stage {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  overflow: auto;
  padding: 16px;
  background-color: var(--pp-sunken);
  background-image: radial-gradient(rgba(23, 24, 27, 0.045) 1px, transparent 1px);
  background-size: 14px 14px;
  scrollbar-width: thin;
}

.image-frame {
  position: relative;
  flex: 0 0 auto;
  display: inline-block;
  max-width: 100%;
  line-height: 0;
}

.source-image {
  display: block;
  max-width: 100%;
  height: auto;
  border-radius: 4px;
  background: #fff;
  box-shadow:
    0 1px 2px rgba(35, 29, 19, 0.08),
    0 18px 40px -24px rgba(35, 29, 19, 0.3);
}

.image-state {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: rgba(255, 253, 249, 0.9);
  color: var(--pp-ink-3);
  font-size: 11.5px;
  text-align: center;
  backdrop-filter: blur(3px);
}

.image-state strong {
  font-family: var(--pp-display);
  font-size: 20px;
  font-weight: 400;
  color: var(--pp-ink-2);
}

.image-state--error {
  color: var(--pp-danger);
  background: rgba(250, 236, 234, 0.94);
}

.image-state--error strong {
  color: var(--pp-danger);
}

@keyframes pp-in {
  from {
    opacity: 0;
    transform: translateX(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

@keyframes pp-loading {
  0% {
    background-position: -24px 0;
    opacity: 0.4;
  }
  50% {
    opacity: 1;
  }
  100% {
    background-position: 24px 0;
    opacity: 0.4;
  }
}

@media (max-width: 640px) {
  .pdf-toolbar {
    flex-wrap: wrap;
  }

  .zoomer {
    margin-left: auto;
  }

  .pdf-scroll,
  .image-stage {
    padding: 10px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .pdf-preview,
  .loading-bar {
    animation: none;
  }

  .icon-btn,
  .zoom-readout {
    transition: none;
  }
}
</style>

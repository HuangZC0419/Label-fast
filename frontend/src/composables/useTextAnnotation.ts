import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { ComponentPublicInstance } from 'vue'
import { authState, logout } from './useAuth'
import { toast } from './useToast'

/**
 * 文本标注页的领域状态与交互逻辑。
 *
 * 拆分目的：
 * 1. 页面组件只负责布局与模板渲染，避免出现上千行的“巨石组件”；
 * 2. 标注状态（文档、span、relation、测量结果）集中管理，切换文档时不会出现状态错配；
 * 3. 与 React 版保持同一份数据流：items/docIds/spansByIndex/relationsByIndex 一一对应。
 */

export type DocStatus = 'pending' | 'in_progress' | 'completed'
export type SplitMode = 'as_is' | 'paragraph' | 'sentence'

export interface Span {
  id: number
  start: number
  end: number
  label: string
}

export interface Relation {
  fromId: number
  toId: number
  type: string
}

export interface Rect {
  x: number
  y: number
  w: number
  h: number
}

export interface ProjectSummary {
  id: number
  name: string
}

export interface SpanRenderEntry {
  span: Span
  segments: Rect[]
}

export interface RelationVisual {
  index: number
  type: string
  color: string
  hovered: boolean
  path: string
  mx: number
  labelY: number
}

/** 后端 sync 接口的最小结构，只声明前端实际读取的字段 */
interface SyncDocument {
  id: number
  text: string
  status?: string
  /** 来源文件（后端 Document.source_file） */
  source_file?: string | null
  /** 该文本在原文件中的分段序号，从 0 开始 */
  unit_index?: number | null
  spans?: Span[]
  relations?: Relation[]
}

interface SyncProject {
  name?: string
  labels?: string[] | string | null
  relation_types?: string[] | string | null
}

interface SyncData {
  project?: SyncProject
  documents?: SyncDocument[]
}

// Ink & Signal 色板：标签保持低饱和暖色，关系使用深色系以承载白字
const LABEL_COLORS = ['#EFB7A3', '#C7D6A7', '#A9C4D8', '#E8D6A2', '#D8B6C4', '#B6C7BF']
const RELATION_COLORS = ['#8C5A3C', '#5B6B8C', '#5F7F6A', '#A6543A', '#7A6A8C', '#5A5A5A']
const LABEL_ALPHA = 0.5
const MAX_FILE_SIZE = 10 * 1024 * 1024
const MAX_HISTORY = 100
/** 中文 / 英文句末标点（不包含英文句点，句点单独判断） */
const SENTENCE_PUNCTUATION = '。．；！？!?;'

/**
 * 句子模式切分。
 * - 句末标点（。；！？!?;）与省略号（…… / ...）作为边界，标点保留在上一句；
 * - 换行作为硬边界：没有句末标点的行式文本（清单、命令、说明）也能按行拆开；
 * - 英文句点仅在后接空白或文本结尾、且前一个字符不是数字时才算句末，
 *   避免切开小数（3.9）、版本号以及 "1. xxx" 这类列表序号。
 */
function splitSentences(normalized: string): string[] {
  const result: string[] = []
  const chars = Array.from(normalized)
  let current = ''

  const flush = () => {
    const trimmed = current.trim()
    if (trimmed) result.push(trimmed)
    current = ''
  }

  let i = 0
  while (i < chars.length) {
    const ch = chars[i]

    if (ch === '\n') {
      flush()
      i++
      continue
    }

    if (ch === '…') {
      let j = i
      while (j < chars.length && chars[j] === '…') j++
      current += chars.slice(i, j).join('')
      flush()
      i = j
      continue
    }

    if (ch === '.') {
      let j = i
      while (j < chars.length && chars[j] === '.') j++
      const run = j - i
      current += '.'.repeat(run)
      if (run >= 3) {
        // 英文省略号 ...
        flush()
        i = j
        continue
      }
      const next = chars[j]
      const prev = chars[i - 1]
      const atEnd = next === undefined || /\s/.test(next)
      const afterDigit = prev !== undefined && /\d/.test(prev)
      if (run === 1 && atEnd && !afterDigit) flush()
      i = j
      continue
    }

    current += ch
    if (SENTENCE_PUNCTUATION.includes(ch)) flush()
    i++
  }

  flush()
  return result
}
const CONFIG_SEPARATOR = /[，,;；]/

interface AnnotationSnapshot {
  spans: Span[]
  relations: Relation[]
}

interface PendingSelection {
  start: number
  end: number
}

interface PendingRelation {
  fromId: number
  toId: number
}

export function useTextAnnotation() {
  /* ================================================================
     认证头
     ================================================================ */
  /** 所有 /api 请求统一带 token；JSON 请求额外带 Content-Type */
  function authHeaders(jsonBody = true): Record<string, string> {
    const headers: Record<string, string> = {}
    if (authState.token) headers.Authorization = `Bearer ${authState.token}`
    if (jsonBody) headers['Content-Type'] = 'application/json'
    return headers
  }

  /**
   * 统一处理 401：清除本地登录态并整页回到登录页。
   * 返回 true 表示已经处理，调用方应立即停止后续流程。
   */
  function handleUnauthorized(response: Response): boolean {
    if (response.status !== 401) return false
    logout()
    window.location.assign(`${import.meta.env.BASE_URL}login`)
    return true
  }

  /* ================================================================
     项目与标签配置
     ================================================================ */
  const projectName = ref('')
  const labelsInput = ref('')
  const relationTypesInput = ref('')
  const projectList = ref<ProjectSummary[]>([])
  const pid = ref(0)
  // 首次进入页面即处于加载态，避免下拉框短暂显示“选择已有项目”
  const projectsLoading = ref(true)
  const projectLoading = ref(false)
  const savingProject = ref(false)

  const labels = computed(() =>
    labelsInput.value.split(CONFIG_SEPARATOR).map((item) => item.trim()).filter(Boolean),
  )
  const relationTypes = computed(() =>
    relationTypesInput.value.split(CONFIG_SEPARATOR).map((item) => item.trim()).filter(Boolean),
  )

  /** 实体标签颜色：按标签顺序循环取色 */
  const palette = computed<Record<string, string>>(() => {
    const result: Record<string, string> = {}
    labels.value.forEach((label, index) => {
      result[label] = LABEL_COLORS[index % LABEL_COLORS.length]
    })
    return result
  })
  /** 关系类型颜色：按关系顺序循环取色 */
  const relPalette = computed<Record<string, string>>(() => {
    const result: Record<string, string> = {}
    relationTypes.value.forEach((type, index) => {
      result[type] = RELATION_COLORS[index % RELATION_COLORS.length]
    })
    return result
  })

  /* ================================================================
     文档与标注数据
     ================================================================ */
  const text = ref('')
  const spans = ref<Span[]>([])
  const relations = ref<Relation[]>([])
  const spansByIndex = ref<Record<number, Span[]>>({})
  const relationsByIndex = ref<Record<number, Relation[]>>({})
  const nextId = ref(1)
  const items = ref<string[]>([])
  const docIds = ref<number[]>([])
  /** 每条文本的来源文件名，与 items 一一对应 */
  const sourceFiles = ref<string[]>([])
  /** 每条文本在其来源文件中的分段序号（从 1 开始），与 items 一一对应 */
  const fileNumbers = ref<number[]>([])
  const itemStatuses = ref<Record<number, DocStatus>>({})
  const currentIndex = ref(-1)
  const splitMode = ref<SplitMode>('sentence')
  const uploadInfo = ref('')
  const savingRecord = ref(false)

  /* ================================================================
     交互浮层与选中态
     ================================================================ */
  const pending = ref<PendingSelection | null>(null)
  const labelPickerOpen = ref(false)
  const dragFromId = ref<number | null>(null)
  const pendingRel = ref<PendingRelation | null>(null)
  const relPickerOpen = ref(false)
  const hoverRelIdx = ref<number | null>(null)
  const selectedSpanId = ref<number | null>(null)
  const relFromId = ref<number | null>(null)
  const showSettings = ref(false)
  const splitHelpOpen = ref(false)

  /* ================================================================
     高亮测量
     ================================================================ */
  const containerRef = ref<HTMLDivElement | null>(null)
  const charRects = ref<Rect[]>([])
  const boxes = ref<Record<number, Rect>>({})
  const overlayHeight = ref(0)
  const fontSize = ref(18)
  const lineH = ref(1.8)
  const relStrokeWidth = ref(2)
  const relDashed = ref(false)

  /** 非响应式的字符 DOM 索引表，避免测量时触发无意义的渲染 */
  const charRefs = new Map<number, HTMLSpanElement>()
  const history = ref<AnnotationSnapshot[]>([])

  const chars = computed(() => Array.from(text.value))
  /** 当前文档的来源文件名，用于工作台标题展示；无来源信息时为空字符串 */
  const currentFileName = computed(() => {
    const index = currentIndex.value
    if (index < 0) return ''
    return baseName(sourceFiles.value[index] || '')
  })
  const hasDocuments = computed(() => items.value.length > 0)
  const canPrev = computed(() => currentIndex.value > 0)
  const canNext = computed(() => currentIndex.value >= 0 && currentIndex.value < items.value.length - 1)

  /**
   * 使用稳定的函数 ref + data-char-index，避免为每个字符创建闭包。
   * 文本长度变化时元素会按 key（索引）复用，因此不需要在更新时重建映射。
   */
  function setCharRef(element: Element | ComponentPublicInstance | null): void {
    if (!(element instanceof HTMLSpanElement)) return
    const index = Number(element.dataset.charIndex)
    if (Number.isInteger(index)) charRefs.set(index, element)
  }

  function rgba(hex: string, alpha: number): string {
    const value = hex.replace('#', '')
    const r = parseInt(value.substring(0, 2), 16)
    const g = parseInt(value.substring(2, 4), 16)
    const b = parseInt(value.substring(4, 6), 16)
    return `rgba(${r},${g},${b},${alpha})`
  }

  /** 标签被删除后仍能安全渲染旧标注，回退到中性色 */
  function spanColor(label: string): string {
    return palette.value[label] ?? '#CBD5E1'
  }

  /**
   * 将字符矩形按“同一行”合并成连续片段。
   * 相比给每个字符单独渲染一个 div，片段数量通常只有几十个，渲染开销更低。
   */
  function spanSegments(start: number, end: number, rects: Rect[]): Rect[] {
    const result: Rect[] = []
    if (start < 0 || end <= start || rects.length === 0) return result

    const safeEnd = Math.min(end, rects.length)
    let index = start
    while (index < safeEnd) {
      const first = rects[index]
      if (!first) {
        index += 1
        continue
      }

      let width = first.w
      let cursor = index + 1
      while (cursor < safeEnd) {
        const current = rects[cursor]
        if (!current) break
        if (Math.abs(current.y - first.y) < 0.5) {
          width += current.w
          cursor += 1
        } else {
          break
        }
      }
      result.push({ x: first.x, y: first.y, w: width, h: first.h })
      index = cursor
    }
    return result
  }

  const spanRenderList = computed<SpanRenderEntry[]>(() =>
    spans.value.map((span) => ({
      span,
      segments: spanSegments(span.start, span.end, charRects.value),
    })),
  )

  /** 关系 hover 时联动高亮两端实体 */
  const linkedSpanIds = computed<Set<number>>(() => {
    const ids = new Set<number>()
    const index = hoverRelIdx.value
    if (index === null) return ids
    const relation = relations.value[index]
    if (!relation) return ids
    ids.add(relation.fromId)
    ids.add(relation.toId)
    return ids
  })

  const relationVisuals = computed<RelationVisual[]>(() => {
    const result: RelationVisual[] = []
    relations.value.forEach((relation, index) => {
      const from = boxes.value[relation.fromId]
      const to = boxes.value[relation.toId]
      if (!from || !to) return

      const x1 = from.x
      const y1 = from.y - 8
      const x2 = to.x
      const y2 = to.y - 8
      const minY = Math.min(y1, y2)
      const dy = Math.abs(y2 - y1)
      const arcHeight = 25 + Math.min(dy * 0.4, 80)
      const cpY = Math.max(12, Math.min(minY - 18, minY - arcHeight))
      const mx = (x1 + x2) / 2

      result.push({
        index,
        type: relation.type,
        color: relPalette.value[relation.type] ?? '#333',
        hovered: hoverRelIdx.value === index,
        path: `M ${x1} ${y1} C ${mx} ${cpY}, ${mx} ${cpY}, ${x2} ${y2}`,
        mx,
        labelY: Math.max(12, cpY - 4),
      })
    })
    return result
  })

  const annotationStyle = computed<Record<string, string>>(() => ({
    fontSize: `${fontSize.value}px`,
    lineHeight: String(lineH.value),
    padding: '3rem',
    minHeight: '300px',
    // flex-basis 使用内容高度：长文档时编辑区随文本增高，由 workspace 滚动，避免被卡片裁剪
    flex: '1 0 auto',
    background: '#fff',
    outline: 'none',
  }))

  function spanSegmentStyle(span: Span, segment: Rect): Record<string, string> {
    const selected = selectedSpanId.value === span.id
    const linked = linkedSpanIds.value.has(span.id)
    return {
      left: `${segment.x}px`,
      top: `${segment.y}px`,
      width: `${segment.w}px`,
      height: `${segment.h}px`,
      background: rgba(spanColor(span.label), LABEL_ALPHA),
      outline: selected ? '2px solid #333' : linked ? '2px solid rgba(51,51,51,.35)' : 'none',
    }
  }

  let measureFrame = 0
  let resizeObserver: ResizeObserver | null = null

  /** 同步测量：DOM 更新后立即计算，避免高亮层闪烁 */
  function measureRectsAndBoxes(): void {
    const container = containerRef.value
    if (!container) return

    // 文本变短后清理超出当前长度的旧 DOM 引用，避免长文档切换造成内存滞留
    for (const index of Array.from(charRefs.keys())) {
      if (index >= chars.value.length) charRefs.delete(index)
    }

    const base = container.getBoundingClientRect()
    const rects: Rect[] = []
    for (let index = 0; index < chars.value.length; index += 1) {
      const element = charRefs.get(index)
      if (!element) {
        rects.push({ x: 0, y: 0, w: 0, h: 0 })
        continue
      }
      const rect = element.getBoundingClientRect()
      rects.push({
        x: rect.left - base.left,
        y: rect.top - base.top,
        w: rect.width,
        h: rect.height,
      })
    }

    charRects.value = rects

    let maxY = 0
    for (const rect of rects) maxY = Math.max(maxY, rect.y + rect.h)
    overlayHeight.value = Math.max(maxY, base.height)

    const nextBoxes: Record<number, Rect> = {}
    for (const span of spans.value) {
      const segments = spanSegments(span.start, span.end, rects)
      const first = segments[0]
      if (first) {
        nextBoxes[span.id] = {
          x: first.x + first.w / 2,
          y: first.y,
          w: first.w,
          h: first.h,
        }
      }
    }
    boxes.value = nextBoxes
  }

  /** 窗口/容器尺寸变化时用 rAF 合并多次测量 */
  function scheduleMeasure(): void {
    if (measureFrame) cancelAnimationFrame(measureFrame)
    measureFrame = requestAnimationFrame(() => {
      measureFrame = 0
      measureRectsAndBoxes()
    })
  }

  // DOM 更新完成后再测量；text/spans/字号/行高任一变化都会影响矩形
  watch([chars, spans, fontSize, lineH], () => measureRectsAndBoxes(), { flush: 'post' })

  /* ================================================================
     状态与文档切换
     ================================================================ */
  function statusOf(index: number): DocStatus {
    return itemStatuses.value[index] ?? 'pending'
  }

  function statusTitle(status: DocStatus): string {
    if (status === 'completed') return '已完成'
    if (status === 'in_progress') return '进行中'
    return '待处理'
  }

  /** 记录标注前的快照，供撤销使用 */
  function pushHistory(): void {
    history.value.push({
      spans: spans.value.map((span) => ({ ...span })),
      relations: relations.value.map((relation) => ({ ...relation })),
    })
    if (history.value.length > MAX_HISTORY) history.value.shift()
  }

  function undo(): void {
    const snapshot = history.value.pop()
    if (!snapshot) return
    spans.value = snapshot.spans
    relations.value = snapshot.relations
    selectedSpanId.value = null
    relFromId.value = null
    pending.value = null
    pendingRel.value = null
    labelPickerOpen.value = false
    relPickerOpen.value = false
  }

  /** 当前文档的编辑在切换前写回缓存，避免丢标注 */
  function saveCurrent(): void {
    const index = currentIndex.value
    if (index < 0) return
    spansByIndex.value = { ...spansByIndex.value, [index]: spans.value.map((span) => ({ ...span })) }
    relationsByIndex.value = {
      ...relationsByIndex.value,
      [index]: relations.value.map((relation) => ({ ...relation })),
    }
  }

  function resetView(): void {
    currentIndex.value = -1
    text.value = ''
    spans.value = []
    relations.value = []
    selectedSpanId.value = null
    relFromId.value = null
    dragFromId.value = null
    pending.value = null
    pendingRel.value = null
    labelPickerOpen.value = false
    relPickerOpen.value = false
    hoverRelIdx.value = null
    charRects.value = []
    boxes.value = {}
    overlayHeight.value = 0
    history.value = []
  }

  function loadIndex(index: number): void {
    if (index < 0 || index >= items.value.length) return
    currentIndex.value = index
    text.value = items.value[index] ?? ''
    spans.value = (spansByIndex.value[index] ?? []).map((span) => ({ ...span }))
    relations.value = (relationsByIndex.value[index] ?? []).map((relation) => ({ ...relation }))
    charRects.value = []
    boxes.value = {}
    overlayHeight.value = 0
    selectedSpanId.value = null
    relFromId.value = null
    dragFromId.value = null
    pending.value = null
    pendingRel.value = null
    labelPickerOpen.value = false
    relPickerOpen.value = false
    hoverRelIdx.value = null
    // 撤销记录与文档绑定，避免把上一份文档的撤销结果套到当前文档
    history.value = []
  }

  function selectItem(index: number): void {
    if (index === currentIndex.value) return
    saveCurrent()
    loadIndex(index)
  }

  function prevItem(): void {
    if (!hasDocuments.value || currentIndex.value <= 0) return
    saveCurrent()
    loadIndex(currentIndex.value - 1)
  }

  function nextItem(): void {
    if (!hasDocuments.value || currentIndex.value >= items.value.length - 1) return
    saveCurrent()
    loadIndex(currentIndex.value + 1)
  }

  // 有标注时从 pending 提升为进行中；已完成状态不因重新浏览而回退
  watch([spans, relations, currentIndex], () => {
    const index = currentIndex.value
    if (index < 0) return
    const hasAnnotation = spans.value.length > 0 || relations.value.length > 0
    const status: DocStatus = hasAnnotation
      ? (statusOf(index) === 'completed' ? 'completed' : 'in_progress')
      : statusOf(index)
    itemStatuses.value = { ...itemStatuses.value, [index]: status }
  })

  /* ================================================================
     文本选择与实体标注
     ================================================================ */
  function getSelectionOffsets(): PendingSelection | null {
    const container = containerRef.value
    const selection = window.getSelection()
    if (!container || !selection || selection.rangeCount === 0) return null

    const range = selection.getRangeAt(0)
    if (!container.contains(range.commonAncestorContainer)) return null

    const preRange = range.cloneRange()
    preRange.selectNodeContents(container)
    preRange.setEnd(range.startContainer, range.startOffset)

    const start = preRange.toString().length
    const length = range.toString().length
    if (length === 0) return null

    const end = start + length
    if (start < 0 || end > text.value.length || start >= end) return null
    return { start, end }
  }

  function handleContainerMouseUp(event: MouseEvent): void {
    if (relPickerOpen.value || dragFromId.value !== null) return
    if (relFromId.value !== null) relFromId.value = null

    event.preventDefault()
    event.stopPropagation()

    const offsets = getSelectionOffsets()
    if (!offsets) return

    // 不使用弹窗：保留浏览器选中态与待标注区间，
    // 用户直接点击上方实体标签 chip 或按 1–9 即可应用
    pending.value = offsets
  }

  function addSpan(label: string): void {
    const offsets = pending.value
    if (!offsets) return
    if (!labels.value.includes(label)) return

    pushHistory()
    spans.value = [
      ...spans.value,
      { id: nextId.value, start: offsets.start, end: offsets.end, label },
    ]
    nextId.value += 1
    labelPickerOpen.value = false
    pending.value = null
    window.getSelection()?.removeAllRanges()
  }

  function cancelLabelPicker(): void {
    labelPickerOpen.value = false
    // 同时清空待标注区间，避免“取消后点击标签 chip”误用旧选区
    pending.value = null
    window.getSelection()?.removeAllRanges()
  }

  function removeSpanById(id: number): void {
    if (!spans.value.some((span) => span.id === id)) return
    pushHistory()
    spans.value = spans.value.filter((span) => span.id !== id)
    relations.value = relations.value.filter(
      (relation) => relation.fromId !== id && relation.toId !== id,
    )
    if (selectedSpanId.value === id) selectedSpanId.value = null
    if (relFromId.value === id) relFromId.value = null
    // 待选关系可能指向被删除的实体，一并关闭避免产生悬空关系
    relPickerOpen.value = false
    pendingRel.value = null
  }

  /** 用鼠标位置找最近的字符，用于右键切换重叠标注 */
  function getCharIndexAtPoint(clientX: number, clientY: number): number {
    const container = containerRef.value
    if (!container || charRects.value.length === 0) return -1

    const base = container.getBoundingClientRect()
    const x = clientX - base.left
    const y = clientY - base.top

    let best = -1
    let bestScore = Number.POSITIVE_INFINITY
    charRects.value.forEach((rect, index) => {
      const dx = x - (rect.x + rect.w / 2)
      const dy = y - (rect.y + rect.h / 2)
      const score = Math.abs(dx) + Math.abs(dy)
      if (score < bestScore) {
        bestScore = score
        best = index
      }
    })
    return best
  }

  function handleContainerContextMenu(event: MouseEvent): void {
    event.preventDefault()
    const index = getCharIndexAtPoint(event.clientX, event.clientY)
    if (index < 0) return

    const candidates = spans.value.filter((span) => span.start <= index && index < span.end)
    if (candidates.length === 0) return

    const currentPosition = candidates.findIndex((span) => span.id === selectedSpanId.value)
    const next = candidates[(currentPosition + 1) % candidates.length]
    if (next) selectedSpanId.value = next.id
  }

  function handleSpanMouseDown(id: number): void {
    dragFromId.value = id
    selectedSpanId.value = id
  }

  /** 兜底：拖拽在编辑区外结束时也要复位拖拽起点，避免状态卡死 */
  function handleWindowMouseUp(): void {
    dragFromId.value = null
  }

  function handleSpanMouseUp(id: number): void {
    const from = dragFromId.value
    if (from !== null && from !== id) {
      // 不使用弹窗：保留待选关系，用户点击上方关系 chip 或按 Ctrl+1–9 应用
      pendingRel.value = { fromId: from, toId: id }
    }
    dragFromId.value = null
  }

  function handleSpanClick(id: number): void {
    if (relFromId.value === null) {
      relFromId.value = id
      selectedSpanId.value = id
      return
    }
    if (relFromId.value !== id) {
      // 不使用弹窗：保留待选关系，用户点击上方关系 chip 或按 Ctrl+1–9 应用
      pendingRel.value = { fromId: relFromId.value, toId: id }
    }
    relFromId.value = null
  }

  /* ================================================================
     关系
     ================================================================ */
  function addRelation(type: string): void {
    const pair = pendingRel.value
    if (!pair) return
    if (!relationTypes.value.includes(type)) return

    // 防御：待选关系两端的实体必须仍然存在
    const sourceExists = spans.value.some((span) => span.id === pair.fromId)
    const targetExists = spans.value.some((span) => span.id === pair.toId)
    if (!sourceExists || !targetExists) {
      relPickerOpen.value = false
      pendingRel.value = null
      relFromId.value = null
      return
    }

    const exists = relations.value.some(
      (relation) => relation.fromId === pair.fromId && relation.toId === pair.toId && relation.type === type,
    )
    if (!exists) {
      pushHistory()
      relations.value = [...relations.value, { fromId: pair.fromId, toId: pair.toId, type }]
    }
    relPickerOpen.value = false
    pendingRel.value = null
    relFromId.value = null
  }

  function cancelRelPicker(): void {
    relPickerOpen.value = false
    pendingRel.value = null
    relFromId.value = null
  }

  function updateRelationType(index: number, type: string): void {
    const current = relations.value[index]
    if (!current || current.type === type) return
    pushHistory()
    const updated = [...relations.value]
    updated[index] = { ...current, type }
    relations.value = updated
  }

  function handleRelationTypeChange(index: number, event: Event): void {
    const value = (event.target as HTMLSelectElement).value
    updateRelationType(index, value)
  }

  function deleteRelation(index: number): void {
    if (index < 0 || index >= relations.value.length) return
    pushHistory()
    const updated = [...relations.value]
    updated.splice(index, 1)
    relations.value = updated
    // 删除后索引整体前移，直接清空 hover 态避免高亮错位
    hoverRelIdx.value = null
  }

  /** 关系面板中展示实体文本，帮助用户区分同标签的不同实体 */
  function spanLabelText(id: number): string {
    const span = spans.value.find((item) => item.id === id)
    if (!span) return `#${id}`
    const raw = chars.value.slice(span.start, span.end).join('')
    return raw.length > 12 ? `${raw.slice(0, 12)}…` : raw
  }

  /* ================================================================
     快捷键
     ================================================================ */
  function handleKeydown(event: KeyboardEvent): void {
    if (event.isComposing) return

    const target = event.target as HTMLElement | null
    const editable =
      !!target &&
      (target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.tagName === 'SELECT' ||
        target.isContentEditable)
    if (editable) return

    if (event.ctrlKey && event.key.toLowerCase() === 'z') {
      event.preventDefault()
      undo()
      return
    }

    if (event.key === 'Delete') {
      if (selectedSpanId.value !== null) {
        removeSpanById(selectedSpanId.value)
        selectedSpanId.value = null
        relFromId.value = null
      }
      return
    }

    if (event.key === 'Escape') {
      event.preventDefault()
      selectedSpanId.value = null
      pending.value = null
      pendingRel.value = null
      labelPickerOpen.value = false
      relPickerOpen.value = false
      relFromId.value = null
      showSettings.value = false
      splitHelpOpen.value = false
      return
    }

    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      prevItem()
      return
    }

    if (event.key === 'ArrowRight') {
      event.preventDefault()
      nextItem()
      return
    }

    const digit = Number(event.key)
    if (Number.isInteger(digit) && digit >= 1 && digit <= 9) {
      const index = digit - 1
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault()
        event.stopPropagation()
        if (pendingRel.value) {
          const type = relationTypes.value[index]
          if (type) addRelation(type)
        }
      } else if (pending.value) {
        const label = labels.value[index]
        if (label) {
          event.preventDefault()
          addSpan(label)
        }
      }
      return
    }

    if (event.key === ' ') {
      event.preventDefault()
      if (pending.value) {
        const label = labels.value[0]
        if (label) addSpan(label)
      } else if (!pendingRel.value) {
        // 空格键 = 保存并下一篇，与按钮行为一致
        void handleSaveAndNext()
      }
    }
  }

  /* ================================================================
     文件导入与切分
     ================================================================ */
  function readFileBuffer(file: File): Promise<ArrayBuffer> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => {
        if (reader.result instanceof ArrayBuffer) resolve(reader.result)
        else reject(new Error('读取文件失败'))
      }
      reader.onerror = () => reject(reader.error ?? new Error('读取文件失败'))
      reader.readAsArrayBuffer(file)
    })
  }

  function tryDecode(buffer: ArrayBuffer): string {
    const encodings = ['utf-8', 'gbk', 'utf-16le', 'utf-16be']
    for (const encoding of encodings) {
      try {
        const decoder = new TextDecoder(encoding, { fatal: true })
        return decoder.decode(buffer)
      } catch {
        // 编码尝试失败是预期行为，继续尝试下一个
      }
    }
    return new TextDecoder('utf-8').decode(buffer)
  }

  function splitText(content: string): string[] {
    const normalized = content.replace(/\r\n/g, '\n')
    if (splitMode.value === 'as_is') return [normalized]
    // 段落模式：以空行（一个或多个换行）作为段落边界
    if (splitMode.value === 'paragraph') {
      return normalized
        .split(/\n\s*\n/)
        .map((part) => part.trim())
        .filter(Boolean)
    }

    // 句子模式：句末标点保留在上一句中；换行视为硬边界
    return splitSentences(normalized)
  }

  /** 从路径中取文件名，兼容 Windows 反斜杠 */
  function baseName(path: string): string {
    const parts = path.split(/[\\/]/)
    return parts[parts.length - 1] || path
  }

  async function handleFiles(files: FileList | null): Promise<void> {
    if (!files || files.length === 0) return
    // 未选择项目时导入的数据没有落盘目标，创建项目后会被服务端数据整体替换，因此直接阻止
    if (!pid.value) {
      toast('请先选择或创建一个项目，再导入待标注文本', 'error')
      return
    }

    const collected: string[] = []
    const collectedFiles: string[] = []
    const collectedNumbers: number[] = []
    let count = 0

    for (const file of Array.from(files)) {
      if (file.size > MAX_FILE_SIZE) {
        uploadInfo.value = `文件过大: ${file.name}`
        continue
      }
      try {
        const buffer = await readFileBuffer(file)
        const content = tryDecode(buffer)
        const units = splitText(content)
        // 同一个文件按句子切分出的每条文本，都记录来源文件名与分段序号
        units.forEach((unit, unitIndex) => {
          collected.push(unit)
          collectedFiles.push(file.name)
          collectedNumbers.push(unitIndex + 1)
        })
        count += units.length
      } catch {
        uploadInfo.value = `导入失败: ${file.name}`
      }
    }

    if (collected.length === 0) return

    const startIndex = items.value.length
    items.value = [...items.value, ...collected]
    docIds.value = [...docIds.value, ...collected.map(() => -1)]
    sourceFiles.value = [...sourceFiles.value, ...collectedFiles]
    fileNumbers.value = [...fileNumbers.value, ...collectedNumbers]

    const statuses = { ...itemStatuses.value }
    collected.forEach((_, offset) => {
      statuses[startIndex + offset] = 'pending'
    })
    itemStatuses.value = statuses

    if (currentIndex.value < 0) loadIndex(0)
    uploadInfo.value = `已导入 ${count} 条`
  }

  async function handleDrop(event: DragEvent): Promise<void> {
    await handleFiles(event.dataTransfer?.files ?? null)
  }

  async function handleFilesSelected(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement
    await handleFiles(input.files)
    input.value = ''
  }

  async function handleConfigUpload(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement
    const file = input.files?.[0]
    if (!file) return

    try {
      const buffer = await readFileBuffer(file)
      const content = tryDecode(buffer)
      const lines = content.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)

      const parsedLabels: string[] = []
      const parsedRelations: string[] = []
      let mode: 'labels' | 'relations' = 'labels'

      for (const line of lines) {
        let cleanLine = line
        if (/^(LABELS|标签)[:：]?/i.test(line)) {
          mode = 'labels'
          cleanLine = line.replace(/^(LABELS|标签)[:：]?/i, '').trim()
        } else if (/^(RELATIONS|关系)[:：]?/i.test(line)) {
          mode = 'relations'
          cleanLine = line.replace(/^(RELATIONS|关系)[:：]?/i, '').trim()
        } else {
          if (/^\[.*\]$/.test(line)) continue
          if (line.startsWith('#')) continue
        }

        if (!cleanLine) continue
        if (mode === 'labels') parsedLabels.push(cleanLine)
        else parsedRelations.push(cleanLine)
      }

      if (parsedLabels.length > 0) labelsInput.value = parsedLabels.join(',')
      if (parsedRelations.length > 0) relationTypesInput.value = parsedRelations.join(',')

      toast(
        String(
          `已导入 ${parsedLabels.length > 0 ? '标签' : ''} ${parsedRelations.length > 0 ? '关系' : ''}`,
        ),
        'success',
      )
    } catch (error) {
      toast(String(`配置导入失败: ${error}`), 'error')
    } finally {
      input.value = ''
    }
  }

  /* ================================================================
     项目接口
     ================================================================ */
  async function fetchProjects(): Promise<void> {
    projectsLoading.value = true
    try {
      const response = await fetch('/api/projects', { headers: authHeaders(false) })
      if (handleUnauthorized(response)) return
      if (!response.ok) return
      const data = (await response.json()) as ProjectSummary[]
      if (Array.isArray(data)) projectList.value = data
    } catch (error) {
      console.error('Failed to fetch projects', error)
    } finally {
      projectsLoading.value = false
    }
  }

  function normalizeStatus(value: unknown): DocStatus {
    return value === 'completed' || value === 'in_progress' ? value : 'pending'
  }

  /** 同步后重新计算 span id 起点，避免新标注与后端旧 id 冲突 */
  function refreshNextId(): void {
    let maxId = 0
    for (const list of Object.values(spansByIndex.value)) {
      for (const span of list) maxId = Math.max(maxId, span.id)
    }
    nextId.value = maxId + 1
  }

  function applySyncData(data: SyncData): void {
    if (data.project) {
      if (typeof data.project.name === 'string') projectName.value = data.project.name
      const labelValue = data.project.labels
      labelsInput.value = Array.isArray(labelValue)
        ? labelValue.join(',')
        : typeof labelValue === 'string'
          ? labelValue
          : ''
      const relationValue = data.project.relation_types
      relationTypesInput.value = Array.isArray(relationValue)
        ? relationValue.join(',')
        : typeof relationValue === 'string'
          ? relationValue
          : ''
    }

    const nextItems: string[] = []
    const nextDocIds: number[] = []
    const nextSourceFiles: string[] = []
    const nextFileNumbers: number[] = []
    const nextStatuses: Record<number, DocStatus> = {}
    const nextSpans: Record<number, Span[]> = {}
    const nextRelations: Record<number, Relation[]> = {}

    if (Array.isArray(data.documents)) {
      data.documents.forEach((document, index) => {
        nextItems.push(typeof document.text === 'string' ? document.text : '')
        nextDocIds.push(typeof document.id === 'number' ? document.id : -1)
        nextSourceFiles.push(typeof document.source_file === 'string' ? document.source_file : '')
        nextFileNumbers.push(
          typeof document.unit_index === 'number' ? document.unit_index + 1 : 1,
        )
        nextStatuses[index] = normalizeStatus(document.status)
        nextSpans[index] = Array.isArray(document.spans)
          ? document.spans.map((span) => ({ ...span }))
          : []
        nextRelations[index] = Array.isArray(document.relations)
          ? document.relations.map((relation) => ({ ...relation }))
          : []
      })
    }

    items.value = nextItems
    docIds.value = nextDocIds
    sourceFiles.value = nextSourceFiles
    fileNumbers.value = nextFileNumbers
    itemStatuses.value = nextStatuses
    spansByIndex.value = nextSpans
    relationsByIndex.value = nextRelations

    if (nextItems.length > 0) loadIndex(0)
    else resetView()

    refreshNextId()
  }

  async function loadProject(projectId: number): Promise<void> {
    projectLoading.value = true
    try {
      const response = await fetch(`/api/projects/${projectId}/sync`, {
        headers: authHeaders(false),
      })
      if (handleUnauthorized(response)) throw new Error('登录已过期，请重新登录')
      if (!response.ok) throw new Error(await response.text())
      const data = (await response.json()) as SyncData
      applySyncData(data)
    } finally {
      projectLoading.value = false
    }
  }

  async function handleProjectSelect(event: Event): Promise<void> {
    const select = event.target as HTMLSelectElement
    const id = Number(select.value)
    if (!id) {
      // 选择占位项不切换项目，把下拉框显示恢复为当前项目
      select.value = pid.value ? String(pid.value) : ''
      return
    }

    const project = projectList.value.find((item) => item.id === id)
    if (!project) return

    const previousPid = pid.value
    const previousName = projectName.value
    // 先把当前编辑写回本地缓存；若加载失败，界面仍停留在旧项目且编辑不丢失
    saveCurrent()

    try {
      await loadProject(project.id)
      // 仅在加载成功后切换项目标识，避免失败时界面与数据不一致
      pid.value = project.id
      projectName.value = project.name
    } catch (error) {
      pid.value = previousPid
      projectName.value = previousName
      select.value = previousPid ? String(previousPid) : ''
      toast(String(`加载失败: ${error}`), 'error')
    }
  }

  async function handleSwitchProject(): Promise<void> {
    if (!projectName.value) return

    const previousPid = pid.value
    saveCurrent()

    try {
      const response = await fetch('/api/projects', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          name: projectName.value,
          labels: labels.value,
          relation_types: relationTypes.value,
        }),
      })
      if (handleUnauthorized(response)) return
      if (!response.ok) throw new Error(await response.text())

      const data = (await response.json()) as ProjectSummary

      // 先刷新下拉选项并加载项目数据，成功后再切换 pid
      await fetchProjects()
      await loadProject(data.id)
      pid.value = data.id
      projectName.value = data.name
      toast(String(`切换到项目: ${data.name} (ID: ${data.id})`), 'success')
    } catch (error) {
      pid.value = previousPid
      toast(String(`创建/切换项目失败: ${error}`), 'error')
    }
  }

  async function clearProject(): Promise<void> {
    if (!pid.value || !projectName.value) return
    if (!confirm('确定要清空项目配置和待标注对象吗？此操作无法撤销。')) return

    try {
      const response = await fetch(`/api/projects/${pid.value}/clear`, {
        method: 'DELETE',
        headers: authHeaders(false),
      })
      if (handleUnauthorized(response)) return
      if (!response.ok) throw new Error('清空失败')
      await loadProject(pid.value)
      toast('已清空', 'success')
    } catch (error) {
      toast(String(`清空失败: ${error}`), 'error')
    }
  }

  async function deleteProject(): Promise<void> {
    if (!pid.value || !projectName.value) return
    if (!confirm(`确定要彻底删除项目 "${projectName.value}" 吗？此操作不可恢复！`)) return

    try {
      const response = await fetch(`/api/projects/${pid.value}`, {
        method: 'DELETE',
        headers: authHeaders(false),
      })
      if (handleUnauthorized(response)) return
      if (!response.ok) throw new Error('删除失败')
      toast('项目已删除', 'success')
      window.location.reload()
    } catch (error) {
      toast(String(`删除失败: ${error}`), 'error')
    }
  }

  async function exportZip(): Promise<void> {
    if (!pid.value) return
    try {
      const response = await fetch(`/api/projects/${pid.value}/export-zip`, {
        headers: authHeaders(false),
      })
      if (handleUnauthorized(response)) return
      if (!response.ok) {
        const errorText = await response.text()
        throw new Error(`导出失败 (${response.status}): ${errorText}`)
      }

      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      const safeName =
        (projectName.value || 'export').replace(/[^a-zA-Z0-9一-鿿 _-]/g, '').trim() || 'export'
      anchor.href = url
      anchor.download = `${safeName}_${new Date().toISOString().slice(0, 10)}.zip`
      document.body.appendChild(anchor)
      anchor.click()
      document.body.removeChild(anchor)
      URL.revokeObjectURL(url)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      toast(String(`打包导出失败: ${message}`), 'error')
    }
  }

  /** 保存整个项目：把当前编辑快照写回缓存后整体同步 */
  async function saveProject(): Promise<void> {
    if (!pid.value || savingProject.value) return

    const nextSpansForSave = { ...spansByIndex.value }
    const nextRelationsForSave = { ...relationsByIndex.value }
    if (currentIndex.value >= 0) {
      nextSpansForSave[currentIndex.value] = spans.value
      nextRelationsForSave[currentIndex.value] = relations.value
    }
    spansByIndex.value = nextSpansForSave
    relationsByIndex.value = nextRelationsForSave

    const payload = {
      project: {
        name: projectName.value,
        labels: labels.value,
        relation_types: relationTypes.value,
      },
      documents: items.value.map((documentText, index) => ({
        id: docIds.value[index] || -1,
        text: documentText,
        status: itemStatuses.value[index] || 'pending',
        source_file: sourceFiles.value[index] || '',
        unit_index: (fileNumbers.value[index] || 1) - 1,
        spans: nextSpansForSave[index] || [],
        relations: nextRelationsForSave[index] || [],
      })),
    }

    savingProject.value = true
    try {
      const response = await fetch(`/api/projects/${pid.value}/sync`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify(payload),
      })
      if (handleUnauthorized(response)) return
      if (!response.ok) throw new Error('保存失败')

      const data = (await response.json()) as { documents?: Array<{ id?: number }> }
      if (data.documents && Array.isArray(data.documents)) {
        const updatedDocIds = [...docIds.value]
        data.documents.forEach((document, index) => {
          if (index < updatedDocIds.length && typeof document.id === 'number') {
            updatedDocIds[index] = document.id
          }
        })
        docIds.value = updatedDocIds
      }

      toast('项目已保存！', 'success')
    } catch (error) {
      toast(String(`保存失败: ${error}`), 'error')
    } finally {
      savingProject.value = false
    }
  }

  /* ================================================================
     单条记录与删除
     ================================================================ */
  async function postRecord(): Promise<boolean> {
    const index = currentIndex.value
    if (index < 0 || savingRecord.value) return false
    if (!pid.value) {
      toast('请先选择或创建一个项目', 'error')
      return false
    }

    saveCurrent()

    const sourceName = baseName(sourceFiles.value[index] || '')
    const record = {
      // 标注对象的来源文件与分段序号（无来源信息时不写入该字段，保持旧格式）
      ...(sourceName
        ? { file_name: sourceName, file_number: fileNumbers.value[index] || 1 }
        : {}),
      id: docIds.value[index] || -1,
      text: text.value,
      spans: spans.value,
      relations: relations.value,
      meta: {
        timestamp: new Date().toISOString(),
        project_name: projectName.value,
        project_id: pid.value,
      },
    }

    savingRecord.value = true
    try {
      const response = await fetch(`/api/projects/${pid.value}/record`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify(record),
      })
      if (handleUnauthorized(response)) return false
      if (!response.ok) {
        const errorText = await response.text()
        throw new Error(`Failed to save record (${response.status}): ${errorText}`)
      }
      itemStatuses.value = { ...itemStatuses.value, [index]: 'completed' }
      return true
    } catch (error) {
      toast(String(`保存记录失败: ${error}`), 'error')
      return false
    } finally {
      savingRecord.value = false
    }
  }

  async function handleSaveOnly(): Promise<void> {
    await postRecord()
  }

  async function handleSaveAndNext(): Promise<void> {
    const index = currentIndex.value
    if (index < 0) return

    const saved = await postRecord()
    if (!saved) return

    if (index < items.value.length - 1) {
      loadIndex(index + 1)
    } else {
      toast('已完成所有文档！', 'info')
    }
  }

  function handleSkip(): void {
    if (currentIndex.value >= items.value.length - 1) {
      toast('已到列表末尾', 'info')
      return
    }
    saveCurrent()
    loadIndex(currentIndex.value + 1)
  }

  /** 删除文档后同步平移所有按索引存储的映射 */
  function shiftMap<T>(source: Record<number, T>, removedIndex: number): Record<number, T> {
    const result: Record<number, T> = {}
    for (const [key, value] of Object.entries(source)) {
      const index = Number(key)
      if (index < removedIndex) result[index] = value
      else if (index > removedIndex) result[index - 1] = value
    }
    return result
  }

  async function deleteDocumentAt(index: number): Promise<void> {
    if (index < 0 || index >= items.value.length) return
    if (!confirm('删除此标注对象？')) return

    const docId = docIds.value[index]
    if (docId && docId !== -1) {
      try {
        const response = await fetch(`/api/documents/${docId}`, {
          method: 'DELETE',
          headers: authHeaders(false),
        })
        if (!response.ok) throw new Error('删除失败')
      } catch (error) {
        toast(String(`删除失败: ${error}`), 'error')
        return
      }
    }

    // 先保存当前编辑，避免删除其他文档时丢失本页标注
    saveCurrent()

    const nextItems = [...items.value]
    nextItems.splice(index, 1)
    const nextDocIds = [...docIds.value]
    nextDocIds.splice(index, 1)
    const nextSourceFiles = [...sourceFiles.value]
    nextSourceFiles.splice(index, 1)
    const nextFileNumbers = [...fileNumbers.value]
    nextFileNumbers.splice(index, 1)

    items.value = nextItems
    docIds.value = nextDocIds
    sourceFiles.value = nextSourceFiles
    fileNumbers.value = nextFileNumbers
    itemStatuses.value = shiftMap(itemStatuses.value, index)
    spansByIndex.value = shiftMap(spansByIndex.value, index)
    relationsByIndex.value = shiftMap(relationsByIndex.value, index)

    if (nextItems.length === 0) {
      resetView()
    } else {
      loadIndex(Math.min(index, nextItems.length - 1))
    }
  }

  function handleDeleteCurrent(): void {
    void deleteDocumentAt(currentIndex.value)
  }

  /* ================================================================
     生命周期
     ================================================================ */
  onMounted(() => {
    void fetchProjects()

    window.addEventListener('keydown', handleKeydown, true)
    window.addEventListener('resize', scheduleMeasure)
    window.addEventListener('mouseup', handleWindowMouseUp)

    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(scheduleMeasure)
      if (containerRef.value) resizeObserver.observe(containerRef.value)
    }

    // 字体加载完成后字宽会变化，需要重新测量
    if ('fonts' in document) {
      document.fonts.ready.then(() => scheduleMeasure()).catch(() => undefined)
    }

    measureRectsAndBoxes()
  })

  onUnmounted(() => {
    // capture 必须与注册时一致，否则监听器不会被移除
    window.removeEventListener('keydown', handleKeydown, true)
    window.removeEventListener('resize', scheduleMeasure)
    window.removeEventListener('mouseup', handleWindowMouseUp)
    resizeObserver?.disconnect()
    resizeObserver = null
    if (measureFrame) cancelAnimationFrame(measureFrame)
  })

  return {
    // 项目与配置
    projectName,
    labelsInput,
    relationTypesInput,
    labels,
    relationTypes,
    palette,
    relPalette,
    projectList,
    pid,
    projectsLoading,
    projectLoading,
    savingProject,
    // 文档
    items,
    currentIndex,
    currentFileName,
    splitMode,
    uploadInfo,
    hasDocuments,
    canPrev,
    canNext,
    // 标注
    text,
    spans,
    relations,
    chars,
    spanRenderList,
    relationVisuals,
    linkedSpanIds,
    // 测量
    containerRef,
    overlayHeight,
    fontSize,
    lineH,
    relStrokeWidth,
    relDashed,
    annotationStyle,
    // 浮层
    pending,
    labelPickerOpen,
    relPickerOpen,
    pendingRel,
    selectedSpanId,
    hoverRelIdx,
    showSettings,
    splitHelpOpen,
    // 状态
    savingRecord,
    statusOf,
    statusTitle,
    // 方法
    setCharRef,
    spanColor,
    spanSegmentStyle,
    spanLabelText,
    handleContainerMouseUp,
    handleContainerContextMenu,
    handleSpanMouseDown,
    handleSpanMouseUp,
    handleSpanClick,
    addSpan,
    cancelLabelPicker,
    addRelation,
    cancelRelPicker,
    handleRelationTypeChange,
    deleteRelation,
    selectItem,
    prevItem,
    nextItem,
    handleSkip,
    handleSaveOnly,
    handleSaveAndNext,
    handleDeleteCurrent,
    handleFilesSelected,
    handleDrop,
    handleConfigUpload,
    handleProjectSelect,
    handleSwitchProject,
    clearProject,
    deleteProject,
    exportZip,
    saveProject,
  }
}

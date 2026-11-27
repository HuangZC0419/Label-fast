import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import type {
  AnnotationRecord,
  AnnotationRelation,
  AnnotationSpan,
  ParagraphAnnotation,
} from '../types'
import {
  canonicalOffsetFromPoint,
  createRangeFromOffsets,
  rangeToCanonicalOffsets,
} from '../utils/markdown'
import type { TextMap } from '../utils/markdown'
import {
  comboFromKeyboardEvent,
  digitFromKeyboardEvent,
  effectiveShortcuts,
  isReservedShortcut,
  shortcutIndex,
} from '../utils/shortcuts'

/**
 * 渲染后 Markdown 的实体/关系标注领域状态。
 *
 * 职责边界：
 * - 这里只维护数据、选区、快捷键与 CSS Highlight 同步；
 * - DOM 布局测量（关系曲线、降级高亮矩形）由 MarkdownAnnotator 负责，
 *   因为二者都依赖真实排版，放在这里会让状态层与浏览器布局耦合。
 */

export const LABEL_COLORS = [
  '#EFB7A3',
  '#C7D6A7',
  '#A9C4D8',
  '#E8D6A2',
  '#D8B6C4',
  '#B6C7BF',
]

export const RELATION_COLORS = [
  '#8C5A3C',
  '#5B6B8C',
  '#5F7F6A',
  '#A6543A',
  '#7A6A8C',
  '#5A5A5A',
]

export function labelColor(label: string, labels: string[]): string {
  const index = labels.indexOf(label)
  return index >= 0 ? LABEL_COLORS[index % LABEL_COLORS.length] : '#9A9DA3'
}

export function relationColor(type: string, relationTypes: string[]): string {
  const index = relationTypes.indexOf(type)
  return index >= 0 ? RELATION_COLORS[index % RELATION_COLORS.length] : '#5A5A5A'
}

export function hexToRgba(hex: string, alpha: number): string {
  const value = hex.replace('#', '')
  const red = Number.parseInt(value.slice(0, 2), 16)
  const green = Number.parseInt(value.slice(2, 4), 16)
  const blue = Number.parseInt(value.slice(4, 6), 16)
  if (![red, green, blue].every(Number.isFinite)) return `rgba(110,114,122,${alpha})`
  return `rgba(${red},${green},${blue},${alpha})`
}

export interface AnnotationPayload {
  text: string
  spans: AnnotationSpan[]
  relations: AnnotationRelation[]
  paragraphs: ParagraphAnnotation[]
}

export interface PendingMarkdownSelection {
  start: number
  end: number
  text: string
  /** 选区起点所在的块 ID；未使用逐块渲染时为空。 */
  blockId?: string
}

export interface PendingMarkdownRelation {
  fromId: number
  toId: number
}

interface AnnotationSnapshot {
  spans: AnnotationSpan[]
  relations: AnnotationRelation[]
  paragraphs: ParagraphAnnotation[]
}

interface UseMarkdownAnnotationOptions {
  labels: () => string[]
  relationTypes: () => string[]
  /**
   * 项目级自定义快捷键覆盖项；缺省表示全部沿用默认 1–9。
   * 用 getter 传入，父组件替换项目对象后无需重建组合式函数。
   */
  shortcuts?: () => Record<string, string>
  /** 标注画布被 v-show 隐藏或处于编辑模式时，不应响应全局快捷键。 */
  isActive?: () => boolean
}

interface HighlightLike {
  add(range: Range): void
}

interface HighlightConstructor {
  new (): HighlightLike
}

interface HighlightRegistryLike {
  set(name: string, highlight: HighlightLike): void
  delete(name: string): void
  keys(): IterableIterator<string>
}

const MAX_HISTORY = 100
const HIGHLIGHT_STYLE_ATTRIBUTE = 'data-lf-highlight-styles'

export function useMarkdownAnnotation(options: UseMarkdownAnnotationOptions) {
  const root = shallowRef<HTMLElement | null>(null)
  const textMap = shallowRef<TextMap | null>(null)
  const canonicalText = ref('')

  const spans = ref<AnnotationSpan[]>([])
  const relations = ref<AnnotationRelation[]>([])
  const paragraphs = ref<ParagraphAnnotation[]>([])
  const history = ref<AnnotationSnapshot[]>([])
  const nextId = ref(1)

  const pendingSelection = ref<PendingMarkdownSelection | null>(null)
  const pendingRelation = ref<PendingMarkdownRelation | null>(null)
  const relationFromId = ref<number | null>(null)
  const selectedSpanId = ref<number | null>(null)
  const selectedRelationIndex = ref<number | null>(null)
  const linkedSpanIds = ref<number[]>([])

  const highlightSupported = ref(false)

  let highlightStyleElement: HTMLStyleElement | null = null

  const hasAnnotations = computed(
    () =>
      spans.value.length > 0 ||
      relations.value.length > 0 ||
      paragraphs.value.length > 0,
  )
  const canUndo = computed(() => history.value.length > 0)
  const selectedRelation = computed<AnnotationRelation | null>(() => {
    const index = selectedRelationIndex.value
    if (index === null) return null
    return relations.value[index] ?? null
  })

  /**
   * 有效快捷键的反查表（组合键 → 标签）。
   * 依赖标签顺序与项目覆盖项，二者变化时自动重建；按键处理只做一次 Map 命中。
   */
  const shortcutByCombo = computed<Map<string, string>>(() =>
    shortcutIndex(
      effectiveShortcuts(options.labels(), options.shortcuts?.() ?? {}),
    ),
  )

  /* ============================================================
     文档与数据
     ============================================================ */

  function setDocument(element: HTMLElement, map: TextMap): void {
    root.value = element
    textMap.value = map
    canonicalText.value = map.text
    syncHighlights()
  }

  function detachDocument(): void {
    root.value = null
    textMap.value = null
    clearHighlightRegistry()
  }

  /**
   * 读取标注时做一次防御性归一化，避免旧文本/悬空关系污染当前文档。
   * `validBlockIds` 存在时，会丢弃指向已不存在块的段落标注与 span.blockId
   * （例如 Markdown 被编辑后块被重新切分）；不传则原样保留。
   */
  function loadAnnotations(
    record: AnnotationRecord | null | undefined,
    validBlockIds?: ReadonlySet<string>,
  ): void {
    clearTransientState()
    history.value = []

    const map = textMap.value
    if (!map || !record) {
      spans.value = []
      relations.value = []
      paragraphs.value = []
      nextId.value = 1
      syncHighlights()
      return
    }

    const usedIds = new Set<number>()
    let loadedSpans: AnnotationSpan[] = []
    let maxId = 0

    for (const source of Array.isArray(record.spans) ? record.spans : []) {
      const rawStart = Number(source.start)
      const rawEnd = Number(source.end)
      if (!Number.isFinite(rawStart) || !Number.isFinite(rawEnd)) continue

      let start = Math.max(0, Math.floor(rawStart))
      let end = Math.min(map.text.length, Math.floor(rawEnd))
      const expectedText = typeof source.text === 'string' ? source.text : ''

      if (expectedText && map.text.slice(start, end) !== expectedText) {
        const relocated = findClosestOccurrence(map.text, expectedText, start)
        if (relocated < 0) continue
        start = relocated
        end = relocated + expectedText.length
      }

      if (start >= end || end > map.text.length) continue

      let id = Number.isInteger(source.id) && Number(source.id) > 0 ? Number(source.id) : 0
      if (!id || usedIds.has(id)) {
        id = 1
        while (usedIds.has(id)) id += 1
      }

      usedIds.add(id)
      maxId = Math.max(maxId, id)
      const label =
        typeof source.label === 'string' && source.label.trim()
          ? source.label.trim()
          : '未标注'
      const span: AnnotationSpan = {
        id,
        start,
        end,
        label,
        text: map.text.slice(start, end),
      }
      const blockId = typeof source.blockId === 'string' ? source.blockId.trim() : ''
      if (blockId && (!validBlockIds || validBlockIds.has(blockId))) {
        span.blockId = blockId
      }
      loadedSpans.push(span)
    }

    /*
     * 历史数据里存在完全重复的记录（同一范围、同一标签被保存了多次）。
     * 按「范围 + 标签」去重，保留后出现的记录（id 更大，通常是最后一次操作）；
     * 不同标签标注同一范围的冲突不在这里合并——它们是真实的数据冲突，
     * 画布会把同一范围的标签合并到一枚胶囊里展示，用户重新应用标签时再收敛。
     */
    const uniqueSpans = new Map<string, AnnotationSpan>()
    const duplicateIdRemap = new Map<number, number>()
    for (const span of loadedSpans) {
      const key = `${span.start}:${span.end}:${span.label}`
      const existing = uniqueSpans.get(key)
      if (existing) duplicateIdRemap.set(existing.id, span.id)
      uniqueSpans.set(key, span)
    }
    loadedSpans = Array.from(uniqueSpans.values())

    // 重复记录被合并后，原本指向旧 id 的关系改指向保留的那条，避免关系静默丢失。
    const resolveSpanId = (id: number): number => {
      let current = id
      for (let step = 0; step < 32; step += 1) {
        const next = duplicateIdRemap.get(current)
        if (next === undefined) return current
        current = next
      }
      return current
    }

    const spanIds = new Set(loadedSpans.map((span) => span.id))
    const seenRelations = new Set<string>()
    const loadedRelations: AnnotationRelation[] = []

    for (const relation of Array.isArray(record.relations) ? record.relations : []) {
      const fromId = resolveSpanId(Number(relation.fromId))
      const toId = resolveSpanId(Number(relation.toId))
      const type = typeof relation.type === 'string' ? relation.type.trim() : ''
      if (!spanIds.has(fromId) || !spanIds.has(toId) || fromId === toId || !type) continue
      const key = `${fromId}:${toId}:${type}`
      if (seenRelations.has(key)) continue
      seenRelations.add(key)
      loadedRelations.push({ fromId, toId, type })
    }

    const usedBlockIds = new Set<string>()
    const loadedParagraphs: ParagraphAnnotation[] = []

    for (const paragraph of Array.isArray(record.paragraphs) ? record.paragraphs : []) {
      if (!paragraph || typeof paragraph !== 'object') continue
      const blockId =
        typeof paragraph.blockId === 'string' ? paragraph.blockId.trim() : ''
      const label = typeof paragraph.label === 'string' ? paragraph.label.trim() : ''
      if (!blockId || !label || usedBlockIds.has(blockId)) continue
      if (validBlockIds && !validBlockIds.has(blockId)) continue
      usedBlockIds.add(blockId)
      loadedParagraphs.push({
        blockId,
        label,
        note: typeof paragraph.note === 'string' ? paragraph.note : '',
      })
    }

    spans.value = loadedSpans
    relations.value = loadedRelations
    paragraphs.value = loadedParagraphs
    nextId.value = maxId + 1
    syncHighlights()
  }

  function getPayload(): AnnotationPayload {
    const map = textMap.value
    return {
      text: map?.text ?? canonicalText.value,
      spans: spans.value.map((span) => ({
        ...span,
        text: map ? map.text.slice(span.start, span.end) : span.text,
      })),
      relations: relations.value.map((relation) => ({ ...relation })),
      paragraphs: paragraphs.value.map((paragraph) => ({ ...paragraph })),
    }
  }

  function getSpan(spanId: number): AnnotationSpan | null {
    return spans.value.find((span) => span.id === spanId) ?? null
  }

  function getSpanText(spanId: number): string {
    return getSpan(spanId)?.text ?? `#${spanId}`
  }

  function getParagraph(blockId: string): ParagraphAnnotation | null {
    return paragraphs.value.find((paragraph) => paragraph.blockId === blockId) ?? null
  }

  /**
   * 设置/更新段落标注；label 为空表示删除该段落的标注。
   * 与实体标注共用同一撤销栈，保存时一起进入 payload。
   */
  function setParagraphLabel(blockId: string, label: string): boolean {
    const id = blockId.trim()
    if (!id) return false
    const nextLabel = label.trim()
    const index = paragraphs.value.findIndex((paragraph) => paragraph.blockId === id)

    if (!nextLabel) {
      if (index < 0) return false
      pushHistory()
      paragraphs.value = paragraphs.value.filter((paragraph) => paragraph.blockId !== id)
      return true
    }

    if (!options.labels().includes(nextLabel)) return false
    if (index >= 0 && paragraphs.value[index].label === nextLabel) return true

    pushHistory()
    if (index >= 0) {
      paragraphs.value = paragraphs.value.map((paragraph) =>
        paragraph.blockId === id ? { ...paragraph, label: nextLabel } : paragraph,
      )
    } else {
      paragraphs.value = [...paragraphs.value, { blockId: id, label: nextLabel, note: '' }]
    }
    return true
  }

  function removeParagraphLabel(blockId: string): boolean {
    return setParagraphLabel(blockId, '')
  }

  function findSpanAtOffset(offset: number): AnnotationSpan | null {
    const candidates = spans.value.filter(
      (span) => span.start <= offset && offset < span.end,
    )
    if (candidates.length === 0) return null
    candidates.sort((left, right) => {
      const leftLength = left.end - left.start
      const rightLength = right.end - right.start
      if (leftLength !== rightLength) return leftLength - rightLength
      return right.id - left.id
    })
    return candidates[0] ?? null
  }

  function findSpanAtPoint(x: number, y: number): AnnotationSpan | null {
    const map = textMap.value
    if (!map) return null
    const offset = canonicalOffsetFromPoint(map, x, y)
    if (offset === null) return null
    return findSpanAtOffset(offset)
  }

  /* ============================================================
     编辑动作
     ============================================================ */

  function pushHistory(): void {
    history.value.push({
      spans: spans.value.map((span) => ({ ...span })),
      relations: relations.value.map((relation) => ({ ...relation })),
      paragraphs: paragraphs.value.map((paragraph) => ({ ...paragraph })),
    })
    if (history.value.length > MAX_HISTORY) history.value.shift()
  }

  function setPendingSelectionFromRange(range: Range): boolean {
    const map = textMap.value
    if (!map) return false
    const offsets = rangeToCanonicalOffsets(map, range)
    if (!offsets) return false
    const text = map.text.slice(offsets.start, offsets.end)
    if (!text.trim()) return false

    const blockId = findClosestBlockId(range.startContainer, map.root)
    pendingSelection.value = blockId ? { ...offsets, text, blockId } : { ...offsets, text }
    pendingRelation.value = null
    relationFromId.value = null
    selectedSpanId.value = null
    selectedRelationIndex.value = null
    syncHighlights()
    return true
  }

  function applyLabel(label: string): boolean {
    const selection = pendingSelection.value
    if (!selection) return false
    if (!options.labels().includes(label)) return false

    /*
     * 同一段文本重复标注时不要继续新增 span：
     * - 同范围、同标签：已经是想要的结果，直接当作成功，避免生成完全重复的记录；
     * - 同范围、不同标签：用新标签整体替换该范围上的旧标签，避免一段文本越标越多。
     * 多人/多次标注留下的冲突，用户重新选中这段文本并应用一次标签即可收敛为一条。
     */
    const sameRange = spans.value.filter(
      (span) => span.start === selection.start && span.end === selection.end,
    )
    if (sameRange.length > 0) {
      if (sameRange.every((span) => span.label === label)) {
        const existing = sameRange[sameRange.length - 1]
        pendingSelection.value = null
        pendingRelation.value = null
        selectedSpanId.value = existing.id
        selectedRelationIndex.value = null
        relationFromId.value = null
        clearBrowserSelection()
        syncHighlights()
        return true
      }

      const removedIds = new Set(sameRange.map((span) => span.id))
      pushHistory()
      spans.value = spans.value.filter((span) => !removedIds.has(span.id))
      relations.value = relations.value.filter(
        (relation) =>
          !removedIds.has(relation.fromId) && !removedIds.has(relation.toId),
      )
      const relabeled: AnnotationSpan = {
        id: nextId.value,
        start: selection.start,
        end: selection.end,
        label,
        text: selection.text,
      }
      if (selection.blockId) relabeled.blockId = selection.blockId
      nextId.value += 1
      spans.value = [...spans.value, relabeled]
      pendingSelection.value = null
      pendingRelation.value = null
      selectedSpanId.value = relabeled.id
      selectedRelationIndex.value = null
      relationFromId.value = null
      clearBrowserSelection()
      syncHighlights()
      return true
    }

    pushHistory()
    const span: AnnotationSpan = {
      id: nextId.value,
      start: selection.start,
      end: selection.end,
      label,
      text: selection.text,
    }
    if (selection.blockId) span.blockId = selection.blockId
    nextId.value += 1
    spans.value = [...spans.value, span]
    pendingSelection.value = null
    pendingRelation.value = null
    selectedSpanId.value = span.id
    selectedRelationIndex.value = null
    // 选中态本身可充当关系起点；再次点击另一个实体即可形成待选关系。
    relationFromId.value = null
    clearBrowserSelection()
    syncHighlights()
    return true
  }

  function applyRelation(type: string): boolean {
    const pair = pendingRelation.value
    if (!pair) return false
    if (!options.relationTypes().includes(type)) return false

    const source = getSpan(pair.fromId)
    const target = getSpan(pair.toId)
    if (!source || !target || source.id === target.id) {
      pendingRelation.value = null
      relationFromId.value = null
      return false
    }

    const duplicate = relations.value.some(
      (relation) =>
        relation.fromId === pair.fromId &&
        relation.toId === pair.toId &&
        relation.type === type,
    )
    if (!duplicate) {
      pushHistory()
      relations.value = [
        ...relations.value,
        { fromId: pair.fromId, toId: pair.toId, type },
      ]
    }

    const index = relations.value.findIndex(
      (relation) =>
        relation.fromId === pair.fromId &&
        relation.toId === pair.toId &&
        relation.type === type,
    )
    selectedRelationIndex.value = index >= 0 ? index : null
    selectedSpanId.value = null
    pendingRelation.value = null
    relationFromId.value = null
    syncHighlights()
    return true
  }

  /**
   * 点击高亮实体。
   * 第一次点击选中并记录关系起点，第二次点击另一个实体形成待选关系。
   */
  function selectSpanAtPoint(x: number, y: number): boolean {
    const hit = findSpanAtPoint(x, y)
    if (!hit) {
      clearTransientState()
      syncHighlights()
      return false
    }
    return selectSpan(hit)
  }

  /**
   * 按 id 选中实体：点击标签名胶囊时使用。
   * 胶囊在正文上方，若让事件穿透会按坐标选中相邻实体，
   * 因此这里直接命中胶囊对应的 span，保证「点哪枚标签就选中哪处标注」。
   */
  function selectSpanById(spanId: number): boolean {
    const hit = getSpan(spanId)
    if (!hit) return false
    return selectSpan(hit)
  }

  /** 选中/关系起点状态机；点击正文与点击标签名胶囊共用。 */
  function selectSpan(hit: AnnotationSpan): boolean {
    if (pendingRelation.value) {
      pendingRelation.value = null
      relationFromId.value = hit.id
      selectedSpanId.value = hit.id
      selectedRelationIndex.value = null
      syncHighlights()
      return true
    }

    // 显式的第一次点击优先；否则已选中的实体可以直接作为关系起点。
    const sourceId =
      relationFromId.value ??
      (selectedSpanId.value !== null && selectedSpanId.value !== hit.id
        ? selectedSpanId.value
        : null)

    if (sourceId !== null && sourceId !== hit.id) {
      pendingRelation.value = { fromId: sourceId, toId: hit.id }
      relationFromId.value = null
      selectedSpanId.value = hit.id
      selectedRelationIndex.value = null
      syncHighlights()
      return true
    }

    selectedSpanId.value = hit.id
    selectedRelationIndex.value = null
    relationFromId.value = hit.id
    pendingRelation.value = null
    syncHighlights()
    return true
  }

  function selectRelation(index: number): void {
    if (index < 0 || index >= relations.value.length) return
    selectedRelationIndex.value = index
    selectedSpanId.value = null
    pendingSelection.value = null
    pendingRelation.value = null
    relationFromId.value = null
    clearBrowserSelection()
    syncHighlights()
  }

  function setLinkedSpans(ids: number[]): void {
    const next = Array.from(new Set(ids))
    if (
      next.length === linkedSpanIds.value.length &&
      next.every((id, index) => id === linkedSpanIds.value[index])
    ) {
      return
    }
    linkedSpanIds.value = next
    syncHighlights()
  }

  function cancelPendingSelection(): void {
    pendingSelection.value = null
    clearBrowserSelection()
    syncHighlights()
  }

  function cancelPendingRelation(): void {
    pendingRelation.value = null
    relationFromId.value = null
    syncHighlights()
  }

  function clearTransientState(): void {
    pendingSelection.value = null
    pendingRelation.value = null
    relationFromId.value = null
    selectedSpanId.value = null
    selectedRelationIndex.value = null
    linkedSpanIds.value = []
  }

  function clearBrowserSelection(): void {
    window.getSelection()?.removeAllRanges()
  }

  function deleteSelected(): boolean {
    if (selectedRelationIndex.value !== null) {
      return removeRelationAt(selectedRelationIndex.value)
    }
    if (selectedSpanId.value !== null) {
      return removeSpan(selectedSpanId.value)
    }
    return false
  }

  function removeSpan(spanId: number): boolean {
    if (!spans.value.some((span) => span.id === spanId)) return false
    pushHistory()
    spans.value = spans.value.filter((span) => span.id !== spanId)
    relations.value = relations.value.filter(
      (relation) => relation.fromId !== spanId && relation.toId !== spanId,
    )
    if (selectedSpanId.value === spanId) selectedSpanId.value = null
    if (relationFromId.value === spanId) relationFromId.value = null
    if (
      pendingRelation.value &&
      (pendingRelation.value.fromId === spanId || pendingRelation.value.toId === spanId)
    ) {
      pendingRelation.value = null
    }
    selectedRelationIndex.value = null
    syncHighlights()
    return true
  }

  function removeRelationAt(index: number): boolean {
    if (index < 0 || index >= relations.value.length) return false
    pushHistory()
    relations.value = relations.value.filter((_, relationIndex) => relationIndex !== index)
    selectedRelationIndex.value = null
    syncHighlights()
    return true
  }

  function undo(): void {
    const snapshot = history.value.pop()
    if (!snapshot) return
    spans.value = snapshot.spans.map((span) => ({ ...span }))
    relations.value = snapshot.relations.map((relation) => ({ ...relation }))
    paragraphs.value = snapshot.paragraphs.map((paragraph) => ({ ...paragraph }))
    nextId.value =
      spans.value.reduce((max, span) => Math.max(max, span.id), 0) + 1
    clearTransientState()
    clearBrowserSelection()
    syncHighlights()
  }

  function clearAnnotations(): void {
    spans.value = []
    relations.value = []
    paragraphs.value = []
    history.value = []
    nextId.value = 1
    clearTransientState()
    syncHighlights()
  }

  /* ============================================================
     快捷键
     ============================================================ */

  /** 输入框 / 文本域 / 可编辑区域内不响应标注快捷键（保留浏览器原生的输入行为）。 */
  function isEditableTarget(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) return false
    return (
      target.tagName === 'INPUT' ||
      target.tagName === 'TEXTAREA' ||
      target.tagName === 'SELECT' ||
      target.isContentEditable
    )
  }

  /**
   * 焦点在弹窗内时不做标注快捷键处理。
   *
   * 弹窗打开后画布仍处于激活态（只是被遮罩盖住），若继续响应按键，
   * 快捷键设置弹窗的「录制」会被背景画布抢先应用标签，甚至一次按键
   * 同时触发录制与标注。这里以对话框语义作为边界，比依赖监听器注册顺序可靠。
   */
  function isInsideDialog(target: EventTarget | null): boolean {
    if (!(target instanceof Element)) return false
    return target.closest('[role="dialog"], [role="alertdialog"]') !== null
  }

  function handleKeydown(event: KeyboardEvent): void {
    if (event.defaultPrevented) return
    if (options.isActive && !options.isActive()) return
    if (isEditableTarget(event.target) || isInsideDialog(event.target)) return
    /*
     * 部分中文输入法在正文区域仍会把 isComposing 置位（并没有真正在输入框里打字），
     * 导致数字标签快捷键被整体拦掉。这里只放行「已有待标注选区/待选关系 + 物理数字键」，
     * 不影响输入框内的中文输入（上面已经排除可编辑目标）。
     */
    if (event.isComposing) {
      const composingDigit = digitFromKeyboardEvent(event)
      if (
        !composingDigit ||
        (!pendingSelection.value && !pendingRelation.value)
      ) {
        return
      }
    }

    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z' && !event.shiftKey) {
      if (canUndo.value) {
        event.preventDefault()
        undo()
      }
      return
    }

    if (event.key === 'Escape') {
      if (
        pendingSelection.value ||
        pendingRelation.value ||
        selectedSpanId.value !== null ||
        selectedRelationIndex.value !== null
      ) {
        event.preventDefault()
        clearTransientState()
        clearBrowserSelection()
        syncHighlights()
      }
      return
    }

    if (event.key === 'Delete') {
      if (selectedSpanId.value !== null || selectedRelationIndex.value !== null) {
        event.preventDefault()
        deleteSelected()
      }
      return
    }

    // Ctrl+1–9 属于关系快捷键，永远优先于标签快捷键：
    // 即使某个标签自定义了组合键，也不能劫持待选关系时的 Ctrl+数字。
    // 数字按物理键识别，兼容需要 Shift 才能打出数字的键盘布局与小键盘。
    const relationDigit = digitFromKeyboardEvent(event)
    if (
      (event.ctrlKey || event.metaKey) &&
      !event.altKey &&
      !event.shiftKey &&
      relationDigit
    ) {
      if (!pendingRelation.value) return
      const type = options.relationTypes()[Number(relationDigit) - 1]
      if (!type) return
      event.preventDefault()
      applyRelation(type)
      return
    }

    // 标签快捷键：默认前 9 个标签 1–9，项目覆盖项优先（支持单键与 Ctrl/Alt 组合）。
    // 没有待标注选区时不拦截按键，避免把页面上其它普通按键吞掉。
    if (!pendingSelection.value) return
    const combo = comboFromKeyboardEvent(event)
    if (!combo || isReservedShortcut(combo)) return
    const label = shortcutByCombo.value.get(combo)
    if (!label) return
    event.preventDefault()
    applyLabel(label)
  }

  /* ============================================================
     CSS Custom Highlight API
     ============================================================ */

  function syncHighlights(): void {
    const registry = getHighlightRegistry()
    const HighlightClass = getHighlightConstructor()
    if (!registry || !HighlightClass) {
      highlightSupported.value = false
      clearHighlightRegistry()
      return
    }

    highlightSupported.value = true
    clearHighlightRegistry()
    updateHighlightStyles()

    const map = textMap.value
    if (!map) return

    // 按 Highlight 名称分组：多个已删除标签会共用 lf-label-unknown，
    // 若按 label 分组会互相覆盖，只剩最后一组可见。
    const labels = options.labels()
    const rangeGroups = new Map<string, Range[]>()
    for (const span of spans.value) {
      const range = createRangeFromOffsets(map, span.start, span.end)
      if (!range) continue
      const labelIndex = labels.indexOf(span.label)
      const name = labelIndex >= 0 ? `lf-label-${labelIndex}` : 'lf-label-unknown'
      const ranges = rangeGroups.get(name) ?? []
      ranges.push(range)
      rangeGroups.set(name, ranges)
    }

    for (const [name, ranges] of rangeGroups) {
      const highlight = new HighlightClass()
      ranges.forEach((range) => highlight.add(range))
      registry.set(name, highlight)
    }

    const selected = selectedSpanId.value !== null ? getSpan(selectedSpanId.value) : null
    if (selected) {
      const range = createRangeFromOffsets(map, selected.start, selected.end)
      if (range) {
        const highlight = new HighlightClass()
        highlight.add(range)
        registry.set('lf-selected', highlight)
      }
    }

    const linkedIds = new Set(linkedSpanIds.value)
    const selectedRelationValue = selectedRelation.value
    if (selectedRelationValue) {
      linkedIds.add(selectedRelationValue.fromId)
      linkedIds.add(selectedRelationValue.toId)
    }
    const linkedRanges: Range[] = []
    for (const spanId of linkedIds) {
      const span = getSpan(spanId)
      if (!span) continue
      const range = createRangeFromOffsets(map, span.start, span.end)
      if (range) linkedRanges.push(range)
    }
    if (linkedRanges.length > 0) {
      const highlight = new HighlightClass()
      linkedRanges.forEach((range) => highlight.add(range))
      registry.set('lf-linked', highlight)
    }
  }

  function updateHighlightStyles(): void {
    if (!document.head) return
    if (!highlightStyleElement || !highlightStyleElement.isConnected) {
      highlightStyleElement = document.createElement('style')
      highlightStyleElement.setAttribute(HIGHLIGHT_STYLE_ATTRIBUTE, '')
      document.head.appendChild(highlightStyleElement)
    }

    const labels = options.labels()
    const rules = labels.map((_, index) => {
      const color = LABEL_COLORS[index % LABEL_COLORS.length]
      return `::highlight(lf-label-${index}) { background-color: ${hexToRgba(color, 0.32)}; }`
    })
    rules.push(
      '::highlight(lf-label-unknown) { background-color: rgba(110, 114, 122, 0.24); }',
    )
    highlightStyleElement.textContent = rules.join('\n')
  }

  function getHighlightRegistry(): HighlightRegistryLike | null {
    if (typeof CSS === 'undefined') return null
    const registry = (CSS as unknown as { highlights?: HighlightRegistryLike }).highlights
    return registry && typeof registry.set === 'function' ? registry : null
  }

  function getHighlightConstructor(): HighlightConstructor | null {
    if (typeof window === 'undefined') return null
    const constructor = (window as unknown as { Highlight?: HighlightConstructor }).Highlight
    return typeof constructor === 'function' ? constructor : null
  }

  function clearHighlightRegistry(): void {
    const registry = getHighlightRegistry()
    if (!registry) return
    try {
      for (const name of Array.from(registry.keys())) {
        if (name.startsWith('lf-')) registry.delete(name)
      }
    } catch {
      // 某些实现会在注册表被外部清理时抛错；清空失败不应影响标注本身。
    }
  }

  /* ============================================================
     生命周期
     ============================================================ */

  watch(
    [spans, selectedSpanId, selectedRelationIndex, linkedSpanIds],
    () => syncHighlights(),
  )
  watch(
    () => options.labels().slice(),
    () => syncHighlights(),
  )

  onMounted(() => {
    window.addEventListener('keydown', handleKeydown, true)
  })

  onBeforeUnmount(() => {
    window.removeEventListener('keydown', handleKeydown, true)
    clearHighlightRegistry()
    highlightStyleElement?.remove()
    highlightStyleElement = null
    root.value = null
    textMap.value = null
  })

  return {
    root,
    textMap,
    canonicalText,
    spans,
    relations,
    paragraphs,
    hasAnnotations,
    canUndo,
    pendingSelection,
    pendingRelation,
    relationFromId,
    selectedSpanId,
    selectedRelationIndex,
    selectedRelation,
    linkedSpanIds,
    highlightSupported,
    nextId,
    setDocument,
    detachDocument,
    loadAnnotations,
    getPayload,
    getSpan,
    getSpanText,
    getParagraph,
    setParagraphLabel,
    removeParagraphLabel,
    findSpanAtOffset,
    setPendingSelectionFromRange,
    applyLabel,
    applyRelation,
    selectSpanAtPoint,
    selectSpanById,
    selectRelation,
    setLinkedSpans,
    cancelPendingSelection,
    cancelPendingRelation,
    clearTransientState,
    deleteSelected,
    removeSpan,
    removeRelationAt,
    undo,
    clearAnnotations,
    syncHighlights,
  }
}

/**
 * 从选区起点向上查找最近的 `[data-block-id]`。
 * 只在当前文档根节点内查找，避免 Teleport 到 body 的 UI 干扰。
 */
function findClosestBlockId(node: Node | null, root: HTMLElement | null): string {
  if (!node || !root) return ''
  let element: Element | null =
    node.nodeType === Node.ELEMENT_NODE ? (node as Element) : node.parentElement

  while (element) {
    const blockId = element.getAttribute('data-block-id')
    if (blockId) return blockId
    if (element === root) break
    element = element.parentElement
  }
  return ''
}

function findClosestOccurrence(text: string, needle: string, anchor: number): number {
  if (!needle) return -1
  let best = -1
  let bestDistance = Number.POSITIVE_INFINITY
  let from = 0

  while (from <= text.length) {
    const index = text.indexOf(needle, from)
    if (index < 0) break
    const distance = Math.abs(index - anchor)
    if (distance < bestDistance) {
      best = index
      bestDistance = distance
    }
    from = index + Math.max(1, needle.length)
  }

  return best
}

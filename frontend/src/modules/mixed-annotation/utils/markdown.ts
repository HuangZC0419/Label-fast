import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import { apiUrl } from '../api/client'

/**
 * Markdown 渲染与 canonical text 映射。
 *
 * 设计目标：
 * 1. 渲染与标注共用同一份 DOM：渲染后只做一次文本节点测量，避免业务层重复解析 Markdown；
 * 2. canonical text 是保存/导出的唯一文本基准，块级元素之间用 \n、表格单元格之间用 \t；
 * 3. 映射以“文本节点”为最小单元，因此跨段落、跨表格单元格的 Range 可以稳定还原为字符偏移。
 */

/* ============================================================
   渲染
   ============================================================ */

interface MarkdownEnv {
  fileId: string
}

const markdown = new MarkdownIt({
  html: true,
  linkify: true,
  breaks: false,
  typographer: false,
})

/** 图片渲染规则：在 Markdown 语法层就改写成后端资源地址，避免浏览器请求原始相对路径。 */
markdown.renderer.rules.image = (tokens, index, options, env, self) => {
  const token = tokens[index]
  const source = token.attrGet('src') ?? ''
  const resolved = resolveMarkdownAssetUrl(source, (env as MarkdownEnv).fileId)
  if (resolved) token.attrSet('src', resolved)
  token.attrSet('loading', 'lazy')
  token.attrSet('decoding', 'async')
  return self.renderToken(tokens, index, options)
}

const SANITIZE_CONFIG = {
  ADD_TAGS: ['details', 'summary'],
  ADD_ATTR: ['colspan', 'rowspan', 'start', 'align', 'class', 'loading', 'decoding'],
  FORBID_TAGS: [
    'script',
    'style',
    'iframe',
    'object',
    'embed',
    'form',
    'input',
    'textarea',
    'button',
    'select',
    'option',
    'link',
    'meta',
  ],
  FORBID_ATTR: ['style', 'contenteditable', 'autofocus'],
}

/**
 * 将 Markdown 渲染为可安全注入的 HTML。
 * 返回的 HTML 已清洗、图片地址已改写、表格已增加横向滚动容器。
 */
export function renderMarkdown(source: string, options: { fileId: string }): string {
  const rawHtml = markdown.render(source ?? '', { fileId: options.fileId })
  const sanitized = DOMPurify.sanitize(rawHtml, SANITIZE_CONFIG)
  const template = document.createElement('template')
  template.innerHTML = sanitized

  rewriteImages(template.content, options.fileId)
  hardenLinks(template.content)
  wrapTables(template.content)

  return template.innerHTML
}

/**
 * 把 Markdown 中的相对图片路径改写为 `/api/files/{fid}/assets/{path}`。
 * 绝对 URL、data URL、锚点以及已经指向 `/api/` 的地址保持原样。
 */
export function resolveMarkdownAssetUrl(source: string, fileId: string): string | null {
  const value = source.trim()
  if (!value) return null

  if (/^(?:[a-z][a-z0-9+.-]*:|\/\/|#)/i.test(value)) {
    return value
  }
  if (value.startsWith('/api/') || value.startsWith('api/')) {
    return apiUrl(value.startsWith('/') ? value : `/${value}`)
  }

  if (!fileId) return value

  const hashIndex = value.search(/[?#]/)
  const pathPart = hashIndex >= 0 ? value.slice(0, hashIndex) : value
  const suffix = hashIndex >= 0 ? value.slice(hashIndex) : ''

  const segments = pathPart
    .replace(/\\/g, '/')
    .replace(/^\/+/, '')
    .split('/')
    .filter((segment) => segment && segment !== '.' && segment !== '..')
    .map(encodePathSegment)

  if (segments.length === 0) return value

  const assetPath = segments.join('/')
  return `${apiUrl(`/api/files/${encodeURIComponent(fileId)}/assets/${assetPath}`)}${suffix}`
}

function encodePathSegment(segment: string): string {
  try {
    return encodeURIComponent(decodeURIComponent(segment))
  } catch {
    return encodeURIComponent(segment)
  }
}

function rewriteImages(root: DocumentFragment, fileId: string): void {
  root.querySelectorAll('img').forEach((image) => {
    const source = image.getAttribute('src') ?? ''
    const resolved = resolveMarkdownAssetUrl(source, fileId)
    if (resolved) image.setAttribute('src', resolved)
    else image.removeAttribute('src')
    image.setAttribute('loading', 'lazy')
    image.setAttribute('decoding', 'async')
    if (!image.hasAttribute('alt')) image.setAttribute('alt', '')
  })
}

function hardenLinks(root: DocumentFragment): void {
  root.querySelectorAll('a').forEach((link) => {
    const href = link.getAttribute('href') ?? ''
    if (!href || href.startsWith('#')) return
    link.setAttribute('target', '_blank')
    link.setAttribute('rel', 'noopener noreferrer')
  })
}

function wrapTables(root: DocumentFragment): void {
  root.querySelectorAll('table').forEach((table) => {
    const parent = table.parentElement
    if (parent?.classList.contains('md-table-scroll')) return
    const wrapper = document.createElement('div')
    wrapper.className = 'md-table-scroll'
    table.parentNode?.insertBefore(wrapper, table)
    wrapper.appendChild(table)
  })
}

/* ============================================================
   canonical text 映射
   ============================================================ */

export interface TextMapEntry {
  node: Text
  /** 文本节点首字符在 canonical text 中的偏移 */
  start: number
  /** 文本节点末尾（不含）在 canonical text 中的偏移 */
  end: number
}

export interface TextMap {
  root: HTMLElement
  text: string
  entries: TextMapEntry[]
  byNode: Map<Text, TextMapEntry>
}

const SKIP_TAGS = new Set([
  'SCRIPT',
  'STYLE',
  'NOSCRIPT',
  'TEMPLATE',
  'SVG',
  'CANVAS',
  'VIDEO',
  'AUDIO',
  'IFRAME',
  'OBJECT',
  'EMBED',
])

/**
 * 块级元素在 canonical text 中插入换行。
 * 表格单独处理，避免表头、行、单元格的嵌套结构产生多余空行。
 */
const BLOCK_TAGS = new Set([
  'ADDRESS',
  'ARTICLE',
  'ASIDE',
  'BLOCKQUOTE',
  'DD',
  'DETAILS',
  'DIALOG',
  'DIV',
  'DL',
  'DT',
  'FIELDSET',
  'FIGCAPTION',
  'FIGURE',
  'FOOTER',
  'FORM',
  'H1',
  'H2',
  'H3',
  'H4',
  'H5',
  'H6',
  'HEADER',
  'HGROUP',
  'LI',
  'MAIN',
  'NAV',
  'OL',
  'P',
  'PRE',
  'SECTION',
  'SUMMARY',
  'UL',
])

class CanonicalBuilder {
  text = ''
  entries: TextMapEntry[] = []
  private lastEntryEnd = 0

  appendText(node: Text): void {
    if (!node.data) return
    const start = this.text.length
    this.text += node.data
    const end = this.text.length
    this.entries.push({ node, start, end })
    this.lastEntryEnd = end
  }

  appendSoftBreak(separator: '\n' | '\t'): void {
    if (this.text.length === 0) return
    const last = this.text[this.text.length - 1]
    if (separator === '\n' && last === '\n') return
    if (separator === '\t' && (last === '\t' || last === '\n')) return
    this.text += separator
  }

  /** 只删除“没有文本节点覆盖”的尾部分隔符，保证已有映射偏移不失效。 */
  trimTrailingSeparators(): void {
    while (
      this.text.length > this.lastEntryEnd &&
      (this.text[this.text.length - 1] === '\n' || this.text[this.text.length - 1] === '\t')
    ) {
      this.text = this.text.slice(0, -1)
    }
  }

  walkChildren(parent: Node): void {
    parent.childNodes.forEach((child) => this.walkNode(child))
  }

  walkNode(node: Node): void {
    if (node.nodeType === Node.TEXT_NODE) {
      if (!isFormattingWhitespace(node as Text)) this.appendText(node as Text)
      return
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return

    const element = node as HTMLElement
    if (SKIP_TAGS.has(element.tagName)) return

    if (element.tagName === 'TABLE') {
      this.appendSoftBreak('\n')
      this.walkTable(element as HTMLTableElement)
      this.appendSoftBreak('\n')
      return
    }
    if (element.tagName === 'BR') {
      this.appendSoftBreak('\n')
      return
    }
    if (element.tagName === 'HR') {
      this.appendSoftBreak('\n')
      return
    }
    if (element.tagName === 'IMG') return

    const block = BLOCK_TAGS.has(element.tagName)
    if (block) this.appendSoftBreak('\n')
    this.walkChildren(element)
    if (block) this.appendSoftBreak('\n')
  }

  walkTable(table: HTMLTableElement): void {
    const caption = Array.from(table.children).find(
      (child) => child.tagName === 'CAPTION',
    ) as HTMLElement | undefined
    if (caption) {
      this.walkChildren(caption)
      this.appendSoftBreak('\n')
    }

    Array.from(table.rows).forEach((row) => {
      const cells = Array.from(row.cells)
      cells.forEach((cell, index) => {
        this.walkChildren(cell)
        if (index < cells.length - 1) {
          this.trimTrailingSeparators()
          this.appendSoftBreak('\t')
        }
      })
      this.appendSoftBreak('\n')
    })
  }
}

/**
 * 遍历已渲染的 DOM，生成 canonical text 与文本节点偏移映射。
 * 调用时机：v-html 更新完成后的 nextTick。
 */
export function buildTextMap(root: HTMLElement): TextMap {
  const builder = new CanonicalBuilder()
  builder.walkChildren(root)
  builder.trimTrailingSeparators()

  const byNode = new Map<Text, TextMapEntry>()
  builder.entries.forEach((entry) => byNode.set(entry.node, entry))

  return {
    root,
    text: builder.text,
    entries: builder.entries,
    byNode,
  }
}

/**
 * 把浏览器 Range 映射为 canonical text 的 [start, end)。
 * 只统计范围内实际文本节点，分隔符只在选区内部出现时才计入。
 */
export function rangeToCanonicalOffsets(
  map: TextMap,
  range: Range,
): { start: number; end: number } | null {
  if (!map.root.contains(range.commonAncestorContainer)) return null

  let start = -1
  let end = -1
  const nodeRange = document.createRange()

  for (const entry of map.entries) {
    nodeRange.selectNodeContents(entry.node)

    // 注意 compareBoundaryPoints 的常量方向：
    // END_TO_START 实际比较 range.start 与节点 end，START_TO_END 比较 range.end 与节点 start。
    if (range.compareBoundaryPoints(Range.END_TO_START, nodeRange) >= 0) continue
    if (range.compareBoundaryPoints(Range.START_TO_END, nodeRange) <= 0) continue

    let localStart = 0
    if (range.compareBoundaryPoints(Range.START_TO_START, nodeRange) > 0) {
      localStart = range.startContainer === entry.node ? range.startOffset : 0
    }

    let localEnd = entry.node.length
    if (range.compareBoundaryPoints(Range.END_TO_END, nodeRange) < 0) {
      localEnd = range.endContainer === entry.node ? range.endOffset : entry.node.length
    }

    localStart = Math.max(0, Math.min(entry.node.length, localStart))
    localEnd = Math.max(0, Math.min(entry.node.length, localEnd))
    if (localEnd <= localStart) continue

    if (start < 0) start = entry.start + localStart
    end = entry.start + localEnd
  }

  if (start < 0 || end <= start) return null
  return { start, end }
}

/**
 * 根据 canonical 偏移还原 DOM Range。
 * 偏移落在分隔符中时：起点向下一文本节点取整，终点向上一文本节点取整。
 */
export function createRangeFromOffsets(
  map: TextMap,
  start: number,
  end: number,
): Range | null {
  if (map.entries.length === 0) return null

  const safeStart = Math.max(0, Math.min(map.text.length, start))
  const safeEnd = Math.max(0, Math.min(map.text.length, end))
  if (safeStart >= safeEnd) return null

  const startPoint = resolveStartPoint(map, safeStart)
  const endPoint = resolveEndPoint(map, safeEnd)
  if (!startPoint || !endPoint) return null

  try {
    const range = document.createRange()
    range.setStart(startPoint.node, startPoint.offset)
    range.setEnd(endPoint.node, endPoint.offset)
    return range.collapsed ? null : range
  } catch {
    return null
  }
}

function resolveStartPoint(
  map: TextMap,
  offset: number,
): { node: Text; offset: number } | null {
  for (const entry of map.entries) {
    if (offset < entry.end) {
      return {
        node: entry.node,
        offset: Math.max(0, offset - entry.start),
      }
    }
  }
  const last = map.entries[map.entries.length - 1]
  return last ? { node: last.node, offset: last.node.length } : null
}

function resolveEndPoint(
  map: TextMap,
  offset: number,
): { node: Text; offset: number } | null {
  let point: { node: Text; offset: number } | null = null
  for (const entry of map.entries) {
    if (entry.start >= offset) break
    point = {
      node: entry.node,
      offset: Math.min(entry.node.length, offset - entry.start),
    }
  }
  if (point) return point

  const first = map.entries[0]
  return first ? { node: first.node, offset: 0 } : null
}

/**
 * 把 DOM 点（文本节点或元素子节点索引）转换为 canonical 偏移。
 * 用于点击高亮实体时定位光标所在的文本位置。
 */
export function canonicalOffsetFromDomPoint(
  map: TextMap,
  container: Node,
  offset: number,
): number | null {
  if (container.nodeType === Node.TEXT_NODE) {
    const entry = map.byNode.get(container as Text)
    if (!entry) return null
    return entry.start + Math.max(0, Math.min(entry.node.length, offset))
  }

  if (container.nodeType !== Node.ELEMENT_NODE) return null
  const element = container as HTMLElement
  if (!map.root.contains(element) && element !== map.root) return null

  if (offset < element.childNodes.length) {
    const child = element.childNodes[offset]
    const firstInside = firstEntryWithin(map, child)
    if (firstInside) return firstInside.start
    const firstAfter = firstEntryAfter(map, child)
    return firstAfter ? firstAfter.start : map.text.length
  }

  const lastInside = lastEntryWithin(map, element)
  return lastInside ? lastInside.end : map.text.length
}

/** 用鼠标坐标定位 canonical 偏移；点击正文空白或图片时返回 null。 */
export function canonicalOffsetFromPoint(
  map: TextMap,
  x: number,
  y: number,
): number | null {
  const doc = document as Document & {
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null
    caretRangeFromPoint?: (x: number, y: number) => Range | null
  }

  let container: Node | null = null
  let offset = 0

  if (typeof doc.caretPositionFromPoint === 'function') {
    const position = doc.caretPositionFromPoint(x, y)
    if (position) {
      container = position.offsetNode
      offset = position.offset
    }
  }

  if (!container && typeof doc.caretRangeFromPoint === 'function') {
    const range = doc.caretRangeFromPoint(x, y)
    if (range) {
      container = range.startContainer
      offset = range.startOffset
    }
  }

  if (!container || !map.root.contains(container)) return null
  return canonicalOffsetFromDomPoint(map, container, offset)
}

/**
 * markdown-it 在块标签之间输出仅含换行的文本节点。
 * 这些节点在浏览器中折叠为不可见空白，若计入 canonical text
 * 会让段落之间出现双换行，并让保存文本与用户看到的内容不一致。
 *
 * 保留范围：pre（代码）与段落/标题/内联文本容器中的换行，
 * 它们可能是 Markdown 软换行或代码内容，属于真实可选中文本。
 */
function isFormattingWhitespace(node: Text): boolean {
  const data = node.data
  if (!data || /\S/.test(data) || !data.includes('\n')) return false

  const parent = node.parentElement
  if (!parent) return false
  if (parent.closest('pre')) return false

  return !parent.closest(
    'p, h1, h2, h3, h4, h5, h6, a, em, strong, b, i, span, code, kbd, samp, small, sub, sup',
  )
}

function firstEntryWithin(map: TextMap, node: Node): TextMapEntry | null {
  for (const entry of map.entries) {
    if (entry.node === node || node.contains(entry.node)) return entry
  }
  return null
}

function lastEntryWithin(map: TextMap, node: Node): TextMapEntry | null {
  for (let index = map.entries.length - 1; index >= 0; index -= 1) {
    const entry = map.entries[index]
    if (entry.node === node || node.contains(entry.node)) return entry
  }
  return null
}

function firstEntryAfter(map: TextMap, node: Node): TextMapEntry | null {
  for (const entry of map.entries) {
    const relation = node.compareDocumentPosition(entry.node)
    if (relation & Node.DOCUMENT_POSITION_FOLLOWING) return entry
  }
  return null
}

import type { BlockInfo, BlocksPayload } from '../types'
import { renderMarkdown } from './markdown'

/**
 * 逐块渲染工具。
 *
 * 设计要点：
 * - 每个块独立调用 renderMarkdown，因此图片改写、表格包装、HTML 清洗
 *   与整篇渲染走完全相同的规则，避免两套渲染逻辑漂移；
 * - canonical text 由 MarkdownAnnotator 对所有块的外层容器统一测量
 *   （块级元素之间的换行在 CanonicalBuilder 中折叠），旧 span 偏移不受切块影响。
 */

/** 可以整体打段落标签的块类型；表格、图片、代码等仍可做实体标注。 */
export const PARAGRAPH_TAGGABLE_TYPES = new Set([
  'heading',
  'paragraph',
  'list',
  'blockquote',
])

export interface RenderedBlock {
  block: BlockInfo
  html: string
}

export function isParagraphTaggable(block: BlockInfo): boolean {
  return PARAGRAPH_TAGGABLE_TYPES.has(block.type)
}

/** 把后端返回的块逐块渲染为可注入 HTML；空列表表示调用方应回退整篇渲染。 */
export function renderBlocks(blocks: BlockInfo[], fileId: string): RenderedBlock[] {
  if (!Array.isArray(blocks) || blocks.length === 0) return []
  return blocks.map((block) => ({
    block,
    html: renderMarkdown(block.markdown ?? '', { fileId }),
  }))
}

/**
 * 防御性归一化 `/blocks` 响应：后端升级期间可能缺少字段，
 * 这里只保留可渲染的块，避免单个坏块导致整篇文档不可用。
 */
export function normalizeBlocks(payload: BlocksPayload | null | undefined): BlockInfo[] {
  const source = payload && Array.isArray(payload.blocks) ? payload.blocks : []
  const result: BlockInfo[] = []
  const seenIds = new Set<string>()

  source.forEach((raw, position) => {
    if (!raw || typeof raw !== 'object') return
    const id = typeof raw.id === 'string' ? raw.id.trim() : ''
    if (!id || seenIds.has(id)) return
    if (typeof raw.markdown !== 'string') return
    seenIds.add(id)

    const page = Number.isFinite(Number(raw.page)) ? Number(raw.page) : 0
    const pageEnd = Number.isFinite(Number(raw.pageEnd)) ? Number(raw.pageEnd) : page

    result.push({
      id,
      index: Number.isFinite(Number(raw.index)) ? Number(raw.index) : position,
      type: typeof raw.type === 'string' && raw.type ? raw.type : 'paragraph',
      markdown: raw.markdown,
      text: typeof raw.text === 'string' ? raw.text : '',
      start: Number.isFinite(Number(raw.start)) ? Number(raw.start) : 0,
      end: Number.isFinite(Number(raw.end)) ? Number(raw.end) : 0,
      page,
      pageEnd,
      sectionId: typeof raw.sectionId === 'string' ? raw.sectionId : '',
      sectionNumber: typeof raw.sectionNumber === 'string' ? raw.sectionNumber : '',
      sectionTitle: typeof raw.sectionTitle === 'string' ? raw.sectionTitle : '',
    })
  })

  return result
}

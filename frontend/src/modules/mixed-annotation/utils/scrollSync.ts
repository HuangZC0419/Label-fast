/**
 * Markdown ↔ PDF 的按页对齐（page-anchored sync）。
 *
 * 比例同步会在两侧内容高度差异很大时越滚越偏；这里给每一页建立「页首在本侧
 * 滚动内容里的偏移」，然后把源侧滚动位置落进某一页内部的百分比，再映射到目标侧
 * 同一页的对应位置。页面之间做线性插值，长段落跨页时也按页均分高度。
 */

export interface ScrollAnchor {
  page: number
  top: number
}

export interface ScrollInfo {
  scrollTop: number
  scrollHeight: number
  viewportHeight: number
  /** 页数（不含末尾哨兵）。 */
  pageCount: number
  /** 按 page 升序、包含末尾哨兵（page=pageCount+1, top=内容高度）。 */
  anchors: ScrollAnchor[]
}

/**
 * 把「页 → 页首偏移」补齐成 1..pageCount 的连续锚点，并追加内容末尾哨兵。
 * 缺页用相邻页线性插值；保证 top 单调不减，避免滚动映射跳变。
 */
export function buildPageAnchors(
  pageTops: Map<number, number>,
  pageCount: number,
  contentHeight: number,
): ScrollAnchor[] {
  if (pageCount <= 0) return []

  const known = Array.from(pageTops.entries())
    .filter(([page, top]) => page >= 1 && page <= pageCount && Number.isFinite(top))
    .sort((left, right) => left[0] - right[0])

  if (known.length === 0) return []

  const tops: number[] = new Array(pageCount + 1).fill(Number.NaN)
  for (const [page, top] of known) tops[page] = top

  // 第一页之前：用第一处已知页首；最后一页之后：插值到内容末尾。
  for (let page = 1; page <= pageCount; page += 1) {
    if (Number.isFinite(tops[page])) continue

    let previousPage = page - 1
    while (previousPage >= 1 && !Number.isFinite(tops[previousPage])) previousPage -= 1
    let nextPage = page + 1
    while (nextPage <= pageCount && !Number.isFinite(tops[nextPage])) nextPage += 1

    if (previousPage >= 1 && nextPage <= pageCount) {
      const ratio = (page - previousPage) / (nextPage - previousPage)
      tops[page] = tops[previousPage] + ratio * (tops[nextPage] - tops[previousPage])
    } else if (previousPage >= 1) {
      // 末尾没有更多页锚点：按剩余页数向内容高度均分。
      const remaining = pageCount - previousPage
      const ratio = remaining > 0 ? (page - previousPage) / Math.max(1, remaining) : 1
      tops[page] = tops[previousPage] + ratio * (contentHeight - tops[previousPage])
    } else if (nextPage <= pageCount) {
      // 文档开头没有页锚点：整体向第一处已知锚点回推。
      const offset = (nextPage - page) / Math.max(1, nextPage - 1)
      tops[page] = Math.max(0, tops[nextPage] - offset * tops[nextPage])
    } else {
      tops[page] = 0
    }
  }

  const anchors: ScrollAnchor[] = []
  let previousTop = 0
  for (let page = 1; page <= pageCount; page += 1) {
    const top = Math.max(previousTop, Number.isFinite(tops[page]) ? tops[page] : previousTop)
    anchors.push({ page, top })
    previousTop = top
  }
  anchors.push({
    page: pageCount + 1,
    top: Math.max(previousTop, Math.max(0, contentHeight)),
  })
  return anchors
}

/**
 * 把源侧滚动位置映射到目标侧。
 * 返回 null 表示锚点不足（调用方应回退到比例同步）。
 */
export function mapScrollTop(source: ScrollInfo, target: ScrollInfo): number | null {
  if (source.anchors.length < 2 || target.anchors.length !== source.anchors.length) {
    return null
  }

  const maxTarget = Math.max(0, target.scrollHeight - target.viewportHeight)
  const sourceTop = clamp(source.scrollTop, 0, Math.max(0, source.scrollHeight))
  const anchors = source.anchors

  if (sourceTop <= anchors[0].top) {
    return clamp(target.anchors[0].top, 0, maxTarget)
  }

  for (let index = 0; index < anchors.length - 1; index += 1) {
    const from = anchors[index]
    const to = anchors[index + 1]
    if (sourceTop > to.top) continue

    const span = Math.max(1, to.top - from.top)
    const ratio = clamp((sourceTop - from.top) / span, 0, 1)
    const targetFrom = target.anchors[index].top
    const targetTo = target.anchors[index + 1].top
    return clamp(targetFrom + ratio * (targetTo - targetFrom), 0, maxTarget)
  }

  return clamp(target.anchors[target.anchors.length - 1].top, 0, maxTarget)
}

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min
  return Math.min(max, Math.max(min, value))
}

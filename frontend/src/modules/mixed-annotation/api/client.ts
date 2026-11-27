import type {
  AnnotationRecord,
  BlocksPayload,
  FigureAnnotation,
  FigureCreatePayload,
  FigureDraftPayload,
} from '../types'

/**
 * 混合标注 API 客户端。
 *
 * 约定：
 * - 所有请求使用相对路径（`/api/...`），由 Vite dev server 或同源后端代理；
 *   严禁在此处硬编码主机名或端口。
 * - `apiFetch` 统一处理 JSON、空响应与非 2xx 错误；
 *   面向用户的错误信息放在 `Error.message`，原始 detail 同时保留在 `detail`。
 * - FormData 请求不手动设置 Content-Type，交由浏览器生成 boundary。
 */

export class ApiError extends Error {
  /** HTTP 状态码；网络层失败时为 0。 */
  readonly status: number
  /** 后端返回的 detail / message 原文。 */
  readonly detail?: string

  constructor(message: string, status = 0, detail?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** 混合标注模块的独立网关前缀；Vite 去前缀后后端仍收到 /api/...。 */
const API_BASE = '/mix-api'

/** 把业务路径规范化为 `/mix-api/api/...` 形式。 */
export function apiUrl(path: string): string {
  const normalized = path.startsWith('/') ? path : `/${path}`
  const withApi =
    normalized === '/api' || normalized.startsWith('/api/')
      ? normalized
      : `/api${normalized}`
  return `${API_BASE}${withApi}`
}

/**
 * 判断请求是否被 AbortSignal 中止。
 * 浏览器抛出的可能是 DOMException（不是所有环境都继承 Error），
 * 也可能是普通 Error，因此按 `name` 判定而非 `instanceof`。
 */
function isAbortError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'name' in error &&
    (error as { name?: unknown }).name === 'AbortError'
  )
}

function describeDetail(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (typeof item === 'string') return item
        if (item && typeof item === 'object' && 'msg' in item) {
          return String((item as { msg: unknown }).msg)
        }
        return JSON.stringify(item)
      })
      .filter(Boolean)
      .join('；')
  }
  if (value && typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch {
      return ''
    }
  }
  return ''
}

async function toApiError(response: Response): Promise<ApiError> {
  let detail = ''
  try {
    const raw = await response.text()
    if (raw.trim()) {
      try {
        const data = JSON.parse(raw) as { detail?: unknown; message?: unknown }
        detail = describeDetail(data?.detail ?? data?.message) || raw.trim()
      } catch {
        detail = raw.trim()
      }
    }
  } catch {
    // 响应体不可读时退化为状态码描述。
  }

  const message = detail || `请求失败（HTTP ${response.status}）`
  return new ApiError(message, response.status, detail || undefined)
}

/**
 * 发起请求并解析 JSON。
 * - 非 2xx：抛出 ApiError（message 为可直接展示的中文文案）。
 * - 204/205 或空响应：返回 undefined。
 * - 非 JSON 但可解析：尽力解析；否则按文本返回。
 */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')

  const body = init.body
  if (body != null && !(body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  let response: Response
  try {
    response = await fetch(apiUrl(path), { ...init, headers })
  } catch (error) {
    if (isAbortError(error)) {
      throw new ApiError(
        '请求超时，请稍后重试。',
        0,
        error instanceof Error ? error.message : undefined,
      )
    }
    throw new ApiError(
      '无法连接本地服务，请确认后端已启动。',
      0,
      error instanceof Error ? error.message : undefined,
    )
  }

  if (!response.ok) throw await toApiError(response)
  if (response.status === 204 || response.status === 205) return undefined as T

  const raw = await response.text()
  if (!raw.trim()) return undefined as T

  const contentType = response.headers.get('content-type') ?? ''
  if (contentType.includes('application/json')) {
    try {
      return JSON.parse(raw) as T
    } catch {
      throw new ApiError('服务端返回了无法解析的 JSON。', response.status)
    }
  }

  try {
    return JSON.parse(raw) as T
  } catch {
    return raw as unknown as T
  }
}

/**
 * 读取文件的块切分结果。
 * 后端在 blocks.json 缺失或 Markdown 哈希不匹配时会懒重建，因此这里直接使用结果。
 */
export async function fetchBlocks(fileId: string): Promise<BlocksPayload> {
  return apiFetch<BlocksPayload>(`/api/files/${encodeURIComponent(fileId)}/blocks`)
}

/* ============================================================
   图表（拖框截图）
   ============================================================ */

/**
 * 截图的访问地址。
 * 后端记录里存的是 `assets/figures/<name>`，路由只接受单层文件名，
 * 因此这里只取最后一段并编码，避免把目录结构带进 URL。
 */
export function figureAssetUrl(fileId: string, assetPath: string): string | null {
  const name = String(assetPath || '')
    .replace(/\\/g, '/')
    .split('/')
    .pop()
    ?.trim()
  if (!fileId || !name) return null
  return apiUrl(
    `/api/files/${encodeURIComponent(fileId)}/figure-assets/${encodeURIComponent(name)}`,
  )
}

export interface CaptionOcrLine {
  text: string
  score: number
}

export interface CaptionOcrResult {
  /** 建议标题（图 3 XXXX / 表 2 XXXX）；未识别到时为空串。 */
  caption: string
  /** 整张截图的 OCR 文本，便于用户核对。 */
  text: string
  lines: CaptionOcrLine[]
}

/**
 * 对刚框选的截图做小图 OCR，自动建议图表标题。
 *
 * 属于“锦上添花”：失败时调用方只需降级为手动填写，不能阻塞创建流程。
 */
export async function recognizeFigureCaption(
  fileId: string,
  blob: Blob,
): Promise<CaptionOcrResult> {
  const form = new FormData()
  form.append('file', blob, 'figure-region.png')
  return apiFetch<CaptionOcrResult>(
    `/api/files/${encodeURIComponent(fileId)}/figure-caption-ocr`,
    { method: 'POST', body: form },
  )
}

/** 创建图表：multipart 上传 PNG + JSON 元数据，返回服务端生成的完整记录。 */
export async function createFigure(
  fileId: string,
  blob: Blob,
  meta: FigureCreatePayload,
): Promise<FigureAnnotation> {
  // 显式构造白名单，避免调用方透传多余字段（后端 FigureCreate 只接受这些键）。
  const payload: FigureCreatePayload = {
    kind: meta.kind,
    caption: meta.caption,
    note: meta.note,
    page: meta.page,
    bbox: meta.bbox,
  }
  const form = new FormData()
  form.append('file', blob, payload.kind === 'table' ? 'table.png' : 'figure.png')
  form.append('meta', JSON.stringify(payload))
  return apiFetch<FigureAnnotation>(`/api/files/${encodeURIComponent(fileId)}/figures`, {
    method: 'POST',
    body: form,
  })
}

/** 修改图表元数据；后端不接受 kind/page/bbox 变更。 */
export async function updateFigure(
  fileId: string,
  figureId: string,
  changes: FigureDraftPayload,
): Promise<FigureAnnotation> {
  // PATCH 只接受 caption/note；kind 属于创建期属性，page/bbox 是定位信息，
  // 这里显式构造请求体，避免未来类型扩展时把不可变字段误发给后端。
  const body = {
    caption: changes.caption,
    note: changes.note,
  }
  return apiFetch<FigureAnnotation>(
    `/api/files/${encodeURIComponent(fileId)}/figures/${encodeURIComponent(figureId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
}

/** 删除图表记录与截图资产（后端返回 204）。 */
export async function deleteFigure(fileId: string, figureId: string): Promise<void> {
  await apiFetch<void>(
    `/api/files/${encodeURIComponent(fileId)}/figures/${encodeURIComponent(figureId)}`,
    { method: 'DELETE' },
  )
}

/**
 * 只读取图表列表。
 * 图表记录随 annotations 一起返回，这里不替换整个标注对象，
 * 避免触发 MarkdownAnnotator 的“标注重新加载”而丢失未保存的编辑。
 */
export async function fetchFigures(fileId: string): Promise<FigureAnnotation[]> {
  const record = await apiFetch<AnnotationRecord>(
    `/api/files/${encodeURIComponent(fileId)}/annotations`,
  )
  return Array.isArray(record?.figures) ? record.figures : []
}

function sanitizeFileName(name: string): string {
  const cleaned = name
    .replace(/[\\/:*?"<>|]/g, '_')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/[. ]+$/, '')
  return cleaned || 'project'
}

/** 下载项目 ZIP，文件名使用项目名。 */
export async function downloadProjectZip(projectId: string, projectName: string): Promise<void> {
  let response: Response
  try {
    response = await fetch(apiUrl(`/projects/${encodeURIComponent(projectId)}/export-zip`), {
      headers: { Accept: 'application/zip, application/octet-stream' },
    })
  } catch (error) {
    throw new ApiError(
      '无法连接本地服务，导出失败。',
      0,
      error instanceof Error ? error.message : undefined,
    )
  }

  if (!response.ok) throw await toApiError(response)

  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  try {
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = `${sanitizeFileName(projectName)}.zip`
    link.rel = 'noopener'
    document.body.appendChild(link)
    link.click()
    link.remove()
  } finally {
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
  }
}

/** 两位补零，仅用于文件名时间戳。 */
function pad2(value: number): string {
  return value < 10 ? `0${value}` : String(value)
}

/**
 * 生成本地时间戳 `yyyyMMdd_HHmmss`。
 * 刻意不引入日期库：这里只需要一个稳定、可排序、无时区歧义的文件名片段。
 */
function timestampForFileName(date = new Date()): string {
  const ymd = `${date.getFullYear()}${pad2(date.getMonth() + 1)}${pad2(date.getDate())}`
  const hms = `${pad2(date.getHours())}${pad2(date.getMinutes())}${pad2(date.getSeconds())}`
  return `${ymd}_${hms}`
}

/**
 * 从 Content-Disposition 中解析文件名（可选增强）。
 * 后端可能返回 `filename*=UTF-8''%E6%B7%B7...xlsx` 或 `filename="..."`；
 * 解析失败时返回 null，由调用方回退到本地生成的文件名。
 */
function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null

  // RFC 5987 编码形式优先：它能正确表达中文文件名。
  const extended = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (extended) {
    try {
      const decoded = decodeURIComponent(extended[1].trim())
      return decoded || null
    } catch {
      // 非法百分号编码：继续尝试普通 filename。
    }
  }

  const plain = /filename="?([^";]+)"?/i.exec(header)
  if (!plain) return null
  const name = plain[1].trim()
  return name || null
}

/**
 * 下载所选项目的标注明细 Excel；文件名带时间戳，避免多次导出互相覆盖。
 *
 * 与 `downloadProjectZip` 保持同一套清理方式：blob → objectURL → 临时 `<a>` → 延迟 revoke。
 * 不使用 `apiFetch`，因为它按 JSON 解析响应体。
 */
export async function downloadProjectExcel(projectIds: string[]): Promise<void> {
  // UI 会在未选项目时禁用提交，这里再兜一层，避免发出必然 422 的请求。
  const ids = Array.from(new Set(projectIds.filter((id) => Boolean(id))))
  if (ids.length === 0) return

  let response: Response
  try {
    response = await fetch(apiUrl('/projects/export-excel'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept:
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, application/octet-stream',
      },
      body: JSON.stringify({ project_ids: ids }),
    })
  } catch (error) {
    throw new ApiError(
      '无法连接本地服务，导出失败。',
      0,
      error instanceof Error ? error.message : undefined,
    )
  }

  if (!response.ok) throw await toApiError(response)

  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  try {
    const link = document.createElement('a')
    link.href = objectUrl
    link.download =
      filenameFromDisposition(response.headers.get('content-disposition')) ??
      `混合标注标注明细_${timestampForFileName()}.xlsx`
    link.rel = 'noopener'
    document.body.appendChild(link)
    link.click()
    link.remove()
  } finally {
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
  }
}

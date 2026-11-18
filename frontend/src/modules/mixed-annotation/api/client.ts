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

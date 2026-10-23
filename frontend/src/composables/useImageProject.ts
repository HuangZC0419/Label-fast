/**
 * 图像标注共享数据层。
 *
 * 框选页与问答页共用同一份模块级状态：
 * 1. 两个页面之间切换时不会丢失当前项目、图片列表或标注草稿；
 * 2. `/annotations` 一次加载 QA 与 Box 两类记录；标注加载成功时
 *    `/projects/current` 同时提交两类记录，避免只保存页面内可见的一类数据而清空另一类；
 * 3. 所有图像 API 使用绝对前缀 `/minimind/api`（SPA 路由位于 /app/image）。
 */
import { computed, ref } from 'vue'
import { toast } from './useToast'

const API_BASE = '/minimind/api'

/** 新建问答草稿时使用的默认用户指令。 */
export const DEFAULT_USER_PROMPT = '详细描述这张图片。'

/** 框选标签配色：低饱和暖色，按标签顺序循环使用，与 Ink & Signal 画布协调。 */
export const LABEL_COLORS = [
  '#EFB7A3',
  '#C7D6A7',
  '#A9C4D8',
  '#E8D6A2',
  '#D8B6C4',
  '#B6C7BF',
] as const

export interface ImageProject {
  id: string
  name: string
  project_dir: string
  image_dir: string
  jsonl_path: string
  box_jsonl_path: string
  labels: string[]
  last_image: string
}

export interface BoxItem {
  x1: number
  y1: number
  x2: number
  y2: number
  label: string
}

export interface QaRecord {
  user_content: string
  assistant_content: string
}

export interface StatusMessage {
  type: 'success' | 'error'
  msg: string
}

export interface PersistProjectOptions {
  /** 静默保存时不弹出 alert，仅记录错误（用于切换/新建项目前的自动保存）。 */
  silent?: boolean
}

interface RawQaMessage {
  role?: string
  content?: string
}

interface RawQaRecord {
  image?: unknown
  conversations?: unknown
}

interface RawBoxRecord {
  image?: unknown
  boxes?: unknown
}

interface AnnotationsResponse {
  qa?: RawQaRecord[]
  box?: RawBoxRecord[]
}

interface ImagesResponse {
  images?: string[]
  labeled?: string[]
  error?: string
}

interface QaSnapshotItem {
  image: string
  user_content: string
  assistant_content: string
}

interface BoxSnapshotItem {
  image: string
  boxes: BoxItem[]
}

interface ProjectSnapshotPayload {
  labels: string[]
  last_image: string
  /** 仅在标注数据成功加载后才提交，避免把未加载误判成“空标注”。 */
  qa_records?: QaSnapshotItem[]
  box_records?: BoxSnapshotItem[]
}

function createEmptyProject(): ImageProject {
  return {
    id: '',
    name: '',
    project_dir: '',
    image_dir: '',
    jsonl_path: '',
    box_jsonl_path: '',
    labels: [],
    last_image: '',
  }
}

/** 去掉用户指令末尾的 <image> 标记，空内容回退到默认指令。 */
function normalizeUserContent(content: unknown): string {
  const text = String(content ?? '')
  const normalized = text.replace(/\s*<image>\s*$/i, '').trim()
  return normalized || DEFAULT_USER_PROMPT
}

/** 图片文件名可能包含子目录，逐段编码以保留路径分隔符。 */
export function getImageUrl(name: string): string {
  const encoded = name
    .split('/')
    .map((segment) => encodeURIComponent(segment))
    .join('/')
  return `${API_BASE}/image_file/${encoded}`
}

/** 标签颜色：优先按标签在项目标签列表中的下标分配，未知标签使用稳定哈希。 */
export function getLabelColor(label: string, labels: readonly string[] = []): string {
  if (!label) return '#9ca3af'

  const index = labels.indexOf(label)
  if (index !== -1) {
    return LABEL_COLORS[index % LABEL_COLORS.length]
  }

  let hash = 0
  for (let i = 0; i < label.length; i += 1) {
    hash = label.charCodeAt(i) + ((hash << 5) - hash)
  }
  const value = (hash & 0x00ffffff).toString(16).toUpperCase()
  return `#${'00000'.substring(0, 6 - value.length)}${value}`
}

function parseBoxes(raw: unknown): BoxItem[] {
  if (!Array.isArray(raw)) return []

  const result: BoxItem[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const source = item as Record<string, unknown>
    const x1 = Number(source.x1)
    const y1 = Number(source.y1)
    const x2 = Number(source.x2)
    const y2 = Number(source.y2)
    if (![x1, y1, x2, y2].every(Number.isFinite)) continue

    result.push({
      x1,
      y1,
      x2,
      y2,
      label: typeof source.label === 'string' ? source.label : '',
    })
  }
  return result
}

function parseMessages(raw: unknown): RawQaMessage[] {
  if (!Array.isArray(raw)) return []

  return raw
    .filter((message): message is Record<string, unknown> => Boolean(message) && typeof message === 'object')
    .map((message) => ({
      role: typeof message.role === 'string' ? message.role : undefined,
      content: typeof message.content === 'string' ? message.content : String(message.content ?? ''),
    }))
}

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string; message?: string }
    return body.detail || body.message || fallback
  } catch {
    return fallback
  }
}

// ---------------------------------------------------------------------------
// 模块级单例状态：两个图像标注页面共享
// ---------------------------------------------------------------------------
const projects = ref<ImageProject[]>([])
const currentProjectId = ref('')
const currentProject = ref<ImageProject>(createEmptyProject())
/** 项目标签列表（可编辑），保存项目时随 labels 一起提交。 */
const labels = ref<string[]>([])
const images = ref<string[]>([])
const labeledSet = ref<Set<string>>(new Set<string>())
const currentIndex = ref(-1)
const boxes = ref<Record<string, BoxItem[]>>({})
const qaRecords = ref<Record<string, QaRecord>>({})
const imagesError = ref('')
const userContent = ref(DEFAULT_USER_PROMPT)
const assistantContent = ref('')
const saveStatus = ref<StatusMessage | null>(null)
const boxSaveStatus = ref<StatusMessage | null>(null)

/**
 * 当前项目的标注记录是否成功从后端加载。
 * 未加载时保存项目只提交 labels / last_image，禁止用空数组覆盖磁盘上的记录。
 */
let annotationsLoaded = false

/** 请求序号：切换/刷新项目时递增，过期响应直接丢弃，避免旧项目数据串入新项目。 */
let fetchGeneration = 0

/** 保存成功后的自动跳图定时器，页面卸载或切换项目时清理。 */
let advanceTimer: number | null = null

function cancelAdvance(): void {
  if (advanceTimer !== null) {
    window.clearTimeout(advanceTimer)
    advanceTimer = null
  }
}

/**
 * 校验后端全局 active project 与前端当前项目一致。
 * 后端图像接口依赖进程级 active project，多标签页切换后可能不一致；
 * 不一致时拒绝写入，避免把当前项目的数据整文件覆盖到另一个项目。
 */
/**
 * 查询后端当前 active project 是否与前端一致。
 * 返回 true/false 表示一致/不一致，null 表示无法确认（网络或接口异常）。
 */
async function backendProjectMatchesCurrent(): Promise<boolean | null> {
  try {
    const response = await fetch(`${API_BASE}/config`)
    if (!response.ok) return null
    const config = (await response.json()) as { project_id?: string }
    if (!currentProjectId.value || !config.project_id) return true
    return config.project_id === currentProjectId.value
  } catch {
    return null
  }
}

async function ensureActiveProject(): Promise<'ok' | 'mismatch' | 'error'> {
  if (!currentProjectId.value) return 'mismatch'
  const matches = await backendProjectMatchesCurrent()
  if (matches === null) return 'error'
  if (!matches) {
    toast(
      '服务端当前项目已发生变化（可能在其他标签页切换过）。请刷新页面后重新选择项目，以免覆盖其他项目的数据。',
      'error',
    )
    return 'mismatch'
  }
  return 'ok'
}

const currentImageName = computed<string | null>(() => {
  if (currentIndex.value >= 0 && currentIndex.value < images.value.length) {
    return images.value[currentIndex.value] ?? null
  }
  return null
})

const boxesForCurrentImage = computed<BoxItem[]>(() => {
  const name = currentImageName.value
  if (!name) return []
  return boxes.value[name] ?? []
})

const labeledCount = computed(() => labeledSet.value.size)
const totalImages = computed(() => images.value.length)

function isLabeled(name: string): boolean {
  return labeledSet.value.has(name)
}

function resetWorkspaceState(): void {
  // 切换项目时让所有在途请求失效，并取消尚未触发的自动跳图
  fetchGeneration += 1
  cancelAdvance()
  images.value = []
  labeledSet.value = new Set<string>()
  imagesError.value = ''
  currentIndex.value = -1
  boxes.value = {}
  qaRecords.value = {}
  userContent.value = DEFAULT_USER_PROMPT
  assistantContent.value = ''
  saveStatus.value = null
  boxSaveStatus.value = null
  annotationsLoaded = false
}

function loadQaDraftForImage(imageName: string | null): void {
  if (!imageName) {
    userContent.value = DEFAULT_USER_PROMPT
    assistantContent.value = ''
    return
  }
  const record = qaRecords.value[imageName]
  userContent.value = record ? normalizeUserContent(record.user_content) : DEFAULT_USER_PROMPT
  assistantContent.value = record ? String(record.assistant_content ?? '') : ''
}

/**
 * 把当前图片的问答编辑内容写入本地记录。
 * 助手回答为空时删除该图片草稿（与原实现一致）。
 */
function captureCurrentQaDraft(): Record<string, QaRecord> {
  const imageName = currentImageName.value
  if (!imageName) return { ...qaRecords.value }

  const nextRecords = { ...qaRecords.value }
  const assistant = String(assistantContent.value ?? '')

  if (assistant.trim()) {
    nextRecords[imageName] = {
      user_content: normalizeUserContent(userContent.value),
      assistant_content: assistant,
    }
  } else {
    delete nextRecords[imageName]
  }

  qaRecords.value = nextRecords
  return nextRecords
}

/** 生成项目快照：无论当前在哪个页面，都同时携带 QA 与 Box 两类记录。 */
function buildProjectSnapshotPayload(): ProjectSnapshotPayload {
  // 即使本次不提交标注记录，也要把当前编辑中的问答草稿写入本地状态。
  const qaSnapshot = captureCurrentQaDraft()

  const payload: ProjectSnapshotPayload = {
    labels: [...labels.value],
    // 图片列表尚未加载成功时保留上一次浏览的图片，避免把 last_image 覆盖成空串
    last_image: currentImageName.value ?? currentProject.value.last_image ?? '',
  }

  if (!annotationsLoaded) return payload

  payload.qa_records = Object.entries(qaSnapshot)
    .filter(([, record]) => Boolean(record) && String(record.assistant_content ?? '').trim())
    .map(([image, record]) => ({
      image,
      user_content: normalizeUserContent(record.user_content),
      assistant_content: String(record.assistant_content ?? ''),
    }))

  payload.box_records = Object.entries(boxes.value)
    .filter(([, list]) => Array.isArray(list) && list.length > 0)
    .map(([image, list]) => ({
      image,
      boxes: list.map((box) => ({ ...box })),
    }))

  return payload
}

async function fetchProjects(): Promise<void> {
  try {
    const response = await fetch(`${API_BASE}/projects`)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    projects.value = (await response.json()) as ImageProject[]
  } catch (error) {
    console.error('加载项目列表失败', error)
  }
}

/**
 * 加载图片列表与两类标注记录。
 * 标注数据失败时保留图片列表，不清空已有记录。
 */
async function fetchImages(preferredImage = ''): Promise<void> {
  // 每次刷新/切换项目生成新序号；旧请求晚到时直接丢弃，避免污染当前项目状态
  const generation = ++fetchGeneration
  annotationsLoaded = false

  try {
    const response = await fetch(`${API_BASE}/images`)
    if (generation !== fetchGeneration) return
    if (!response.ok) {
      throw new Error(await readErrorDetail(response, `HTTP ${response.status}`))
    }

    const data = (await response.json()) as ImagesResponse
    if (generation !== fetchGeneration) return

    // 读取前确认后端 active project 未被其他标签页切换，避免把别的项目数据当成当前项目
    const firstCheck = await backendProjectMatchesCurrent()
    if (generation !== fetchGeneration) return
    if (firstCheck === false) {
      imagesError.value = '服务端当前项目已发生变化，请刷新页面后重新选择项目'
      return
    }

    images.value = Array.isArray(data.images) ? data.images : []
    labeledSet.value = new Set(Array.isArray(data.labeled) ? data.labeled : [])
    imagesError.value = data.error || ''

    try {
      const annotationsResponse = await fetch(`${API_BASE}/annotations`)
      if (generation !== fetchGeneration) return
      if (annotationsResponse.ok) {
        const annotations = (await annotationsResponse.json()) as AnnotationsResponse
        if (generation !== fetchGeneration) return

        // 应用前再校验一次，防止请求期间其他标签页切换了后端当前项目
        const secondCheck = await backendProjectMatchesCurrent()
        if (generation !== fetchGeneration) return
        if (secondCheck === false) {
          imagesError.value = '服务端当前项目已发生变化，请刷新页面后重新选择项目'
          return
        }

        // 只有 qa 与 box 两个数组都存在时才认为“标注已完整加载”，
        // 防止畸形响应把某一类记录置空后在保存时覆盖磁盘文件
        const hasBox = Array.isArray(annotations.box)
        const hasQa = Array.isArray(annotations.qa)

        if (hasBox) {
          const nextBoxes: Record<string, BoxItem[]> = {}
          for (const record of annotations.box ?? []) {
            const imageName = typeof record.image === 'string' ? record.image : ''
            if (!imageName) continue
            nextBoxes[imageName] = parseBoxes(record.boxes)
          }
          boxes.value = nextBoxes
        }

        if (hasQa) {
          const nextQaRecords: Record<string, QaRecord> = {}
          for (const record of annotations.qa ?? []) {
            const imageName = typeof record.image === 'string' ? record.image : ''
            if (!imageName) continue
            const messages = parseMessages(record.conversations)
            const userMessage = messages.find((message) => message.role === 'user')
            const assistantMessage = messages.find((message) => message.role === 'assistant')
            nextQaRecords[imageName] = {
              user_content: normalizeUserContent(userMessage?.content ?? ''),
              assistant_content: assistantMessage ? String(assistantMessage.content ?? '') : '',
            }
          }
          qaRecords.value = nextQaRecords
        }

        annotationsLoaded = hasBox && hasQa
      }
    } catch (error) {
      // 标注数据加载失败不影响图片浏览，保留空记录等待下次刷新。
      // annotationsLoaded 保持 false，保存项目时不会提交空的记录数组。
      console.error('加载标注数据失败', error)
    }

    if (generation !== fetchGeneration) return

    if (images.value.length > 0) {
      const preferredIndex = preferredImage ? images.value.indexOf(preferredImage) : -1
      if (preferredIndex !== -1) {
        currentIndex.value = preferredIndex
      } else {
        const firstUnlabeled = images.value.findIndex((image) => !labeledSet.value.has(image))
        currentIndex.value = firstUnlabeled !== -1 ? firstUnlabeled : 0
      }
      loadQaDraftForImage(images.value[currentIndex.value] ?? null)
    } else {
      currentIndex.value = -1
      userContent.value = DEFAULT_USER_PROMPT
      assistantContent.value = ''
    }
  } catch (error) {
    if (generation !== fetchGeneration) return
    console.error(error)
    imagesError.value = '无法加载图片列表，请检查后端服务是否正常运行'
  }
}

/** 提交当前项目快照（标签、最后浏览图片、QA 记录、Box 记录）。 */
async function persistCurrentProject(options: PersistProjectOptions = {}): Promise<boolean> {
  const { silent = false } = options

  if (!currentProjectId.value) {
    if (!silent) toast('请先选择或创建一个项目', 'info')
    return false
  }

  const activeCheck = await ensureActiveProject()
  if (activeCheck !== 'ok') {
    if (activeCheck === 'error' && !silent) {
      toast('无法确认服务端当前项目状态，已取消保存，请检查后端服务后重试。', 'error')
    }
    return false
  }

  try {
    const recordsLoaded = annotationsLoaded
    const payload = buildProjectSnapshotPayload()
    const response = await fetch(`${API_BASE}/projects/current`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })

    if (!response.ok) {
      const message = await readErrorDetail(response, '保存失败')
      if (!silent) {
        toast(String(message), 'error')
      } else {
        console.error(message)
      }
      return false
    }

    const updated = (await response.json()) as ImageProject
    await fetchProjects()

    currentProjectId.value = updated.id
    currentProject.value = { ...updated }
    labels.value = Array.isArray(updated.labels) ? [...updated.labels] : []

    if (!silent) {
      if (recordsLoaded) {
        toast('当前项目已保存', 'success')
      } else {
        toast('项目配置已保存。标注数据尚未成功加载，为避免覆盖已有记录，本次未写入标注；请刷新图片列表后重试。', 'info')
      }
    } else if (!recordsLoaded) {
      console.warn('标注数据未加载，静默保存时已跳过标注记录，避免覆盖磁盘数据')
    }
    return true
  } catch (error) {
    const message = `保存当前项目失败: ${(error as Error).message}`
    if (!silent) {
      toast(message, 'error')
    } else {
      console.error(message)
    }
    return false
  }
}

/** 创建项目前先静默保存旧项目，失败则取消创建。 */
async function createProject(name: string): Promise<boolean> {
  const projectName = name.trim()
  if (!projectName) {
    toast('请输入项目名称', 'info')
    return false
  }

  if (currentProjectId.value) {
    const saved = await persistCurrentProject({ silent: true })
    if (!saved) {
      toast('当前项目保存失败，已取消新建项目', 'error')
      return false
    }
  }

  try {
    const response = await fetch(`${API_BASE}/projects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: '',
        name: projectName,
        image_dir: '',
        jsonl_path: '',
        labels: [],
      }),
    })

    if (!response.ok) {
      toast(await readErrorDetail(response, '新建项目失败'), 'error')
      return false
    }

    const created = (await response.json()) as ImageProject
    await fetchProjects()

    currentProjectId.value = created.id
    currentProject.value = { ...created }
    labels.value = Array.isArray(created.labels) ? [...created.labels] : []
    resetWorkspaceState()
    await fetchImages(created.last_image || '')
    return true
  } catch (error) {
    toast(`创建项目失败: ${(error as Error).message}`, 'error')
    return false
  }
}

/**
 * 切换项目：先静默保存旧项目，失败时不切换。
 * 调用前 currentProjectId 可已被界面临时设为目标值，内部会先恢复旧值再保存。
 */
async function switchProject(id: string): Promise<boolean> {
  if (!id) return false

  const previousProjectId = currentProject.value.id || ''
  if (previousProjectId === id) {
    currentProjectId.value = id
    return true
  }

  if (previousProjectId) {
    currentProjectId.value = previousProjectId
    const saved = await persistCurrentProject({ silent: true })
    if (!saved) {
      currentProjectId.value = previousProjectId
      toast('当前项目保存失败，已取消切换', 'error')
      return false
    }
  }

  // 持久化过程中会刷新项目列表，这里重新查找以取得最新的 last_image / labels。
  const targetProject = projects.value.find((project) => project.id === id)
  if (!targetProject) {
    currentProjectId.value = previousProjectId
    toast('项目不存在或已被删除', 'error')
    return false
  }

  try {
    const response = await fetch(`${API_BASE}/projects/switch/${encodeURIComponent(id)}`, {
      method: 'POST',
    })
    if (!response.ok) {
      throw new Error(await readErrorDetail(response, '切换项目失败'))
    }
  } catch (error) {
    currentProjectId.value = previousProjectId
    toast(`切换项目失败: ${(error as Error).message}`, 'error')
    return false
  }

  currentProject.value = { ...targetProject }
  labels.value = Array.isArray(targetProject.labels) ? [...targetProject.labels] : []
  resetWorkspaceState()
  currentProjectId.value = id
  await fetchImages(targetProject.last_image || '')
  return true
}

async function deleteProject(): Promise<void> {
  if (!currentProjectId.value) {
    toast('请先选择一个项目', 'info')
    return
  }

  if (!window.confirm(`确定删除项目 "${currentProject.value.name}" 吗？项目目录和标注结果都会被删除。`)) {
    return
  }

  const projectId = currentProjectId.value

  try {
    const response = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}`, {
      method: 'DELETE',
    })
    if (!response.ok) {
      throw new Error(await readErrorDetail(response, '删除失败'))
    }

    currentProjectId.value = ''
    currentProject.value = createEmptyProject()
    labels.value = []
    resetWorkspaceState()
    await fetchProjects()
    toast('项目已删除', 'success')
  } catch (error) {
    toast(`删除项目失败: ${(error as Error).message}`, 'error')
  }
}

function selectImage(index: number): void {
  if (index < 0 || index >= images.value.length) return

  cancelAdvance()

  if (currentIndex.value !== index) {
    captureCurrentQaDraft()
  }

  currentIndex.value = index
  loadQaDraftForImage(images.value[index] ?? null)
  saveStatus.value = null
  boxSaveStatus.value = null
}

function prevImage(): void {
  if (currentIndex.value > 0) {
    selectImage(currentIndex.value - 1)
  }
}

function nextImage(): void {
  if (currentIndex.value < images.value.length - 1) {
    selectImage(currentIndex.value + 1)
  }
}

function addLabel(name: string): boolean {
  const value = name.trim()
  if (!value) return false
  if (!labels.value.includes(value)) {
    labels.value = [...labels.value, value]
  }
  return true
}

function addBox(box: BoxItem): void {
  const imageName = currentImageName.value
  if (!imageName) return

  const list = boxes.value[imageName] ? [...boxes.value[imageName]!] : []
  list.push({ ...box })
  boxes.value = { ...boxes.value, [imageName]: list }
}

function removeBox(index: number): void {
  const imageName = currentImageName.value
  if (!imageName) return

  const list = [...(boxes.value[imageName] ?? [])]
  if (index < 0 || index >= list.length) return
  list.splice(index, 1)
  boxes.value = { ...boxes.value, [imageName]: list }
}

function clearBoxes(): void {
  const imageName = currentImageName.value
  if (!imageName) return
  boxes.value = { ...boxes.value, [imageName]: [] }
}

/** 保存当前图片问答。advance 为 true 时保存成功后自动切到下一张。 */
async function saveQa(advance = true): Promise<boolean> {
  const imageName = currentImageName.value
  if (!imageName) return false

  const answer = String(assistantContent.value ?? '')
  if (!answer.trim()) {
    saveStatus.value = { type: 'error', msg: '助手回答不能为空' }
    return false
  }

  const activeCheck = await ensureActiveProject()
  if (activeCheck !== 'ok') {
    saveStatus.value = {
      type: 'error',
      msg: activeCheck === 'mismatch' ? '服务端项目已变化，已取消保存' : '无法确认服务端项目状态，已取消保存',
    }
    return false
  }

  try {
    const response = await fetch(`${API_BASE}/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image: imageName,
        user_content: normalizeUserContent(userContent.value),
        assistant_content: answer,
      }),
    })

    if (!response.ok) {
      throw new Error(await readErrorDetail(response, '保存失败'))
    }

    labeledSet.value.add(imageName)
    qaRecords.value = {
      ...qaRecords.value,
      [imageName]: {
        user_content: normalizeUserContent(userContent.value),
        assistant_content: answer,
      },
    }
    saveStatus.value = { type: 'success', msg: '保存成功!' }

    if (advance) {
      cancelAdvance()
      advanceTimer = window.setTimeout(() => {
        advanceTimer = null
        // 用户若已手动切图，避免重复跳过。
        if (currentImageName.value !== imageName) return
        saveStatus.value = null
        nextImage()
      }, 500)
    }
    return true
  } catch (error) {
    saveStatus.value = { type: 'error', msg: `保存失败: ${(error as Error).message}` }
    return false
  }
}

/** 保存当前图片框选。保存成功后标记已标注并自动切到下一张。 */
async function saveBoxes(): Promise<boolean> {
  const imageName = currentImageName.value
  if (!imageName) return false

  const list = boxes.value[imageName] ?? []
  if (list.length === 0) {
    boxSaveStatus.value = { type: 'error', msg: '当前图片没有框可以保存' }
    return false
  }

  const activeCheck = await ensureActiveProject()
  if (activeCheck !== 'ok') {
    boxSaveStatus.value = {
      type: 'error',
      msg: activeCheck === 'mismatch' ? '服务端项目已变化，已取消保存' : '无法确认服务端项目状态，已取消保存',
    }
    return false
  }

  try {
    const response = await fetch(`${API_BASE}/save_boxes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image: imageName,
        boxes: list.map((box) => ({ ...box })),
      }),
    })

    if (!response.ok) {
      throw new Error(await readErrorDetail(response, '保存失败'))
    }

    labeledSet.value.add(imageName)
    boxSaveStatus.value = { type: 'success', msg: '框标注已保存，自动切换下一张' }

    cancelAdvance()
    advanceTimer = window.setTimeout(() => {
      advanceTimer = null
      if (currentImageName.value !== imageName) return
      boxSaveStatus.value = null
      nextImage()
    }, 600)
    return true
  } catch (error) {
    boxSaveStatus.value = { type: 'error', msg: `保存失败: ${(error as Error).message}` }
    return false
  }
}

async function exportZip(mode: 'qa' | 'box'): Promise<void> {
  if (!currentProjectId.value) {
    toast('请先选择或创建一个项目', 'info')
    return
  }

  const activeCheck = await ensureActiveProject()
  if (activeCheck === 'error') {
    toast('无法确认服务端当前项目状态，已取消导出，请检查后端服务后重试。', 'error')
    return
  }
  if (activeCheck !== 'ok') return

  window.open(`${API_BASE}/export-zip?mode=${mode}`, '_blank')
}

export function useImageProject() {
  return {
    // 状态
    projects,
    currentProjectId,
    currentProject,
    labels,
    images,
    labeledSet,
    currentIndex,
    boxes,
    qaRecords,
    imagesError,
    userContent,
    assistantContent,
    saveStatus,
    boxSaveStatus,

    // 计算属性
    currentImageName,
    boxesForCurrentImage,
    labeledCount,
    totalImages,

    // 方法与工具
    fetchProjects,
    createProject,
    switchProject,
    persistCurrentProject,
    deleteProject,
    fetchImages,
    selectImage,
    prevImage,
    nextImage,
    loadQaDraftForImage,
    captureCurrentQaDraft,
    cancelAdvance,
    saveQa,
    saveBoxes,
    addLabel,
    addBox,
    removeBox,
    clearBoxes,
    exportZip,
    isLabeled,
  }
}

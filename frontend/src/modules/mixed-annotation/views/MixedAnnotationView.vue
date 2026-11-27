<script setup lang="ts">
import '../styles/app.css'
import '../styles/markdown.css'
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import AppHeader from '../components/AppHeader.vue'
import FileList from '../components/project/FileList.vue'
import ProjectDictionaryCard from '../components/project/ProjectDictionaryCard.vue'
import ProjectSettingsDialog from '../components/project/ProjectSettingsDialog.vue'
import ExportExcelDialog from '../components/project/ExportExcelDialog.vue'
import SplitProjectDialog from '../components/project/SplitProjectDialog.vue'
import ShortcutSettingsDialog from '../components/project/ShortcutSettingsDialog.vue'
import ImportDialog from '../components/project/ImportDialog.vue'
import ReconvertDialog from '../components/project/ReconvertDialog.vue'
import ConfirmDialog from '../components/common/ConfirmDialog.vue'
import EmptyState from '../components/common/EmptyState.vue'
import MixedWorkspace from '../components/workspace/MixedWorkspace.vue'
import { ApiError, apiFetch, downloadProjectExcel, downloadProjectZip } from '../api/client'
import type {
  BatchSummary,
  ConversionOptions,
  FileStatus,
  ImportProgress,
  MixedFile,
  Project,
  ProjectDictionaryPatch,
  ProjectLabelUsage,
  ProjectSettingsPayload,
  ProjectShortcutsPatch,
  ProjectSplitResponse,
  SplitGroup,
} from '../types'

/**
 * 新建项目草稿：设置弹窗只填名称，创建时字典字段固定提交空数组；
 * 编辑态仅携带名称，不会用空字典覆盖现有标签与关系。
 */
interface ProjectDraft {
  name: string
  labels?: string[]
  relation_types?: string[]
}

interface Notice {
  kind: 'success' | 'error' | 'info'
  text: string
}

interface FileStatusPayload {
  status?: FileStatus
  progress?: number
  stage?: string
  message?: string
  error?: string
  page_count?: number
}

type ProjectListPayload = Project[] | { projects?: Project[] }
type ProjectDetailPayload =
  | (Project & { files?: MixedFile[] })
  | { project: Project; files?: MixedFile[] }

const STATUS_LABELS: Record<FileStatus, string> = {
  uploaded: '排队中',
  converting: '转换中',
  completed: '已完成',
  failed: '转换失败',
}

const SELECTED_PROJECT_KEY = 'label-fast-mixed:project'
const POLL_INTERVAL = 1500
/** 单个批量上传请求的硬超时：避免夜间某个请求永久挂起卡死整个批次。 */
const UPLOAD_TIMEOUT = 120_000
/** 项目详情/快照请求超时：避免导入校准永久等待，锁死 importing。 */
const DETAIL_TIMEOUT = 15_000
/** 超过该数量时，轮询改用一次项目详情请求，避免 N 个 /status 请求。 */
const STATUS_PER_FILE_LIMIT = 8
/** 本地独有乐观条目连续缺失多少轮后判定为幽灵条目。 */
const MAX_MISSING_ROUNDS = 3
/** 字典卡片连续编辑合并为一次 PATCH 的防抖窗口。 */
const DICTIONARY_DEBOUNCE = 300
/** 保存成功后保持「已保存」状态的时长。 */
const DICTIONARY_SAVED_HOLD = 1500

/** 左侧「标签与关系」卡片的保存状态。 */
type DictionaryStatus = 'idle' | 'saving' | 'saved' | 'error'

interface WorkspaceApi {
  flushSave: () => Promise<boolean>
}

/** 字典卡片的命令式接口：删除在用标签的确认被取消时还原草稿。 */
interface DictionaryCardApi {
  restoreRemoved: (section: 'labels' | 'relation_types', value: string) => void
}

/** 待确认的「删除在用标签」请求：确认后才入队，取消时不发送任何 PATCH。 */
interface LabelRemovePrompt {
  patch: ProjectDictionaryPatch
}

/** 后端恢复接口的响应：完整项目对象 + 本次补回的标签列表。 */
type LabelRestorePayload = Partial<Project> & { restored?: string[]; project?: Partial<Project> }

const projects = ref<Project[]>([])
const currentProject = ref<Project | null>(null)
const files = ref<MixedFile[]>([])
const selectedFile = ref<MixedFile | null>(null)
const workspaceRef = ref<WorkspaceApi | null>(null)
const dictionaryCardRef = ref<DictionaryCardApi | null>(null)

const projectsLoading = ref(false)
const filesLoading = ref(false)
const savingProject = ref(false)
const uploading = ref(false)
const importing = ref(false)
/** 拖拽文件夹后异步读取目录期间为 true，同样需要锁定项目切换。 */
const scanBusy = ref(false)
const importProgress = ref<ImportProgress | null>(null)
const exporting = ref(false)
/** 「导入」弹窗：上传面板从左侧栏搬到顶栏按钮后面，这里是它的开关。 */
const importOpen = ref(false)
/** 「导出 Excel 表单」弹窗：可多选项目，导出期间禁止重复提交。 */
const excelOpen = ref(false)
const exportingExcel = ref(false)
const excelError = ref('')
/** 统一设置弹窗：创建与编辑共用；字典项由左侧卡片独立保存。 */
const settingsOpen = ref(false)
const settingsMode = ref<'create' | 'edit'>('edit')
const settingsError = ref('')
/** 「拆分项目」弹窗：按文件序号区间把当前项目拆成多个新项目。 */
const splitOpen = ref(false)
const splitBusy = ref(false)
const splitError = ref('')
/** 「自定义快捷键」弹窗：项目级共享，保存时走 PATCH 的 set/unset 增量。 */
const shortcutOpen = ref(false)
const shortcutBusy = ref(false)
const shortcutError = ref('')
/** 字典卡片保存状态，供卡片展示「保存中 / 已保存 / 失败」反馈。 */
const dictionaryStatus = ref<DictionaryStatus>('idle')
/** 标签引用统计：删除前确认与「字典缺失」区域都依赖它。 */
const labelUsage = ref<ProjectLabelUsage>({ used: {}, missing: [] })
/** 「全部恢复」请求进行中。 */
const restoringLabels = ref(false)
const deleteOpen = ref(false)
const deleteError = ref('')
/** 删除在用标签的确认弹窗：不再是浏览器原生 confirm，避免丢失引用条数说明。 */
const labelRemoveOpen = ref(false)
const labelRemoveMessage = ref('')
const pendingLabelRemove = ref<LabelRemovePrompt | null>(null)
/** 删除目标快照：删除过程中 currentProject/files 会被清空，弹窗文案不能跟着变。 */
const deleteTargetName = ref('')
const deleteImpactText = ref('')
const retryingId = ref<string | null>(null)
const notice = ref<Notice | null>(null)
const workspaceRevision = ref(0)
let noticeTimer: number | null = null

/* 字典保存队列：防抖定时器、串行在途标记与 latest-wins 排队标记。 */
let dictionaryDebounceTimer: number | null = null
let dictionarySavedTimer: number | null = null
/** 递增令牌：旧的「已保存 → 空闲」定时器不得覆盖更新的状态。 */
let dictionarySavedToken = 0
/** 待提交的增量字段：同字段 add/remove 各自求并集，互斥项以最后一次操作为准。 */
let dictionaryPending: ProjectDictionaryPatch = {}
let dictionarySaveInFlight = false
let dictionaryRerun = false
/** 切换项目/删除/卸载时递增；旧请求返回后据此丢弃结果。 */
let dictionaryGeneration = 0
/** 字典成功回写代数：晚到的详情快照据此判断是否应保留本地字典。 */
let dictionaryRevision = 0
/** usage 请求令牌：只接受「当前项目 + 最新一次请求」的响应，旧响应直接丢弃。 */
let labelUsageToken = 0

const conversionOptions = reactive<ConversionOptions>({
  enable_table: true,
  enable_formula: false,
  dpi: 200,
  parse_method: 'auto',
})

/* 「重新 OCR」弹窗：按文件覆盖识别参数，不影响项目默认上传参数。 */
const reconvertOpen = ref(false)
const reconvertBusy = ref(false)
const reconvertError = ref('')

function openReconvertDialog(): void {
  if (!selectedFile.value || selectedFile.value.status === 'converting') return
  reconvertError.value = ''
  reconvertOpen.value = true
}

async function submitReconvert(options: ConversionOptions): Promise<void> {
  const file = selectedFile.value
  const project = currentProject.value
  if (!file || !project || reconvertBusy.value) return

  reconvertBusy.value = true
  reconvertError.value = ''
  try {
    await apiFetch<unknown>(`/files/${encodeURIComponent(file.id)}/convert`, {
      method: 'POST',
      body: JSON.stringify(options),
    })
    reconvertOpen.value = false
    file.status = 'converting'
    file.progress = 0
    file.stage = '已提交'
    file.error = ''
    file.message = ''
    await loadProjectDetail(project.id)
    setNotice(
      'info',
      `已按 ${options.dpi} DPI / ${
        options.parse_method === 'ocr'
          ? '强制 OCR'
          : options.parse_method === 'txt'
            ? '仅文本层'
            : '自动解析'
      } 重新提交「${file.name}」`,
    )
  } catch (error) {
    reconvertError.value = messageOf(error)
  } finally {
    reconvertBusy.value = false
  }
}

const fileStatusLabel = computed(() =>
  selectedFile.value ? STATUS_LABELS[selectedFile.value.status] : '',
)

const hasPendingConversion = computed(() =>
  files.value.some(
    (file) => file.status === 'converting' || file.status === 'uploaded',
  ),
)

/** 后端串行队列的状态汇总；批量导入后据此展示识别进度。 */
const batchSummary = computed<BatchSummary>(() => {
  const summary: BatchSummary = {
    queued: 0,
    converting: 0,
    completed: 0,
    failed: 0,
  }
  for (const file of files.value) {
    if (file.status === 'uploaded') summary.queued += 1
    else if (file.status === 'converting') summary.converting += 1
    else if (file.status === 'completed') summary.completed += 1
    else if (file.status === 'failed') summary.failed += 1
  }
  return summary
})

const emptyState = computed(() => {
  if (!currentProject.value) {
    return {
      title: 'Start here.',
      message: '先在顶栏新建项目，再点顶部「导入」上传 PDF 或图片开始转换。',
    }
  }
  return {
    title: 'Pick a document.',
    message: '从左侧文件列表选择一个文件，进入 Markdown 标注。',
  }
})

/* ------------------------------------------------------------------ */
/* 通用工具                                                            */
/* ------------------------------------------------------------------ */

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object'
    ? (value as Record<string, unknown>)
    : null
}

function normalizeProjects(payload: ProjectListPayload): Project[] {
  if (Array.isArray(payload)) return payload
  return Array.isArray(payload.projects) ? payload.projects : []
}

function normalizeDetail(payload: ProjectDetailPayload): {
  project: Project
  files: MixedFile[]
} {
  if ('project' in payload) {
    return { project: payload.project, files: payload.files ?? [] }
  }
  const { files: detailFiles, ...project } = payload
  return { project, files: detailFiles ?? [] }
}

/** 从 `{project}` / `{file}` / 裸对象响应中取 id，兼容两种常见封装。 */
function extractId(payload: unknown, wrapper: 'project' | 'file'): string | null {
  const record = asRecord(payload)
  if (!record) return null
  const nested = asRecord(record[wrapper]) ?? record
  return typeof nested.id === 'string' ? nested.id : null
}

function extractProjectPatch(payload: unknown): Partial<Project> | null {
  const record = asRecord(payload)
  if (!record) return null
  const nested = asRecord(record.project) ?? record
  return typeof nested.id === 'string' ? (nested as unknown as Partial<Project>) : null
}

function messageOf(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : '操作失败，请稍后重试。'
}

function readSavedProjectId(): string | null {
  try {
    return window.localStorage.getItem(SELECTED_PROJECT_KEY)
  } catch {
    return null
  }
}

function rememberProject(id: string | null): void {
  try {
    if (id) window.localStorage.setItem(SELECTED_PROJECT_KEY, id)
    else window.localStorage.removeItem(SELECTED_PROJECT_KEY)
  } catch {
    // 隐私模式或存储不可用时忽略，不影响主流程。
  }
}

function dismissNotice(): void {
  if (noticeTimer !== null) {
    window.clearTimeout(noticeTimer)
    noticeTimer = null
  }
  notice.value = null
}

function setNotice(kind: Notice['kind'], text: string): void {
  if (noticeTimer !== null) {
    window.clearTimeout(noticeTimer)
    noticeTimer = null
  }
  notice.value = { kind, text }
  if (kind !== 'error') {
    noticeTimer = window.setTimeout(() => {
      notice.value = null
      noticeTimer = null
    }, 4500)
  }
}

function syncSelectedFile(): void {
  const id = selectedFile.value?.id
  selectedFile.value = id
    ? files.value.find((file) => file.id === id) ?? null
    : null
}

function mergeFile(next: MixedFile): void {
  const index = files.value.findIndex((file) => file.id === next.id)
  if (index >= 0) files.value[index] = next
  if (selectedFile.value?.id === next.id) selectedFile.value = next
}

/** 从 `{file}` / 裸对象响应中提取文件，兼容后端的两种封装。 */
function extractFile(payload: unknown): MixedFile | null {
  const record = asRecord(payload)
  if (!record) return null
  const nested = asRecord(record.file) ?? record
  return typeof nested.id === 'string' ? (nested as unknown as MixedFile) : null
}

/** 批量上传返回的文件可能是列表里尚不存在的新文件，需要追加而非覆盖。 */
function upsertFile(next: MixedFile): void {
  const index = files.value.findIndex((file) => file.id === next.id)
  if (index >= 0) {
    files.value[index] = { ...files.value[index], ...next }
    if (selectedFile.value?.id === next.id) selectedFile.value = files.value[index]
    return
  }
  files.value.push(next)
}

/** 本地独有乐观条目的连续缺失轮数；服务端重新返回后立即清除。 */
const missingRounds = new Map<string, number>()

/**
 * 以服务端列表为权威，但保留本地仍有、服务端尚未返回的待处理文件。
 * 批量导入刚成功时，项目详情接口可能短暂缺少该条目；直接覆盖会丢失乐观条目。
 * 连续 MAX_MISSING_ROUNDS 轮缺失的条目视为幽灵条目并丢弃，避免永久保留。
 */
function mergeFileList(serverFiles: MixedFile[]): MixedFile[] {
  const serverIds = new Set(serverFiles.map((file) => file.id))

  // 服务端已返回的条目：清除缺失计数。
  for (const id of Array.from(missingRounds.keys())) {
    if (serverIds.has(id)) missingRounds.delete(id)
  }

  const localPending: MixedFile[] = []
  for (const file of files.value) {
    if (serverIds.has(file.id)) continue
    if (file.status !== 'uploaded' && file.status !== 'converting') {
      missingRounds.delete(file.id)
      continue
    }

    const rounds = (missingRounds.get(file.id) ?? 0) + 1
    if (rounds >= MAX_MISSING_ROUNDS) {
      // 连续多轮服务端都未返回，判定为幽灵条目。
      missingRounds.delete(file.id)
      continue
    }
    missingRounds.set(file.id, rounds)
    localPending.push(file)
  }

  // 清理已不在本地列表中的计数，避免 Map 无限增长。
  const localIds = new Set(files.value.map((file) => file.id))
  for (const id of Array.from(missingRounds.keys())) {
    if (!localIds.has(id)) missingRounds.delete(id)
  }

  return localPending.length > 0
    ? [...serverFiles, ...localPending]
    : serverFiles
}

/* ------------------------------------------------------------------ */
/* 项目与文件加载                                                      */
/* ------------------------------------------------------------------ */

let detailRequest = 0

interface TimeoutSignal {
  signal: AbortSignal
  clear: () => void
}

/** 为只读请求提供超时信号；调用方必须在 finally 中 clear，避免定时器泄漏。 */
function withTimeout(ms: number): TimeoutSignal {
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), ms)
  return {
    signal: controller.signal,
    clear: () => window.clearTimeout(timeoutId),
  }
}

async function loadProjectDetail(
  id: string,
  options: { preserveLocal?: boolean } = {},
): Promise<boolean> {
  const requestId = ++detailRequest
  // 记录发起时的字典回写代数：若响应晚于字典 PATCH 成功返回，需保留本地字典。
  const revisionAtStart = dictionaryRevision
  const timeout = withTimeout(DETAIL_TIMEOUT)
  filesLoading.value = true
  try {
    const payload = await apiFetch<ProjectDetailPayload>(
      `/projects/${encodeURIComponent(id)}`,
      { signal: timeout.signal },
    )
    if (requestId !== detailRequest || currentProject.value?.id !== id) {
      return false
    }
    const detail = normalizeDetail(payload)
    // 详情请求可能早于字典 PATCH 发出、晚于其完成返回；
    // 此时用服务端快照整体覆盖会把刚保存的标签/关系短暂回退。
    // 字典保存进行中或仍有排队变更时，保留本地字典字段。
    const local = currentProject.value
    const keepLocalDictionary =
      local !== null &&
      local.id === detail.project.id &&
      (dictionarySaveInFlight ||
        hasDictionaryPending() ||
        dictionaryRevision !== revisionAtStart)
    currentProject.value = keepLocalDictionary
      ? {
          ...detail.project,
          labels: local.labels,
          relation_types: local.relation_types,
        }
      : detail.project
    files.value = options.preserveLocal
      ? mergeFileList(detail.files)
      : detail.files
    syncSelectedFile()
    // 详情加载成功后刷新引用统计：多人协作时别人的标注可能新增缺失标签。
    void refreshLabelUsage(detail.project.id)
    return true
  } catch (error) {
    if (requestId === detailRequest && currentProject.value?.id === id) {
      setNotice('error', messageOf(error))
    }
    return false
  } finally {
    timeout.clear()
    if (requestId === detailRequest) filesLoading.value = false
  }
}

/**
 * 只读项目快照：不更新 files/currentProject，也不消耗 detailRequest 令牌。
 * 供批量导入校准使用，避免与轮询的详情刷新互相取代。
 */
async function fetchProjectSnapshot(
  id: string,
): Promise<{ project: Project; files: MixedFile[] } | null> {
  const timeout = withTimeout(DETAIL_TIMEOUT)
  try {
    const payload = await apiFetch<ProjectDetailPayload>(
      `/projects/${encodeURIComponent(id)}`,
      { signal: timeout.signal },
    )
    return normalizeDetail(payload)
  } catch {
    return null
  } finally {
    timeout.clear()
  }
}

async function openProject(id: string): Promise<void> {
  const summary = projects.value.find((project) => project.id === id)
  if (!summary) return
  // 切换项目前丢弃上一项目尚未落盘的字典保存队列，避免写错项目。
  resetDictionarySaving()
  // 引用统计属于项目维度：先清空，避免短暂展示上一个项目的缺失标签。
  resetLabelUsage()
  currentProject.value = summary
  files.value = []
  selectedFile.value = null
  missingRounds.clear()
  rememberProject(id)
  await loadProjectDetail(id)
}

async function loadProjects(preferredId?: string): Promise<void> {
  projectsLoading.value = true
  try {
    const payload = await apiFetch<ProjectListPayload>('/projects')
    projects.value = normalizeProjects(payload)

    const targetId =
      preferredId ?? currentProject.value?.id ?? readSavedProjectId()
    const target =
      projects.value.find((project) => project.id === targetId) ??
      projects.value[0] ??
      null

    if (!target) {
      resetDictionarySaving()
      resetLabelUsage()
      currentProject.value = null
      files.value = []
      selectedFile.value = null
      rememberProject(null)
      return
    }

    if (currentProject.value?.id === target.id) {
      currentProject.value = target
      await loadProjectDetail(target.id)
    } else {
      await openProject(target.id)
    }
  } catch (error) {
    setNotice('error', messageOf(error))
  } finally {
    projectsLoading.value = false
  }
}

async function selectProject(id: string): Promise<void> {
  // 上传/导入/扫描/保存期间锁定项目，避免写入错误项目。
  if (importing.value || uploading.value || scanBusy.value || savingProject.value) return
  if (!id || currentProject.value?.id === id) return
  // 切换项目前先把当前项目未落盘的标注/Markdown 写完；失败则取消切换。
  const saved = await workspaceRef.value?.flushSave()
  if (saved === false) return
  // 字典卡片有独立防抖链路：切换前尽量提交，失败时由用户确认是否丢弃。
  if (!(await flushDictionaryNow())) {
    const confirmed = window.confirm(
      '标签/关系尚未保存成功，切换项目将丢失这些修改。仍要继续吗？',
    )
    if (!confirmed) return
  }
  await openProject(id)
}

function onScanningChange(active: boolean): void {
  scanBusy.value = active
}

/* ------------------------------------------------------------------ */
/* 导入弹窗                                                            */
/* ------------------------------------------------------------------ */

/** 顶栏「导入」按钮：没有项目时按钮已禁用，这里再兜一层并给出原因。 */
function openImportDialog(): void {
  if (!currentProject.value) {
    setNotice('error', '请先新建或选择项目，再导入文件。')
    return
  }
  if (scanBusy.value) return
  importOpen.value = true
}

/**
 * 弹窗开关：上传/转换进行中允许关闭（上传任务由本组件继续，后台排队不受影响），
 * 用户可以先关掉窗口回去标注。ImportDialog 常驻挂载，因此目录扫描的
 * scanning-change 不会因为关闭弹窗而丢失，scanBusy 仍能正常释放。
 */
function onImportOpenChange(open: boolean): void {
  importOpen.value = open
}

async function selectFile(id: string): Promise<void> {
  const file = files.value.find((item) => item.id === id)
  if (!file || file.id === selectedFile.value?.id) return
  // 切换文件前强制落盘；失败则取消切换，避免 1.2 秒防抖窗口内的修改丢失。
  const saved = await workspaceRef.value?.flushSave()
  if (saved === false) return
  selectedFile.value = file
}

async function refreshFiles(): Promise<void> {
  // 防御性守卫：不仅依赖按钮 disabled。
  if (importing.value || scanBusy.value) return
  if (!currentProject.value) return
  await loadProjectDetail(currentProject.value.id)
}

/** 工作区保存 / 主动刷新后同步文件元数据；失败保持静默，不打断编辑。 */
async function refreshSelectedFile(): Promise<void> {
  const current = selectedFile.value
  try {
    if (current) {
      const payload = await apiFetch<unknown>(
        `/files/${encodeURIComponent(current.id)}`,
      )
      const record = asRecord(payload)
      const nested = asRecord(record?.file) ?? record
      if (nested && typeof nested.id === 'string') {
        mergeFile(nested as unknown as MixedFile)
      }
    }
  } catch {
    // 后台刷新失败不产生提示；下一轮轮询或手动刷新会补齐。
  }
  // 标注变动可能让「被引用但字典缺失」的标签集合变化，静默刷新一次统计。
  const projectId = currentProject.value?.id
  if (projectId) void refreshLabelUsage(projectId)
}

/* ------------------------------------------------------------------ */
/* 项目操作                                                            */
/* ------------------------------------------------------------------ */

/** 返回是否成功，供设置弹窗决定关闭时机。 */
async function createProject(draft: ProjectDraft): Promise<boolean> {
  // 新建项目会切换当前项目：先落盘；失败则取消新建，避免丢草稿。
  const saved = await workspaceRef.value?.flushSave()
  if (saved === false) return false
  // 字典草稿同理：先尽力提交，未成功时由用户确认是否丢弃。
  if (!(await flushDictionaryNow())) {
    const confirmed = window.confirm(
      '标签/关系尚未保存成功，切换项目将丢失这些修改。仍要继续吗？',
    )
    if (!confirmed) return false
  }
  savingProject.value = true
  try {
    // 新建项目固定以完整字典字段提交：弹窗不再填字典，一律从空数组起步。
    const body: Required<ProjectDraft> = {
      name: draft.name,
      labels: draft.labels ?? [],
      relation_types: draft.relation_types ?? [],
    }
    const payload = await apiFetch<unknown>('/projects', {
      method: 'POST',
      body: JSON.stringify(body),
    })
    const createdId = extractId(payload, 'project')
    await loadProjects(createdId ?? undefined)
    if (currentProject.value?.id !== createdId) {
      const created =
        projects.value.find((project) => project.id === createdId) ??
        projects.value.find((project) => project.name === draft.name)
      if (created && currentProject.value?.id !== created.id) {
        await openProject(created.id)
      }
    }
    setNotice('success', `项目「${draft.name}」已创建。`)
    return true
  } catch (error) {
    setNotice('error', messageOf(error))
    return false
  } finally {
    savingProject.value = false
  }
}

/**
 * 仅更新项目名称。字典（标签/关系）由左侧卡片独立保存，
 * 这里绝不能携带空数组，否则会覆盖用户已配置的字典。
 */
async function saveProject(draft: ProjectDraft): Promise<boolean> {
  const project = currentProject.value
  if (!project) return false
  savingProject.value = true
  try {
    const payload = await apiFetch<unknown>(
      `/projects/${encodeURIComponent(project.id)}`,
      { method: 'PATCH', body: JSON.stringify({ name: draft.name }) },
    )
    // 请求期间字典可能已更新：以最新的 currentProject 为底，只改名称。
    const base =
      currentProject.value?.id === project.id ? currentProject.value : project
    const serverPatch = extractProjectPatch(payload) ?? {}
    const updated: Project = {
      ...base,
      name:
        typeof serverPatch.name === 'string' ? serverPatch.name : draft.name,
    }
    currentProject.value = updated
    const index = projects.value.findIndex((item) => item.id === project.id)
    if (index >= 0) projects.value[index] = updated
    setNotice('success', '项目配置已保存。')
    return true
  } catch (error) {
    setNotice('error', messageOf(error))
    return false
  } finally {
    savingProject.value = false
  }
}

/* ------------------------------------------------------------------ */
/* 按文件序号区间拆分项目                                              */
/* ------------------------------------------------------------------ */

/** 顶栏「设置」菜单入口：没有文件时该项已被禁用，这里再兜一层。 */
function openSplitDialog(): void {
  if (!currentProject.value) return
  if (files.value.length === 0) {
    setNotice('error', '当前项目没有可拆分的文件。')
    return
  }
  splitError.value = ''
  splitOpen.value = true
}

/**
 * 提交拆分：文件是**移动**语义，拆完源项目可能不再包含任何文件。
 *
 * 顺序很重要：先落盘当前文件的标注与字典，再提交拆分——
 * 新项目会继承字典与快捷键，未落盘的修改不会跟着过去。
 * 失败时把后端中文 detail 就地显示在弹窗内（而非只发全局提示）。
 */
async function submitSplit(groups: SplitGroup[]): Promise<void> {
  const project = currentProject.value
  if (!project || splitBusy.value) return
  const projectId = project.id
  splitError.value = ''

  const saved = await workspaceRef.value?.flushSave()
  if (saved === false) {
    splitError.value = '当前文件的标注尚未保存成功，请先处理保存失败再拆分。'
    return
  }
  if (!(await flushDictionaryNow())) {
    splitError.value = '标签/关系尚未保存成功，请稍后重试拆分。'
    return
  }

  splitBusy.value = true
  try {
    const payload = await apiFetch<ProjectSplitResponse>(
      `/projects/${encodeURIComponent(projectId)}/split`,
      { method: 'POST', body: JSON.stringify({ groups }) },
    )
    const results = Array.isArray(payload?.projects) ? payload.projects : []
    if (results.length === 0) {
      throw new Error('拆分接口未返回新项目，请刷新后确认结果。')
    }
    const firstId = results[0]?.project?.id
    const movedCount = results.reduce((total, item) => {
      const count = Array.isArray(item.file_ids)
        ? item.file_ids.length
        : Number(item.file_count)
      return total + (Number.isFinite(count) ? count : 0)
    }, 0)

    splitOpen.value = false
    // 切到第一个新项目，让用户立刻看到拆分结果。
    await loadProjects(firstId)
    setNotice(
      'success',
      `已拆分为 ${results.length} 个项目，移动 ${movedCount} 个文件。`,
    )
  } catch (error) {
    const message = messageOf(error)
    splitError.value = message
    setNotice('error', message)
  } finally {
    splitBusy.value = false
  }
}

/* ------------------------------------------------------------------ */
/* 项目级自定义快捷键                                                  */
/* ------------------------------------------------------------------ */

/** 归一化项目 shortcuts：老项目没有该字段，一律按 `{}` 处理。 */
function normalizeShortcuts(
  source: Record<string, string> | null | undefined,
): Record<string, string> {
  const result: Record<string, string> = {}
  for (const [label, combo] of Object.entries(source ?? {})) {
    if (!label || typeof combo !== 'string') continue
    const value = combo.trim()
    if (!value) continue
    result[label] = value
  }
  return result
}

/**
 * 服务端未返回完整 shortcuts 时的本地推算（与服务端增量语义一致）：
 * 先删覆盖、再写覆盖，保证 UI 与实际保存结果不背离。
 */
function applyShortcutPatch(
  base: Record<string, string> | null | undefined,
  set: Record<string, string>,
  unset: string[],
): Record<string, string> {
  const next = normalizeShortcuts(base)
  for (const label of unset) delete next[label]
  for (const [label, combo] of Object.entries(set)) {
    if (combo) next[label] = combo
  }
  return next
}

function openShortcutDialog(): void {
  if (!currentProject.value) return
  shortcutError.value = ''
  shortcutOpen.value = true
}

/**
 * 保存快捷键增量：`shortcuts_set` / `shortcuts_unset` 一起提交。
 * 成功后用响应里的完整项目回写 `currentProject.shortcuts`（老后端缺字段时本地推算）。
 */
async function submitShortcuts(payload: ProjectShortcutsPatch): Promise<void> {
  const project = currentProject.value
  if (!project || shortcutBusy.value) return

  const set = payload.shortcuts_set ?? {}
  // unset 与 set 互斥：同一标签若既设置又被清除，以设置为准。
  const unset = (payload.shortcuts_unset ?? []).filter(
    (label) => !(label in set),
  )
  if (Object.keys(set).length === 0 && unset.length === 0) {
    shortcutOpen.value = false
    setNotice('info', '快捷键没有改动。')
    return
  }

  shortcutBusy.value = true
  shortcutError.value = ''
  try {
    // 快捷键按标签名校验：刚在字典卡片里新增、尚未落盘的标签必须先提交，
    // 否则服务端会以「标签不存在」拒绝。
    if (!(await flushDictionaryNow())) {
      shortcutError.value = '标签/关系尚未保存成功，请稍后重试保存快捷键。'
      return
    }

    const body: ProjectShortcutsPatch = {}
    if (Object.keys(set).length > 0) body.shortcuts_set = set
    if (unset.length > 0) body.shortcuts_unset = unset

    const response = await apiFetch<unknown>(
      `/projects/${encodeURIComponent(project.id)}`,
      { method: 'PATCH', body: JSON.stringify(body) },
    )
    const serverPatch = extractProjectPatch(response)
    const serverShortcuts = serverPatch?.shortcuts
    const shortcuts = serverShortcuts
      ? normalizeShortcuts(serverShortcuts)
      : applyShortcutPatch(project.shortcuts, set, unset)

    if (currentProject.value?.id === project.id) {
      currentProject.value = { ...currentProject.value, shortcuts }
    }
    // 列表摘要同步：切回该项目时不会看到旧快捷键。
    const index = projects.value.findIndex((item) => item.id === project.id)
    if (index >= 0) {
      projects.value[index] = { ...projects.value[index], shortcuts }
    }

    shortcutOpen.value = false
    setNotice('success', '快捷键已保存。')
  } catch (error) {
    const message = messageOf(error)
    shortcutError.value = message
    setNotice('error', message)
  } finally {
    shortcutBusy.value = false
  }
}

/** 切换项目时关闭这些项目级弹窗，避免草稿作用于错误的项目。 */
watch(
  () => currentProject.value?.id,
  () => {
    splitOpen.value = false
    shortcutOpen.value = false
    // 导入弹窗承载的是「当前项目」的上传目标，切项目/删项目后必须关闭。
    importOpen.value = false
  },
)

/* ------------------------------------------------------------------ */
/* 标签与关系字典保存（300ms 防抖 + 串行 latest-wins）                  */
/* ------------------------------------------------------------------ */

/** 增量载荷的四个数组字段；合并、判空、请求体构造都以此为准。 */
const DICTIONARY_PATCH_KEYS = [
  'labels_add',
  'labels_remove',
  'relation_types_add',
  'relation_types_remove',
] as const

type DictionaryPatchKey = (typeof DICTIONARY_PATCH_KEYS)[number]

/** 读取增量字段，缺省视为空数组（避免到处写 `?? []`）。 */
function dictionaryValues(
  patch: ProjectDictionaryPatch,
  key: DictionaryPatchKey,
): string[] {
  const values = patch[key]
  return Array.isArray(values) ? values : []
}

/** 本次增量是否包含任何一个待提交的字典变更。 */
function patchHasChanges(patch: ProjectDictionaryPatch): boolean {
  return DICTIONARY_PATCH_KEYS.some(
    (key) => dictionaryValues(patch, key).length > 0,
  )
}

/** 待提交队列是否非空。 */
function hasDictionaryPending(): boolean {
  return patchHasChanges(dictionaryPending)
}

/** 递增令牌并清掉「已保存 → 空闲」定时器，避免旧计时器回写新状态。 */
function clearDictionarySavedTimer(): void {
  dictionarySavedToken += 1
  if (dictionarySavedTimer !== null) {
    window.clearTimeout(dictionarySavedTimer)
    dictionarySavedTimer = null
  }
}

function clearDictionaryDebounceTimer(): void {
  if (dictionaryDebounceTimer !== null) {
    window.clearTimeout(dictionaryDebounceTimer)
    dictionaryDebounceTimer = null
  }
}

/** 切换项目 / 删除项目 / 卸载时彻底丢弃队列与状态；在途请求由代数令牌作废。 */
function resetDictionarySaving(): void {
  dictionaryGeneration += 1
  clearDictionaryDebounceTimer()
  clearDictionarySavedTimer()
  dictionaryPending = {}
  dictionaryRerun = false
  dictionarySaveInFlight = false
  dictionaryStatus.value = 'idle'
}

/**
 * 同一字段的 add / remove 合并。
 *
 * 规则：add 求并集、remove 求并集；同一个值若既在 add 又在 remove 中，
 * 以「最后一次用户操作」为准 —— 新增时从 remove 里剔除，删除时从 add 里剔除，
 * 从而保证发出去的载荷中 add 与 remove 永远互斥。
 */
function mergePatchField(
  target: ProjectDictionaryPatch,
  patch: ProjectDictionaryPatch,
  addKey: 'labels_add' | 'relation_types_add',
  removeKey: 'labels_remove' | 'relation_types_remove',
): void {
  const add = [...dictionaryValues(target, addKey)]
  const remove = [...dictionaryValues(target, removeKey)]

  for (const value of dictionaryValues(patch, addKey)) {
    if (!value) continue
    const staleIndex = remove.indexOf(value)
    if (staleIndex >= 0) remove.splice(staleIndex, 1)
    if (!add.includes(value)) add.push(value)
  }

  for (const value of dictionaryValues(patch, removeKey)) {
    if (!value) continue
    const staleIndex = add.indexOf(value)
    if (staleIndex >= 0) add.splice(staleIndex, 1)
    if (!remove.includes(value)) remove.push(value)
  }

  target[addKey] = add
  target[removeKey] = remove
}

/**
 * 增量合并：同字段的 add / remove 各自求并集，互斥值以本次操作为准。
 * `force` 一旦确认就保留，直到该批修改成功落盘。
 */
function mergeDictionaryPatch(
  base: ProjectDictionaryPatch,
  patch: ProjectDictionaryPatch,
): ProjectDictionaryPatch {
  const next: ProjectDictionaryPatch = {
    labels_add: [...dictionaryValues(base, 'labels_add')],
    labels_remove: [...dictionaryValues(base, 'labels_remove')],
    relation_types_add: [...dictionaryValues(base, 'relation_types_add')],
    relation_types_remove: [...dictionaryValues(base, 'relation_types_remove')],
    force: Boolean(base.force) || Boolean(patch.force),
  }
  mergePatchField(next, patch, 'labels_add', 'labels_remove')
  mergePatchField(next, patch, 'relation_types_add', 'relation_types_remove')
  return next
}

/**
 * 把一次增量应用到本地列表（与服务端语义一致：只增不隐式删）。
 * 用于两条兜底路径：服务端未返回完整字典时的本地推算，以及排队增量的 UI 叠加。
 */
function applyPatchToValues(
  values: string[],
  patch: ProjectDictionaryPatch,
  field: 'labels' | 'relation_types',
): string[] {
  const addKey: DictionaryPatchKey =
    field === 'labels' ? 'labels_add' : 'relation_types_add'
  const removeKey: DictionaryPatchKey =
    field === 'labels' ? 'labels_remove' : 'relation_types_remove'
  const removed = new Set(dictionaryValues(patch, removeKey))
  const next = values.filter((value) => !removed.has(value))
  for (const value of dictionaryValues(patch, addKey)) {
    if (!next.includes(value)) next.push(value)
  }
  return next
}

/** 剔除空数组与 false 的 force，避免发出无意义的字段。 */
function toDictionaryRequestBody(
  patch: ProjectDictionaryPatch,
): ProjectDictionaryPatch {
  const body: ProjectDictionaryPatch = {}
  for (const key of DICTIONARY_PATCH_KEYS) {
    const values = dictionaryValues(patch, key)
    if (values.length > 0) body[key] = [...values]
  }
  if (patch.force) body.force = true
  return body
}

/** 本次增量里仍被标注引用的标签，用于删除前的确认与引用条数说明。 */
function inUseLabelRemovals(
  patch: ProjectDictionaryPatch,
): Array<{ name: string; count: number }> {
  const items: Array<{ name: string; count: number }> = []
  for (const name of dictionaryValues(patch, 'labels_remove')) {
    const count = labelUsage.value.used[name] ?? 0
    if (count > 0) items.push({ name, count })
  }
  return items
}

/** 确认弹窗文案：逐条列出引用条数，并说明后果。 */
function describeInUseRemovals(
  items: Array<{ name: string; count: number }>,
): string {
  const detail = items
    .map((item) => `「${item.name}」仍有 ${item.count} 处标注引用`)
    .join('；')
  return `${detail}。删除后这些标注会失去标签，正文中只显示为灰色且看不到标签名。确认删除吗？`
}

/**
 * 卡片每次变更的入口。
 *
 * 删除仍被引用的标签必须先确认：这里把本次增量挂起，用户在弹窗里确认后
 * 才带着 `force: true` 入队；取消则完全不发请求，并把卡片草稿还原。
 */
function handleDictionarySave(patch: ProjectDictionaryPatch): void {
  if (!currentProject.value) return
  if (!patchHasChanges(patch)) return

  const inUse = patch.force ? [] : inUseLabelRemovals(patch)
  if (inUse.length > 0) {
    pendingLabelRemove.value = { patch }
    labelRemoveMessage.value = describeInUseRemovals(inUse)
    labelRemoveOpen.value = true
    return
  }

  enqueueDictionaryPatch(patch)
}

/**
 * 把增量并入待提交队列并重置 300ms 防抖。
 * 只发送真正变化过的字段，避免误覆盖另一组字典。
 */
function enqueueDictionaryPatch(patch: ProjectDictionaryPatch): void {
  if (!currentProject.value) return
  if (!patchHasChanges(patch)) return
  dictionaryPending = mergeDictionaryPatch(dictionaryPending, patch)
  // 新的编辑使旧的「已保存」复位计时失效。
  clearDictionarySavedTimer()
  dictionaryStatus.value = 'saving'
  clearDictionaryDebounceTimer()
  dictionaryDebounceTimer = window.setTimeout(() => {
    dictionaryDebounceTimer = null
    void flushDictionarySave()
  }, DICTIONARY_DEBOUNCE)
}

/** 用户确认删除在用标签：本次 PATCH 带 force，服务端才允许删除。 */
function confirmRemoveInUseLabels(): void {
  const prompt = pendingLabelRemove.value
  pendingLabelRemove.value = null
  labelRemoveOpen.value = false
  if (!prompt) return
  enqueueDictionaryPatch({ ...prompt.patch, force: true })
}

/**
 * 弹窗关闭（取消 / Esc / 点遮罩）：本次删除不入队，
 * 并把卡片已经乐观移除的项按原位置插回草稿，避免草稿与真实字典不一致。
 */
function onLabelRemoveOpenChange(open: boolean): void {
  labelRemoveOpen.value = open
  if (open) return
  const prompt = pendingLabelRemove.value
  pendingLabelRemove.value = null
  if (!prompt) return
  for (const name of dictionaryValues(prompt.patch, 'labels_remove')) {
    dictionaryCardRef.value?.restoreRemoved('labels', name)
  }
  for (const name of dictionaryValues(prompt.patch, 'relation_types_remove')) {
    dictionaryCardRef.value?.restoreRemoved('relation_types', name)
  }
}

/** 成功后保持 1.5 秒「已保存」；期间若有新保存则旧计时器失效。 */
function scheduleDictionaryIdleReset(): void {
  clearDictionarySavedTimer()
  const token = dictionarySavedToken
  dictionarySavedTimer = window.setTimeout(() => {
    dictionarySavedTimer = null
    if (token !== dictionarySavedToken) return
    if (dictionarySaveInFlight || hasDictionaryPending()) return
    dictionaryStatus.value = 'idle'
  }, DICTIONARY_SAVED_HOLD)
}

/**
 * 字典字段取值：服务端返回的完整数组合并结果优先；缺失时按本次增量本地推算。
 * 注意这里不再接受「整份数组提交」，因此不存在用旧快照覆盖服务端的可能。
 */
function resolveDictionaryValue(
  field: 'labels' | 'relation_types',
  values: string[],
  patch: ProjectDictionaryPatch,
  serverPatch: Partial<Project> | null,
): string[] {
  const serverValue = serverPatch?.[field]
  if (Array.isArray(serverValue)) return [...serverValue]
  return applyPatchToValues(values, patch, field)
}

/**
 * 把服务端合并结果回写到 currentProject，再把仍在排队的增量叠加到 UI 上。
 *
 * 叠加的意义：PATCH 返回时队列里可能已经有用户刚输入的新标签，
 * 如果只用服务端快照整体覆盖，这些尚未落盘的标签会瞬间从卡片上消失。
 */
function writeBackDictionary(
  projectId: string,
  patch: ProjectDictionaryPatch,
  serverPatch: Partial<Project> | null,
): void {
  const current = currentProject.value
  if (!current || current.id !== projectId) return
  const labels = resolveDictionaryValue('labels', current.labels, patch, serverPatch)
  const relations = resolveDictionaryValue(
    'relation_types',
    current.relation_types,
    patch,
    serverPatch,
  )
  currentProject.value = {
    ...current,
    labels: applyPatchToValues(labels, dictionaryPending, 'labels'),
    relation_types: applyPatchToValues(
      relations,
      dictionaryPending,
      'relation_types',
    ),
  }
}

/**
 * 只回写 projects 列表摘要中的字典字段，不触碰 currentProject。
 * 供切换项目后才返回的旧代际响应使用，避免切回项目时摘要回退。
 */
function applyDictionaryToSummary(
  projectId: string,
  patch: ProjectDictionaryPatch,
  serverPatch: Partial<Project> | null,
): void {
  const index = projects.value.findIndex((item) => item.id === projectId)
  if (index < 0) return
  const summary = projects.value[index]
  projects.value[index] = {
    ...summary,
    labels: resolveDictionaryValue('labels', summary.labels, patch, serverPatch),
    relation_types: resolveDictionaryValue(
      'relation_types',
      summary.relation_types,
      patch,
      serverPatch,
    ),
  }
}

/**
 * 串行发送字典 PATCH（只含增量字段）：
 * - 在途时不并发，只把新变更留到当前请求结束后再发一次（latest wins）；
 * - 固定 projectId，响应回来若已切换项目则丢弃 currentProject 回写，
 *   但仍回写列表摘要，避免切回时看到旧字典；
 * - 失败不覆盖 currentProject，把失败字段并回队列，等待用户再次保存。
 */
async function flushDictionarySave(): Promise<void> {
  if (dictionarySaveInFlight) {
    if (hasDictionaryPending()) dictionaryRerun = true
    return
  }
  if (!hasDictionaryPending()) return
  const project = currentProject.value
  if (!project) {
    resetDictionarySaving()
    return
  }

  clearDictionaryDebounceTimer()
  const generation = dictionaryGeneration
  const projectId = project.id
  const patch = dictionaryPending
  dictionaryPending = {}
  dictionarySaveInFlight = true
  dictionaryStatus.value = 'saving'
  let succeeded = false

  try {
    const payload = await apiFetch<unknown>(
      `/projects/${encodeURIComponent(projectId)}`,
      { method: 'PATCH', body: JSON.stringify(toDictionaryRequestBody(patch)) },
    )
    // 后端返回合并后的完整项目，字典字段以服务端结果为准。
    const serverPatch = extractProjectPatch(payload)
    if (generation !== dictionaryGeneration) {
      // 项目已切换：不碰 currentProject，但成功结果仍要回写列表摘要。
      applyDictionaryToSummary(projectId, patch, serverPatch)
      return
    }

    writeBackDictionary(projectId, patch, serverPatch)
    applyDictionaryToSummary(projectId, patch, serverPatch)
    // 递增回写代数：早于本次 PATCH 发出、晚于其返回的详情快照不得覆盖本地字典。
    dictionaryRevision += 1

    succeeded = true
    dictionaryStatus.value = 'saved'
    scheduleDictionaryIdleReset()
    // 引用计数可能随删除/新增变化，刷新后「字典缺失」区域才会同步。
    void refreshLabelUsage(projectId, { force: true })
  } catch (error) {
    if (generation !== dictionaryGeneration) return
    const current = currentProject.value
    if (!current || current.id !== projectId) return
    // 失败不覆盖 currentProject：卡片保留用户草稿。
    // 把本次失败的字段并回队列（已排队的新值优先），保证重试仍能提交。
    dictionaryPending = mergeDictionaryPatch(patch, dictionaryPending)
    // 清掉可能遗留的防抖：失败后不再自动跳回「保存中」，让重试入口稳定可见。
    clearDictionaryDebounceTimer()
    clearDictionarySavedTimer()
    dictionaryStatus.value = 'error'
    // 409 = 删除仍被引用的标签（多因 usage 尚未返回而没走确认弹窗）。
    // 必须把这次删除从队列里撤回，否则整批后续标签新增都会被它一起卡住；
    // 同时把卡片上已乐观移除的 chip 放回去，让用户看清后重新操作。
    const rejectedRemovals =
      error instanceof ApiError && error.status === 409
        ? dictionaryValues(patch, 'labels_remove')
        : []
    if (rejectedRemovals.length > 0) {
      const rejected = new Set(rejectedRemovals)
      dictionaryPending = {
        ...dictionaryPending,
        labels_remove: dictionaryValues(dictionaryPending, 'labels_remove').filter(
          (value) => !rejected.has(value),
        ),
      }
      for (const value of rejectedRemovals) {
        dictionaryCardRef.value?.restoreRemoved('labels', value)
      }
    }
    // 409 时后端 detail 已包含每个标签的引用条数，直接展示给用户。
    setNotice('error', messageOf(error))
    // 统计可能是旧的（或首次加载失败）才导致没有拦下确认：刷新后下一次删除会带条数确认。
    void refreshLabelUsage(projectId, { force: true })
  } finally {
    if (generation === dictionaryGeneration) {
      dictionarySaveInFlight = false
      // 失败后不自动重试，等待用户下一次保存动作。
      if (succeeded && (dictionaryRerun || hasDictionaryPending())) {
        dictionaryRerun = false
        void flushDictionarySave()
      } else {
        dictionaryRerun = false
      }
    }
  }
}

/**
 * 项目切换/新建前的强制落盘：清掉 300ms 防抖窗口，等待串行队列清空（最多约 5 秒）。
 * 返回 false 表示仍有未成功提交的字典修改，调用方需让用户确认是否丢弃。
 */
async function flushDictionaryNow(): Promise<boolean> {
  clearDictionaryDebounceTimer()
  if (!dictionarySaveInFlight && hasDictionaryPending()) {
    await flushDictionarySave()
  }

  const deadline = Date.now() + 5000
  while (
    (dictionarySaveInFlight || hasDictionaryPending()) &&
    Date.now() < deadline
  ) {
    // 已明确失败且没有在途请求时不会自动重试，无需空等到超时。
    if (!dictionarySaveInFlight && dictionaryStatus.value === 'error') break
    await new Promise((resolve) => window.setTimeout(resolve, 25))
  }

  return dictionaryStatus.value !== 'error'
}

/* ------------------------------------------------------------------ */
/* 标签引用统计与缺失恢复                                              */
/* ------------------------------------------------------------------ */

/** 把后端返回的 usage 归一化：只保留有限的正整数计数与去空白的标签名。 */
function normalizeLabelUsage(payload: unknown): ProjectLabelUsage {
  const record = asRecord(payload)
  const usedSource = asRecord(record?.used) ?? {}
  const used: Record<string, number> = {}
  for (const [name, raw] of Object.entries(usedSource)) {
    const label = name.trim()
    const count = Number(raw)
    if (!label || !Number.isFinite(count) || count <= 0) continue
    used[label] = Math.floor(count)
  }

  const missingSource = record?.missing
  const missing: string[] = []
  for (const raw of Array.isArray(missingSource) ? missingSource : []) {
    if (typeof raw !== 'string') continue
    const label = raw.trim()
    if (label && !missing.includes(label)) missing.push(label)
  }

  return { used, missing }
}

/** usage 全量扫描注释文件，最短刷新间隔：避免轮询/连续保存把它打成高频请求。 */
const LABEL_USAGE_MIN_INTERVAL_MS = 10_000
let labelUsageLastAt = 0
let labelUsageLastProject = ''

/**
 * 刷新标签引用统计（供删除确认与「字典缺失」区域使用）。
 *
 * 竞态处理：每次请求递增令牌并固定 projectId，
 * 只有「最新一次请求 + 仍是当前项目」的响应才允许写入状态，旧响应直接丢弃。
 * 失败时保留上一次快照：usage 只是辅助提示，不应打断主流程。
 *
 * 服务端该接口需要扫描项目全部 annotations.json（国标3 量级约 60ms），
 * 因此同一项目 10 秒内只刷新一次；字典保存/恢复等确实改变字典的操作传
 * `force: true` 绕过节流。
 */
async function refreshLabelUsage(
  projectId: string,
  options: { force?: boolean } = {},
): Promise<void> {
  const now = Date.now()
  if (
    !options.force &&
    labelUsageLastProject === projectId &&
    now - labelUsageLastAt < LABEL_USAGE_MIN_INTERVAL_MS
  ) {
    return
  }
  const token = ++labelUsageToken
  try {
    const payload = await apiFetch<unknown>(
      `/projects/${encodeURIComponent(projectId)}/labels/usage`,
    )
    if (token !== labelUsageToken) return
    if (currentProject.value?.id !== projectId) return
    labelUsage.value = normalizeLabelUsage(payload)
    labelUsageLastProject = projectId
    labelUsageLastAt = Date.now()
  } catch {
    // 静默失败：下一次详情加载/保存会再次尝试。
  }
}

/** 切换或清空项目时丢弃上一个项目的引用统计。 */
function resetLabelUsage(): void {
  labelUsageToken += 1
  labelUsageLastProject = ''
  labelUsageLastAt = 0
  labelUsage.value = { used: {}, missing: [] }
}

/** 从恢复响应中取出本次补回的标签列表，兼容 `{project: {...}}` 封装。 */
function extractRestoredLabels(payload: unknown): string[] {
  const record = asRecord(payload)
  if (!record) return []
  const nested = asRecord(record.project ?? record)
  const value = (nested?.restored ?? record.restored) as unknown
  if (!Array.isArray(value)) return []
  const restored: string[] = []
  for (const raw of value) {
    if (typeof raw !== 'string') continue
    const label = raw.trim()
    if (label && !restored.includes(label)) restored.push(label)
  }
  return restored
}

/**
 * 把「被标注引用但字典缺失」的标签补回项目字典。
 * 成功后同步项目对象与列表摘要，并刷新引用统计（missing 变空、卡片恢复区消失）。
 */
async function restoreMissingLabels(): Promise<void> {
  const project = currentProject.value
  if (!project || restoringLabels.value) return
  const projectId = project.id
  restoringLabels.value = true
  try {
    const payload = await apiFetch<LabelRestorePayload>(
      `/projects/${encodeURIComponent(projectId)}/labels/restore`,
      { method: 'POST' },
    )
    const serverPatch = extractProjectPatch(payload)
    const restored = extractRestoredLabels(payload)

    if (currentProject.value?.id === projectId) {
      writeBackDictionary(projectId, {}, serverPatch)
      // 服务端已把缺失标签补回字典，早于本次响应的详情快照不得覆盖它。
      dictionaryRevision += 1
    }
    applyDictionaryToSummary(projectId, {}, serverPatch)
    await refreshLabelUsage(projectId, { force: true })

    setNotice(
      'success',
      restored.length > 0
        ? `已恢复 ${restored.length} 个标签。`
        : '字典中没有可恢复的标签。',
    )
  } catch (error) {
    setNotice('error', messageOf(error))
  } finally {
    restoringLabels.value = false
  }
}

/** 返回是否成功；确认交互由 ConfirmDialog 负责，成功后关闭弹窗。 */
async function deleteProject(): Promise<boolean> {
  const project = currentProject.value
  if (!project) return false

  savingProject.value = true
  try {
    await apiFetch<unknown>(`/projects/${encodeURIComponent(project.id)}`, {
      method: 'DELETE',
    })
    // 删除已成功：先关闭确认弹窗，避免列表刷新期间标题/影响范围闪空。
    deleteOpen.value = false
    // 项目已不存在：丢弃字典保存队列与状态。
    resetDictionarySaving()
    resetLabelUsage()
    currentProject.value = null
    files.value = []
    selectedFile.value = null
    stopPolling()
    rememberProject(null)
    await loadProjects()
    setNotice('success', `项目「${project.name}」已删除。`)
    return true
  } catch (error) {
    setNotice('error', messageOf(error))
    return false
  } finally {
    savingProject.value = false
  }
}

/* ------------------------------------------------------------------ */
/* 设置弹窗与删除确认                                                  */
/* ------------------------------------------------------------------ */

function openCreateSettings(): void {
  settingsMode.value = 'create'
  settingsError.value = ''
  settingsOpen.value = true
}

/** 「项目设置」入口：只编辑项目名称与转换参数，字典已移到左侧卡片。 */
function openProjectSettings(): void {
  if (!currentProject.value) return
  settingsMode.value = 'edit'
  settingsError.value = ''
  settingsOpen.value = true
}

/** 提交名称 + 转换参数：先创建/PATCH 项目，成功后再应用识别参数。 */
async function handleSettingsSubmit(payload: ProjectSettingsPayload): Promise<void> {
  if (savingProject.value) return
  settingsError.value = ''
  // 新建项目只填名称：字典从空数组起步，后续由左侧卡片维护。
  // 编辑项目只改名称：不携带字典字段，避免覆盖现有标签/关系。
  const ok =
    settingsMode.value === 'create'
      ? await createProject({
          name: payload.name,
          labels: [],
          relation_types: [],
        })
      : await saveProject({ name: payload.name })
  if (!ok) {
    settingsError.value =
      notice.value?.kind === 'error' ? notice.value.text : '保存失败，请稍后重试。'
    return
  }
  applyConversionOptions(payload.options)
  settingsOpen.value = false
}

/** 删除影响范围随当前项目与文件列表动态生成。 */
const deleteImpact = computed(() => {
  const project = currentProject.value
  if (!project) return ''
  return `将同时删除 ${files.value.length} 个文件、${project.labels.length} 个标签、${project.relation_types.length} 种关系，以及全部标注记录和图表截图。此操作不可恢复。`
})

function openDeleteDialog(): void {
  const project = currentProject.value
  if (!project) return
  // 快照文案：删除过程中 currentProject 会被清空，弹窗内容必须保持不变。
  deleteTargetName.value = project.name
  deleteImpactText.value = deleteImpact.value
  deleteError.value = ''
  deleteOpen.value = true
}

async function confirmDeleteProject(): Promise<void> {
  deleteError.value = ''
  const ok = await deleteProject()
  if (!ok) {
    deleteError.value =
      notice.value?.kind === 'error' ? notice.value.text : '删除失败，请稍后重试。'
  }
}

/* ------------------------------------------------------------------ */
/* 文件操作                                                            */
/* ------------------------------------------------------------------ */

function applyConversionOptions(options: ConversionOptions): void {
  Object.assign(conversionOptions, options)
}

function onInvalidUpload(message: string): void {
  setNotice('error', message)
}

async function handleUpload(file: File): Promise<void> {
  const project = currentProject.value
  if (!project) {
    setNotice('error', '请先创建或选择项目。')
    return
  }
  if (uploading.value || importing.value) return

  const projectId = project.id
  const knownIds = new Set(files.value.map((item) => item.id))
  uploading.value = true
  // 与批量导入一致：单文件上传也必须有硬超时，避免挂起后永久锁住项目操作。
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), UPLOAD_TIMEOUT)
  try {
    const form = new FormData()
    form.append('file', file)
    form.append('enable_table', String(conversionOptions.enable_table))
    form.append('enable_formula', String(conversionOptions.enable_formula))
    form.append('dpi', String(conversionOptions.dpi))

    const payload = await apiFetch<unknown>(
      `/projects/${encodeURIComponent(projectId)}/files`,
      { method: 'POST', body: form, signal: controller.signal },
    )

    if (currentProject.value?.id === projectId) {
      await loadProjectDetail(projectId)
      const createdId = extractId(payload, 'file')
      const created =
        (createdId && files.value.find((item) => item.id === createdId)) ||
        files.value.find((item) => !knownIds.has(item.id))
      if (created) {
        // 上传成功后自动选中新文件：切换前先把当前文件未落盘的内容写完。
        const saved = await workspaceRef.value?.flushSave()
        if (saved !== false) selectedFile.value = created
      }
    }
    setNotice('success', `已上传「${file.name}」，正在转换。`)
  } catch (error) {
    setNotice('error', messageOf(error))
  } finally {
    window.clearTimeout(timeoutId)
    uploading.value = false
  }
}

/**
 * 批量导入：先用只读项目快照校准文件列表，再按文件名顺序逐个上传。
 * 固定 projectId，导入/扫描期间项目切换被禁用，避免文件写入错误项目。
 */
async function handleBatchImport(batch: File[]): Promise<void> {
  const project = currentProject.value
  if (!project) {
    setNotice('error', '请先创建或选择项目。')
    return
  }
  if (importing.value || uploading.value) return
  if (batch.length === 0) return

  const projectId = project.id
  // 固定本次导入的识别参数，避免中途变更影响已排队的文件。
  const options: ConversionOptions = { ...conversionOptions }

  // 先进入锁状态，确保初始详情刷新的等待期间也无法再次导入或上传。
  importing.value = true
  importProgress.value = null

  let skipped = 0
  let submitted = 0
  let processed = 0
  const failures: string[] = []

  try {
    // 只读快照不会与轮询的详情刷新互相取代，也不会消费 detailRequest 令牌。
    const snapshot = await fetchProjectSnapshot(projectId)
    if (currentProject.value?.id !== projectId) {
      setNotice('error', '项目已切换，已取消本次导入。')
      return
    }
    if (!snapshot) {
      setNotice('error', '无法读取项目文件列表，已取消本次导入。')
      return
    }

    // 快照 + 当前列表共同构造去重基准，兼顾服务端权威数据与本地乐观条目。
    const knownNames = new Set<string>()
    for (const file of [...snapshot.files, ...files.value]) {
      const key = file.name.trim().toLowerCase()
      if (key) knownNames.add(key)
    }

    const queue: File[] = []
    for (const file of batch) {
      const key = file.name.trim().toLowerCase()
      if (!key || knownNames.has(key)) {
        skipped += 1
        continue
      }
      knownNames.add(key)
      queue.push(file)
    }

    if (queue.length === 0) {
      setNotice(
        'info',
        `已提交 0 个、跳过 ${skipped} 个同名、0 个上传失败。`,
      )
      return
    }

    importProgress.value = {
      done: 0,
      total: queue.length,
      current: queue[0].name,
    }

    // 严格串行：逐个 await，避免同时创建多个上传任务。
    for (const file of queue) {
      if (currentProject.value?.id !== projectId) break

      importProgress.value = {
        done: processed,
        total: queue.length,
        current: file.name,
      }

      const form = new FormData()
      form.append('file', file)
      form.append('enable_table', String(options.enable_table))
      form.append('enable_formula', String(options.enable_formula))
      form.append('dpi', String(options.dpi))
      form.append('defer_conversion', 'true')

      // 单文件 2 分钟硬超时；超时按失败处理，继续下一个文件。
      const controller = new AbortController()
      let timedOut = false
      const timeoutId = window.setTimeout(() => {
        timedOut = true
        controller.abort()
      }, UPLOAD_TIMEOUT)

      try {
        const payload = await apiFetch<unknown>(
          `/projects/${encodeURIComponent(projectId)}/files`,
          { method: 'POST', body: form, signal: controller.signal },
        )
        submitted += 1
        // 立即合并进列表，使 status=uploaded 触发 hasPendingConversion 轮询。
        const created = extractFile(payload)
        if (created) upsertFile(created)
      } catch (error) {
        // 单个失败/超时不中断后续文件。
        failures.push(
          `${file.name}：${
            timedOut
              ? '上传超时（2 分钟，服务端可能已入库，请刷新确认）'
              : messageOf(error)
          }`,
        )
      } finally {
        window.clearTimeout(timeoutId)
      }

      processed += 1
      importProgress.value = {
        done: processed,
        total: queue.length,
        current: queue[processed]?.name ?? '',
      }
    }

    if (currentProject.value?.id === projectId) {
      // 与后端详情对齐一次，补齐排序与状态字段；保留尚未回传的乐观条目。
      await loadProjectDetail(projectId, { preserveLocal: true })
    }

    // 三条出口统一使用固定三项统计：已提交 / 跳过同名 / 上传失败。
    const summary = `已提交 ${submitted} 个、跳过 ${skipped} 个同名、${failures.length} 个上传失败`
    if (failures.length > 0) {
      const preview = failures.slice(0, 3).join('；')
      const more = failures.length > 3 ? '…' : ''
      setNotice('error', `${summary}：${preview}${more}`)
    } else {
      setNotice('success', `${summary}，后端将按顺序自动识别，可关闭页面。`)
    }
  } catch (error) {
    setNotice('error', messageOf(error))
  } finally {
    // 无条件释放锁，避免异常路径永久卡死 UI。
    importing.value = false
    importProgress.value = null
  }
}

async function deleteFile(file: MixedFile): Promise<void> {
  // 防御性守卫：不仅依赖按钮 disabled。
  if (importing.value || scanBusy.value) return
  const project = currentProject.value
  if (!project) return
  const confirmed = window.confirm(`删除文件「${file.name}」及其标注？`)
  if (!confirmed) return

  try {
    await apiFetch<unknown>(`/files/${encodeURIComponent(file.id)}`, {
      method: 'DELETE',
    })
    if (selectedFile.value?.id === file.id) selectedFile.value = null
    await loadProjectDetail(project.id)
    setNotice('success', `已删除「${file.name}」。`)
  } catch (error) {
    setNotice('error', messageOf(error))
  }
}

async function retryFile(file: MixedFile): Promise<void> {
  // 防御性守卫：不仅依赖按钮 disabled。
  if (importing.value || scanBusy.value) return
  const project = currentProject.value
  if (!project || retryingId.value) return

  retryingId.value = file.id
  try {
    await apiFetch<unknown>(
      `/files/${encodeURIComponent(file.id)}/convert`,
      {
        method: 'POST',
        body: JSON.stringify({ ...conversionOptions }),
      },
    )
    file.status = 'converting'
    file.progress = 0
    file.stage = '已提交'
    file.error = ''
    await loadProjectDetail(project.id)
    setNotice('info', `已重新提交「${file.name}」的转换任务。`)
  } catch (error) {
    setNotice('error', messageOf(error))
  } finally {
    retryingId.value = null
  }
}

async function reconvertSelectedFile(): Promise<void> {
  const file = selectedFile.value
  if (!file) return
  const confirmed = window.confirm(
    `重新 OCR 转换会清空「${file.name}」现有的实体/关系标注和图表记录，且无法恢复。\n\n` +
      '只在 Markdown 乱码（PDF 文本层编码异常）时使用。是否继续？',
  )
  if (!confirmed) return
  await retryFile(file)
}

/* ------------------------------------------------------------------ */
/* 轮询转换状态                                                        */
/* ------------------------------------------------------------------ */

let pollTimer: number | null = null
let pollInFlight = false

function applyStatus(file: MixedFile, status: FileStatusPayload): void {
  if (status.status) file.status = status.status
  if (typeof status.progress === 'number') file.progress = status.progress
  if (typeof status.page_count === 'number') file.page_count = status.page_count
  if (typeof status.stage === 'string') file.stage = status.stage
  if (typeof status.message === 'string') file.message = status.message
  if (typeof status.error === 'string') file.error = status.error
}

function stopPolling(): void {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

function startPolling(): void {
  if (pollTimer !== null) return
  pollTimer = window.setInterval(() => {
    void pollStatuses()
  }, POLL_INTERVAL)
}

/** 统一处理本轮转为 completed/failed 的文件：刷新、通知与工作区重建。 */
async function handleFinishedFiles(
  projectId: string,
  finished: string[],
  reload: boolean,
): Promise<void> {
  if (finished.length === 0) return

  const selectedIdBefore = selectedFile.value?.id ?? null
  if (reload) {
    // 与大批量路径统一：保留刚上传、详情接口暂时未返回的乐观条目。
    await loadProjectDetail(projectId, { preserveLocal: true })
    if (currentProject.value?.id !== projectId) return
  }

  const completed = files.value.filter(
    (file) => finished.includes(file.id) && file.status === 'completed',
  )
  const failed = files.value.filter(
    (file) => finished.includes(file.id) && file.status === 'failed',
  )
  if (
    selectedIdBefore &&
    completed.some((file) => file.id === selectedIdBefore)
  ) {
    // 当前打开的文件刚转换完成：强制重建工作区以拉取新的 Markdown。
    workspaceRevision.value += 1
  }
  if (completed.length > 0) {
    setNotice(
      'success',
      completed.length === 1
        ? `「${completed[0].name}」转换完成。`
        : `${completed.length} 个文件转换完成。`,
    )
  } else if (failed.length > 0) {
    setNotice(
      'error',
      failed.length === 1
        ? `「${failed[0].name}」转换失败，可在文件列表中重试。`
        : `${failed.length} 个文件转换失败，可在文件列表中重试。`,
    )
  }
}

async function pollStatuses(): Promise<void> {
  const project = currentProject.value
  if (!project || pollInFlight) return

  const pending = files.value.filter(
    (file) => file.status === 'converting' || file.status === 'uploaded',
  )
  if (pending.length === 0) {
    stopPolling()
    return
  }

  pollInFlight = true
  try {
    const finished: string[] = []

    if (pending.length <= STATUS_PER_FILE_LIMIT) {
      // 小批量：逐文件查询状态，保持原有细粒度进度，不回归。
      const results = await Promise.allSettled(
        pending.map((file) =>
          apiFetch<FileStatusPayload>(
            `/files/${encodeURIComponent(file.id)}/status`,
          ),
        ),
      )
      if (currentProject.value?.id !== project.id) return

      results.forEach((result, index) => {
        if (result.status !== 'fulfilled') return
        const file = pending[index]
        const previous = file.status
        applyStatus(file, result.value)
        if (
          previous !== file.status &&
          (file.status === 'completed' || file.status === 'failed')
        ) {
          finished.push(file.id)
        }
      })

      await handleFinishedFiles(project.id, finished, true)
      return
    }

    // 大批量：每轮只拉一次项目详情，避免几十上百个 /status 请求。
    const statusBefore = new Map(
      files.value.map((file) => [file.id, file.status] as const),
    )
    // preserveLocal：保留本地已上传、详情接口暂时未返回的乐观条目。
    await loadProjectDetail(project.id, { preserveLocal: true })
    if (currentProject.value?.id !== project.id) return

    for (const file of files.value) {
      const previous = statusBefore.get(file.id)
      if (
        previous !== undefined &&
        previous !== file.status &&
        (file.status === 'completed' || file.status === 'failed')
      ) {
        finished.push(file.id)
      }
    }

    // 详情已在本轮刷新完成，无需再次 reload。
    await handleFinishedFiles(project.id, finished, false)
  } catch {
    // 单轮失败不打断轮询，下一轮继续重试。
  } finally {
    pollInFlight = false
  }
}

watch(hasPendingConversion, (active) => {
  if (active) startPolling()
  else stopPolling()
})

/* ------------------------------------------------------------------ */
/* 导出                                                                */
/* ------------------------------------------------------------------ */

async function exportProject(): Promise<void> {
  const project = currentProject.value
  if (!project || exporting.value) return
  exporting.value = true
  try {
    await downloadProjectZip(project.id, project.name)
    setNotice('success', `正在下载「${project.name}」的 ZIP。`)
  } catch (error) {
    setNotice('error', messageOf(error))
  } finally {
    exporting.value = false
  }
}

/* ------------------------------------------------------------------ */
/* 导出 Excel 表单（可多选项目）                                       */
/* ------------------------------------------------------------------ */

/** 顶栏入口：没有项目时直接提示，避免打开空弹窗。 */
function openExcelDialog(): void {
  if (projects.value.length === 0) {
    setNotice('error', '请先新建项目。')
    return
  }
  // 每次打开都清掉上一次的失败信息，避免旧错误误导本次操作。
  excelError.value = ''
  excelOpen.value = true
}

/** 提交所选项目：成功关闭弹窗，失败保留弹窗并就地展示后端中文错误。 */
async function submitExcelExport(projectIds: string[]): Promise<void> {
  if (projectIds.length === 0 || exportingExcel.value) return
  exportingExcel.value = true
  excelError.value = ''
  try {
    await downloadProjectExcel(projectIds)
    setNotice('success', '正在下载所选项目的标注明细 Excel。')
    excelOpen.value = false
  } catch (error) {
    const message = messageOf(error)
    excelError.value = message
    setNotice('error', message)
  } finally {
    exportingExcel.value = false
  }
}

onMounted(() => {
  void loadProjects()
})

onUnmounted(() => {
  stopPolling()
  detailRequest += 1
  // 卸载前清掉防抖窗口；已有待提交修改尽力发出，不静默丢弃。
  clearDictionaryDebounceTimer()
  if (hasDictionaryPending()) void flushDictionarySave()
  // 组件已卸载，后续状态回写无害；只需清掉复位定时器与 usage 令牌。
  clearDictionarySavedTimer()
  resetLabelUsage()
  if (noticeTimer !== null) {
    window.clearTimeout(noticeTimer)
    noticeTimer = null
  }
})
</script>

<template>
  <div class="mx-root">
    <AppHeader
      :projects="projects"
      :current-project="currentProject"
      :selected-file="selectedFile"
      :file-status-label="fileStatusLabel"
      :exporting="exporting"
      :excel-exporting="exportingExcel"
      :project-switch-disabled="importing || uploading || scanBusy || savingProject"
      :split-disabled="files.length === 0"
      @select-project="selectProject"
      @create="openCreateSettings"
      @settings="openProjectSettings"
      @split-project="openSplitDialog"
      @delete-project="openDeleteDialog"
      @import="openImportDialog"
      @reconvert="openReconvertDialog"
      @export="exportProject"
      @export-excel="openExcelDialog"
    >
      <!--
        工作区挂载点：MixedWorkspace 通过 <Teleport to="#mw-toolbar-slot"> 把文件头搬进来。
        该节点必须常驻（AppHeader 先于 MixedWorkspace 渲染），否则 Teleport 找不到宿主。
      -->
      <template #workspace>
        <div id="mw-toolbar-slot" class="mx-workspace-slot"></div>
      </template>
    </AppHeader>

    <div class="mx-body">
      <aside class="project-sidebar" aria-label="文件">
        <ProjectDictionaryCard
          v-if="currentProject"
          ref="dictionaryCardRef"
          :project="currentProject"
          :status="dictionaryStatus"
          :missing-labels="labelUsage.missing"
          :usage="labelUsage.used"
          :restoring="restoringLabels"
          :shortcuts="currentProject.shortcuts ?? {}"
          @save="handleDictionarySave"
          @restore="restoreMissingLabels"
          @edit-shortcuts="openShortcutDialog"
        />

        <!--
          上传面板已移入顶栏「导入」弹窗：侧栏只留「字典 + 文件列表」，
          文件列表因此拿到全部剩余高度，不再被上传区挤压。
        -->
        <FileList
          :files="files"
          :selected-id="selectedFile?.id ?? null"
          :loading="filesLoading"
          :retrying-id="retryingId"
          :busy="importing || scanBusy"
          @select="selectFile"
          @remove="deleteFile"
          @retry="retryFile"
          @refresh="refreshFiles"
        />
      </aside>

      <div class="mx-main">
        <Transition name="notice">
          <div
            v-if="notice"
            class="notice-bar"
            :class="`is-${notice.kind}`"
            role="status"
            aria-live="polite"
          >
            <svg
              class="notice-icon"
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              stroke-width="1.4"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <template v-if="notice.kind === 'success'">
                <path d="m3.5 8.5 3 3 6-7" />
              </template>
              <template v-else-if="notice.kind === 'error'">
                <circle cx="8" cy="8" r="5.5" />
                <path d="M8 5v3.6" />
                <path d="M8 10.8v.1" />
              </template>
              <template v-else>
                <circle cx="8" cy="8" r="5.5" />
                <path d="M8 7.4v3.8" />
                <path d="M8 5v.1" />
              </template>
            </svg>
            <p class="notice-text">{{ notice.text }}</p>
            <button
              type="button"
              class="notice-close"
              aria-label="关闭提示"
              @click="dismissNotice"
            >
              <svg
                viewBox="0 0 16 16"
                fill="none"
                stroke="currentColor"
                stroke-width="1.4"
                stroke-linecap="round"
                aria-hidden="true"
              >
                <path d="m4.5 4.5 7 7M11.5 4.5l-7 7" />
              </svg>
            </button>
          </div>
        </Transition>

        <div class="workspace-shell">
          <MixedWorkspace
            v-if="selectedFile && currentProject"
            ref="workspaceRef"
            :key="`${selectedFile.id}-${workspaceRevision}`"
            :project="currentProject"
            :file="selectedFile"
            :labels="currentProject.labels"
            :relation-types="currentProject.relation_types"
            :shortcuts="currentProject.shortcuts ?? {}"
            @saved="refreshSelectedFile"
            @refresh="refreshSelectedFile"
            @edit-shortcuts="openShortcutDialog"
            @reconvert="reconvertSelectedFile"
          />
          <EmptyState
            v-else
            :title="emptyState.title"
            :message="emptyState.message"
          />
        </div>
      </div>
    </div>

    <ProjectSettingsDialog
      v-model:open="settingsOpen"
      :mode="settingsMode"
      :project="currentProject"
      :options="conversionOptions"
      :busy="savingProject"
      :error="settingsError"
      @submit="handleSettingsSubmit"
    />

    <ConfirmDialog
      v-model:open="deleteOpen"
      :title="`删除项目「${deleteTargetName}」？`"
      :message="deleteImpactText"
      confirm-label="删除项目"
      busy-label="删除中…"
      danger
      :busy="savingProject"
      :error="deleteError"
      @confirm="confirmDeleteProject"
    />

    <!--
      删除仍被标注引用的标签：先说明引用条数，确认后才带 force 重发 PATCH。
      取消通过 update:open 触发，父组件据此把卡片草稿还原。
    -->
    <ConfirmDialog
      :open="labelRemoveOpen"
      title="删除仍被引用的标签？"
      :message="labelRemoveMessage"
      confirm-label="仍然删除"
      danger
      @update:open="onLabelRemoveOpenChange"
      @confirm="confirmRemoveInUseLabels"
    />

    <!--
      顶栏「导入」弹窗：上传逻辑仍由本组件持有（uploading / importing /
      importProgress / batchSummary 与三个处理函数原样透传），
      弹窗只负责外壳，关闭窗口不会中断上传与后台转换排队。
    -->
    <ImportDialog
      :open="importOpen"
      :uploading="uploading"
      :disabled="!currentProject"
      :importing="importing"
      :import-progress="importProgress"
      :batch-summary="batchSummary"
      @update:open="onImportOpenChange"
      @upload="handleUpload"
      @upload-batch="handleBatchImport"
      @scanning-change="onScanningChange"
      @invalid="onInvalidUpload"
    />

    <ExportExcelDialog
      :open="excelOpen"
      :projects="projects"
      :current-project-id="currentProject?.id ?? null"
      :busy="exportingExcel"
      :error="excelError"
      @update:open="excelOpen = $event"
      @submit="submitExcelExport"
    />

    <!-- 按文件序号区间拆分：草稿与校验都在弹窗内部，父组件只负责提交与切项目。 -->
    <SplitProjectDialog
      v-model:open="splitOpen"
      :project-name="currentProject?.name ?? ''"
      :files="files"
      :busy="splitBusy"
      :error="splitError"
      @submit="submitSplit"
    />

    <!-- 重新 OCR：参数设置弹窗（按当前选中文件生效）。 -->
    <ReconvertDialog
      :open="reconvertOpen"
      :file-name="selectedFile?.name ?? ''"
      :page-count="selectedFile?.page_count ?? 0"
      :busy="reconvertBusy"
      :error="reconvertError"
      @close="reconvertOpen = false"
      @submit="submitReconvert"
    />

    <!-- 项目级自定义快捷键：保存走 PATCH 的 shortcuts_set / shortcuts_unset 增量。 -->
    <ShortcutSettingsDialog
      v-model:open="shortcutOpen"
      :labels="currentProject?.labels ?? []"
      :shortcuts="currentProject?.shortcuts ?? {}"
      :busy="shortcutBusy"
      :error="shortcutError"
      @save="submitShortcuts"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import type { Project, ProjectDictionaryPatch } from '../../types'
import { labelColor, relationColor } from '../../composables/useMarkdownAnnotation'
import { effectiveShortcuts, formatShortcutCompact } from '../../utils/shortcuts'

/**
 * 项目字典卡片：在导入面板之上配置「实体标签 / 关系类型」。
 *
 * 职责边界：
 * - 只维护编辑草稿（labels / relation_types），不负责请求；
 * - 每次增删只 emit 增量（labels_add / labels_remove 等），由父组件串行 PATCH；
 *   绝不提交整份数组，避免多人协作时用旧快照覆盖别人的新增项；
 * - 保存失败不自行回滚草稿，父组件负责把服务端状态同步回项目对象，
 *   避免“用户正在输入时草稿被覆盖”造成的输入丢失。
 * - 标签的快捷键只做**展示**（有效快捷键 = 默认 1–9 + 项目覆盖项），
 *   编辑入口是头部的「快捷键设置」按钮，由独立的设置弹窗负责。
 */
const props = defineProps<{
  project: Project
  status: 'idle' | 'saving' | 'saved' | 'error'
  /** 被正文标注引用、但项目字典中已不存在的标签。 */
  missingLabels?: string[]
  /** 各标签被标注引用的条数，用于删除确认与缺失提示。 */
  usage?: Record<string, number>
  /** 「全部恢复」请求进行中。 */
  restoring?: boolean
  /** 项目级自定义快捷键覆盖项；缺省按 `{}` 处理（老项目没有该字段）。 */
  shortcuts?: Record<string, string>
}>()

const emit = defineEmits<{
  save: [patch: ProjectDictionaryPatch]
  /** 请求父组件调用后端的字典恢复接口，补回被引用但缺失的标签。 */
  restore: []
  /** 打开项目级快捷键设置弹窗。 */
  'edit-shortcuts': []
}>()

type DictionarySection = 'labels' | 'relation_types'

/** 超过该数量时提供「展开全部 / 收起」切换，避免折叠态把标签藏住。 */
const LABEL_COLLAPSE_THRESHOLD = 9

interface DuplicateHint {
  section: DictionarySection
  value: string
}

const labels = ref<string[]>([...props.project.labels])
const relations = ref<string[]>([...props.project.relation_types])

/**
 * 卡片整体折叠态，默认展开。
 *
 * 标签多的项目（24 / 35 个）会让卡片占满侧栏、把文件列表挤没；
 * 折叠只隐藏 .panel-body（v-show，保留 DOM 与草稿），头部与「快捷键设置」按钮仍在，
 * 因此展开/折叠不会重置编辑草稿，也不会打断正在进行的输入。
 */
const collapsed = ref(false)
/** 卡片根节点：折叠时主动移走焦点，避免焦点停留在 display:none 的输入框里。 */
const panelRef = ref<HTMLElement | null>(null)

/** 被引用但字典缺失的标签列表（只读，顺序由服务端决定）。 */
const missingList = computed(() => props.missingLabels ?? [])
/** 标签引用计数；缺失提示与删除确认都从这里取数。 */
const usageMap = computed<Record<string, number>>(() => props.usage ?? {})
const restoring = computed(() => props.restoring === true)

/**
 * 标签的有效快捷键：默认前 9 个标签 1–9，项目覆盖项优先。
 * 没有快捷键的标签（第 10 个之后且未自定义）不显示徽标。
 */
const labelShortcuts = computed(() =>
  effectiveShortcuts(labels.value, props.shortcuts ?? {}),
)

function shortcutBadge(label: string): string {
  return formatShortcutCompact(labelShortcuts.value[label] ?? '')
}

/**
 * 自定义覆盖项数量：只统计「当前字典里真实存在」的覆盖项。
 * 之所以不直接取 Object.keys(shortcuts).length：删掉标签后残留的旧覆盖项
 * 不会生效，把它们算进计数会让「快捷键 · N」与实际可用的自定义键不一致。
 */
const shortcutOverrideCount = computed(() => {
  const overrides = props.shortcuts ?? {}
  return labels.value.filter((label) => {
    const combo = overrides[label]
    return typeof combo === 'string' && combo.trim() !== ''
  }).length
})

function requestShortcutSettings(): void {
  emit('edit-shortcuts')
}

/** 两个分区各自的「展开全部」状态：只有超阈值时才生效。 */
const expanded = reactive<Record<DictionarySection, boolean>>({
  labels: false,
  relation_types: false,
})

/** 同一时间只展开一个分区的编辑态。 */
const activeSection = ref<DictionarySection | null>(null)
/** 两个分区共用同一份输入值（因为只展开一个），切换分区时清空。 */
const inputValue = ref('')
/** 两个分区各持一个模板引用，避免切换时卸载顺序把引用置空。 */
const labelsInputEl = ref<HTMLInputElement | null>(null)
const relationsInputEl = ref<HTMLInputElement | null>(null)
/** 退出编辑后把焦点还给对应分区的「编辑」按钮，避免落到 body。 */
const labelsEditBtn = ref<HTMLButtonElement | null>(null)
const relationsEditBtn = ref<HTMLButtonElement | null>(null)
/** 最近一次发出的增量载荷，供失败后的「重试」原样重发。 */
const lastPatch = ref<ProjectDictionaryPatch | null>(null)
/**
 * 最近一次删除的位置快照：父组件「删除在用标签」确认被取消时，
 * 卡片需要把该项按原位置插回草稿，因此必须记住下标。
 */
const lastRemoval = ref<{ section: DictionarySection; value: string; index: number } | null>(null)

/** 重复项短暂高亮：记录分区 + 值，而不是下标，避免列表变化后错位。 */
const duplicate = ref<DuplicateHint | null>(null)
let duplicateTimer: ReturnType<typeof setTimeout> | null = null

/**
 * 输入法组合状态。仅依赖 event.isComposing 在部分浏览器/输入法的
 * 首次回车并不可靠，因此同时监听 compositionstart / compositionend。
 */
let composing = false

const isEditingLabels = computed(() => activeSection.value === 'labels')
const isEditingRelations = computed(() => activeSection.value === 'relation_types')

const inputPlaceholder = computed(() =>
  isEditingLabels.value ? '输入实体标签，回车添加' : '输入关系类型，回车添加',
)
const inputAriaLabel = computed(() =>
  isEditingLabels.value ? '添加实体标签' : '添加关系类型',
)

/**
 * 重复项的读屏提示。只在当前展开分区的编辑区渲染，
 * 并在 duplicate 计时结束后随 v-if 一起消失。
 */
const duplicateMessage = computed(() => {
  const hint = duplicate.value
  if (!hint || hint.section !== activeSection.value) return ''
  return hint.section === 'labels' ? '已存在同名标签' : '已存在同名关系'
})

function resetFromProject(): void {
  labels.value = [...props.project.labels]
  relations.value = [...props.project.relation_types]
  activeSection.value = null
  inputValue.value = ''
  composing = false
  lastPatch.value = null
  lastRemoval.value = null
  expanded.labels = false
  expanded.relation_types = false
  // 项目切换恢复默认展开，避免上一个项目的折叠态让新项目看起来“没有字典”。
  collapsed.value = false
  clearDuplicate()
}

// 仅当项目切换时重置，避免父组件回写 project.labels 时打断正在进行的编辑。
watch(() => props.project.id, resetFromProject, { immediate: true })

/**
 * 同项目其他标注员新增的字典项同步。
 *
 * 服务端 PATCH 返回合并后的完整字典，父组件据此替换 `project.labels` 引用；
 * 这里必须区分两种状态：
 * - 非编辑态：服务端列表就是权威结果，直接替换本地草稿；
 * - 编辑态：只把服务端新增项追加到草稿末尾，不删除本地项、不打断输入，
 *   否则用户刚输入（尚未落盘）的标签会在回写瞬间消失。
 */
function syncSectionFromServer(section: DictionarySection, serverValues: string[]): void {
  const next = Array.isArray(serverValues) ? serverValues : []
  const draft = section === 'labels' ? labels.value : relations.value
  if (activeSection.value === section) {
    const known = new Set(draft)
    const appended = next.filter((value) => !known.has(value))
    if (appended.length === 0) return
    if (section === 'labels') labels.value = [...draft, ...appended]
    else relations.value = [...draft, ...appended]
    return
  }
  if (section === 'labels') labels.value = [...next]
  else relations.value = [...next]
}

watch(
  () => props.project.labels,
  (next) => syncSectionFromServer('labels', next ?? []),
)
watch(
  () => props.project.relation_types,
  (next) => syncSectionFromServer('relation_types', next ?? []),
)

/** 标签/关系数量回落时收起展开态，避免下次增量直接以“展开”出现。 */
watch(
  () => labels.value.length,
  (count) => {
    if (count <= LABEL_COLLAPSE_THRESHOLD) expanded.labels = false
  },
)
watch(
  () => relations.value.length,
  (count) => {
    if (count <= LABEL_COLLAPSE_THRESHOLD) expanded.relation_types = false
  },
)

/** 分区是否提供「展开全部 / 收起」切换。 */
function canExpand(section: DictionarySection): boolean {
  const count = section === 'labels' ? labels.value.length : relations.value.length
  return count > LABEL_COLLAPSE_THRESHOLD
}

function toggleExpanded(section: DictionarySection): void {
  if (!canExpand(section)) return
  expanded[section] = !expanded[section]
}

/** 折叠态摘要：让用户不展开也能知道字典规模与缺失情况。 */
const collapsedSummary = computed(() => {
  const parts = [`${labels.value.length} 个标签`, `${relations.value.length} 种关系`]
  if (missingList.value.length > 0) parts.push(`${missingList.value.length} 个缺失`)
  return parts.join(' · ')
})

function toggleCollapsed(): void {
  collapsed.value = !collapsed.value
  if (!collapsed.value) return
  // 折叠后输入区不可见：把焦点移到卡片外，避免键盘／读屏停留在隐藏元素上。
  const active = document.activeElement
  if (active instanceof HTMLElement && panelRef.value?.contains(active)) {
    active.blur()
  }
}

/** 缺失标签的 title：带引用条数，便于判断恢复的紧迫程度。 */
function missingTitle(label: string): string {
  const count = usageMap.value[label] ?? 0
  return count > 0 ? `${label} · ${count} 处标注引用` : `${label} · 被标注引用但字典缺失`
}

function requestRestore(): void {
  if (restoring.value) return
  emit('restore')
}

function emitPatch(patch: ProjectDictionaryPatch): void {
  lastPatch.value = patch
  emit('save', patch)
}

function retrySave(): void {
  if (lastPatch.value) emit('save', lastPatch.value)
}

async function focusInput(): Promise<void> {
  await nextTick()
  const target = isEditingLabels.value ? labelsInputEl.value : relationsInputEl.value
  target?.focus()
}

/** 退出编辑后输入框被卸载，焦点必须显式还给该分区的「编辑」按钮。 */
function focusEditButton(section: DictionarySection): void {
  const target = section === 'labels' ? labelsEditBtn.value : relationsEditBtn.value
  target?.focus()
}

function toggleSection(section: DictionarySection): void {
  if (activeSection.value === section) {
    finishEditing()
    return
  }
  activeSection.value = section
  inputValue.value = ''
  composing = false
  void focusInput()
}

function finishEditing(): void {
  const section = activeSection.value
  activeSection.value = null
  inputValue.value = ''
  composing = false
  if (!section) return
  // 等「完成」按钮文案切回「编辑」后再还焦点，避免与卸载补丁竞争。
  void nextTick(() => focusEditButton(section))
}

function onCompositionStart(): void {
  composing = true
}

function onCompositionEnd(): void {
  composing = false
}

function onInputEnter(event: KeyboardEvent): void {
  // 组合期间回车用于确认候选词，不能提交。
  if (composing || event.isComposing) return
  event.preventDefault()
  commitInput()
}

function onInputEscape(event: KeyboardEvent): void {
  if (composing || event.isComposing) return
  event.stopPropagation()
  event.preventDefault()
  finishEditing()
}

/** 卡片级 Esc：焦点落在删除按钮等位置时也能退出编辑。 */
function onSectionEscape(event: KeyboardEvent): void {
  if (!activeSection.value) return
  if (composing || event.isComposing) return
  event.stopPropagation()
  event.preventDefault()
  finishEditing()
}

/* ------------------------------------------------------------------ */
/* 增删                                                                */
/* ------------------------------------------------------------------ */

function commitInput(): void {
  const section = activeSection.value
  if (!section) return

  const value = inputValue.value.trim()
  if (!value) return

  const list = section === 'labels' ? labels.value : relations.value
  if (list.includes(value)) {
    flashDuplicate(section, value)
    return
  }

  // 只发增量：新增项单独走 *_add，服务端做并集，不会覆盖别人的标签。
  if (section === 'labels') {
    labels.value = [...list, value]
    emitPatch({ labels_add: [value] })
  } else {
    relations.value = [...list, value]
    emitPatch({ relation_types_add: [value] })
  }

  inputValue.value = ''
  // 点「＋」时焦点会落到按钮上，提交后拉回输入框便于连续录入。
  void focusInput()
}

function removeItem(section: DictionarySection, value: string): void {
  const list = section === 'labels' ? labels.value : relations.value
  const index = list.indexOf(value)
  if (index >= 0) lastRemoval.value = { section, value, index }

  if (section === 'labels') {
    labels.value = labels.value.filter((item) => item !== value)
    emitPatch({ labels_remove: [value] })
  } else {
    relations.value = relations.value.filter((item) => item !== value)
    emitPatch({ relation_types_remove: [value] })
  }
  // 删除按钮随列表重渲染消失，把焦点交还输入框便于连续增删。
  if (activeSection.value === section) void focusInput()
}

/**
 * 把某项按删除前的位置插回草稿。
 *
 * 供父组件在「删除在用标签」确认被取消时调用：此时父组件尚未发出
 * `labels_remove`，草稿必须与真实字典保持一致，否则用户会看到标签已消失
 * 但项目里仍然存在。
 */
function restoreRemoved(section: DictionarySection, value: string): void {
  const list = section === 'labels' ? labels.value : relations.value
  if (!list.includes(value)) {
    const removal = lastRemoval.value
    const at =
      removal && removal.section === section && removal.value === value
        ? Math.min(Math.max(removal.index, 0), list.length)
        : list.length
    const next = [...list]
    next.splice(at, 0, value)
    if (section === 'labels') labels.value = next
    else relations.value = next
  }
  if (lastRemoval.value?.section === section && lastRemoval.value.value === value) {
    lastRemoval.value = null
  }
  if (activeSection.value === section) void focusInput()
}

defineExpose({ restoreRemoved })

function flashDuplicate(section: DictionarySection, value: string): void {
  duplicate.value = { section, value }
  if (duplicateTimer) clearTimeout(duplicateTimer)
  duplicateTimer = setTimeout(() => {
    duplicate.value = null
    duplicateTimer = null
  }, 900)
}

function clearDuplicate(): void {
  if (duplicateTimer) {
    clearTimeout(duplicateTimer)
    duplicateTimer = null
  }
  duplicate.value = null
}

function isDuplicate(section: DictionarySection, value: string): boolean {
  return duplicate.value?.section === section && duplicate.value.value === value
}

function chipStyle(section: DictionarySection, value: string): Record<string, string> {
  return {
    background:
      section === 'labels'
        ? labelColor(value, labels.value)
        : relationColor(value, relations.value),
  }
}

onBeforeUnmount(() => {
  clearDuplicate()
})
</script>

<template>
  <section
    ref="panelRef"
    class="panel dict-panel"
    :class="{ 'is-expanded': !collapsed && (expanded.labels || expanded.relation_types) }"
    aria-label="标签与关系"
    @keydown.esc="onSectionEscape"
  >
    <header class="panel-head">
      <!-- 折叠按钮放在标题左侧：头部是最稳定的入口，折叠后「快捷键设置」按钮仍保留。 -->
      <button
        type="button"
        class="dict-collapse-btn"
        :aria-expanded="!collapsed"
        aria-controls="dict-panel-body"
        :aria-label="collapsed ? '展开标签与关系' : '收起标签与关系'"
        :title="collapsed ? '展开标签与关系' : '收起标签与关系'"
        @click="toggleCollapsed"
      >
        <svg
          class="dict-collapse-icon"
          :class="{ 'is-collapsed': collapsed }"
          viewBox="0 0 16 16"
          width="12"
          height="12"
          aria-hidden="true"
          focusable="false"
        >
          <path
            d="M4 6.5 8 10.5 12 6.5"
            fill="none"
            stroke="currentColor"
            stroke-width="1.7"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </button>

      <h2 class="panel-title">
        标签与关系
        <span class="panel-title-cn">Dictionary</span>
      </h2>

      <!--
        快捷键是项目级设置：入口放在卡片头部，与字典编辑分开，避免误触改坏字典。
        accent 胶囊 + 键盘图标让它在头部一眼可辨；有自定义覆盖项时附带计数，
        让用户在打开弹窗之前就知道「已经配过几个」。
      -->
      <button
        type="button"
        class="dict-shortcut-btn"
        :title="
          shortcutOverrideCount > 0
            ? `为本项目的标签录制自定义快捷键（已自定义 ${shortcutOverrideCount} 个）`
            : '为本项目的标签录制自定义快捷键'
        "
        @click="requestShortcutSettings"
      >
        <svg
          class="dict-shortcut-icon"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="1.3"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
          focusable="false"
        >
          <rect x="1.8" y="4.2" width="12.4" height="7.6" rx="1.6" />
          <path d="M4.2 6.6h.01M6.4 6.6h.01M8.6 6.6h.01M10.8 6.6h.01M4.2 8.8h.01M11.8 8.8h.01" />
          <path d="M6 9.4h4" />
        </svg>
        <span class="dict-shortcut-text">快捷键设置</span>
        <span v-if="shortcutOverrideCount > 0" class="dict-shortcut-count">
          · {{ shortcutOverrideCount }}
        </span>
      </button>

      <div class="dict-status">
        <!-- live region 只承载状态文本，「重试」是可交互控件，必须放在其外。 -->
        <span class="dict-status-live" role="status" aria-live="polite">
          <span v-if="status === 'saving'" class="dict-status-text is-saving">保存中…</span>
          <span v-else-if="status === 'saved'" class="dict-status-text is-saved">已保存</span>
          <span v-else-if="status === 'error'" class="dict-status-text is-error">保存失败</span>
        </span>
        <button
          v-if="status === 'error' && lastPatch"
          type="button"
          class="dict-retry"
          title="重新提交最近一次修改"
          @click="retrySave"
        >
          重试
        </button>
      </div>
    </header>

    <!-- 折叠态摘要：不展开也能看到规模与缺失，避免“折叠=不知道有什么”。 -->
    <p v-if="collapsed" class="dict-summary">{{ collapsedSummary }}</p>

    <div v-show="!collapsed" id="dict-panel-body" class="panel-body">
      <!-- 实体标签 -->
      <section class="dict-section">
        <div class="dict-section-head">
          <div class="dict-section-title">
            <h3 class="dict-section-name">实体标签</h3>
            <span class="dict-count">{{ labels.length }} 个</span>
          </div>
          <button
            ref="labelsEditBtn"
            type="button"
            class="dict-edit-btn"
            :aria-expanded="isEditingLabels"
            aria-controls="dict-labels-chips"
            @click="toggleSection('labels')"
          >
            {{ isEditingLabels ? '完成' : '编辑' }}
          </button>
        </div>

        <div
          id="dict-labels-chips"
          class="dict-chip-row"
          :class="{ 'is-expanded': expanded.labels }"
        >
          <span
            v-for="label in labels"
            :key="label"
            class="dict-chip"
            :class="{ 'is-duplicate': isDuplicate('labels', label) }"
            :style="chipStyle('labels', label)"
            :title="label"
          >
            <span
              v-if="shortcutBadge(label)"
              class="dict-chip-key"
              :class="{ 'is-combo': shortcutBadge(label).length > 1 }"
              :title="`快捷键：${shortcutBadge(label)}`"
            >{{ shortcutBadge(label) }}</span>
            <span class="dict-chip-text">{{ label }}</span>
            <button
              v-if="isEditingLabels"
              type="button"
              class="dict-chip-remove"
              :aria-label="`删除标签 ${label}`"
              :title="`删除标签 ${label}`"
              @click="removeItem('labels', label)"
            >
              ×
            </button>
          </span>
          <span v-if="labels.length === 0" class="dict-empty">尚未配置实体标签</span>
        </div>

        <button
          v-if="canExpand('labels')"
          type="button"
          class="dict-expand-btn"
          :aria-expanded="expanded.labels"
          aria-controls="dict-labels-chips"
          :title="expanded.labels ? '收起标签列表' : '展开显示全部标签'"
          @click="toggleExpanded('labels')"
        >
          {{ expanded.labels ? '收起' : `展开全部 ${labels.length} 个` }}
        </button>

        <div v-if="isEditingLabels" class="dict-add-row">
          <input
            ref="labelsInputEl"
            v-model="inputValue"
            class="mx-input dict-input"
            type="text"
            maxlength="200"
            :placeholder="inputPlaceholder"
            :aria-label="inputAriaLabel"
            :aria-invalid="Boolean(duplicateMessage)"
            :aria-describedby="duplicateMessage ? 'dict-labels-dup' : undefined"
            autocomplete="off"
            @keydown.enter="onInputEnter"
            @keydown.esc="onInputEscape"
            @compositionstart="onCompositionStart"
            @compositionend="onCompositionEnd"
          />
          <button
            type="button"
            class="mx-btn dict-add-btn"
            :aria-label="inputAriaLabel"
            title="添加"
            @click="commitInput"
          >
            ＋
          </button>
        </div>
        <p
          v-if="duplicateMessage"
          id="dict-labels-dup"
          class="dict-duplicate-hint"
          role="status"
        >
          {{ duplicateMessage }}
        </p>
      </section>

      <!-- 字典缺失：被正文引用、但已从字典中消失的标签，提供一键补回 -->
      <section v-if="missingList.length > 0" class="dict-section dict-missing">
        <div class="dict-section-head">
          <div class="dict-section-title">
            <h3 class="dict-section-name">字典缺失</h3>
            <span class="dict-count">{{ missingList.length }} 个</span>
          </div>
          <button
            type="button"
            class="dict-restore-btn"
            :disabled="restoring"
            :aria-busy="restoring"
            title="把这些标签补回项目字典，正文中已有的标注会立即恢复标签名与颜色"
            @click="requestRestore"
          >
            {{ restoring ? '恢复中…' : '全部恢复' }}
          </button>
        </div>

        <div class="dict-chip-row">
          <span
            v-for="label in missingList"
            :key="label"
            class="dict-chip is-missing"
            :title="missingTitle(label)"
          >
            <span class="dict-chip-text">{{ label }}</span>
            <span v-if="usageMap[label]" class="dict-chip-usage">{{ usageMap[label] }}</span>
          </span>
        </div>

        <p class="dict-missing-hint" role="status" aria-live="polite">
          这些标签仍被正文标注引用；恢复后即可正常显示标签名与颜色。
        </p>
      </section>

      <!-- 关系类型 -->
      <section class="dict-section">
        <div class="dict-section-head">
          <div class="dict-section-title">
            <h3 class="dict-section-name">关系类型</h3>
            <span class="dict-count">{{ relations.length }} 种</span>
          </div>
          <button
            ref="relationsEditBtn"
            type="button"
            class="dict-edit-btn"
            :aria-expanded="isEditingRelations"
            aria-controls="dict-relations-chips"
            @click="toggleSection('relation_types')"
          >
            {{ isEditingRelations ? '完成' : '编辑' }}
          </button>
        </div>

        <div
          id="dict-relations-chips"
          class="dict-chip-row"
          :class="{ 'is-expanded': expanded.relation_types }"
        >
          <span
            v-for="type in relations"
            :key="type"
            class="dict-chip is-relation"
            :class="{ 'is-duplicate': isDuplicate('relation_types', type) }"
            :style="chipStyle('relation_types', type)"
            :title="type"
          >
            <span class="dict-chip-text">{{ type }}</span>
            <button
              v-if="isEditingRelations"
              type="button"
              class="dict-chip-remove"
              :aria-label="`删除关系 ${type}`"
              :title="`删除关系 ${type}`"
              @click="removeItem('relation_types', type)"
            >
              ×
            </button>
          </span>
          <span v-if="relations.length === 0" class="dict-empty">尚未配置关系类型</span>
        </div>

        <button
          v-if="canExpand('relation_types')"
          type="button"
          class="dict-expand-btn"
          :aria-expanded="expanded.relation_types"
          aria-controls="dict-relations-chips"
          :title="expanded.relation_types ? '收起关系列表' : '展开显示全部关系'"
          @click="toggleExpanded('relation_types')"
        >
          {{ expanded.relation_types ? '收起' : `展开全部 ${relations.length} 个` }}
        </button>

        <div v-if="isEditingRelations" class="dict-add-row">
          <input
            ref="relationsInputEl"
            v-model="inputValue"
            class="mx-input dict-input"
            type="text"
            maxlength="200"
            :placeholder="inputPlaceholder"
            :aria-label="inputAriaLabel"
            :aria-invalid="Boolean(duplicateMessage)"
            :aria-describedby="duplicateMessage ? 'dict-relations-dup' : undefined"
            autocomplete="off"
            @keydown.enter="onInputEnter"
            @keydown.esc="onInputEscape"
            @compositionstart="onCompositionStart"
            @compositionend="onCompositionEnd"
          />
          <button
            type="button"
            class="mx-btn dict-add-btn"
            :aria-label="inputAriaLabel"
            title="添加"
            @click="commitInput"
          >
            ＋
          </button>
        </div>
        <p
          v-if="duplicateMessage"
          id="dict-relations-dup"
          class="dict-duplicate-hint"
          role="status"
        >
          {{ duplicateMessage }}
        </p>
      </section>
    </div>
  </section>
</template>

<style scoped>
/* ---------- 折叠按钮 ---------- */
/* chevron 放在标题左侧：折叠后头部仍是可点击、可读的稳定入口。 */
.dict-collapse-btn {
  display: inline-grid;
  place-items: center;
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 5px;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  transition:
    background-color 160ms var(--ease-out),
    border-color 160ms var(--ease-out),
    color 160ms var(--ease-out);
}

.dict-collapse-btn:hover {
  border-color: var(--line);
  background: var(--surface-sunken);
  color: var(--ink);
}

.dict-collapse-btn:focus-visible {
  outline: 2px solid var(--signal);
  outline-offset: 1px;
}

.dict-collapse-icon {
  transition: transform 160ms var(--ease-out);
}

/* 展开时朝下，折叠时转 90° 指向右侧。 */
.dict-collapse-icon.is-collapsed {
  transform: rotate(-90deg);
}

/*
 * 头部在 330px 侧栏内必须保持单行：标题可压缩，按钮不参与换行，
 * 否则“折叠 + 快捷键 + 保存状态”会把标题挤成两行。
 */
.dict-panel .panel-head {
  gap: 6px;
}

.dict-panel .panel-title {
  flex: 1 1 auto;
  flex-wrap: nowrap;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.dict-panel .panel-title-cn {
  flex-shrink: 0;
}

/* ---------- 折叠摘要 ---------- */
.dict-summary {
  margin: 0;
  padding: 0 16px 12px;
  font-size: 10.5px;
  line-height: 1.45;
  color: var(--ink-4);
  font-variant-numeric: tabular-nums;
}

/* ---------- 头部状态 ---------- */
/* 头部现在有三个块（标题 / 快捷键按钮 / 保存状态），用 margin-left:auto 保持状态贴右。 */
.dict-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  min-height: 16px;
  margin-left: auto;
}

/*
 * 「快捷键」入口：accent 胶囊按钮。
 *
 * 原来的灰色描边按钮混在头部三个元素（折叠 / 标题 / 状态）之间几乎不可见，
 * 用户根本找不到「给标签改快捷键」的入口。改为浅橙底 + 橙字 + 键盘图标，
 * 高度仍压到 24px、字号 10px，保证 330px 侧栏头部不换行。
 */
.dict-shortcut-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  flex-shrink: 0;
  height: 24px;
  padding: 0 7px;
  border: 1px solid rgba(228, 87, 46, .35);
  border-radius: 999px;
  background: var(--signal-soft);
  color: var(--signal-deep);
  font-family: inherit;
  font-size: 10px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
  transition:
    background-color 160ms var(--ease-out),
    border-color 160ms var(--ease-out),
    color 160ms var(--ease-out),
    box-shadow 160ms var(--ease-out);
}

.dict-shortcut-icon {
  width: 14px;
  height: 14px;
  flex: 0 0 auto;
}

.dict-shortcut-btn:hover {
  border-color: var(--signal);
  background: #F7DACF;
  color: var(--signal-ink);
  box-shadow: 0 6px 14px -12px rgba(228, 87, 46, .6);
}

.dict-shortcut-btn:focus-visible {
  outline: none;
  border-color: var(--signal);
  box-shadow: 0 0 0 3px rgba(228, 87, 46, .22);
}

/* 计数只做数量提示，用更深的字色区分「文案」与「数字」。 */
.dict-shortcut-count {
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--signal-ink);
}

/* live region 与「重试」按钮分离，文本区域自身保持行内布局。 */
.dict-status-live {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 16px;
}

.dict-status-text {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  font-weight: 500;
  line-height: 1.2;
  white-space: nowrap;
  color: var(--ink-4);
}

.dict-status-text::before {
  content: '';
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  opacity: .8;
}

.dict-status-text.is-saving {
  color: var(--ink-3);
}

.dict-status-text.is-saved {
  color: var(--success);
}

.dict-status-text.is-error {
  color: var(--danger);
}

.dict-retry {
  flex-shrink: 0;
  height: 18px;
  padding: 0 6px;
  border: 1px solid rgba(181, 64, 58, .28);
  border-radius: 999px;
  background: var(--danger-bg);
  color: var(--danger);
  font-size: 10px;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
  transition:
    background-color 160ms var(--ease-out),
    border-color 160ms var(--ease-out);
}

.dict-retry:hover {
  background: #F5DFDC;
  border-color: rgba(181, 64, 58, .5);
}

/* ---------- 分区 ---------- */
.dict-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.dict-section + .dict-section {
  padding-top: 9px;
  border-top: 1px dashed var(--line);
}

.dict-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.dict-section-title {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}

.dict-section-name {
  margin: 0;
  font-size: 11.5px;
  font-weight: 600;
  line-height: 1.2;
  color: var(--ink-2);
}

.dict-count {
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 400;
  font-variant-numeric: tabular-nums;
  color: var(--ink-4);
  white-space: nowrap;
}

.dict-edit-btn {
  flex-shrink: 0;
  height: 22px;
  padding: 0 7px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--ink-3);
  font-size: 10.5px;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
  transition:
    background-color 160ms var(--ease-out),
    border-color 160ms var(--ease-out),
    color 160ms var(--ease-out);
}

.dict-edit-btn:hover {
  background: var(--surface-sunken);
  border-color: var(--line);
  color: var(--ink);
}

.dict-edit-btn[aria-expanded='true'] {
  background: var(--signal-soft);
  border-color: transparent;
  color: var(--signal-deep);
}

/* ---------- 标签块 ---------- */
/* 折叠态最多约 3 行；展开态完全展示，由侧栏整体滚动，不在卡片内部裁切。 */
.dict-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  min-width: 0;
  max-height: 112px;
  overflow-y: auto;
  padding-right: 2px;
}

.dict-chip-row.is-expanded {
  max-height: none;
  overflow: visible;
}

/* 展开全部 / 收起：只在超出阈值时出现，避免常驻干扰。 */
.dict-expand-btn {
  align-self: flex-start;
  height: 20px;
  padding: 0 2px;
  border: 0;
  background: transparent;
  color: var(--signal-deep);
  font-size: 10.5px;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.dict-expand-btn:hover {
  color: var(--ink);
}

/* ---------- 字典缺失 ---------- */
.dict-missing .dict-section-name {
  color: var(--warning);
}

.dict-restore-btn {
  flex-shrink: 0;
  height: 22px;
  padding: 0 8px;
  border: 1px solid rgba(169, 118, 30, .3);
  border-radius: 999px;
  background: var(--warning-bg, #FAF2E1);
  color: var(--warning);
  font-size: 10.5px;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
  transition:
    background-color 160ms var(--ease-out),
    border-color 160ms var(--ease-out);
}

.dict-restore-btn:hover:not(:disabled) {
  border-color: rgba(169, 118, 30, .55);
  background: #F6E9CC;
}

.dict-restore-btn:disabled {
  opacity: .6;
  cursor: not-allowed;
}

/* 缺失项用虚线灰 chip 表达“存在但不可用”，与正常标签形成对比。 */
.dict-chip.is-missing {
  border: 1px dashed rgba(154, 157, 163, .85);
  background: transparent;
  color: var(--ink-3);
}

.dict-chip-usage {
  flex-shrink: 0;
  padding: 0 4px;
  border-radius: 999px;
  background: rgba(23, 24, 27, .06);
  color: var(--ink-4);
  font-family: var(--font-mono);
  font-size: 9px;
  font-variant-numeric: tabular-nums;
  line-height: 1.5;
}

.dict-missing-hint {
  margin: 0;
  font-size: 10px;
  line-height: 1.5;
  color: var(--ink-4);
}

.dict-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  min-height: 23px;
  padding: 3px 7px;
  border: 1px solid rgba(23, 24, 27, .16);
  border-radius: 7px;
  color: var(--ink);
  font-size: 11px;
  font-weight: 500;
  line-height: 1.25;
  transition:
    box-shadow 180ms var(--ease-out),
    border-color 180ms var(--ease-out);
}

.dict-chip.is-relation {
  color: #FFFDF9;
  border-color: rgba(23, 24, 27, .22);
}

.dict-chip.is-duplicate {
  border-color: var(--signal);
  animation: dict-chip-flash 700ms var(--ease-out);
}

@keyframes dict-chip-flash {
  0% { box-shadow: 0 0 0 0 rgba(228, 87, 46, .55); }
  40% { box-shadow: 0 0 0 3px rgba(228, 87, 46, .28); }
  100% { box-shadow: 0 0 0 0 rgba(228, 87, 46, 0); }
}

.dict-chip-text {
  min-width: 0;
  overflow-wrap: anywhere;
}

/*
 * 快捷键徽标：默认数字 1–9 只有 1 个字符；自定义组合键可能很长
 * （如 Alt+Shift+P、Ctrl+Alt+Shift+K），这里限宽省略，避免把 chip 撑爆。
 *
 * 对比度：原来半透明白在浅色 chip 上几乎看不见，改为近乎实白 + 细描边 + 600 字重；
 * 自定义组合键用 signal-soft 底色，和「默认数字键」在视觉上分层，
 * 但尺寸仍受 max-width 约束，不会把 chip 拉宽。
 */
.dict-chip-key {
  flex-shrink: 0;
  max-width: 76px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 0 3px;
  border: 1px solid rgba(23, 24, 27, .1);
  border-radius: 3px;
  background: rgba(255, 255, 255, .92);
  color: var(--ink-2);
  font-family: var(--font-mono);
  font-size: 8.5px;
  font-weight: 600;
  line-height: 1.5;
}

.dict-chip-key.is-combo {
  border-color: rgba(228, 87, 46, .28);
  background: var(--signal-soft);
  color: var(--signal-ink);
  letter-spacing: -.02em;
}

/* 关系 chip 是深色底：白描边 + 半透明白底，保持与实体 chip 同样的“可读优先”。 */
.dict-chip.is-relation .dict-chip-key {
  border-color: rgba(255, 253, 249, .3);
  background: rgba(255, 255, 255, .22);
  color: rgba(255, 253, 249, .95);
}

.dict-chip-remove {
  display: inline-grid;
  place-items: center;
  flex-shrink: 0;
  width: 14px;
  height: 14px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: rgba(255, 255, 255, .55);
  color: var(--ink-2);
  font-size: 11px;
  line-height: 1;
  cursor: pointer;
  transition:
    background-color 160ms var(--ease-out),
    color 160ms var(--ease-out);
}

.dict-chip-remove:hover {
  background: rgba(255, 255, 255, .9);
  color: var(--danger);
}

.dict-chip.is-relation .dict-chip-remove {
  background: rgba(255, 255, 255, .18);
  color: rgba(255, 253, 249, .9);
}

.dict-chip.is-relation .dict-chip-remove:hover {
  background: rgba(255, 255, 255, .35);
  color: #FFFDF9;
}

.dict-empty {
  padding: 2px 0;
  font-size: 10.5px;
  line-height: 1.4;
  color: var(--ink-4);
}

/* ---------- 添加行 ---------- */
.dict-add-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.dict-add-row .dict-input {
  flex: 1 1 auto;
  width: auto;
  min-width: 0;
  height: 28px;
  padding: 0 8px;
  font-size: 11.5px;
}

.dict-add-row .dict-add-btn {
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  padding: 0;
  border-radius: var(--radius-sm);
  font-size: 15px;
  line-height: 1;
}

/* 重复项被拦截时同步输入框边框与读屏提示，避免只靠颜色闪烁传达。 */
.dict-add-row .dict-input[aria-invalid='true'] {
  border-color: var(--warning);
}

.dict-duplicate-hint {
  margin: 0;
  font-size: 10.5px;
  line-height: 1.4;
  color: var(--warning);
}

@media (prefers-reduced-motion: reduce) {
  .dict-chip.is-duplicate {
    animation: none;
    box-shadow: 0 0 0 2px rgba(228, 87, 46, .28);
  }
}
</style>


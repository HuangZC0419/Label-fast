<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Project } from '../../types'

/**
 * 导出 Excel 表单弹窗：选择一个或多个项目，由后端汇总标注明细并下载 xlsx。
 *
 * 与 ProjectSettingsDialog 保持同一套弹窗约定：
 * - 不使用 <Teleport>，就地渲染以继承 `.mx-root` 的主题令牌与 `.mx-modal` 样式；
 * - Escape 关闭、Tab 焦点陷阱、打开时聚焦、关闭后把焦点还给触发元素；
 * - busy 期间锁定所有会改变选择或关闭弹窗的入口，避免在途请求被“取消感”误导。
 *
 * 组件不发起请求，只维护选择草稿；下载由父组件执行，失败信息通过 `error` 回传就地展示。
 */
const props = defineProps<{
  open: boolean
  /** 全量项目列表（顶栏同源数据），弹窗内不自行请求。 */
  projects: Project[]
  /** 默认勾选项：打开弹窗时选中当前项目，减少最常见的单项目导出操作。 */
  currentProjectId: string | null
  /** 正在生成下载；期间禁用一切交互并切换主按钮文案。 */
  busy: boolean
  /** 后端错误，弹窗内就地展示，避免被遮罩后的全局提示吞没。 */
  error?: string
}>()

const emit = defineEmits<{
  'update:open': [open: boolean]
  submit: [projectIds: string[]]
}>()

const dialogRef = ref<HTMLElement | null>(null)
const listRef = ref<HTMLElement | null>(null)
const cancelRef = ref<HTMLButtonElement | null>(null)
/** 已选项目 id；用数组配合复选框的 value 绑定，避免手写 Set 的响应式细节。 */
const selectedIds = ref<string[]>([])
let restoreFocus: HTMLElement | null = null

const FOCUSABLE =
  'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'

const allIds = computed(() => props.projects.map((project) => project.id))
/** 只统计仍存在于列表中的 id：项目列表在弹窗打开期间刷新时不至于虚高。 */
const selectedCount = computed(() => {
  const valid = new Set(allIds.value)
  return selectedIds.value.filter((id) => valid.has(id)).length
})
const hasProjects = computed(() => props.projects.length > 0)
const canSubmit = computed(
  () => hasProjects.value && selectedCount.value > 0 && !props.busy,
)

/** 打开时的默认选择：当前项目；当前项目为空或已不在列表中则从零开始。 */
function defaultSelection(): string[] {
  const id = props.currentProjectId
  if (!id) return []
  return allIds.value.includes(id) ? [id] : []
}

function close(): void {
  if (props.busy) return
  emit('update:open', false)
}

function selectAll(): void {
  if (props.busy) return
  selectedIds.value = [...allIds.value]
}

function clearAll(): void {
  if (props.busy) return
  selectedIds.value = []
}

function submit(): void {
  if (!canSubmit.value) return
  // 以当前项目列表为准过滤，避免列表在弹窗打开期间变化后残留失效 id。
  const valid = new Set(allIds.value)
  const ids = selectedIds.value.filter((id) => valid.has(id))
  if (ids.length === 0) return
  emit('submit', ids)
}

function labelCount(project: Project): number {
  return Array.isArray(project.labels) ? project.labels.length : 0
}

/** 把焦点放到第一个项目复选框；无可选项时退到取消按钮 / 弹窗本体。 */
function focusInitial(): void {
  const firstCheckbox = listRef.value?.querySelector<HTMLInputElement>(
    'input[type="checkbox"]',
  )
  ;(firstCheckbox ?? cancelRef.value ?? dialogRef.value)?.focus()
}

watch(
  () => props.open,
  async (open) => {
    if (!open) {
      if (restoreFocus?.isConnected) restoreFocus.focus()
      restoreFocus = null
      return
    }
    // 每次打开都重置为默认选择，避免上一次的勾选状态被误继承。
    selectedIds.value = defaultSelection()
    restoreFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    focusInitial()
  },
)

// 兼容「挂载即打开」的用法：watch 只在变化时触发，首次渲染需自行初始化选择与焦点。
onMounted(async () => {
  if (!props.open) return
  selectedIds.value = defaultSelection()
  await nextTick()
  focusInitial()
})

function onKeydown(event: KeyboardEvent): void {
  if (!props.open) return

  if (event.key === 'Escape') {
    close()
    return
  }

  // 弹窗打开期间屏蔽全局 Ctrl+S，避免在背景触发标注保存。
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault()
    return
  }

  if (event.key !== 'Tab' || !dialogRef.value) return
  const focusable = dialogRef.value.querySelectorAll<HTMLElement>(FOCUSABLE)
  if (focusable.length === 0) {
    event.preventDefault()
    dialogRef.value.focus()
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

// 捕获阶段监听：不依赖与工作区全局快捷键的注册顺序。
onMounted(() => window.addEventListener('keydown', onKeydown, true))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown, true))
</script>

<template>
  <div v-if="open" class="mx-modal-backdrop" @click.self="close">
    <section
      ref="dialogRef"
      class="mx-modal eed-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="eed-title"
      aria-describedby="eed-desc"
      tabindex="-1"
    >
      <header class="eed-head">
        <h2 id="eed-title" class="eed-title">导出 Excel 表单</h2>
        <button
          type="button"
          class="eed-close"
          aria-label="关闭"
          :disabled="busy"
          @click="close"
        >
          ×
        </button>
      </header>

      <div class="eed-body">
        <p id="eed-desc" class="eed-desc">
          选择要导出的项目，可多选；导出的 Excel 为「标注明细」表，每个知识 / 每张图表一行，并附合计行。
        </p>

        <div class="eed-toolbar">
          <span class="eed-count">
            已选 <strong>{{ selectedCount }}</strong> / {{ projects.length }}
          </span>
          <div class="eed-toolbar-actions">
            <button
              type="button"
              class="eed-link"
              :disabled="busy || !hasProjects || selectedCount === projects.length"
              @click="selectAll"
            >
              全选
            </button>
            <button
              type="button"
              class="eed-link"
              :disabled="busy || selectedCount === 0"
              @click="clearAll"
            >
              清空
            </button>
          </div>
        </div>

        <div v-if="hasProjects" ref="listRef" class="eed-list">
          <label
            v-for="project in projects"
            :key="project.id"
            class="eed-item"
            :class="{ 'is-disabled': busy }"
          >
            <input
              v-model="selectedIds"
              type="checkbox"
              class="eed-check"
              :value="project.id"
              :disabled="busy"
            />
            <span class="eed-name" :title="project.name">{{ project.name }}</span>
            <span class="eed-meta">{{ labelCount(project) }} 个标签</span>
          </label>
        </div>
        <p v-else class="eed-empty">还没有项目</p>
      </div>

      <p v-if="error" class="eed-error" role="alert">{{ error }}</p>

      <footer class="eed-actions">
        <button
          ref="cancelRef"
          type="button"
          class="mx-btn btn-ghost"
          :disabled="busy"
          @click="close"
        >
          取消
        </button>
        <button
          type="button"
          class="mx-btn mx-btn-primary"
          :disabled="!canSubmit"
          @click="submit"
        >
          {{ busy ? '正在生成…' : `导出（${selectedCount} 个项目）` }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.eed-dialog {
  width: min(460px, 100%);
}

.eed-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 16px 18px 10px;
}

.eed-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink);
}

.eed-close {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--ink-4);
  font-size: 17px;
  line-height: 1;
  cursor: pointer;
}

.eed-close:hover:not(:disabled) {
  background: var(--surface-sunken);
  color: var(--ink-2);
}

.eed-close:disabled {
  opacity: .45;
  cursor: not-allowed;
}

.eed-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 2px 18px 16px;
  min-width: 0;
}

.eed-desc {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.65;
  color: var(--ink-4);
}

/* 选择工具条：左侧计数、右侧文字动作，与列表保持同一视觉节奏。 */
.eed-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-top: 4px;
  border-top: 1px dashed var(--line);
}

.eed-count {
  font-size: 11.5px;
  color: var(--ink-3);
}

.eed-count strong {
  font-weight: 600;
  color: var(--ink);
}

.eed-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.eed-link {
  height: 26px;
  padding: 0 8px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--ink-3);
  font-size: 11.5px;
  cursor: pointer;
  transition: background-color 140ms var(--ease-out), color 140ms var(--ease-out);
}

.eed-link:hover:not(:disabled) {
  background: var(--surface-sunken);
  color: var(--ink);
}

.eed-link:disabled {
  opacity: .4;
  cursor: not-allowed;
}

/* 列表限高：项目多时内部滚动，弹窗整体不撑破视口。 */
.eed-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 280px;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 2px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface-raised);
}

.eed-item {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  height: 32px;
  padding: 0 8px;
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.eed-item:hover {
  background: var(--surface-sunken);
}

.eed-item.is-disabled {
  cursor: not-allowed;
  opacity: .6;
}

.eed-check {
  width: 14px;
  height: 14px;
  flex: 0 0 auto;
  margin: 0;
  accent-color: var(--signal-deep);
  cursor: inherit;
}

.eed-name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--ink-2);
}

.eed-meta {
  flex: 0 0 auto;
  font-size: 10.5px;
  color: var(--ink-4);
  white-space: nowrap;
}

.eed-empty {
  margin: 0;
  padding: 26px 10px;
  border: 1px dashed var(--line);
  border-radius: var(--radius);
  text-align: center;
  font-size: 11.5px;
  color: var(--ink-4);
}

.eed-error {
  margin: 0;
  padding: 8px 18px;
  border-top: 1px solid rgba(181, 64, 58, .2);
  background: var(--danger-bg);
  color: var(--danger);
  font-size: 11.5px;
  line-height: 1.5;
}

.eed-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 18px 16px;
  border-top: 1px solid var(--line);
}
</style>

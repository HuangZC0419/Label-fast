<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { Project } from '../../types'

/**
 * 顶栏「项目切换器」：项目列表切换 + 面板内新建项目入口。
 * 项目设置 / 删除项目由顶栏独立的「设置」菜单负责，不在此处承载。
 *
 * 设计要点：
 * - 面板就地渲染（不使用 Teleport），以继承 `.mx-root` 下的设计令牌与动画；
 * - 本组件只负责交互与展示，不持有项目数据，状态全部来自父级；
 * - 页面中仅有一个实例，因此面板 id 使用常量即可，无需 `useId`。
 */
const props = defineProps<{
  projects: Project[]
  currentProject: Project | null
  /** 批量导入/保存期间锁定项目切换，避免写入错误项目。 */
  projectSwitchDisabled?: boolean
}>()

const emit = defineEmits<{
  'select-project': [id: string]
  create: []
}>()

/** 面板固定 id，供 aria-controls 引用（页面上只渲染一个切换器）。 */
const PANEL_ID = 'project-switch-panel'

const open = ref(false)
const rootRef = ref<HTMLElement | null>(null)
const triggerRef = ref<HTMLButtonElement | null>(null)
const panelRef = ref<HTMLElement | null>(null)

/* ------------------------------------------------------------------ */
/* 焦点管理                                                            */
/* ------------------------------------------------------------------ */

/** 收集面板内所有可聚焦条目（项目条目 + 新建项目），跳过 disabled。 */
function getFocusableItems(): HTMLElement[] {
  const panel = panelRef.value
  if (!panel) return []
  return Array.from(panel.querySelectorAll<HTMLElement>('[data-switch-item]:not(:disabled)'))
}

/** 打开后把焦点落在当前项目上；没有当前项目就落第一项，没有项目则落到「新建项目」。 */
function focusInitialItem(): void {
  const items = getFocusableItems()
  if (!items.length) return
  const checked = panelRef.value?.querySelector<HTMLElement>(
    '[data-switch-item][aria-checked="true"]:not(:disabled)',
  )
  ;(checked ?? items[0])?.focus()
}

/* ------------------------------------------------------------------ */
/* 开合与关闭                                                          */
/* ------------------------------------------------------------------ */

function openPanel(): void {
  if (props.projectSwitchDisabled) return
  open.value = true
  void nextTick(focusInitialItem)
}

function closePanel(returnFocus = false): void {
  if (!open.value) return
  open.value = false
  if (returnFocus) {
    // 面板随 open 卸载，先把焦点交还触发器，弹窗关闭后仍能回到原处。
    void nextTick(() => triggerRef.value?.focus())
  }
}

function togglePanel(): void {
  if (props.projectSwitchDisabled) return
  if (open.value) closePanel()
  else openPanel()
}

function onDocumentPointerDown(event: PointerEvent): void {
  if (!open.value) return
  const target = event.target as Node | null
  if (target && rootRef.value?.contains(target)) return
  closePanel()
}

// 仅在展开时监听文档点击，避免常驻全局事件。
watch(open, (value) => {
  if (value) document.addEventListener('pointerdown', onDocumentPointerDown)
  else document.removeEventListener('pointerdown', onDocumentPointerDown)
})

// 批量操作开始后立即收起面板，避免用户继续切换项目。
watch(
  () => props.projectSwitchDisabled,
  (disabled) => {
    if (disabled && open.value) closePanel()
  },
)

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
})

/* ------------------------------------------------------------------ */
/* 键盘交互                                                            */
/* ------------------------------------------------------------------ */

function onRootKeydown(event: KeyboardEvent): void {
  if (!open.value) return

  if (event.key === 'Escape') {
    event.preventDefault()
    closePanel(true)
    return
  }

  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return

  const items = getFocusableItems()
  if (!items.length) return

  event.preventDefault()
  const currentIndex = items.indexOf(document.activeElement as HTMLElement)

  if (event.key === 'Home') {
    items[0].focus()
    return
  }
  if (event.key === 'End') {
    items[items.length - 1].focus()
    return
  }
  if (currentIndex < 0) {
    items[0].focus()
    return
  }
  const delta = event.key === 'ArrowDown' ? 1 : -1
  items[(currentIndex + delta + items.length) % items.length].focus()
}

/** Tab 把焦点移出组件时收起面板（不抢回焦点，符合浏览器默认行为）。 */
function onRootFocusOut(event: FocusEvent): void {
  if (!open.value) return
  const next = event.relatedTarget as Node | null
  if (!next) return
  if (rootRef.value?.contains(next)) return
  closePanel()
}

/* ------------------------------------------------------------------ */
/* 操作                                                                */
/* ------------------------------------------------------------------ */

function selectProject(id: string): void {
  const isSame = props.currentProject?.id === id
  closePanel(true)
  // 切到同一项目时只关闭面板，不重复触发父级加载。
  if (!isSame) emit('select-project', id)
}

/** 面板内「新建项目」入口：先收起面板，再把焦点交还触发器。 */
function createProject(): void {
  closePanel(true)
  emit('create')
}
</script>

<template>
  <div
    ref="rootRef"
    class="project-switch"
    @keydown="onRootKeydown"
    @focusout="onRootFocusOut"
  >
    <button
      ref="triggerRef"
      type="button"
      class="project-switch-trigger"
      :class="{ 'is-open': open }"
      :disabled="projectSwitchDisabled"
      :title="
        projectSwitchDisabled ? '当前操作进行中，暂时无法切换项目' : '切换或新建项目'
      "
      aria-haspopup="menu"
      :aria-expanded="open"
      :aria-controls="PANEL_ID"
      @click="togglePanel"
    >
      <span class="project-switch-label">
        <span class="project-switch-eyebrow">当前项目</span>
        <span class="project-switch-name">{{ currentProject?.name ?? '未选择项目' }}</span>
      </span>
      <svg
        class="project-switch-chevron"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path d="m4.5 6.5 3.5 3.5 3.5-3.5" />
      </svg>
    </button>

    <div
      v-if="open"
      :id="PANEL_ID"
      ref="panelRef"
      class="project-switch-panel"
      role="menu"
      aria-label="项目切换"
    >
      <!-- 包裹层用 presentation，避免 menu 内出现非 menuitem 的可访问节点。 -->
      <div class="project-switch-caption" role="presentation">
        <span>全部项目</span>
        <span class="project-switch-count">{{ projects.length }}</span>
      </div>

      <div class="project-switch-list" role="presentation">
        <button
          v-for="project in projects"
          :key="project.id"
          type="button"
          role="menuitemradio"
          data-switch-item
          class="project-switch-item"
          :class="{ 'is-active': project.id === currentProject?.id }"
          :aria-checked="project.id === currentProject?.id"
          @click="selectProject(project.id)"
        >
          <span class="project-switch-item-name">{{ project.name }}</span>
          <svg
            v-if="project.id === currentProject?.id"
            class="project-switch-check"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="m3.5 8.5 3 3 6-6.5" />
          </svg>
        </button>
        <p v-if="projects.length === 0" class="project-switch-empty">
          还没有项目，先新建一个吧
        </p>
      </div>

      <div class="project-switch-sep" role="separator" />

      <button
        type="button"
        role="menuitem"
        data-switch-item
        class="project-switch-create"
        @click="createProject"
      >
        <svg
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
          aria-hidden="true"
        >
          <path d="M8 3v10M3 8h10" />
        </svg>
        新建项目
      </button>
    </div>
  </div>
</template>

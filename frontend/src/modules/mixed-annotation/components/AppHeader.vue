<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { MixedFile, Project } from '../types'

type MenuAction = 'settings' | 'delete'

const props = defineProps<{
  projects: Project[]
  currentProject: Project | null
  selectedFile: MixedFile | null
  fileStatusLabel: string
  /** 父组件正在导出项目 ZIP；用于禁用重复点击并切换按钮文案。 */
  exporting?: boolean
  /** 批量导入/保存期间锁定项目切换，避免写入错误项目。 */
  projectSwitchDisabled?: boolean
}>()

const emit = defineEmits<{
  'select-project': [id: string]
  create: []
  /** 打开项目设置弹窗（名称 + 转换参数）。 */
  settings: []
  'delete-project': []
  export: []
}>()

/* ------------------------------------------------------------------ */
/* 项目操作菜单                                                        */
/* ------------------------------------------------------------------ */

const menuOpen = ref(false)
const menuRef = ref<HTMLElement | null>(null)
const menuButtonRef = ref<HTMLButtonElement | null>(null)

function closeMenu(): void {
  menuOpen.value = false
}

function toggleMenu(): void {
  if (!props.currentProject || props.projectSwitchDisabled) return
  menuOpen.value = !menuOpen.value
}

function choose(action: MenuAction): void {
  closeMenu()
  // 菜单项随菜单卸载，先把焦点交回触发按钮，便于弹窗关闭后恢复焦点。
  menuButtonRef.value?.focus()
  if (action === 'delete') emit('delete-project')
  else emit('settings')
}

function onDocumentPointerDown(event: PointerEvent): void {
  if (!menuOpen.value) return
  const target = event.target as Node | null
  if (target && menuRef.value?.contains(target)) return
  closeMenu()
}

function onDocumentKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') closeMenu()
}

onMounted(() => {
  document.addEventListener('pointerdown', onDocumentPointerDown)
  document.addEventListener('keydown', onDocumentKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
  document.removeEventListener('keydown', onDocumentKeydown)
})

function onProjectChange(event: Event): void {
  const id = (event.target as HTMLSelectElement).value
  if (id) emit('select-project', id)
}
</script>

<template>
  <div class="mx-header">
    <label class="header-project">
      <span class="sr-only">当前项目</span>
      <select
        class="mx-input header-select"
        :value="currentProject?.id ?? ''"
        :disabled="projects.length === 0 || projectSwitchDisabled"
        :title="projectSwitchDisabled ? '当前操作进行中，暂时无法切换项目' : undefined"
        @change="onProjectChange"
      >
        <option value="" disabled>{{ projects.length ? '选择项目' : '暂无项目' }}</option>
        <option v-for="project in projects" :key="project.id" :value="project.id">
          {{ project.name }}
        </option>
      </select>
    </label>

    <button
      type="button"
      class="mx-btn mx-btn-icon header-create"
      title="新建项目"
      aria-label="新建项目"
      :disabled="projectSwitchDisabled"
      @click="emit('create')"
    >
      <svg
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linecap="round"
        aria-hidden="true"
      >
        <path d="M8 3v10M3 8h10" />
      </svg>
    </button>

    <div ref="menuRef" class="header-menu">
      <button
        ref="menuButtonRef"
        type="button"
        class="mx-btn header-menu-btn"
        :disabled="!currentProject || projectSwitchDisabled"
        aria-haspopup="menu"
        :aria-expanded="menuOpen"
        title="项目操作与设置"
        aria-label="项目操作与设置"
        @click="toggleMenu"
      >
        <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
          <circle cx="8" cy="3" r="1.3" />
          <circle cx="8" cy="8" r="1.3" />
          <circle cx="8" cy="13" r="1.3" />
        </svg>
        设置
      </button>
      <div v-if="menuOpen" class="header-menu-panel" role="menu">
        <button type="button" role="menuitem" class="header-menu-item" @click="choose('settings')">
          项目设置
        </button>
        <div class="header-menu-sep" role="separator"></div>
        <button type="button" role="menuitem" class="header-menu-item is-danger" @click="choose('delete')">
          删除项目
        </button>
      </div>
    </div>

    <div v-if="selectedFile" class="header-file" :title="selectedFile.name">
      <span class="file-state-dot" :class="`is-${selectedFile.status}`" aria-hidden="true" />
      <span class="header-file-name">{{ selectedFile.name }}</span>
      <span class="header-file-state">{{ fileStatusLabel }}</span>
    </div>
    <div v-else class="header-file is-empty">
      <span class="file-state-dot" aria-hidden="true" />
      <span class="header-file-state">未选择文件</span>
    </div>

    <div class="header-actions">
      <button
        type="button"
        class="mx-btn mx-btn-primary header-export"
        :disabled="!currentProject || exporting"
        title="导出当前项目为 ZIP"
        @click="emit('export')"
      >
        <svg
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M8 2.5v7" />
          <path d="m5 6.5 3 3 3-3" />
          <path d="M3 10.5v2a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-2" />
        </svg>
        {{ exporting ? '导出中…' : '导出 ZIP' }}
      </button>
    </div>
  </div>
</template>

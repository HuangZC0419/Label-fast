<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { MixedFile, Project } from '../types'
import ProjectSwitcher from './project/ProjectSwitcher.vue'

/**
 * 混合标注模块头：项目切换器 + 设置菜单 + 工作区插槽 + 导出动作。
 *
 * 项目切换/新建由 ProjectSwitcher 负责；项目设置与删除由独立的「设置」菜单承载。
 * `workspace` 具名插槽用于承载 MixedWorkspace Teleport 过来的文件头
 * （文件标题、状态、模式切换、预览与同步滚动），从而把原来的两行合并成一行。
 */
const props = defineProps<{
  projects: Project[]
  currentProject: Project | null
  selectedFile: MixedFile | null
  fileStatusLabel: string
  /** 父组件正在导出项目 ZIP；用于禁用重复点击并切换按钮文案。 */
  exporting?: boolean
  /** 父组件正在生成标注明细 Excel；用于禁用重复点击并切换按钮文案。 */
  excelExporting?: boolean
  /** 批量导入/保存期间锁定项目切换，避免写入错误项目。 */
  projectSwitchDisabled?: boolean
  /** 当前项目没有可拆分的文件时禁用「拆分项目」入口。 */
  splitDisabled?: boolean
}>()

const emit = defineEmits<{
  'select-project': [id: string]
  create: []
  /** 打开项目设置弹窗（名称 + 转换参数）。 */
  settings: []
  /** 打开项目按文件序号区间拆分弹窗。 */
  'split-project': []
  'delete-project': []
  /** 打开导入弹窗（拖拽/选择文件/选择文件夹 + 上传进度 + 队列统计）。 */
  import: []
  /** 打开当前文件的「重新 OCR」参数弹窗。 */
  reconvert: []
  export: []
  /** 打开「导出 Excel 表单」弹窗（可多选项目）。 */
  'export-excel': []
}>()

type MenuAction = 'settings' | 'split' | 'delete'

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
  else if (action === 'split') emit('split-project')
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
</script>

<template>
  <div class="mx-header">
    <!-- 项目切换器：触发器展示当前项目，下拉内承载列表与「新建项目」。 -->
    <div class="header-project">
      <ProjectSwitcher
        :projects="projects"
        :current-project="currentProject"
        :project-switch-disabled="projectSwitchDisabled"
        @select-project="emit('select-project', $event)"
        @create="emit('create')"
      />
    </div>

    <!-- 设置菜单：项目设置与删除项目，与切换器分离。 -->
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
        <button
          type="button"
          role="menuitem"
          class="header-menu-item"
          :disabled="!currentProject || splitDisabled"
          :title="splitDisabled ? '当前项目没有可拆分的文件' : '按文件序号区间拆分为多个新项目'"
          @click="choose('split')"
        >
          拆分项目
        </button>
        <div class="header-menu-sep" role="separator"></div>
        <button type="button" role="menuitem" class="header-menu-item is-danger" @click="choose('delete')">
          删除项目
        </button>
      </div>
    </div>

    <!--
      导入入口：原来在左侧栏底部，占用纵向空间且要先把视线移到侧栏。
      现在与「设置」同排，成为模块头的显性动作，点开即弹上传窗口。
    -->
    <button
      type="button"
      class="header-import"
      :disabled="!currentProject"
      :title="
        !currentProject
          ? '请先新建或选择项目'
          : '导入数据：PDF / 图片，支持整个文件夹'
      "
      @click="emit('import')"
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
        <path d="M8 10.5V2.5" />
        <path d="m4.8 5.7 3.2-3.2 3.2 3.2" />
        <path d="M2.8 11v1.8a1.2 1.2 0 0 0 1.2 1.2h8a1.2 1.2 0 0 0 1.2-1.2V11" />
      </svg>
      导入数据
    </button>

    <!--
      重新 OCR：紧挨「导入数据」，针对当前选中文件重新识别。
      打开参数弹窗，可调 DPI / 解析方式 / 表格与公式识别；会清空该文件已有标注。
    -->
    <button
      type="button"
      class="header-reconvert"
      :disabled="!selectedFile || selectedFile.status === 'converting' || !currentProject"
      :title="
        !currentProject
          ? '请先选择项目'
          : !selectedFile
            ? '请先选择要重新识别的文件'
            : '重新 OCR：调整识别精度后重新转换当前文件'
      "
      @click="emit('reconvert')"
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
        <path d="M13.6 6.6A5.6 5.6 0 1 0 14 9.2" />
        <path d="M13.8 2.8v3.9h-3.9" />
      </svg>
      重新 OCR
    </button>

    <!--
      工作区插槽：MixedWorkspace 用 Teleport 把「文件标题 + 状态 + 视图控件」
      搬进模块头，让模块头与工作区文件头合并为一行，省掉一整行高度留给标注区。
    -->
    <div class="header-workspace">
      <slot name="workspace" />
    </div>

    <!--
      文件状态胶囊只在没有工作区插槽时出现：有插槽时文件标题已由工作区行展示，
      再显示一遍既重复又占宽度。
    -->
    <template v-if="!$slots.workspace">
      <div v-if="selectedFile" class="header-file" :title="selectedFile.name">
        <span class="file-state-dot" :class="`is-${selectedFile.status}`" aria-hidden="true" />
        <span class="header-file-name">{{ selectedFile.name }}</span>
        <span class="header-file-state">{{ fileStatusLabel }}</span>
      </div>
      <div v-else class="header-file is-empty">
        <span class="file-state-dot" aria-hidden="true" />
        <span class="header-file-state">未选择文件</span>
      </div>
    </template>

    <div class="header-actions">
      <!-- Excel 次级动作：可多选项目；用 accent 描边按钮提亮，但仍弱于 ZIP 主按钮。 -->
      <button
        type="button"
        class="mx-btn header-export-excel"
        :disabled="projects.length === 0 || excelExporting"
        title="导出标注明细 Excel（可选择多个项目）"
        @click="emit('export-excel')"
      >
        <svg
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="1.4"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <rect x="2.5" y="3.5" width="11" height="9" rx="1.2" />
          <path d="M2.5 6.6h11" />
          <path d="M6.4 3.5v9" />
          <path d="M6.4 9.8h7.1" />
        </svg>
        {{ excelExporting ? '导出中…' : '导出 Excel 表单' }}
      </button>

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


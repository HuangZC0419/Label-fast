<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import ProjectSidebar from '../components/image/ProjectSidebar.vue'
import ImageViewer from '../components/image/ImageViewer.vue'
import BoxPanel from '../components/image/BoxPanel.vue'
import { useImageProject, type BoxItem } from '../composables/useImageProject'
import '../styles/image.css'

const {
  projects,
  currentProjectId,
  currentProject,
  labels,
  images,
  labeledSet,
  currentIndex,
  imagesError,
  boxSaveStatus,
  currentImageName,
  boxesForCurrentImage,
  fetchProjects,
  fetchImages,
  createProject,
  switchProject,
  persistCurrentProject,
  deleteProject,
  selectImage,
  prevImage,
  nextImage,
  saveBoxes,
  addLabel,
  addBox,
  removeBox,
  clearBoxes,
  exportZip,
  cancelAdvance,
} = useImageProject()

/** 绘制开关属于页面交互状态，不进入共享数据层。 */
const drawingEnabled = ref(false)
const currentLabel = ref('')
const newProjectName = ref('')

const hasImage = computed(() => Boolean(currentImageName.value))
const canExport = computed(() => Boolean(currentProjectId.value))

const positionLabel = computed(() => {
  if (currentIndex.value < 0 || images.value.length === 0) return ''
  return `${currentIndex.value + 1} / ${images.value.length}`
})

const emptyHint = computed(() => {
  if (!currentProjectId.value) return '请先在左侧选择或创建一个项目'
  if (imagesError.value) return imagesError.value
  return '暂无图片，请将图片放入图片存放目录'
})

/** 受控 select：切换失败时通过 currentProjectId 回滚显示。 */
const projectSelection = computed<string>({
  get: () => currentProjectId.value,
  set: (value) => {
    void handleProjectSwitch(value)
  },
})

// 标签切换项目后自动选中第一个，避免 currentLabel 指向已不存在的标签。
watch(
  labels,
  (list) => {
    if (!list.includes(currentLabel.value)) {
      currentLabel.value = list.length > 0 ? list[0]! : ''
    }
  },
  { immediate: true },
)

async function handleProjectSwitch(id: string): Promise<void> {
  if (!id || id === currentProject.value.id) return

  const previousId = currentProject.value.id
  currentProjectId.value = id
  const switched = await switchProject(id)

  if (!switched) {
    currentProjectId.value = previousId
    return
  }
  drawingEnabled.value = false
}

async function handleCreateProject(): Promise<void> {
  const created = await createProject(newProjectName.value)
  if (created) {
    newProjectName.value = ''
    drawingEnabled.value = false
  }
}

async function handleSaveProject(): Promise<void> {
  await persistCurrentProject()
}

async function handleDeleteProject(): Promise<void> {
  await deleteProject()
  drawingEnabled.value = false
}

async function handleRefreshImages(): Promise<void> {
  await fetchImages(currentImageName.value ?? currentProject.value.last_image ?? '')
}

function handleSelectImage(index: number): void {
  selectImage(index)
}

function handleAddLabel(name: string): void {
  if (addLabel(name)) {
    currentLabel.value = name.trim()
  }
}

function handleSelectLabel(name: string): void {
  currentLabel.value = name
}

function handleToggleDrawing(): void {
  if (!hasImage.value || labels.value.length === 0) return

  if (!currentLabel.value) {
    currentLabel.value = labels.value[0] ?? ''
  }
  drawingEnabled.value = !drawingEnabled.value

  if (boxSaveStatus.value?.type === 'error') {
    boxSaveStatus.value = null
  }
}

function handleBoxCreated(box: BoxItem): void {
  addBox(box)
}

function handleSaveBoxes(): void {
  void saveBoxes()
}

function handleRemoveBox(index: number): void {
  removeBox(index)
}

function handleClearBoxes(): void {
  clearBoxes()
}

function handleExport(): void {
  void exportZip('box')
}

/** 输入控件内不触发导航/数字快捷键。 */
function isTypingTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null
  if (!element) return false
  const tag = element.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || element.isContentEditable
}

function handleKeydown(event: KeyboardEvent): void {
  // 长按产生的重复按键不重复触发保存，避免连续写入。
  if (event.repeat) return

  // Ctrl+Enter 在任何输入位置都直接保存当前图片框标注。
  if (event.ctrlKey && event.key === 'Enter') {
    event.preventDefault()
    void saveBoxes()
    return
  }

  if (event.key === 'Escape') {
    if (drawingEnabled.value) {
      event.preventDefault()
      drawingEnabled.value = false
    }
    return
  }

  if (isTypingTarget(event.target)) return
  if (event.ctrlKey || event.metaKey || event.altKey) return

  // 空格：保存当前图片框标注。
  if (event.key === ' ') {
    event.preventDefault()
    void saveBoxes()
    return
  }

  const key = event.key.toLowerCase()
  if (key === 'a') {
    event.preventDefault()
    prevImage()
    return
  }
  if (key === 'd') {
    event.preventDefault()
    nextImage()
    return
  }

  // 1-9 / 0 选择标签并自动进入绘制模式。
  if (/^[0-9]$/.test(event.key)) {
    const targetIndex = event.key === '0' ? 9 : Number(event.key) - 1
    const label = labels.value[targetIndex]
    if (!label) return

    event.preventDefault()
    currentLabel.value = label
    drawingEnabled.value = true
    boxSaveStatus.value = { type: 'success', msg: `已选中标签: ${label} (快捷键 ${event.key})` }

    window.setTimeout(() => {
      if (boxSaveStatus.value?.msg.includes(label)) {
        boxSaveStatus.value = null
      }
    }, 1500)
  }
}

onMounted(async () => {
  window.addEventListener('keydown', handleKeydown)

  // 页面之间切换时共享状态仍然存在，仅在项目已选中但图片尚未加载时补拉一次。
  await fetchProjects()
  if (currentProjectId.value && images.value.length === 0 && !imagesError.value) {
    await fetchImages(currentProject.value.last_image || '')
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
  // 页面离开时取消保存后的自动跳图，避免在另一个页面推进共享状态
  cancelAdvance()
})
</script>

<template>
  <div class="image-page image-page-box">
    <ProjectSidebar
      v-model="projectSelection"
      v-model:newProjectName="newProjectName"
      :projects="projects"
      :current-project="currentProject"
      :images="images"
      :labeled-set="labeledSet"
      :current-index="currentIndex"
      :images-error="imagesError"
      @create-project="handleCreateProject"
      @save-project="handleSaveProject"
      @delete-project="handleDeleteProject"
      @refresh-images="handleRefreshImages"
      @select-image="handleSelectImage"
    />

    <div class="image-workspace">
      <ImageViewer
        :image-name="currentImageName"
        :boxes="boxesForCurrentImage"
        :labels="labels"
        :drawing-enabled="drawingEnabled"
        :current-label="currentLabel"
        :can-prev="currentIndex > 0"
        :can-next="currentIndex >= 0 && currentIndex < images.length - 1"
        :position-label="positionLabel"
        :empty-hint="emptyHint"
        @box-created="handleBoxCreated"
        @prev="prevImage"
        @next="nextImage"
      />

      <BoxPanel
        :labels="labels"
        :current-label="currentLabel"
        :drawing-enabled="drawingEnabled"
        :boxes="boxesForCurrentImage"
        :status="boxSaveStatus"
        :has-image="hasImage"
        :can-export="canExport"
        @add-label="handleAddLabel"
        @select-label="handleSelectLabel"
        @toggle-drawing="handleToggleDrawing"
        @remove-box="handleRemoveBox"
        @clear-boxes="handleClearBoxes"
        @save-boxes="handleSaveBoxes"
        @export-zip="handleExport"
      />
    </div>
  </div>
</template>

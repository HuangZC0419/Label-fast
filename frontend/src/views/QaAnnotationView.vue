<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import ProjectSidebar from '../components/image/ProjectSidebar.vue'
import ImageViewer from '../components/image/ImageViewer.vue'
import QaPanel from '../components/image/QaPanel.vue'
import { useImageProject } from '../composables/useImageProject'
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
  saveStatus,
  currentImageName,
  boxesForCurrentImage,
  userContent,
  assistantContent,
  fetchProjects,
  fetchImages,
  createProject,
  switchProject,
  persistCurrentProject,
  deleteProject,
  selectImage,
  prevImage,
  nextImage,
  loadQaDraftForImage,
  saveQa,
  exportZip,
  cancelAdvance,
} = useImageProject()

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

const projectSelection = computed<string>({
  get: () => currentProjectId.value,
  set: (value) => {
    void handleProjectSwitch(value)
  },
})

async function handleProjectSwitch(id: string): Promise<void> {
  if (!id || id === currentProject.value.id) return

  const previousId = currentProject.value.id
  currentProjectId.value = id
  const switched = await switchProject(id)

  if (!switched) {
    currentProjectId.value = previousId
  }
}

async function handleCreateProject(): Promise<void> {
  const created = await createProject(newProjectName.value)
  if (created) {
    newProjectName.value = ''
  }
}

async function handleSaveProject(): Promise<void> {
  await persistCurrentProject()
}

async function handleDeleteProject(): Promise<void> {
  await deleteProject()
}

async function handleRefreshImages(): Promise<void> {
  await fetchImages(currentImageName.value ?? currentProject.value.last_image ?? '')
}

function handleSelectImage(index: number): void {
  selectImage(index)
}

function handleSave(): void {
  void saveQa(true)
}

function handleSkip(): void {
  saveStatus.value = null
  // “跳过（不保存）”应丢弃当前未保存的修改：恢复该图片上一次保存的内容后再切换
  loadQaDraftForImage(currentImageName.value)
  nextImage()
}

function handleExport(): void {
  void exportZip('qa')
}

function isTypingTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null
  if (!element) return false
  const tag = element.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || element.isContentEditable
}

function handleKeydown(event: KeyboardEvent): void {
  // 长按产生的重复按键不重复触发保存。
  if (event.repeat) return

  // Ctrl+Enter 在 textarea 内同样生效。
  if (event.ctrlKey && event.key === 'Enter') {
    event.preventDefault()
    void saveQa(true)
    return
  }

  if (isTypingTarget(event.target)) return
  if (event.ctrlKey || event.metaKey || event.altKey) return

  if (event.key === ' ') {
    event.preventDefault()
    void saveQa(true)
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
  }
}

onMounted(async () => {
  window.addEventListener('keydown', handleKeydown)

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
  <div class="image-page image-page-qa">
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
        :drawing-enabled="false"
        current-label=""
        :can-prev="currentIndex > 0"
        :can-next="currentIndex >= 0 && currentIndex < images.length - 1"
        :position-label="positionLabel"
        :empty-hint="emptyHint"
        @prev="prevImage"
        @next="nextImage"
      />

      <QaPanel
        v-model:userContent="userContent"
        v-model:assistantContent="assistantContent"
        :status="saveStatus"
        :has-image="hasImage"
        :can-export="canExport"
        @save="handleSave"
        @skip="handleSkip"
        @export-zip="handleExport"
      />
    </div>
  </div>
</template>

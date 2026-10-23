<script setup lang="ts">
import type { ImageProject } from '../../composables/useImageProject'

const props = defineProps<{
  /** 当前选中的项目 id，用于 select 的受控显示与失败回滚。 */
  modelValue: string
  projects: ImageProject[]
  currentProject: ImageProject
  images: string[]
  labeledSet: Set<string>
  currentIndex: number
  imagesError: string
  newProjectName: string
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: string): void
  (event: 'update:newProjectName', value: string): void
  (event: 'create-project'): void
  (event: 'save-project'): void
  (event: 'delete-project'): void
  (event: 'refresh-images'): void
  (event: 'select-image', index: number): void
}>()

function handleProjectChange(event: Event): void {
  const select = event.target as HTMLSelectElement
  // 占位项不允许清空当前项目，避免前端状态与后端 active project 脱节。
  if (!select.value) {
    select.value = props.modelValue
    return
  }
  emit('update:modelValue', select.value)
}

function handleNameInput(event: Event): void {
  emit('update:newProjectName', (event.target as HTMLInputElement).value)
}

function isLabeled(name: string): boolean {
  return props.labeledSet.has(name)
}
</script>

<template>
  <aside class="image-sidebar">
    <!-- 项目配置：暖白项目卡 -->
    <div class="image-sidebar-config">
      <section class="image-project-card" aria-labelledby="image-project-title">
        <header class="image-project-head">
          <div>
            <span class="image-eyebrow">Project</span>
            <h2 id="image-project-title" class="image-project-title">项目配置</h2>
          </div>
        </header>

        <label class="image-field">
          <span class="image-field-label">历史项目</span>
          <select class="image-select" :value="modelValue" @change="handleProjectChange">
            <option value="">-- 请选择项目 --</option>
            <option v-for="project in projects" :key="project.id" :value="project.id">
              {{ project.name }}
            </option>
          </select>
        </label>

        <div class="image-divider"><span>或新建</span></div>

        <div class="image-new-row">
          <input
            class="image-input"
            :value="newProjectName"
            placeholder="新项目名称"
            aria-label="新项目名称"
            @input="handleNameInput"
            @keyup.enter="emit('create-project')"
          />
          <button type="button" class="image-btn" @click="emit('create-project')">
            新建项目
          </button>
        </div>

        <div v-if="modelValue" class="image-status-banner ok">
          当前项目: <strong>{{ currentProject.name }}</strong>
        </div>
        <div v-else class="image-status-banner hint">
          请选择历史项目，或输入名称创建新项目
        </div>

        <!-- 项目路径（只读展示） -->
        <div v-if="modelValue" class="image-project-paths">
          <div class="image-field">
            <span class="image-path-label">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
              </svg>
              图片存放位置
            </span>
            <div class="image-path">{{ currentProject.image_dir }}</div>
            <span class="image-path-hint">将待标注图片放入此文件夹，支持子目录</span>
          </div>

          <div class="image-field">
            <span class="image-path-label">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <ellipse cx="12" cy="5" rx="8" ry="3" />
                <path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
                <path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
              </svg>
              标注结果保存位置
            </span>
            <div class="image-path">{{ currentProject.project_dir }}</div>
            <span class="image-path-hint">问答和框选标注结果自动保存到此文件夹</span>
          </div>

          <div class="image-project-actions">
            <button type="button" class="image-btn image-btn-primary" @click="emit('save-project')">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
                <polyline points="17 21 17 13 7 13 7 21" />
                <polyline points="7 3 7 8 15 8" />
              </svg>
              保存当前项目
            </button>
            <button type="button" class="image-btn image-btn-danger" @click="emit('delete-project')">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <polyline points="3 6 5 6 21 6" />
                <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                <path d="M10 11v6M14 11v6" />
                <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
              </svg>
              删除项目
            </button>
          </div>
        </div>
      </section>
    </div>

    <!-- 图片列表 -->
    <div class="image-list-head">
      <span class="image-list-title">
        图片列表
        <span class="image-list-total">{{ images.length }}</span>
      </span>
      <div class="image-list-head-right">
        <span v-if="modelValue" class="image-list-progress" title="已标注 / 总图片">
          ✓ {{ labeledSet.size }} / {{ images.length }}
        </span>
        <button type="button" class="image-list-refresh" title="刷新列表" aria-label="刷新图片列表" @click="emit('refresh-images')">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M21 12a9 9 0 1 1-2.64-6.36" />
            <polyline points="21 3 21 9 15 9" />
          </svg>
        </button>
      </div>
    </div>

    <div class="image-list">
      <div v-if="!modelValue" class="image-list-empty">
        <svg class="image-list-empty-icon" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
        </svg>
        <p class="image-list-empty-en">No project yet</p>
        <p class="image-list-empty-text">
          请先选择或创建一个项目，然后把图片放入对应的 images 文件夹。
        </p>
      </div>
      <template v-else>
        <div v-if="imagesError" class="image-list-note warn" role="alert">{{ imagesError }}</div>
        <div v-else-if="images.length === 0" class="image-list-empty">
          <svg class="image-list-empty-icon" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <circle cx="8.5" cy="8.5" r="1.5" />
            <path d="m21 15-5-5L5 21" />
          </svg>
          <p class="image-list-empty-en">No images yet</p>
          <p class="image-list-empty-text">
            将 .png / .jpg / .jpeg / .bmp / .gif / .webp 图片放入图片目录后，点击右上角刷新。
          </p>
        </div>
      </template>

      <button
        v-for="(image, index) in images"
        :key="image"
        type="button"
        class="image-list-item"
        :class="{ active: currentIndex === index, labeled: isLabeled(image) }"
        :title="image"
        @click="emit('select-image', index)"
      >
        <span class="image-list-name">{{ image }}</span>
        <span v-if="isLabeled(image)" class="image-list-check" aria-label="已标注">✓</span>
      </button>
    </div>
  </aside>
</template>

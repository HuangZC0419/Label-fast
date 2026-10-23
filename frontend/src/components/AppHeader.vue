<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAuth } from '../composables/useAuth'

const route = useRoute()
const { state: authState, logout } = useAuth()

const moduleTitle = computed(() =>
  typeof route.meta.title === 'string' ? route.meta.title : '标注工作台',
)

// 当前模块的英文眉题，配合中文标题形成「展示字 + 界面字」的层级
const moduleEyebrow = computed(() => {
  switch (route.name) {
    case 'text-annotation':
      return 'Text Annotation'
    case 'image-annotation':
      return 'Image Annotation'
    case 'qa-annotation':
      return 'Q&A Annotation'
    default:
      return 'Workspace'
  }
})

const username = computed(() => authState.user?.username ?? '')
const userInitial = computed(() => username.value.charAt(0).toUpperCase() || 'L')

function handleLogout(): void {
  logout()
  // 整页跳转以清空图像标注页的模块级共享状态，避免换账号后看到上一账号的数据
  window.location.assign(`${import.meta.env.BASE_URL}login`)
}
</script>

<template>
  <header class="header app-header">
    <div class="header-brand">
      <span class="header-brand-name header-wordmark">LabelFast</span>
      <span class="header-separator" aria-hidden="true"></span>
      <div class="header-module">
        <span class="header-module-eyebrow">{{ moduleEyebrow }}</span>
        <h1 class="header-module-title">{{ moduleTitle }}</h1>
      </div>
    </div>

    <div class="user-info">
      <div class="header-user" :title="username">
        <span class="header-user-avatar" aria-hidden="true">{{ userInitial }}</span>
        <span class="username">{{ username }}</span>
      </div>
      <button type="button" class="logout-btn" @click="handleLogout">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
          <path d="m16 17 5-5-5-5" />
          <path d="M21 12H9" />
        </svg>
        退出
      </button>
    </div>
  </header>
</template>

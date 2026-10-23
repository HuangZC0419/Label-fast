<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <nav class="app-nav-rail" aria-label="主导航">
    <!-- 顶部品牌标记：朱砂细线标注括号 -->
    <RouterLink to="/app/text" class="nav-brand" aria-label="LabelFast 文本标注">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M8 4.5H5v15h3" />
        <path d="M16 4.5h3v15h-3" />
        <path d="M10 12h4" />
      </svg>
    </RouterLink>

    <div class="nav-items">
      <RouterLink
        to="/app/text"
        class="app-nav-item"
        title="文本标注"
        aria-label="文本标注"
      >
        <span class="app-nav-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <path d="M14 2v6h6" />
            <path d="M8 13h8M8 17h5" />
          </svg>
        </span>
        <span class="app-nav-label">文本</span>
      </RouterLink>

      <RouterLink
        to="/app/image"
        class="app-nav-item"
        title="图像标注"
        aria-label="图像标注"
      >
        <span class="app-nav-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <circle cx="8.5" cy="8.5" r="1.5" />
            <path d="m21 15-5-5L5 21" />
          </svg>
        </span>
        <span class="app-nav-label">图像</span>
      </RouterLink>

      <RouterLink
        to="/app/qa"
        class="app-nav-item"
        title="大模型问答标注"
        aria-label="大模型问答标注"
      >
        <span class="app-nav-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z" />
            <path d="M8 9h8M8 13h5" />
          </svg>
        </span>
        <span class="app-nav-label">问答</span>
      </RouterLink>
    </div>

    <div class="nav-signoff" aria-hidden="true">
      <span>LF</span>
      <span class="nav-signoff-rule"></span>
      <span>2026</span>
    </div>
  </nav>
</template>

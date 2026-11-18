<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <nav class="app-nav-rail" aria-label="主导航">
    <!-- 顶部品牌标记：朱砂细线标注括号 -->
    <RouterLink to="/app/text" class="nav-brand" aria-label="数据标注与分类工具 文本标注">
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

      <RouterLink to="/app/classify" class="app-nav-item" title="航空标准分类" aria-label="航空标准分类">
        <span class="app-nav-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 3 3 7.5 12 12l9-4.5z" />
            <path d="m3 12 9 4.5 9-4.5" />
            <path d="m3 16.5 9 4.5 9-4.5" />
          </svg>
        </span>
        <span class="app-nav-label">国标</span>
      </RouterLink>

      <RouterLink to="/app/mixed" class="app-nav-item" title="混合标注" aria-label="混合标注">
        <span class="app-nav-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
            <path d="M6 3h9l4 4v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" />
            <path d="M15 3v4h4" />
            <path d="M8 12h6M8 16h4" />
            <path d="m17 15 2 2 2-2" />
          </svg>
        </span>
        <span class="app-nav-label">混合</span>
      </RouterLink>

      <RouterLink to="/app/model" class="app-nav-item" title="模型标注" aria-label="模型标注">
        <span class="app-nav-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
            <path d="M6 3h9l4 4v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" />
            <path d="M15 3v4h4" />
            <path d="M8 12h6M8 16h4" />
            <circle cx="17" cy="17" r="3" />
          </svg>
        </span>
        <span class="app-nav-label">模型</span>
      </RouterLink>
    </div>

    <div class="nav-signoff" aria-hidden="true">
      <span>LF</span>
      <span class="nav-signoff-rule"></span>
      <span>2026</span>
    </div>
  </nav>
</template>

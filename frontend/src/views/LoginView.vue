<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'

const router = useRouter()
const { login } = useAuth()

const username = ref('')
const password = ref('')
const showPassword = ref(false)
const errorMessage = ref('')
const submitting = ref(false)

async function handleSubmit(): Promise<void> {
  errorMessage.value = ''

  if (!username.value.trim() || !password.value.trim()) {
    errorMessage.value = '请填写账号和密码'
    return
  }

  submitting.value = true
  try {
    await login(username.value.trim(), password.value)
    await router.push('/app/text')
  } catch (error) {
    errorMessage.value
      = error instanceof Error ? error.message : '登录失败，请重试'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <!-- 左侧品牌面板：深墨画布 + 展陈式排版 -->
      <aside class="login-brand">
        <div class="login-brand-top">
          <div class="login-brand-logo" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
              <path d="M8 4.5H5v15h3" />
              <path d="M16 4.5h3v15h-3" />
              <path d="M10 12h4" />
            </svg>
          </div>
          <span class="login-brand-kicker">Offline annotation studio</span>
        </div>

        <div class="login-brand-core">
          <h1 class="login-brand-wordmark">LabelFast<span class="login-brand-period">.</span></h1>
          <p class="login-brand-tagline">Annotation, <em>edited</em>.</p>

          <div class="login-brand-sample">
            <div class="login-brand-sample-head">
              <span>Sample · 001</span>
              <span>ZH → Entity</span>
            </div>
            <p class="login-brand-sample-text">
              在 <span class="login-hl">一段安静的文本</span> 里，圈出
              <span class="login-hl login-hl--amber">关键的人物</span> 与语气，<br />
              让每一次标注都更接近
              <span class="login-hl login-hl--line">真实的语言</span>。
            </p>
          </div>
        </div>

        <div class="login-brand-foot">
          <span class="login-brand-status" aria-hidden="true"></span>
          Offline-first · 2026
        </div>
      </aside>

      <!-- 右侧表单面板：暖纸色画布 -->
      <section class="login-form-panel">
        <div class="login-mobile-brand" aria-hidden="true">
          <span class="login-brand-logo">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
              <path d="M8 4.5H5v15h3" />
              <path d="M16 4.5h3v15h-3" />
              <path d="M10 12h4" />
            </svg>
          </span>
          <span>LabelFast<span class="login-brand-period">.</span></span>
        </div>

        <div class="login-form-wrapper">
          <p class="login-eyebrow">Welcome back</p>
          <h2 class="login-form-title">欢迎登录</h2>
          <p class="login-form-desc">继续你的文本、图像与问答标注工作。</p>

          <p class="login-notice">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 11v5" />
              <path d="M12 8h.01" />
            </svg>
            <span>账号由管理员在 <code>backend/users.xlsx</code> 中统一维护</span>
          </p>

          <div v-if="errorMessage" class="login-error" role="alert">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 8v5" />
              <path d="M12 16h.01" />
            </svg>
            <span>{{ errorMessage }}</span>
          </div>

          <form @submit.prevent="handleSubmit">
            <div class="login-field">
              <label class="login-field-label" for="login-account">账号</label>
              <div class="login-input-wrap">
                <input
                  id="login-account"
                  v-model="username"
                  class="login-input"
                  type="text"
                  placeholder="邮箱 / 手机号 / 用户名"
                  aria-label="账号"
                  autocomplete="username"
                  autofocus
                />
              </div>
            </div>

            <div class="login-field">
              <label class="login-field-label" for="login-password">密码</label>
              <div class="login-input-wrap">
                <input
                  id="login-password"
                  v-model="password"
                  class="login-input"
                  :type="showPassword ? 'text' : 'password'"
                  placeholder="请输入密码"
                  aria-label="密码"
                  autocomplete="current-password"
                />
                <button
                  type="button"
                  class="login-input-icon"
                  tabindex="-1"
                  :aria-label="showPassword ? '隐藏密码' : '显示密码'"
                  @click="showPassword = !showPassword"
                >
                  <svg v-if="showPassword" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                    <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                    <line x1="1" y1="1" x2="23" y2="23" />
                  </svg>
                  <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                </button>
              </div>
            </div>

            <button class="login-btn login-btn-primary" type="submit" :disabled="submitting">
              <template v-if="submitting">
                <svg class="login-spinner" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true">
                  <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                </svg>
                验证中...
              </template>
              <template v-else>登 录</template>
            </button>
          </form>
        </div>

        <footer class="login-form-foot">
          <span class="login-foot-link">隐私政策</span>
          <span aria-hidden="true">·</span>
          <span class="login-foot-link">用户协议</span>
          <span class="login-copyright">© 2026 LabelFast</span>
        </footer>
      </section>
    </div>
  </div>
</template>

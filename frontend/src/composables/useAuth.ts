import { computed, reactive } from 'vue'

export interface AuthUser {
  id: number
  username: string
}

export interface AuthState {
  user: AuthUser | null
  token: string | null
  loading: boolean
}

interface LoginResponse {
  token: string
  user: AuthUser
}

const TOKEN_KEY = 'token'

/** 全局唯一的认证状态，所有页面共享同一份用户与 token 数据。 */
export const authState = reactive<AuthState>({
  user: null,
  token: sessionStorage.getItem(TOKEN_KEY),
  loading: Boolean(sessionStorage.getItem(TOKEN_KEY)),
})

export const isAuthenticated = computed(
  () => Boolean(authState.token && authState.user),
)

let authReadyPromise: Promise<void> | null = null

/** 清除本地登录态，供校验失败与退出登录复用。 */
function clearAuth(): void {
  sessionStorage.removeItem(TOKEN_KEY)
  authState.token = null
  authState.user = null
  authState.loading = false
}

async function verifySession(): Promise<void> {
  if (!authState.token) {
    authState.loading = false
    return
  }

  try {
    const response = await fetch('/api/auth/me', {
      headers: {
        Authorization: `Bearer ${authState.token}`,
      },
    })

    if (!response.ok) {
      clearAuth()
      return
    }

    authState.user = (await response.json()) as AuthUser
  } catch {
    // 网络异常时保留本地 token，等待下次页面刷新或重新登录时再校验。
    console.warn('Token 校验请求失败（网络异常），保留本地 token 待下次重试')
  } finally {
    authState.loading = false
  }
}

/**
 * 启动时校验登录态。
 * 返回单例 Promise，多个路由守卫同时调用也不会重复请求 /api/auth/me。
 */
export function ensureAuthReady(): Promise<void> {
  if (!authReadyPromise) {
    authReadyPromise = verifySession()
  }
  return authReadyPromise
}

export async function login(username: string, password: string): Promise<void> {
  const response = await fetch('/api/auth/login', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ username, password }),
  })

  if (!response.ok) {
    let message = '登录失败'
    try {
      const errorBody = (await response.json()) as {
        detail?: string
        message?: string
      }
      message = errorBody.detail || errorBody.message || message
    } catch {
      // 后端未返回 JSON 时沿用默认提示。
    }
    throw new Error(message)
  }

  const data = (await response.json()) as LoginResponse
  if (!data.token || !data.user) {
    throw new Error('登录响应格式异常')
  }

  sessionStorage.setItem(TOKEN_KEY, data.token)
  authState.token = data.token
  authState.user = data.user
  authState.loading = false
}

export function logout(): void {
  clearAuth()
  authReadyPromise = Promise.resolve()
}

/** 页面统一通过该入口访问认证能力，避免各处直接依赖模块内部变量。 */
export function useAuth() {
  return {
    state: authState,
    isAuthenticated,
    ensureAuthReady,
    login,
    logout,
  }
}

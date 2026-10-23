import { reactive } from 'vue'

export type ToastType = 'success' | 'error' | 'info'

export interface ToastItem {
  id: number
  message: string
  type: ToastType
  duration: number
}

/** 全局唯一的提示队列，所有页面共享。 */
const items = reactive<ToastItem[]>([])
const timers = new Map<number, ReturnType<typeof setTimeout>>()
let nextId = 1

/** 手动关闭一条提示，并清理它的自动关闭计时器。 */
export function dismiss(id: number): void {
  const timer = timers.get(id)
  if (timer) {
    clearTimeout(timer)
    timers.delete(id)
  }

  const index = items.findIndex(item => item.id === id)
  if (index !== -1) {
    items.splice(index, 1)
  }
}

/**
 * 弹出一条全局提示。
 * 默认时长：success / info 3.5 秒，error 6 秒。
 */
export function toast(message: string, type: ToastType = 'info', duration?: number): void {
  const resolvedDuration = duration ?? (type === 'error' ? 6000 : 3500)
  const item: ToastItem = {
    id: nextId++,
    message,
    type,
    duration: resolvedDuration,
  }

  items.push(item)

  // 最多同时保留 4 条，超出时关闭最早的一条，避免遮挡页面操作
  if (items.length > 4) {
    dismiss(items[0].id)
  }

  timers.set(item.id, setTimeout(() => dismiss(item.id), resolvedDuration))
}

/** 组件侧访问入口：与全局队列保持同一份响应式数据。 */
export function useToast(): { items: ToastItem[]; dismiss(id: number): void } {
  return { items, dismiss }
}

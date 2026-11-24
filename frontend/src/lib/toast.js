import { reactive } from 'vue'

/**
 * 极简全局提示，替代 Element Plus 的 ElMessage（换来整包 Element Plus 的移除）。
 * 用法与 ElMessage 对齐：toast.success('已保存') / toast.error(msg, 5000)
 */
let seq = 0
export const toasts = reactive([])

const dismiss = (id) => {
  const index = toasts.findIndex((item) => item.id === id)
  if (index >= 0) toasts.splice(index, 1)
}

const push = (type, message, duration) => {
  const id = ++seq
  toasts.push({ id, type, message: String(message) })
  setTimeout(() => dismiss(id), duration)
  return id
}

export const toast = {
  success: (message, duration = 3000) => push('success', message, duration),
  error: (message, duration = 4500) => push('error', message, duration),
  warning: (message, duration = 3500) => push('warning', message, duration),
  info: (message, duration = 3000) => push('info', message, duration),
  dismiss
}

export default toast
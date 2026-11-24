const pad = (value) => String(value).padStart(2, '0')

export const formatTime = (value) => {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, 19)
}

export const formatClock = (value) => {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(11, 19)
}

export const parseJson = (raw) => {
  if (!raw) return null
  try {
    return typeof raw === 'string' ? JSON.parse(raw) : raw
  } catch (error) {
    return null
  }
}

// 时间一律按本地墙钟（后端存的和界面显示的都是它）。
// 不要用 toISOString()——那是 UTC，会让筛选条件整体偏 8 小时。
export const toLocalIso = (value) => {
  if (!value) return null
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  )
}

// 取窗口起点：按本地墙钟回推，与库里 reported_at 的口径一致
export const isoBefore = (milliseconds) => toLocalIso(new Date(Date.now() - milliseconds))
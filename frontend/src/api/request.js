import axios from 'axios'

const request = axios.create({
  baseURL: '/api',
  timeout: 8000
})

let unauthorizedHandler = null

/** 由 main.js 注入“跳转登录页”的行为，避免 api 层直接依赖 router 产生循环引用 */
export const setUnauthorizedHandler = (handler) => {
  unauthorizedHandler = handler
}

request.interceptors.request.use((config) => {
  const token = localStorage.getItem('robot-cloud-token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

request.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status
    const url = error.config?.url || ''
    const isLoginRequest = url.includes('/auth/login')
    if (status === 401 && !isLoginRequest && unauthorizedHandler) {
      unauthorizedHandler()
    }
    return Promise.reject(error)
  }
)

export default request
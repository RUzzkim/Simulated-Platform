import { reactive } from 'vue'
import request from '../api/request'

const TOKEN_KEY = 'robot-cloud-token'
const USER_KEY = 'robot-cloud-user'

const readUser = () => {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch (error) {
    return null
  }
}

const state = reactive({
  token: localStorage.getItem(TOKEN_KEY) || '',
  user: readUser()
})

export const auth = state

export const isLoggedIn = () => !!state.token

export const hasRole = (...roles) => !!state.user && roles.includes(state.user.role)

/** 写操作（注册/重命名/下发指令/接入凭据）只开放给 ADMIN 与 OPERATOR */
export const canWrite = () => hasRole('ADMIN', 'OPERATOR')

const persist = () => {
  if (state.token) {
    localStorage.setItem(TOKEN_KEY, state.token)
  } else {
    localStorage.removeItem(TOKEN_KEY)
  }
  if (state.user) {
    localStorage.setItem(USER_KEY, JSON.stringify(state.user))
  } else {
    localStorage.removeItem(USER_KEY)
  }
}

export const setSession = ({ token, user }) => {
  state.token = token
  state.user = user
  persist()
}

export const clearSession = () => {
  state.token = ''
  state.user = null
  persist()
}

export const login = async (username, password) => {
  const { data } = await request.post('/auth/login', { username, password })
  setSession(data)
  return data
}

export const refreshMe = async () => {
  const { data } = await request.get('/auth/me')
  state.user = data
  persist()
  return data
}

export const logout = () => clearSession()
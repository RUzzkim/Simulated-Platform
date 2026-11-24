import { createRouter, createWebHistory } from 'vue-router'
import { auth, isLoggedIn, hasRole } from '../stores/auth'

// 路由懒加载：每个页面单独打包，首屏只加载登录/设备总览所需代码
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('../views/Login.vue'), meta: { public: true } },
    { path: '/register', name: 'register', component: () => import('../views/Register.vue'), meta: { public: true } },
    { path: '/', name: 'devices', component: () => import('../views/DeviceList.vue') },
    { path: '/devices/:id', name: 'device-detail', component: () => import('../views/DeviceDetail.vue') },
    { path: '/system', name: 'system-status', component: () => import('../views/SystemStatus.vue') },
    { path: '/analysis', name: 'analysis', component: () => import('../views/Analysis.vue') },
    {
      path: '/publish',
      name: 'publish',
      component: () => import('../views/PublishCenter.vue'),
      meta: { roles: ['ADMIN', 'OPERATOR'] }
    },
    {
      path: '/audit-logs',
      name: 'audit-logs',
      component: () => import('../views/AuditLogs.vue'),
      meta: { roles: ['ADMIN', 'OPERATOR'] }
    },
    { path: '/users', name: 'users', component: () => import('../views/Users.vue'), meta: { roles: ['ADMIN'] } }
  ]
})

router.beforeEach((to) => {
  if (to.meta.public) {
    return true
  }
  if (!isLoggedIn()) {
    return { name: 'login', query: to.fullPath === '/' ? {} : { redirect: to.fullPath } }
  }
  if (to.meta.roles && !hasRole(...to.meta.roles)) {
    return { name: 'devices' }
  }
  return true
})

/** 令牌失效后由 axios 拦截器调用 */
export const redirectToLogin = () => {
  if (auth.token) {
    auth.token = ''
  }
  if (router.currentRoute.value.name !== 'login') {
    router.replace({ name: 'login' })
  }
}

export default router
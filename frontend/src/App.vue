<template>
  <div class="flex h-screen flex-col">
    <header v-if="!isLoginPage" class="flex h-[60px] shrink-0 items-center gap-4 bg-[#1f2d3d] px-5 text-white">
      <router-link to="/" class="text-[17px] leading-none font-semibold whitespace-nowrap text-white">
        机械臂云端监控平台
      </router-link>
      <nav class="flex flex-1 items-center gap-1">
        <router-link
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="rounded-sm px-4 py-2 text-sm transition-colors"
          :class="
            route.path === item.to
              ? 'border-b-2 border-[#409eff] font-medium text-white'
              : 'border-b-2 border-transparent text-[#c0c9d4] hover:text-white'
          "
        >
          {{ item.label }}
        </router-link>
      </nav>
      <Badge v-if="auth.user" :class="roleClass(auth.user.role)">{{ auth.user.role }}</Badge>
      <span class="text-[13px] text-[#e6ebf1]">{{ auth.user?.displayName || auth.user?.username }}</span>
      <DropdownMenu>
        <DropdownMenuTrigger as-child>
          <Button
            variant="ghost"
            size="sm"
            class="h-7 gap-1 px-2 text-[#9aa7b4] hover:bg-white/10 hover:text-white"
          >
            账号
            <ChevronDown class="size-3.5" />
            <span class="sr-only">账号菜单</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" class="w-44">
          <DropdownMenuLabel>
            {{ auth.user?.displayName || auth.user?.username }} · {{ auth.user?.role }}
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem @select="openPasswordDialog">修改密码</DropdownMenuItem>
          <DropdownMenuItem variant="destructive" @select="logoutVisible = true">退出登录</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </header>
    <main
      class="flex-1 overflow-auto p-5"
      :style="{
        backgroundColor: '#f6f8fc',
        backgroundImage: [
          'radial-gradient(at 0% 0%, hsla(212, 90%, 88%, 0.85) 0px, transparent 55%)',
          'radial-gradient(at 100% 0%, hsla(255, 85%, 90%, 0.75) 0px, transparent 55%)',
          'radial-gradient(at 100% 100%, hsla(190, 90%, 88%, 0.70) 0px, transparent 55%)',
          'radial-gradient(at 0% 100%, hsla(280, 75%, 92%, 0.60) 0px, transparent 55%)'
        ].join(', '),
        backgroundRepeat: 'no-repeat',
        backgroundSize: '100% 100%'
      }"
    >
      <router-view />
    </main>

    <Toaster />

    <Dialog v-model:open="passwordVisible">
      <DialogContent class="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>修改密码</DialogTitle>
          <DialogDescription>需要先验证原密码，新密码至少 8 位；改完当前会话不受影响。</DialogDescription>
        </DialogHeader>
        <div class="grid gap-4">
          <div class="grid gap-2">
            <Label for="current-password">原密码</Label>
            <Input
              id="current-password"
              v-model="passwordForm.currentPassword"
              type="password"
              @keyup.enter="submitPassword"
            />
          </div>
          <div class="grid gap-2">
            <Label for="new-password">新密码</Label>
            <Input
              id="new-password"
              v-model="passwordForm.newPassword"
              type="password"
              placeholder="至少 8 位"
              @keyup.enter="submitPassword"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="passwordVisible = false">取消</Button>
          <Button :disabled="saving" @click="submitPassword">{{ saving ? '保存中…' : '保存' }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="logoutVisible">
      <DialogContent class="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>退出登录</DialogTitle>
          <DialogDescription>确认退出登录？退出后需要重新输入账号和密码。</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" @click="logoutVisible = false">取消</Button>
          <Button variant="destructive" @click="confirmLogout">退出登录</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChevronDown } from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import Toaster from '@/components/Toaster.vue'
import { toast } from '@/lib/toast'
import { auth, clearSession, hasRole } from './stores/auth'
import { changePassword } from './api/auth'

const route = useRoute()
const router = useRouter()
const passwordVisible = ref(false)
const logoutVisible = ref(false)
const saving = ref(false)
const passwordForm = reactive({ currentPassword: '', newPassword: '' })

const isLoginPage = computed(() => route.name === 'login' || route.name === 'register')
const isAdmin = computed(() => hasRole('ADMIN'))
const canViewAudit = computed(() => hasRole('ADMIN', 'OPERATOR'))
const canDispatch = computed(() => hasRole('ADMIN', 'OPERATOR'))

const navItems = computed(() => [
  { to: '/', label: '设备总览' },
  { to: '/analysis', label: '分析中心' },
  { to: '/system', label: '系统状态' },
  ...(canDispatch.value ? [{ to: '/publish', label: '下发中心' }] : []),
  ...(canViewAudit.value ? [{ to: '/audit-logs', label: '审计日志' }] : []),
  ...(isAdmin.value ? [{ to: '/users', label: '账号管理' }] : [])
])

const ROLE_CLASS = {
  ADMIN: 'border-red-400/40 bg-red-500/20 text-red-200',
  OPERATOR: 'border-amber-400/40 bg-amber-500/20 text-amber-200',
  VIEWER: 'border-slate-400/40 bg-slate-500/20 text-slate-200'
}
const roleClass = (role) => ROLE_CLASS[role] || ROLE_CLASS.VIEWER

const openPasswordDialog = () => {
  passwordForm.currentPassword = ''
  passwordForm.newPassword = ''
  passwordVisible.value = true
}

const confirmLogout = () => {
  logoutVisible.value = false
  clearSession()
  router.replace({ name: 'login' })
}

const submitPassword = async () => {
  if (passwordForm.newPassword.length < 8) {
    toast.warning('新密码至少 8 位')
    return
  }
  saving.value = true
  try {
    await changePassword({ ...passwordForm })
    toast.success('密码已修改')
    passwordVisible.value = false
  } catch (error) {
    toast.error(error.response?.data?.error || '修改失败')
  } finally {
    saving.value = false
  }
}
</script>
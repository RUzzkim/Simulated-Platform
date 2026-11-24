<template>
  <div class="fixed inset-0 flex items-center justify-center overflow-auto p-4">
    <!-- 全屏背景：fixed 铺满视口，卡片滚动时也不会露出背景外的空白（与登录页共用同一段视频/封面） -->
    <video
      class="fixed inset-0 h-full w-full object-cover"
      autoplay
      loop
      muted
      playsinline
      :poster="bgPoster"
    >
      <source :src="bgVideo" type="video/mp4" />
    </video>
    <!-- 半透明遮罩：压暗背景 -->
    <div class="fixed inset-0 bg-slate-950/45" />

    <!-- 深色半透明卡（无磨砂），透出深色壁纸又保证浅色文字可读 -->
    <div
      class="relative z-10 my-auto w-full max-w-[400px] rounded-2xl border border-white/15 bg-slate-950/25 p-6 text-white shadow-2xl"
    >
      <div class="mb-4">
        <h1 class="text-lg font-semibold tracking-tight text-white">注册平台账号</h1>
        <p class="mt-1 text-sm text-slate-200">提交后需要管理员审批通过才能登录</p>
      </div>

      <form v-if="!submitted" class="grid gap-3" @submit.prevent="submit">
        <div class="grid gap-2">
          <Label for="reg-username" class="text-slate-100">用户名</Label>
          <Input
            id="reg-username"
            v-model="form.username"
            placeholder="zhangsan"
            autofocus
            autocomplete="username"
            class="bg-white/90"
          />
        </div>
        <div class="grid gap-2">
          <Label for="reg-display" class="text-slate-100">显示名</Label>
          <Input id="reg-display" v-model="form.displayName" placeholder="张三" class="bg-white/90" />
        </div>
        <div class="grid gap-2">
          <Label class="text-slate-100">申请角色</Label>
          <Select v-model="form.role">
            <SelectTrigger class="w-full bg-white/90">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="role in roleOptions" :key="role.value" :value="role.value">
                {{ role.label }}
              </SelectItem>
            </SelectContent>
          </Select>
          <p class="text-xs text-slate-300">最终角色以管理员审批为准</p>
        </div>
        <div class="grid gap-2">
          <Label for="reg-password" class="text-slate-100">密码</Label>
          <Input
            id="reg-password"
            v-model="form.password"
            type="password"
            placeholder="至少 8 位"
            autocomplete="new-password"
            class="bg-white/90"
          />
        </div>
        <div class="grid gap-2">
          <Label for="reg-confirm" class="text-slate-100">确认密码</Label>
          <Input
            id="reg-confirm"
            v-model="form.confirm"
            type="password"
            placeholder="再次输入密码"
            autocomplete="new-password"
            class="bg-white/90"
            @keyup.enter="submit"
          />
        </div>
        <Button type="submit" class="w-full" :disabled="loading">
          {{ loading ? '提交中…' : '提交注册申请' }}
        </Button>
      </form>

      <div v-else class="grid gap-3 py-2 text-center">
        <p class="text-sm font-medium text-white">注册申请已提交</p>
        <p class="text-sm leading-relaxed text-slate-200">
          账号 <span class="font-medium text-white">{{ form.username }}</span> 正在等待管理员审批，
          审批通过后即可用该账号登录。
        </p>
      </div>

      <p class="mt-4 text-xs leading-relaxed text-slate-200">
        已有账号？
        <router-link to="/login" class="font-medium text-[#7cc0ff] hover:underline">返回登录</router-link>
      </p>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { toast } from '@/lib/toast'
import { register } from '../api/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

const roleOptions = [
  { label: 'OPERATOR（操作员：注册设备/下发指令）', value: 'OPERATOR' },
  { label: 'VIEWER（只读：仅查看数据）', value: 'VIEWER' },
  { label: 'ADMIN（管理员：账号与全部操作）', value: 'ADMIN' }
]

// 全屏背景：与登录页共用 public/login-bg.mp4（视频）/ login-bg.jpg（封面）。
const bgVideo = `${import.meta.env.BASE_URL}login-bg.mp4`
const bgPoster = `${import.meta.env.BASE_URL}login-bg.jpg`

const loading = ref(false)
const submitted = ref(false)
const form = reactive({ username: '', displayName: '', role: 'OPERATOR', password: '', confirm: '' })

const submit = async () => {
  if (!form.username.trim()) {
    toast.warning('请输入用户名')
    return
  }
  if (form.password.length < 8) {
    toast.warning('密码至少 8 位')
    return
  }
  if (form.password !== form.confirm) {
    toast.warning('两次输入的密码不一致')
    return
  }
  loading.value = true
  try {
    await register({
      username: form.username.trim(),
      displayName: form.displayName.trim() || undefined,
      role: form.role,
      password: form.password
    })
    submitted.value = true
    toast.success('注册申请已提交，等待管理员审批')
  } catch (error) {
    toast.error(error.response?.data?.error || '注册失败')
  } finally {
    loading.value = false
  }
}
</script>

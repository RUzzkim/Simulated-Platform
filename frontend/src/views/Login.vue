<template>
  <div class="fixed inset-0 flex items-center justify-center overflow-auto p-4">
    <!-- 全屏背景：优先播放视频（放 public/login-bg.mp4），无视频时显示 poster 静态图（public/login-bg.jpg） -->
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
    <!-- 半透明遮罩：压暗背景，保证卡片与文字可读 -->
    <div class="fixed inset-0 bg-slate-950/45" />
    <div
      class="relative z-10 grid w-full max-w-[860px] overflow-hidden rounded-2xl border shadow-2xl md:grid-cols-[1.05fr_1fr]"
    >
      <!-- 品牌区：工业深色 + 团队LOGO -->
      <div
        class="relative hidden flex-col justify-between overflow-hidden bg-slate-950/30 p-8 text-white md:flex"
      >
        <div class="relative flex items-center gap-3">
          <img :src="logoUrl" alt="团队logo" class="size-20 shrink-0" />
          <div class="leading-tight">
            <p class="text-base font-semibold text-white">仿真机械臂云端监控平台</p>
            <p class="text-xs text-slate-200">Simulated Robot Arm Cloud Platform</p>
          </div>
        </div>
        <div class="relative">
          <h2 class="text-2xl font-semibold tracking-tight text-white">端 — 边 — 云协同</h2>
          <p class="mt-2 text-sm leading-relaxed text-slate-200">
            仿真、实时控制与云端管理一体化，实时监控机械臂状态。
          </p>
          <ul class="mt-5 grid gap-2 text-sm text-slate-100">
            <li v-for="f in features" :key="f" class="flex items-center gap-2">
              <span class="size-1.5 rounded-full bg-[#409eff]" />
              {{ f }}
            </li>
          </ul>
        </div>
        <p class="relative text-[11px] text-slate-300">@国创小分队</p>
      </div>

      <!-- 登录表单：深色半透明底，透出壁纸又保证浅色文字可读 -->
      <div class="flex flex-col justify-center bg-slate-950/30 p-8">
        <div class="mb-6 flex items-center gap-3 md:hidden">
          <img :src="logoUrl" alt="机械臂标志" class="size-14 shrink-0" />
          <div class="leading-tight">
            <p class="text-base font-semibold text-white">机械臂云端监控平台</p>
            <p class="text-xs text-slate-200">端 — 边 — 云协同</p>
          </div>
        </div>
        <div class="mb-5 hidden md:block">
          <h1 class="text-xl font-semibold tracking-tight text-white">欢迎回来</h1>
          <p class="text-sm text-slate-200">请使用平台账号登录</p>
        </div>
        <form class="grid gap-4" @submit.prevent="submit">
          <div class="grid gap-2">
            <Label for="login-username" class="text-slate-100">用户名</Label>
            <Input
              id="login-username"
              v-model="form.username"
              placeholder="如：admin"
              autofocus
              autocomplete="username"
              class="bg-white/90"
            />
          </div>
          <div class="grid gap-2">
            <Label for="login-password" class="text-slate-100">密码</Label>
            <Input
              id="login-password"
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              autocomplete="current-password"
              class="bg-white/90"
            />
          </div>
          <Button type="submit" class="w-full" :disabled="loading">
            {{ loading ? '登录中…' : '登录' }}
          </Button>
        </form>
        <div class="mt-5 grid gap-2">
          <p class="text-xs leading-relaxed text-slate-200">
            只读账号目前仅支持查看数据，注册设备/下发指令等需要操作员及以上身份。
          </p>
          <p class="text-xs leading-relaxed text-slate-200">
            还没有账号？
            <router-link to="/register" class="font-medium text-[#7cc0ff] hover:underline">申请注册</router-link>
            （需管理员审批）
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from '@/lib/toast'
import { login } from '../stores/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

// LOGO 从 public/ 根目录读取；替换图片只需覆盖 public/robot-logo.png。
const logoUrl = `${import.meta.env.BASE_URL}robot-logo.png`
// 全屏背景：放 public/login-bg.mp4 就是视频背景，放 public/login-bg.jpg 就是图片背景（也作视频加载前的封面）。
const bgVideo = `${import.meta.env.BASE_URL}login-bg.mp4`
const bgPoster = `${import.meta.env.BASE_URL}login-bg.jpg`
const features = ['实时遥测监控', '故障边沿检测', '健康评分与异常检测', '参数/策略版本化下发']

const submit = async () => {
  if (!form.username.trim() || !form.password) {
    toast.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const session = await login(form.username.trim(), form.password)
    toast.success(`欢迎，${session.user.displayName || session.user.username}`)
    router.replace(route.query.redirect || '/')
  } catch (error) {
    toast.error(error.response?.data?.error || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>
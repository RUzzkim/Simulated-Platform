<template>
  <div class="flex flex-col gap-6 p-1">
    <div class="flex flex-wrap items-center gap-3">
      <div>
        <h2 class="text-xl font-semibold tracking-tight">设备总览</h2>
        <p class="text-muted-foreground text-sm">
          共 {{ devices.length }} 台设备 · 每 5 秒自动刷新，点击行查看详情
          <span v-if="lastUpdated">· 更新于 {{ formatClock(lastUpdated) }}</span>
        </p>
      </div>
      <div class="ml-auto flex items-center gap-2">
        <Button variant="outline" size="sm" :disabled="loading" @click="load()">
          <RefreshCw :class="loading ? 'animate-spin' : ''" />
          刷新
        </Button>
        <Button v-if="canWrite()" size="sm" @click="openRegister">
          <Plus />
          注册设备
        </Button>
      </div>
    </div>

    <p v-if="error" class="text-destructive text-sm">{{ error }}</p>

    <Card class="gap-0 py-0">
      <CardContent class="px-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead class="w-[80px] pl-6">ID</TableHead>
              <TableHead>设备编号</TableHead>
              <TableHead>设备名称</TableHead>
              <TableHead class="w-[140px]">状态</TableHead>
              <TableHead class="w-[220px]">最近上报</TableHead>
              <TableHead class="w-[100px] pr-6 text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="row in devices"
              :key="row.id"
              class="cursor-pointer"
              @click="openDetail(row)"
            >
              <TableCell class="text-muted-foreground pl-6 tabular-nums">{{ row.id }}</TableCell>
              <TableCell class="font-medium">{{ row.deviceCode }}</TableCell>
              <TableCell>{{ row.name || '-' }}</TableCell>
              <TableCell>
                <Badge :class="statusClass(row.status)">{{ row.status }}</Badge>
              </TableCell>
              <TableCell class="text-muted-foreground tabular-nums">
                {{ formatTime(row.updatedAt) }}
              </TableCell>
              <TableCell class="pr-6 text-right">
                <Button variant="ghost" size="sm" @click.stop="openDetail(row)">详情</Button>
              </TableCell>
            </TableRow>
            <TableRow v-if="!devices.length && !loading">
              <TableCell colspan="6" class="text-muted-foreground h-24 text-center">
                暂无设备，点击右上角「注册设备」新增
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>

    <Dialog v-model:open="registerVisible">
      <DialogContent class="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>注册设备</DialogTitle>
          <DialogDescription>
            设备编号是边/端上报时的唯一标识，注册后可在详情页签发接入凭据。
          </DialogDescription>
        </DialogHeader>
        <div class="grid gap-4">
          <div class="grid gap-2">
            <Label for="register-code">设备编号</Label>
            <Input
              id="register-code"
              v-model="registerForm.deviceCode"
              placeholder="robot-001"
              @keyup.enter="submitRegister"
            />
          </div>
          <div class="grid gap-2">
            <Label for="register-name">设备名称</Label>
            <Input
              id="register-name"
              v-model="registerForm.name"
              placeholder="机械臂一号"
              @keyup.enter="submitRegister"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="registerVisible = false">取消</Button>
          <Button :disabled="saving" @click="submitRegister">
            {{ saving ? '保存中…' : '保存' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { toast } from '@/lib/toast'
import { Plus, RefreshCw } from 'lucide-vue-next'
import { getDevices, registerDevice } from '@/api/device'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { canWrite } from '@/stores/auth'
import { formatClock, formatTime, toLocalIso } from '@/utils/format'

const router = useRouter()
const devices = ref([])
const loading = ref(false)
const error = ref('')
const lastUpdated = ref('')
const saving = ref(false)
const registerVisible = ref(false)
const registerForm = reactive({ deviceCode: '', name: '' })
let timer = null

const load = async (silent = false) => {
  if (!silent) loading.value = true
  try {
    const { data } = await getDevices()
    devices.value = data
    lastUpdated.value = toLocalIso(new Date())
    error.value = ''
  } catch (e) {
    error.value = e.response?.data?.error || '读取设备列表失败'
  } finally {
    if (!silent) loading.value = false
  }
}

const STATUS_CLASS = {
  ONLINE: 'border-transparent bg-emerald-100 text-emerald-800',
  RUNNING: 'border-transparent bg-emerald-100 text-emerald-800',
  OFFLINE: 'border-transparent bg-slate-200 text-slate-600'
}

const statusClass = (status) => STATUS_CLASS[status] || 'border-transparent bg-amber-100 text-amber-800'

const openDetail = (row) => router.push(`/devices/${row.id}`)

const openRegister = () => {
  registerForm.deviceCode = ''
  registerForm.name = ''
  registerVisible.value = true
}

const submitRegister = async () => {
  if (!registerForm.deviceCode.trim()) {
    toast.error('设备编号不能为空')
    return
  }
  saving.value = true
  try {
    await registerDevice({
      deviceCode: registerForm.deviceCode.trim(),
      name: registerForm.name.trim()
    })
    toast.success('设备已注册')
    registerVisible.value = false
    await load()
  } catch (error) {
    toast.error(error.response?.data?.error || '注册失败')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  load()
  timer = setInterval(() => load(true), 5000)
})

onUnmounted(() => clearInterval(timer))
</script>
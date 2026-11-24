<template>
  <div class="flex flex-col gap-6 p-1">
    <div class="flex flex-wrap items-center gap-3">
      <div>
        <h2 class="text-xl font-semibold tracking-tight">审计日志</h2>
        <p class="text-muted-foreground text-sm">
          登录 / 账号 / 设备 / 指令 / 凭据 / 边缘事件全埋点 · 第 {{ page + 1 }} 页，本页 {{ logs.length }} 条
        </p>
      </div>
      <div class="ml-auto flex items-center gap-2">
        <Button variant="outline" size="sm" :disabled="loading" @click="reset">重置</Button>
        <Button size="sm" :disabled="loading" @click="reload">
          <Search />
          {{ loading ? '查询中…' : '查询' }}
        </Button>
      </div>
    </div>

    <Card>
      <CardHeader>
        <CardTitle>筛选条件</CardTitle>
        <CardDescription>动作、来源、对象编号与时间范围可组合使用</CardDescription>
      </CardHeader>
      <CardContent>
        <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div class="grid gap-2">
            <Label for="audit-action">动作</Label>
            <Select :model-value="filters.action || ALL" @update:model-value="onActionChange">
              <SelectTrigger id="audit-action" class="w-full">
                <SelectValue placeholder="全部动作" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem :value="ALL">全部动作</SelectItem>
                <SelectItem v-for="item in actions" :key="item" :value="item">{{ item }}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="grid gap-2">
            <Label for="audit-actor">来源</Label>
            <Select :model-value="filters.actorType || ALL" @update:model-value="onActorChange">
              <SelectTrigger id="audit-actor" class="w-full">
                <SelectValue placeholder="全部来源" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem :value="ALL">全部来源</SelectItem>
                <SelectItem v-for="item in actorOptions" :key="item.value" :value="item.value">
                  {{ item.label }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="grid gap-2">
            <Label for="audit-target">对象编号</Label>
            <Input
              id="audit-target"
              v-model="filters.targetId"
              placeholder="如 robot-001"
              @keyup.enter="reload"
            />
          </div>
          <div class="grid gap-2 md:col-span-2">
            <Label>时间范围</Label>
            <div class="flex items-center gap-2">
              <Input v-model="filters.from" type="datetime-local" lang="zh-CN" class="w-full min-w-[160px]" />
              <span class="text-muted-foreground text-xs">～</span>
              <Input v-model="filters.to" type="datetime-local" lang="zh-CN" class="w-full min-w-[160px]" />
            </div>
          </div>
        </div>
      </CardContent>
    </Card>

    <Card class="gap-0 py-0">
      <CardContent class="px-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead class="w-[180px] pl-6">时间</TableHead>
              <TableHead class="w-[170px]">动作</TableHead>
              <TableHead class="w-[110px]">来源</TableHead>
              <TableHead class="w-[140px]">操作者</TableHead>
              <TableHead class="w-[160px]">对象</TableHead>
              <TableHead class="w-[100px]">结果</TableHead>
              <TableHead class="min-w-[200px]">详情</TableHead>
              <TableHead class="w-[140px] pr-6">来源 IP</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="row in logs" :key="row.id">
              <TableCell class="text-muted-foreground pl-6 tabular-nums">
                {{ formatTime(row.occurredAt) }}
              </TableCell>
              <TableCell>{{ row.action }}</TableCell>
              <TableCell>
                <Badge :class="actorClass(row.actorType)">{{ row.actorType }}</Badge>
              </TableCell>
              <TableCell>{{ row.actorName || '-' }}</TableCell>
              <TableCell class="text-muted-foreground">
                {{ row.targetType ? `${row.targetType}:${row.targetId}` : '-' }}
              </TableCell>
              <TableCell>
                <Badge :class="resultClass(row.result)">{{ row.result }}</Badge>
              </TableCell>
              <TableCell class="text-muted-foreground">
                <div class="max-w-[360px] truncate" :title="row.detail || ''">{{ row.detail || '-' }}</div>
              </TableCell>
              <TableCell class="text-muted-foreground pr-6 tabular-nums">{{ row.clientIp }}</TableCell>
            </TableRow>
            <TableRow v-if="!logs.length">
              <TableCell colspan="8" class="text-muted-foreground h-24 text-center">
                {{ loading ? '查询中…' : '没有符合条件的审计记录' }}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>

        <div class="flex flex-wrap items-center gap-3 border-t px-6 py-3">
          <Button variant="outline" size="sm" :disabled="page === 0 || loading" @click="prev">上一页</Button>
          <span class="text-muted-foreground text-xs">第 {{ page + 1 }} 页，本页 {{ logs.length }} 条</span>
          <Button variant="outline" size="sm" :disabled="logs.length < size || loading" @click="next">
            下一页
          </Button>
        </div>
      </CardContent>
    </Card>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { toast } from '@/lib/toast'
import { Search } from 'lucide-vue-next'
import { getAuditActions, getAuditLogs } from '../api/audit'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatTime, toLocalIso } from '../utils/format'

// reka-ui 的 Select 不接受空字符串作为选项值，用哨兵值表示「全部」
const ALL = '__all__'
const actorOptions = [
  { label: '用户操作 (USER)', value: 'USER' },
  { label: '设备上报 (DEVICE)', value: 'DEVICE' },
  { label: '系统 (SYSTEM)', value: 'SYSTEM' },
  { label: '登录失败 (ANONYMOUS)', value: 'ANONYMOUS' }
]

const ACTOR_CLASS = {
  USER: 'border-transparent bg-blue-100 text-blue-700',
  DEVICE: 'border-transparent bg-emerald-100 text-emerald-800',
  SYSTEM: 'border-transparent bg-slate-200 text-slate-700',
  ANONYMOUS: 'border-transparent bg-amber-100 text-amber-800'
}

const logs = ref([])
const actions = ref([])
const loading = ref(false)
const page = ref(0)
const size = 20
const filters = reactive({ action: '', actorType: '', targetId: '', from: '', to: '' })

const actorClass = (type) => ACTOR_CLASS[type] || 'border-transparent bg-slate-200 text-slate-700'
const resultClass = (result) =>
  result === 'SUCCESS' ? 'border-transparent bg-emerald-100 text-emerald-800' : 'border-transparent bg-red-100 text-red-700'

const onActionChange = (value) => {
  filters.action = value === ALL ? '' : value
}

const onActorChange = (value) => {
  filters.actorType = value === ALL ? '' : value
}


const buildParams = () => {
  const params = { page: page.value, size }
  if (filters.action) params.action = filters.action
  if (filters.actorType) params.actorType = filters.actorType
  if (filters.targetId) params.targetId = filters.targetId.trim()
  const from = toLocalIso(filters.from)
  const to = toLocalIso(filters.to)
  if (from) params.from = from
  if (to) params.to = to
  return params
}

const load = async () => {
  loading.value = true
  try {
    const { data } = await getAuditLogs(buildParams())
    logs.value = data
  } catch (error) {
    toast.error(error.response?.data?.error || '查询审计日志失败')
  } finally {
    loading.value = false
  }
}

const reload = () => {
  page.value = 0
  load()
}

const reset = () => {
  filters.action = ''
  filters.actorType = ''
  filters.targetId = ''
  filters.from = ''
  filters.to = ''
  reload()
}

const prev = () => {
  if (page.value > 0) {
    page.value -= 1
    load()
  }
}

const next = () => {
  if (logs.value.length === size) {
    page.value += 1
    load()
  }
}

onMounted(async () => {
  load()
  try {
    const { data } = await getAuditActions()
    actions.value = data
  } catch (error) {
    // 过滤下拉数据拿不到不影响主表格
  }
})
</script>
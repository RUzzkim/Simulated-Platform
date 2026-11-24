<template>
  <div class="flex flex-col gap-6 p-1">
    <div class="flex flex-wrap items-center gap-3">
      <div>
        <h2 class="text-xl font-semibold tracking-tight">分析中心</h2>
        <p class="text-muted-foreground text-sm">
          设备健康评分与遥测异常检测 · 综合分越低越靠前
          <span v-if="lastUpdated">· 更新于 {{ formatClock(lastUpdated) }}</span>
        </p>
      </div>
      <div class="ml-auto flex items-center gap-2">
        <Select :model-value="String(windowHours)" @update:model-value="onWindowChange">
          <SelectTrigger size="sm" class="w-[130px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="opt in windowOptions" :key="opt.value" :value="String(opt.value)">
              {{ opt.label }}
            </SelectItem>
          </SelectContent>
        </Select>
        <Button size="sm" :disabled="loading" @click="load">
          <RefreshCw :class="loading ? 'animate-spin' : ''" />
          刷新
        </Button>
      </div>
    </div>

    <p v-if="error" class="text-destructive text-sm">{{ error }}</p>

    <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <Card v-for="item in summaryCards" :key="item.title">
        <CardHeader>
          <CardDescription>{{ item.title }}</CardDescription>
          <CardTitle class="text-2xl tabular-nums">{{ item.value }}</CardTitle>
          <CardAction>
            <Badge :class="item.badgeClass">{{ item.badge }}</Badge>
          </CardAction>
        </CardHeader>
        <CardContent>
          <p class="text-muted-foreground text-xs leading-relaxed">{{ item.hint }}</p>
        </CardContent>
      </Card>
    </div>

    <Card class="gap-0 py-0">
      <CardContent class="px-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead class="w-[80px] pl-6">评分</TableHead>
              <TableHead class="w-[70px]">等级</TableHead>
              <TableHead class="w-[180px]">设备</TableHead>
              <TableHead class="w-[110px]">可用性</TableHead>
              <TableHead class="w-[110px]">故障</TableHead>
              <TableHead class="w-[110px]">遥测</TableHead>
              <TableHead class="w-[150px]">重点关节</TableHead>
              <TableHead class="min-w-[160px] pr-6">说明</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="row in devices"
              :key="row.deviceId"
              class="cursor-pointer"
              @click="goDetail(row.deviceId)"
            >
              <TableCell class="pl-6">
                <span class="text-lg font-semibold tabular-nums" :class="scoreText(row.score)">{{ row.score }}</span>
              </TableCell>
              <TableCell>
                <Badge :class="gradeClass(row.grade)">{{ row.grade }}</Badge>
              </TableCell>
              <TableCell>
                <div class="font-medium">{{ row.name || row.deviceCode }}</div>
                <div class="text-muted-foreground text-xs">{{ row.deviceCode }}</div>
              </TableCell>
              <TableCell><SubScore :value="row.availability" /></TableCell>
              <TableCell><SubScore :value="row.faultHealth" /></TableCell>
              <TableCell><SubScore :value="row.telemetryHealth" /></TableCell>
              <TableCell class="text-muted-foreground text-xs">
                <span v-if="row.topAnomalyJoints?.length">
                  {{ row.topAnomalyJoints.map((j) => `${j.joint}(${j.anomalyPoints})`).join('，') }}
                </span>
                <span v-else>-</span>
              </TableCell>
              <TableCell class="text-muted-foreground text-xs">
                <div class="max-w-[280px] truncate" :title="(row.notes || []).join('；')">
                  {{ (row.notes || []).join('；') || '正常' }}
                </div>
              </TableCell>
            </TableRow>
            <TableRow v-if="!devices.length">
              <TableCell colspan="8" class="text-muted-foreground h-24 text-center">
                {{ loading ? '计算中…' : '暂无设备' }}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <div class="text-muted-foreground border-t px-6 py-3 text-xs leading-relaxed">
          综合分 = 可用性×0.25 + 故障×0.35 + 遥测×0.40。故障分按窗口内 WARNING/ERROR/CRITICAL 加权扣分；
          遥测分 = 100×(1−异常帧占比)，异常按每关节 effort/velocity 的均值±3σ 判定。点行进设备详情看曲线。
        </div>
      </CardContent>
    </Card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { RefreshCw } from 'lucide-vue-next'
import { getFleetHealth } from '@/api/analysis'
import { formatClock, toLocalIso } from '@/utils/format'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import SubScore from '@/components/SubScore.vue'

const router = useRouter()
const windowOptions = [
  { label: '最近 6 小时', value: 6 },
  { label: '最近 24 小时', value: 24 },
  { label: '最近 7 天', value: 168 },
  { label: '最近 30 天', value: 720 }
]
const windowHours = ref(24)
const devices = ref([])
const loading = ref(false)
const error = ref('')
const lastUpdated = ref('')

const GRADE_CLASS = {
  A: 'border-transparent bg-emerald-100 text-emerald-800',
  B: 'border-transparent bg-lime-100 text-lime-800',
  C: 'border-transparent bg-amber-100 text-amber-800',
  D: 'border-transparent bg-red-100 text-red-700'
}
const gradeClass = (grade) => GRADE_CLASS[grade] || GRADE_CLASS.D
const scoreText = (score) => {
  if (score >= 90) return 'text-emerald-600'
  if (score >= 75) return 'text-lime-600'
  if (score >= 60) return 'text-amber-600'
  return 'text-red-600'
}

const summaryCards = computed(() => {
  const total = devices.value.length
  const gradeD = devices.value.filter((d) => d.grade === 'D').length
  const gradeC = devices.value.filter((d) => d.grade === 'C').length
  const avg = total ? Math.round(devices.value.reduce((s, d) => s + d.score, 0) / total) : 0
  const worst = total ? devices.value[0] : null
  return [
    {
      title: '设备总数',
      value: total,
      badge: '机队',
      badgeClass: 'border-transparent bg-slate-200 text-slate-700',
      hint: '参与健康评估的设备数量'
    },
    {
      title: '平均健康分',
      value: avg,
      badge: avg >= 75 ? '良好' : avg >= 60 ? '一般' : '偏低',
      badgeClass: avg >= 75 ? 'border-transparent bg-emerald-100 text-emerald-800' : avg >= 60 ? 'border-transparent bg-amber-100 text-amber-800' : 'border-transparent bg-red-100 text-red-700',
      hint: '全机队综合分的算术平均'
    },
    {
      title: '需关注设备',
      value: gradeC + gradeD,
      badge: gradeD > 0 ? `${gradeD} 台 D 级` : '无 D 级',
      badgeClass: gradeD > 0 ? 'border-transparent bg-red-100 text-red-700' : 'border-transparent bg-amber-100 text-amber-800',
      hint: 'C 级及以下（综合分 < 75）建议排查'
    },
    {
      title: '最低分设备',
      value: worst ? worst.score : '-',
      badge: worst ? worst.grade : '-',
      badgeClass: worst ? gradeClass(worst.grade) : 'border-transparent bg-slate-200 text-slate-700',
      hint: worst ? worst.name || worst.deviceCode : '暂无设备'
    }
  ]
})

const onWindowChange = (value) => {
  windowHours.value = Number(value)
  load()
}

const goDetail = (id) => router.push(`/devices/${id}`)

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const { data } = await getFleetHealth({ windowHours: windowHours.value })
    devices.value = data
    lastUpdated.value = toLocalIso(new Date())
  } catch (e) {
    error.value = e.response?.data?.error || '读取健康分析失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

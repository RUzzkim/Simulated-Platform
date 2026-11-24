<template>
  <div class="flex flex-col gap-6 p-1">
    <div class="flex flex-wrap items-center gap-3">
      <div>
        <h2 class="text-xl font-semibold tracking-tight">系统运行状态</h2>
        <p class="text-muted-foreground text-sm">
          遥测批量写入水位、MQTT 入站健康度与设备在线情况
          <span v-if="lastUpdated">· 更新于 {{ formatClock(lastUpdated) }}</span>
        </p>
      </div>
      <div class="ml-auto flex items-center gap-2">
        <Badge :variant="autoRefresh ? 'secondary' : 'outline'">
          {{ autoRefresh ? '自动刷新 5s' : '已暂停' }}
        </Badge>
        <Button variant="outline" size="sm" @click="autoRefresh = !autoRefresh">
          {{ autoRefresh ? '暂停' : '继续' }}
        </Button>
        <Button size="sm" :disabled="loading" @click="load">
          <RefreshCw :class="loading ? 'animate-spin' : ''" />
          刷新
        </Button>
      </div>
    </div>

    <p v-if="error" class="text-destructive text-sm">{{ error }}</p>

    <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <Card v-for="item in cards" :key="item.title">
        <CardHeader>
          <CardDescription>{{ item.title }}</CardDescription>
          <CardTitle class="text-2xl tabular-nums">{{ item.value }}</CardTitle>
          <CardAction>
            <Badge :variant="item.badge.variant">{{ item.badge.text }}</Badge>
          </CardAction>
        </CardHeader>
        <CardContent>
          <p class="text-muted-foreground text-xs leading-relaxed">{{ item.hint }}</p>
        </CardContent>
      </Card>
    </div>

    <div class="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>遥测批量写入</CardTitle>
          <CardDescription>MQTT 线程只入队，单线程攒批后批量落库</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>指标</TableHead>
                <TableHead class="text-right">数值</TableHead>
                <TableHead>说明</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="row in writerRows" :key="row.label">
                <TableCell class="font-medium">{{ row.label }}</TableCell>
                <TableCell class="text-right tabular-nums">{{ row.value }}</TableCell>
                <TableCell class="text-muted-foreground">{{ row.hint }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>MQTT 入站</CardTitle>
          <CardDescription>坏报文只丢帧、不断连接</CardDescription>
        </CardHeader>
        <CardContent class="flex flex-col gap-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>指标</TableHead>
                <TableHead class="text-right">数值</TableHead>
                <TableHead>说明</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="row in mqttRows" :key="row.label">
                <TableCell class="font-medium">{{ row.label }}</TableCell>
                <TableCell class="text-right tabular-nums">{{ row.value }}</TableCell>
                <TableCell class="text-muted-foreground">{{ row.hint }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
          <Separator />
          <div class="text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
            <span>设备总数 {{ stats?.deviceTotal ?? '-' }}</span>
            <span>在线 {{ stats?.deviceOnline ?? '-' }}</span>
            <span>审计记录 {{ stats?.auditTotal ?? '-' }}</span>
            <span>运行时长 {{ uptimeText }}</span>
          </div>
        </CardContent>
      </Card>
    </div>

    <Card>
      <CardHeader>
        <CardTitle>遥测归档</CardTitle>
        <CardDescription>保留期之前的明细按「设备 + 小时」聚合成均值后删除，长期趋势改看 hourly 桶</CardDescription>
        <CardAction>
          <div class="flex items-center gap-2">
            <Input v-model="retentionDays" type="number" min="1" class="h-8 w-20" />
            <Button variant="outline" size="sm" :disabled="archiving" @click="archive(true)">试运行</Button>
            <Button v-if="isAdmin" variant="destructive" size="sm" :disabled="archiving" @click="archive(false)">
              执行归档
            </Button>
          </div>
        </CardAction>
      </CardHeader>
      <CardContent class="flex flex-col gap-3">
        <div class="grid gap-4 sm:grid-cols-3">
          <div>
            <div class="text-muted-foreground text-xs">明细行数</div>
            <div class="mt-1 text-lg font-medium tabular-nums">{{ formatNumber(stats?.telemetry?.detailRows) }}</div>
          </div>
          <div>
            <div class="text-muted-foreground text-xs">归档小时桶</div>
            <div class="mt-1 text-lg font-medium tabular-nums">{{ formatNumber(stats?.telemetry?.hourlyRows) }}</div>
          </div>
          <div>
            <div class="text-muted-foreground text-xs">最近归档</div>
            <div class="mt-1 text-sm font-medium tabular-nums">
              {{ stats?.telemetry?.lastArchivedAt ? formatTime(stats.telemetry.lastArchivedAt) : '尚未归档' }}
            </div>
          </div>
        </div>
        <p v-if="archiveResult" class="text-muted-foreground text-xs">{{ archiveResult }}</p>
        <p class="text-muted-foreground text-xs leading-relaxed">
          「试运行」只统计不删；「执行归档」会真的删掉保留期之外的明细（仅 ADMIN）。
          定时归档默认关闭，设 <code>TELEMETRY_ARCHIVE_ENABLED=true</code> 后每天 03:30 自动跑。
        </p>
      </CardContent>
    </Card>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RefreshCw } from 'lucide-vue-next'
import { getSystemStats, runArchive } from '@/api/system'
import { Input } from '@/components/ui/input'
import { toast } from '@/lib/toast'
import { hasRole } from '@/stores/auth'
import { formatClock, formatTime, toLocalIso } from '@/utils/format'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

const stats = ref(null)
const loading = ref(false)
const error = ref('')
const lastUpdated = ref('')
const autoRefresh = ref(true)
let timer = null

const writer = computed(() => stats.value?.telemetryWriter || null)
const router = computed(() => stats.value?.mqttRouter || null)

const formatNumber = (value) => (value === null || value === undefined ? '-' : Number(value).toLocaleString())

const uptimeText = computed(() => {
  const total = stats.value?.uptimeSeconds
  if (total === null || total === undefined) return '-'
  const days = Math.floor(total / 86400)
  const hours = Math.floor((total % 86400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  return [days ? `${days} 天` : '', hours ? `${hours} 小时` : '', `${minutes} 分`].filter(Boolean).join(' ')
})

const health = computed(() => {
  const dropped = writer.value?.dropped || 0
  const failed = writer.value?.failedFlushes || 0
  if (dropped > 0 || failed > 0) return { text: '有丢弃', variant: 'destructive' }
  return { text: '正常', variant: 'secondary' }
})

const cards = computed(() => [
  {
    title: '已入库遥测',
    value: formatNumber(writer.value?.inserted),
    badge: health.value,
    hint: `队列容量 ${formatNumber(writer.value?.capacity)}，队列占用 ${formatNumber(writer.value?.queueSize)}`
  },
  {
    title: '丢弃帧数',
    value: formatNumber(writer.value?.dropped),
    badge: { text: (writer.value?.dropped || 0) > 0 ? '需关注' : '无丢弃', variant: (writer.value?.dropped || 0) > 0 ? 'destructive' : 'outline' },
    hint: '队列满时丢弃并计数，持续增长说明要调大队列或加消费者'
  },
  {
    title: '在线设备',
    value: `${stats.value?.deviceOnline ?? '-'} / ${stats.value?.deviceTotal ?? '-'}`,
    badge: { text: '设备', variant: 'outline' },
    hint: `审计记录 ${formatNumber(stats.value?.auditTotal)} 条`
  },
  {
    title: '坏报文',
    value: formatNumber((router.value?.malformedDropped || 0) + (router.value?.handlerFailed || 0)),
    badge: { text: (router.value?.malformedDropped || 0) > 0 ? '需修设备' : '无异常', variant: (router.value?.malformedDropped || 0) > 0 ? 'destructive' : 'outline' },
    hint: '只丢当前帧、不断 MQTT 连接；持续增长说明有设备在发非严格 JSON'
  }
])

const writerRows = computed(() => [
  { label: '入队 enqueued', value: formatNumber(writer.value?.enqueued), hint: 'MQTT 线程写入队列的总帧数' },
  { label: '入库 inserted', value: formatNumber(writer.value?.inserted), hint: '批量落库成功的帧数' },
  { label: '丢弃 dropped', value: formatNumber(writer.value?.dropped), hint: '队列满被丢弃的帧数' },
  { label: '失败批次 failedFlushes', value: formatNumber(writer.value?.failedFlushes), hint: '单批落库异常次数' },
  { label: '批次数 flushCount', value: formatNumber(writer.value?.flushCount), hint: '累计提交的批次数' },
  { label: '最近批大小', value: formatNumber(writer.value?.lastBatchSize), hint: '单批上限 500' },
  { label: '最近耗时', value: writer.value ? `${writer.value.lastFlushMicros} µs` : '-', hint: '最近一批的落库耗时' }
])

const mqttRows = computed(() => [
  { label: '坏报文 malformedDropped', value: formatNumber(router.value?.malformedDropped), hint: 'JSON 解析失败，已丢弃' },
  { label: '处理失败 handlerFailed', value: formatNumber(router.value?.handlerFailed), hint: '解析成功但落库/处理异常' }
])

const retentionDays = ref(30)
const archiving = ref(false)
const archiveResult = ref('')
const isAdmin = computed(() => hasRole('ADMIN'))

const archive = async (dryRun) => {
  archiving.value = true
  try {
    const { data } = await runArchive({ retentionDays: Number(retentionDays.value) || 30, dryRun })
    const label = dryRun ? '试运行' : '已归档'
    archiveResult.value =
      `${label}（截止 ${formatTime(data.cutoff)}）：命中 ${data.candidates} 帧 / 处理 ${data.framesArchived} 帧 / ` +
      `${data.bucketsWritten} 个小时桶 / ${data.devicesTouched} 台设备`
    toast.success(dryRun ? '试运行完成，未删除数据' : '归档完成')
    await load()
  } catch (e) {
    toast.error(e.response?.data?.error || '归档失败')
  } finally {
    archiving.value = false
  }
}

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const { data } = await getSystemStats()
    stats.value = data
    lastUpdated.value = toLocalIso(new Date())
  } catch (e) {
    error.value = e.response?.data?.error || '读取系统状态失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  load()
  timer = setInterval(() => {
    if (autoRefresh.value) load()
  }, 5000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>
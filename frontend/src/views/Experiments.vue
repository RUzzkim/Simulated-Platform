<template>
  <div class="flex flex-col gap-6 p-1">
    <div class="flex flex-wrap items-center gap-3">
      <div>
        <h2 class="text-xl font-semibold tracking-tight">实验回放</h2>
        <p class="text-muted-foreground text-sm">
          V2.0 单关节卡滞实验记录 · 共 {{ total }} 条 · 第 {{ page + 1 }} 页
          <span v-if="lastUpdated">· 更新于 {{ formatClock(lastUpdated) }}</span>
        </p>
      </div>
      <div class="ml-auto flex items-center gap-2">
        <Button variant="outline" size="sm" :disabled="loading" @click="reset">
          <RotateCcw />
          重置
        </Button>
        <Button size="sm" :disabled="loading" @click="reload">
          <Search />
          {{ loading ? '查询中…' : '查询' }}
        </Button>
      </div>
    </div>

    <p v-if="error" class="text-destructive text-sm">{{ error }}</p>

    <Card>
      <CardHeader>
        <CardTitle>筛选条件</CardTitle>
        <CardDescription>运行 ID 支持前缀匹配，状态按任务结果过滤；设备 ID 可从设备详情跳转带入</CardDescription>
      </CardHeader>
      <CardContent>
        <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div class="grid gap-2">
            <Label for="experiment-run-id">运行 ID</Label>
            <Input
              id="experiment-run-id"
              v-model="filters.runId"
              placeholder="32 位十六进制或前缀"
              @keyup.enter="reload"
            />
          </div>
          <div class="grid gap-2">
            <Label for="experiment-status">任务状态</Label>
            <Select :model-value="filters.status || ALL" @update:model-value="onStatusChange">
              <SelectTrigger id="experiment-status" class="w-full">
                <SelectValue placeholder="全部状态" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem :value="ALL">全部状态</SelectItem>
                <SelectItem v-for="status in statusOptions" :key="status" :value="status">
                  {{ statusText(status) }} ({{ status }})
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="grid gap-2">
            <Label for="experiment-device">设备 ID（可选）</Label>
            <Input
              id="experiment-device"
              v-model="filters.deviceId"
              placeholder="如 1"
              @keyup.enter="reload"
            />
          </div>
        </div>
      </CardContent>
    </Card>

    <Card class="gap-0 py-0">
      <CardContent class="px-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead class="w-[190px] pl-6">运行 ID</TableHead>
              <TableHead class="min-w-[200px]">场景</TableHead>
              <TableHead class="w-[130px]">策略 / 算法</TableHead>
              <TableHead class="w-[130px]">任务状态</TableHead>
              <TableHead class="w-[110px]">故障关节</TableHead>
              <TableHead class="w-[110px]">检测延迟</TableHead>
              <TableHead class="w-[150px]">决策</TableHead>
              <TableHead class="w-[110px]">末端误差</TableHead>
              <TableHead class="w-[170px] pr-6">开始时间</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="row in runs"
              :key="row.run_id"
              class="cursor-pointer"
              @click="openDetail(row)"
            >
              <TableCell class="pl-6">
                <div class="flex items-center gap-1">
                  <span class="font-mono text-xs" :title="row.run_id">{{ shortId(row.run_id) }}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    class="h-6 px-1.5 text-xs"
                    @click.stop="copy(row.run_id)"
                  >
                    复制
                  </Button>
                </div>
              </TableCell>
              <TableCell>
                <div class="font-medium">{{ row.scenario?.scenario_id || '-' }}</div>
                <div class="text-muted-foreground text-xs">
                  {{ row.scenario?.split || '-' }} · seed {{ row.scenario?.seed ?? '-' }}
                </div>
              </TableCell>
              <TableCell>
                <div class="font-medium">{{ row.strategy || '-' }}</div>
                <div class="text-muted-foreground font-mono text-xs">{{ row.algorithm_version || '-' }}</div>
              </TableCell>
              <TableCell>
                <Badge :class="statusClass(runStatus(row))">{{ statusText(runStatus(row)) }}</Badge>
              </TableCell>
              <TableCell>
                <div class="font-medium">{{ faultJoint(row) }}</div>
                <div class="text-muted-foreground text-xs">{{ faultTypeText(row.fault?.type) }}</div>
              </TableCell>
              <TableCell class="tabular-nums">{{ numText(row.fault?.detection_latency_ms, 0, ' ms') }}</TableCell>
              <TableCell>
                <div>{{ actionText(row.decision?.action) }}</div>
                <div class="text-muted-foreground max-w-[150px] truncate text-xs" :title="row.decision?.reason || ''">
                  {{ row.decision?.reason || '-' }}
                </div>
              </TableCell>
              <TableCell class="tabular-nums">{{ numText(row.task?.final_ee_error_m, 4, ' m') }}</TableCell>
              <TableCell class="text-muted-foreground pr-6 tabular-nums">{{ formatEpoch(row.started_at_ms) }}</TableCell>
            </TableRow>
            <TableRow v-if="!runs.length">
              <TableCell colspan="9" class="text-muted-foreground h-24 text-center">
                {{ loading ? '加载中…' : error ? '加载失败，请重试' : '暂无实验记录' }}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>

        <div class="flex flex-wrap items-center gap-3 border-t px-6 py-3">
          <Button variant="outline" size="sm" :disabled="page === 0 || loading" @click="prev">上一页</Button>
          <span class="text-muted-foreground text-xs">
            第 {{ page + 1 }} 页 · 共 {{ total }} 条 · 本页 {{ runs.length }} 条
          </span>
          <Button variant="outline" size="sm" :disabled="!hasNext || loading" @click="next">下一页</Button>
        </div>
      </CardContent>
    </Card>

    <Dialog v-model:open="detailVisible" @update:open="onDetailOpenChange">
      <DialogContent class="sm:max-w-5xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>实验回放 · {{ shortId(detail.run?.run_id) }}</DialogTitle>
          <DialogDescription>
            {{ detail.run?.scenario?.description || '单关节卡滞实验运行详情' }}
          </DialogDescription>
          <div v-if="detail.run" class="mt-2 flex flex-wrap gap-2">
            <Button variant="outline" size="sm" @click="downloadDetail('json')">
              <Download />
              导出 JSON
            </Button>
            <Button variant="outline" size="sm" @click="downloadDetail('csv')">
              <Download />
              导出事件 CSV
            </Button>
          </div>
        </DialogHeader>

        <p v-if="detailError" class="text-destructive text-sm">{{ detailError }}</p>

        <template v-if="detail.run">
          <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Card v-for="item in summaryItems" :key="item.label" class="gap-1 py-3">
              <CardHeader class="px-4">
                <CardDescription class="text-xs">{{ item.label }}</CardDescription>
                <CardTitle class="text-base">{{ item.value }}</CardTitle>
              </CardHeader>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>运行详情</CardTitle>
              <CardDescription>场景、仿真参数、故障与轨迹元数据</CardDescription>
            </CardHeader>
            <CardContent>
              <div class="grid gap-x-8 gap-y-3 sm:grid-cols-2">
                <div v-for="item in metaItems" :key="item.label" class="min-w-0">
                  <div class="text-muted-foreground text-xs">{{ item.label }}</div>
                  <div class="mt-0.5 text-sm break-all" :class="item.mono ? 'font-mono text-xs' : ''">
                    {{ item.value }}
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>故障 / 决策时间线</CardTitle>
              <CardDescription>按仿真时间排序 · 共 {{ detail.events.length }} 条</CardDescription>
            </CardHeader>
            <CardContent>
              <p v-if="eventError" class="text-destructive mb-3 text-sm">{{ eventError }}</p>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead class="w-[130px]">仿真时间</TableHead>
                    <TableHead class="w-[90px]">类型</TableHead>
                    <TableHead class="w-[110px]">故障类型</TableHead>
                    <TableHead class="w-[80px]">关节</TableHead>
                    <TableHead class="w-[90px]">动作</TableHead>
                    <TableHead class="w-[170px]">原因</TableHead>
                    <TableHead class="w-[130px]">可达性</TableHead>
                    <TableHead>详情</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow v-for="(event, index) in detail.events" :key="`${event.event_type}-${index}`">
                    <TableCell class="tabular-nums">
                      <div>{{ numText(event.sim_time_s, 2, ' s') }}</div>
                      <div class="text-muted-foreground text-xs">{{ formatEpoch(event.timestamp) }}</div>
                    </TableCell>
                    <TableCell>
                      <Badge :class="eventClass(event.event_type)">{{ eventText(event.event_type) }}</Badge>
                    </TableCell>
                    <TableCell>{{ faultTypeText(event.fault_type) }}</TableCell>
                    <TableCell>{{ event.joint_index != null ? `J${event.joint_index}` : '-' }}</TableCell>
                    <TableCell>{{ actionText(event.action) }}</TableCell>
                    <TableCell class="text-muted-foreground text-xs">{{ event.reason || '-' }}</TableCell>
                    <TableCell>
                      <Badge :class="reachClass(event.reachability_status)">
                        {{ reachText(event.reachability_status) }}
                      </Badge>
                    </TableCell>
                    <TableCell class="text-muted-foreground text-xs">
                      <div class="max-w-[260px] truncate" :title="event.detail || ''">{{ event.detail || '-' }}</div>
                    </TableCell>
                  </TableRow>
                  <TableRow v-if="!detail.events.length">
                    <TableCell colspan="8" class="text-muted-foreground h-16 text-center">
                      {{ detailLoading ? '加载中…' : '暂无事件记录' }}
                    </TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>回放曲线</CardTitle>
              <CardDescription>
                {{ metricMeta.label }} · {{ parsedSeries.length }} 个采样点 · 时间轴对齐运行开始时刻
              </CardDescription>
              <CardAction>
                <Select :model-value="metric" @update:model-value="onMetricChange">
                  <SelectTrigger class="w-[150px]" size="sm">
                    <SelectValue placeholder="选择指标" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem v-for="(meta, key) in METRICS" :key="key" :value="key">
                      {{ meta.label }}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </CardAction>
            </CardHeader>
            <CardContent>
              <p v-if="seriesError" class="text-destructive mb-3 text-sm">{{ seriesError }}</p>
              <div v-show="parsedSeries.length" ref="chartRef" class="h-[340px] w-full"></div>
              <p v-if="!parsedSeries.length" class="text-muted-foreground py-8 text-center text-sm">
                {{ detailLoading ? '加载中…' : '暂无曲线数据' }}
              </p>
            </CardContent>
          </Card>
        </template>
        <p v-else class="text-muted-foreground py-8 text-center text-sm">
          {{ detailLoading ? '加载中…' : '暂无运行数据' }}
        </p>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import * as echarts from 'echarts'
import { Download, RotateCcw, Search } from 'lucide-vue-next'
import { toast } from '@/lib/toast'
import {
  exportExperimentRun,
  getExperimentEvents,
  getExperimentRun,
  getExperimentRuns,
  getExperimentSeries,
} from '@/api/experiment'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatClock, parseJson, toLocalIso } from '@/utils/format'

// reka-ui 的 Select 不接受空字符串作为选项值，用哨兵值表示「全部」
const ALL = '__all__'
const PAGE_SIZE = 20
// 契约 2.0.0 的任务状态枚举
const statusOptions = ['RECOVERED', 'SAFE_STOPPED', 'FAILED', 'NOT_APPLICABLE', 'IN_PROGRESS', 'INCOMPLETE']

const STATUS_TEXT = {
  RECOVERED: '已恢复',
  SAFE_STOPPED: '安全停止',
  FAILED: '失败',
  NOT_APPLICABLE: '不适用',
  IN_PROGRESS: '运行中',
  INCOMPLETE: '未完成'
}
const STATUS_CLASS = {
  RECOVERED: 'border-transparent bg-emerald-100 text-emerald-800',
  SAFE_STOPPED: 'border-transparent bg-amber-100 text-amber-800',
  FAILED: 'border-transparent bg-red-100 text-red-700',
  NOT_APPLICABLE: 'border-transparent bg-slate-200 text-slate-700',
  IN_PROGRESS: 'border-transparent bg-sky-100 text-sky-800',
  INCOMPLETE: 'border-transparent bg-slate-200 text-slate-600'
}
const ACTION_TEXT = { RECOVER: '恢复', STOP: '停止' }
const FAULT_TEXT = { JOINT_LOCKED: '关节卡滞' }
const REACH_TEXT = {
  REACHABLE: '可达',
  NO_FEASIBLE_PLAN: '无可行解',
  NOT_ASSESSED: '未评估'
}
const REACH_CLASS = {
  REACHABLE: 'border-transparent bg-emerald-100 text-emerald-800',
  NO_FEASIBLE_PLAN: 'border-transparent bg-amber-100 text-amber-800',
  NOT_ASSESSED: 'border-transparent bg-slate-200 text-slate-700'
}
const EVENT_TEXT = { FAULT: '故障', DECISION: '决策' }
const EVENT_CLASS = {
  FAULT: 'border-transparent bg-red-100 text-red-700',
  DECISION: 'border-transparent bg-blue-100 text-blue-700'
}

const METRICS = {
  position: { label: '关节位置', field: 'position', unit: 'rad' },
  velocity: { label: '关节速度', field: 'velocity', unit: 'rad/s' },
  torque: { label: '关节力矩', field: 'effort', unit: 'N·m' },
  ee: { label: '末端误差', field: 'error', unit: 'm' }
}

const route = useRoute()

const runs = ref([])
const total = ref(0)
const page = ref(0)
const loading = ref(false)
const error = ref('')
const lastUpdated = ref('')
const filters = reactive({
  runId: '',
  status: '',
  deviceId: route.query.deviceId ? String(route.query.deviceId) : ''
})

const detailVisible = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
const eventError = ref('')
const seriesError = ref('')
const detail = reactive({ run: null, events: [] })
const seriesRows = ref([])
const metric = ref('position')

const chartRef = ref(null)
let chart = null
// 详情请求序号：快速切换运行时丢弃过期响应
let detailSeq = 0

const METRIC_DEFAULT = METRICS.position
const metricMeta = computed(() => METRICS[metric.value] || METRIC_DEFAULT)

const statusText = (status) => STATUS_TEXT[status] || status || '-'
const statusClass = (status) => STATUS_CLASS[status] || 'border-transparent bg-slate-200 text-slate-700'
const actionText = (action) => ACTION_TEXT[action] || action || '-'
const faultTypeText = (type) => FAULT_TEXT[type] || type || '-'
const reachText = (status) => REACH_TEXT[status] || status || '-'
const reachClass = (status) => REACH_CLASS[status] || 'border-transparent bg-slate-200 text-slate-700'
const eventText = (type) => EVENT_TEXT[type] || type || '-'
const eventClass = (type) => EVENT_CLASS[type] || 'border-transparent bg-slate-200 text-slate-700'

const runStatus = (run) => run?.task?.status || run?.status || ''
const faultJoint = (run) => {
  const fault = run?.fault
  if (!fault) return '-'
  return fault.joint_name || (fault.joint_index != null ? `J${fault.joint_index}` : '-')
}

const shortId = (runId) => {
  if (!runId) return '-'
  return runId.length > 12 ? `${runId.slice(0, 8)}…${runId.slice(-4)}` : runId
}

const toNumber = (value) => {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

const numText = (value, digits = 3, unit = '') => {
  const parsed = toNumber(value)
  if (parsed === null) return '-'
  return `${parsed.toFixed(digits)}${unit}`
}

const formatEpoch = (epochMs) => {
  const parsed = toNumber(epochMs)
  if (parsed === null) return '-'
  const date = new Date(parsed)
  if (Number.isNaN(date.getTime())) return '-'
  return toLocalIso(date).replace('T', ' ')
}

const hasNext = computed(() => (page.value + 1) * PAGE_SIZE < total.value)

const summaryItems = computed(() => {
  const run = detail.run || {}
  const task = run.task || {}
  const fault = run.fault || {}
  const reach = run.reachability || {}
  const decision = run.decision || {}
  return [
    { label: '策略 / 算法', value: `${run.strategy || '-'} · ${run.algorithm_version || '-'}` },
    { label: '任务状态', value: statusText(runStatus(run)) },
    { label: '故障关节', value: faultJoint(run) },
    { label: '检测延迟', value: numText(fault.detection_latency_ms, 0, ' ms') },
    { label: '决策', value: actionText(decision.action) },
    { label: '可达性', value: reachText(reach.status) },
    { label: '末端误差', value: numText(task.final_ee_error_m, 4, ' m') },
    { label: '恢复耗时', value: numText(task.recovery_time_s, 2, ' s') }
  ]
})

const metaItems = computed(() => {
  const run = detail.run || {}
  const simulation = run.simulation || {}
  const scenario = run.scenario || {}
  const fault = run.fault || {}
  const decision = run.decision || {}
  const task = run.task || {}
  const trace = run.trace || {}
  return [
    { label: '场景', value: `${scenario.scenario_id || '-'} · ${scenario.split || '-'} · seed ${scenario.seed ?? '-'}` },
    { label: '场景说明', value: scenario.description || '-' },
    {
      label: '仿真环境',
      value: `${simulation.simulation_id || '-'} / ${simulation.robot_id || '-'} · ${simulation.plant || '-'} · ${simulation.control_hz ?? '-'} Hz · ${simulation.duration_s ?? '-'} s`
    },
    { label: '故障类型', value: faultTypeText(fault.type) },
    { label: '注入 / 检出', value: `${numText(fault.injected_at_s, 2, ' s')} / ${numText(fault.detected_at_s, 2, ' s')}` },
    { label: '决策原因', value: decision.reason || '-' },
    { label: '停止耗时', value: numText(task.stop_time_s, 2, ' s') },
    { label: '峰值故障关节力矩', value: numText(task.peak_fault_joint_torque_nm, 2, ' N·m') },
    {
      label: '峰值关节速度 / 力矩',
      value: `${numText(task.max_joint_speed_rad_s, 3, ' rad/s')} / ${numText(task.max_joint_torque_nm, 3, ' N·m')}`
    },
    {
      label: '轨迹文件',
      value: `${trace.path || '-'} · ${trace.frame_count ?? '-'} 帧 · ${trace.sample_rate_hz ?? '-'} Hz`,
      mono: true
    },
    { label: '轨迹 SHA-256', value: trace.sha256 || '-', mono: true }
  ]
})

const parsedSeries = computed(() =>
  seriesRows.value.map((row) => {
    const payload = parseJson(row.jointPayload)
    const joints = Array.isArray(payload) ? payload : payload && Array.isArray(payload.joints) ? payload.joints : []
    return {
      reportedAt: row.reportedAt,
      joints,
      ee: parseJson(row.endEffectorPayload)
    }
  })
)

const chartNames = computed(() => {
  if (metric.value === 'ee') return [METRICS.ee.label]
  const names = new Set()
  parsedSeries.value.forEach((frame) => {
    frame.joints.forEach((joint) => {
      if (joint.name) names.add(joint.name)
    })
  })
  return [...names]
})

const eeError = (payload) => {
  if (payload == null) return null
  if (typeof payload === 'number') return Number.isFinite(payload) ? payload : null
  const direct = toNumber(payload.error)
  if (direct !== null) return direct
  if (payload.error && typeof payload.error === 'object') {
    const nested = toNumber(payload.error.norm ?? payload.error.value ?? payload.error.m)
    if (nested !== null) return nested
  }
  return toNumber(payload.position_error ?? payload.positionError)
}

// 以运行开始时刻为原点换算仿真时间；时间不可解析时退化为时分秒
const elapsedLabel = (reportedAt) => {
  const started = toNumber(detail.run?.started_at_ms)
  const time = new Date(reportedAt).getTime()
  if (started !== null && Number.isFinite(time)) {
    const seconds = (time - started) / 1000
    if (seconds >= 0) return seconds.toFixed(2)
  }
  return formatClock(reportedAt)
}

const buildParams = () => {
  const params = { page: page.value, size: PAGE_SIZE }
  if (filters.runId.trim()) params.runId = filters.runId.trim()
  if (filters.status) params.status = filters.status
  // 后端 deviceId 为 Long，非数字输入不下发，避免 400
  if (/^\d+$/.test(filters.deviceId.trim())) params.deviceId = filters.deviceId.trim()
  return params
}

const load = async () => {
  loading.value = true
  try {
    const { data } = await getExperimentRuns(buildParams())
    runs.value = data?.items || []
    total.value = data?.total || 0
    error.value = ''
    lastUpdated.value = toLocalIso(new Date())
  } catch (e) {
    error.value = e.response?.data?.error || '读取实验列表失败'
    runs.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

const reload = () => {
  page.value = 0
  load()
}

const reset = () => {
  filters.runId = ''
  filters.status = ''
  filters.deviceId = ''
  reload()
}

const onStatusChange = (value) => {
  filters.status = value === ALL ? '' : value
  reload()
}

const prev = () => {
  if (page.value > 0) {
    page.value -= 1
    load()
  }
}

const next = () => {
  if (hasNext.value) {
    page.value += 1
    load()
  }
}

const sortEvents = (events) =>
  [...(events || [])].sort((a, b) => {
    const left = toNumber(a.sim_time_s) ?? toNumber(a.timestamp) ?? 0
    const right = toNumber(b.sim_time_s) ?? toNumber(b.timestamp) ?? 0
    return left - right
  })

const disposeChart = () => {
  if (chart) {
    chart.dispose()
    chart = null
  }
}

const renderChart = async () => {
  await nextTick()
  if (!chartRef.value || !parsedSeries.value.length) return
  if (!chart) chart = echarts.init(chartRef.value)
  const meta = metricMeta.value
  const frames = parsedSeries.value
  const option = {
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value) => (value == null ? '-' : `${value} ${meta.unit}`)
    },
    legend: { type: 'scroll', top: 0 },
    grid: { left: 64, right: 24, top: 40, bottom: 40 },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      name: '仿真时间 (s)',
      data: frames.map((frame) => elapsedLabel(frame.reportedAt))
    },
    yAxis: { type: 'value', name: `${meta.label} (${meta.unit})`, scale: true },
    series: chartNames.value.map((name) => ({
      name,
      type: 'line',
      smooth: true,
      showSymbol: false,
      data: frames.map((frame) => {
        if (metric.value === 'ee') return eeError(frame.ee)
        const joint = frame.joints.find((item) => item.name === name)
        return joint ? toNumber(joint[meta.field]) : null
      })
    }))
  }
  chart.setOption(option, true)
  chart.resize()
}

const loadDetail = async (runId) => {
  const seq = ++detailSeq
  detailLoading.value = true
  detailError.value = ''
  eventError.value = ''
  seriesError.value = ''
  detail.events = []
  seriesRows.value = []

  await Promise.all([
    getExperimentRun(runId)
      .then(({ data }) => {
        if (seq !== detailSeq) return
        detail.run = data || detail.run
      })
      .catch((e) => {
        if (seq !== detailSeq) return
        detailError.value = e.response?.data?.error || '读取运行详情失败'
      }),
    getExperimentEvents(runId)
      .then(({ data }) => {
        if (seq !== detailSeq) return
        detail.events = sortEvents(data)
      })
      .catch((e) => {
        if (seq !== detailSeq) return
        eventError.value = e.response?.data?.error || '读取事件时间线失败'
      }),
    getExperimentSeries(runId, { limit: 800, downsample: false })
      .then(({ data }) => {
        if (seq !== detailSeq) return
        seriesRows.value = data || []
      })
      .catch((e) => {
        if (seq !== detailSeq) return
        seriesError.value = e.response?.data?.error || '读取回放曲线失败'
      })
  ])

  if (seq !== detailSeq) return
  detailLoading.value = false
  await renderChart()
}

const openDetail = (row) => {
  detail.run = row
  detail.events = []
  seriesRows.value = []
  detailError.value = ''
  eventError.value = ''
  seriesError.value = ''
  detailVisible.value = true
  nextTick(() => loadDetail(row.run_id))
}

const onDetailOpenChange = (open) => {
  if (!open) {
    detailSeq += 1
    disposeChart()
    detail.run = null
    detail.events = []
    seriesRows.value = []
    detailLoading.value = false
  }
}

const downloadDetail = async (format) => {
  const runId = detail.run?.run_id
  if (!runId) return
  try {
    const response = await exportExperimentRun(runId, format)
    const blob = response.data instanceof Blob ? response.data : new Blob([response.data])
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = format === 'csv' ? `${runId}-events.csv` : `${runId}.json`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } catch (error) {
    toast.error('导出失败，请稍后重试')
  }
}

const onMetricChange = (value) => {
  metric.value = value
  renderChart()
}

const copy = async (text) => {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    toast.success('已复制')
  } catch (error) {
    toast.warning('浏览器不允许自动复制，请手动选中')
  }
}

const resizeChart = () => {
  if (chart) chart.resize()
}

onMounted(() => {
  load()
  window.addEventListener('resize', resizeChart)
})

onUnmounted(() => {
  window.removeEventListener('resize', resizeChart)
  disposeChart()
})
</script>

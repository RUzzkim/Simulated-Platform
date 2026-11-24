<template>
  <div class="flex flex-col gap-6">
    <div class="flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 class="text-xl font-semibold">下发中心</h1>
        <p class="text-muted-foreground mt-1 text-sm">
          参数 / 策略 / 模型版本化下发：新建版本 → 下发到设备 → 边缘端回执成功后自动置为「生效」。
        </p>
      </div>
      <div class="flex items-end gap-3">
        <div class="grid gap-1.5">
          <Label>目标设备</Label>
          <Select v-model="deviceId" class="w-56">
            <SelectTrigger class="w-56">
              <SelectValue placeholder="选择设备" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="device in devices" :key="device.id" :value="device.id">
                {{ device.deviceCode }} · {{ device.name }}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
        <Button variant="outline" size="sm" :disabled="loading" @click="reload">刷新</Button>
        <Button v-if="canWrite()" size="sm" @click="openParameterDialog">新建参数版本</Button>
      </div>
    </div>

    <Card>
      <CardHeader>
        <CardTitle>当前生效</CardTitle>
        <CardDescription>
          边缘端启动/重连后调用 <code class="text-xs">GET /api/edge/publishables</code> 拉取同一份数据做对齐
        </CardDescription>
      </CardHeader>
      <CardContent class="grid gap-4 sm:grid-cols-3">
        <div class="rounded-md border p-3">
          <div class="text-muted-foreground text-xs">参数</div>
          <div v-if="publishables.parameter" class="mt-1 text-sm font-medium">
            v{{ publishables.parameter.version }}
            <Badge class="ml-2 border-transparent bg-emerald-100 text-emerald-800">ACTIVE</Badge>
          </div>
          <div v-else class="text-muted-foreground mt-1 text-sm">尚未生效（等待回执）</div>
          <div v-if="publishables.parameter" class="text-muted-foreground mt-2 line-clamp-3 break-all text-xs">
            {{ compact(publishables.parameter.payload) }}
          </div>
        </div>
        <div class="rounded-md border p-3">
          <div class="text-muted-foreground text-xs">策略</div>
          <div v-if="publishables.strategies?.length" class="mt-1 flex flex-col gap-1 text-sm font-medium">
            <span v-for="item in publishables.strategies" :key="item.name" class="truncate">
              {{ item.name }} v{{ item.version }}
            </span>
          </div>
          <div v-else class="text-muted-foreground mt-1 text-sm">尚未生效</div>
        </div>
        <div class="rounded-md border p-3">
          <div class="text-muted-foreground text-xs">模型</div>
          <div v-if="publishables.models?.length" class="mt-1 flex flex-col gap-1 text-sm font-medium">
            <span v-for="item in publishables.models" :key="item.modelName" class="truncate">
              {{ item.modelName }} v{{ item.version }}
            </span>
          </div>
          <div v-else class="text-muted-foreground mt-1 text-sm">尚未生效</div>
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>参数版本</CardTitle>
        <CardDescription>按设备版本化，下发后等边缘端回执；重新下发旧版本即回滚</CardDescription>
        <CardAction>
          <Button v-if="canWrite()" variant="outline" size="sm" @click="openParameterDialog">新建版本</Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead class="w-20">版本</TableHead>
              <TableHead class="w-32">状态</TableHead>
              <TableHead class="w-40">创建人</TableHead>
              <TableHead class="w-52">创建时间</TableHead>
              <TableHead>载荷</TableHead>
              <TableHead class="w-24 text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="item in parameters" :key="item.id">
              <TableCell class="font-medium">v{{ item.version }}</TableCell>
              <TableCell>
                <Badge :class="statusClass(item.status)">{{ item.status }}</Badge>
              </TableCell>
              <TableCell class="text-muted-foreground text-sm">{{ item.createdByName || '-' }}</TableCell>
              <TableCell class="text-muted-foreground text-sm tabular-nums">{{ formatTime(item.createdAt) }}</TableCell>
              <TableCell class="text-muted-foreground max-w-md truncate text-xs">{{ compact(item.payload) }}</TableCell>
              <TableCell class="text-right">
                <Button
                  v-if="canWrite()"
                  variant="ghost"
                  size="sm"
                  :disabled="publishing"
                  @click="askPublish('parameter', item)"
                >
                  {{ item.version < maxParameterVersion ? '回滚' : '下发' }}
                </Button>
              </TableCell>
            </TableRow>
            <TableRow v-if="!parameters.length">
              <TableCell colspan="6" class="text-muted-foreground h-16 text-center">暂无参数版本</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>模型版本</CardTitle>
        <CardDescription>云端只存制品地址与元数据，真正的模型文件由边缘端从 artifactUrl 拉取</CardDescription>
        <CardAction>
          <Button v-if="canWrite()" variant="outline" size="sm" @click="openModelDialog">新建版本</Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead class="w-40">模型</TableHead>
              <TableHead class="w-20">版本</TableHead>
              <TableHead class="w-32">状态</TableHead>
              <TableHead>制品地址</TableHead>
              <TableHead class="w-32">创建人</TableHead>
              <TableHead class="w-24 text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="item in models" :key="item.id">
              <TableCell class="font-medium">{{ item.modelName }}</TableCell>
              <TableCell class="tabular-nums">v{{ item.version }}</TableCell>
              <TableCell>
                <Badge :class="statusClass(item.status)">{{ item.status }}</Badge>
              </TableCell>
              <TableCell class="text-muted-foreground max-w-md truncate text-xs">{{ item.artifactUrl || '-' }}</TableCell>
              <TableCell class="text-muted-foreground text-sm">{{ item.createdByName || '-' }}</TableCell>
              <TableCell class="text-right">
                <Button
                  v-if="canWrite()"
                  variant="ghost"
                  size="sm"
                  :disabled="publishing"
                  @click="askPublish('model', item)"
                >
                  下发
                </Button>
              </TableCell>
            </TableRow>
            <TableRow v-if="!models.length">
              <TableCell colspan="6" class="text-muted-foreground h-16 text-center">暂无模型版本</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>策略版本</CardTitle>
        <CardDescription>策略是全局定义（同名下版本递增），下发时指定目标设备；同一名称只有一个版本处于生效态</CardDescription>
        <CardAction>
          <Button v-if="canWrite()" variant="outline" size="sm" @click="openStrategyDialog">新建版本</Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead class="w-48">名称</TableHead>
              <TableHead class="w-20">版本</TableHead>
              <TableHead class="w-32">状态</TableHead>
              <TableHead class="w-32">创建人</TableHead>
              <TableHead class="w-52">创建时间</TableHead>
              <TableHead>载荷</TableHead>
              <TableHead class="w-24 text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="item in strategies" :key="item.id">
              <TableCell class="font-medium">{{ item.name }}</TableCell>
              <TableCell class="tabular-nums">v{{ item.version }}</TableCell>
              <TableCell>
                <Badge :class="statusClass(item.status)">{{ item.status }}</Badge>
              </TableCell>
              <TableCell class="text-muted-foreground text-sm">{{ item.createdByName || '-' }}</TableCell>
              <TableCell class="text-muted-foreground text-sm tabular-nums">{{ formatTime(item.createdAt) }}</TableCell>
              <TableCell class="text-muted-foreground max-w-md truncate text-xs">{{ compact(item.payload) }}</TableCell>
              <TableCell class="text-right">
                <Button
                  v-if="canWrite()"
                  variant="ghost"
                  size="sm"
                  :disabled="publishing || !deviceId"
                  @click="askPublish('strategy', item)"
                >
                  下发
                </Button>
              </TableCell>
            </TableRow>
            <TableRow v-if="!strategies.length">
              <TableCell colspan="7" class="text-muted-foreground h-16 text-center">暂无策略版本</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>

    <Dialog v-model:open="parameterVisible">
      <DialogContent class="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>新建参数版本</DialogTitle>
          <DialogDescription>JSON 对象，例如 { "kp": 1.2, "ki": 0.05 }；保存后为 DRAFT，下发并回执成功才生效。</DialogDescription>
        </DialogHeader>
        <div class="grid gap-2">
          <Label for="parameter-payload">参数载荷</Label>
          <Textarea id="parameter-payload" v-model="parameterText" rows="8" class="font-mono text-xs" />
        </div>
        <DialogFooter>
          <Button variant="outline" @click="parameterVisible = false">取消</Button>
          <Button :disabled="saving" @click="submitParameter">{{ saving ? '保存中…' : '保存' }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="modelVisible">
      <DialogContent class="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>新建模型版本</DialogTitle>
          <DialogDescription>同一模型名下版本自动递增；元数据可留空（JSON 对象）。</DialogDescription>
        </DialogHeader>
        <div class="grid gap-4">
          <div class="grid gap-2">
            <Label for="model-name">模型名</Label>
            <Input id="model-name" v-model="modelForm.modelName" placeholder="torque-nn" />
          </div>
          <div class="grid gap-2">
            <Label for="model-url">制品地址</Label>
            <Input id="model-url" v-model="modelForm.artifactUrl" placeholder="https://.../model.pt" />
          </div>
          <div class="grid gap-2">
            <Label for="model-metadata">元数据（JSON）</Label>
            <Textarea id="model-metadata" v-model="modelForm.metadata" rows="5" class="font-mono text-xs" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="modelVisible = false">取消</Button>
          <Button :disabled="saving" @click="submitModel">{{ saving ? '保存中…' : '保存' }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="strategyVisible">
      <DialogContent class="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>新建策略版本</DialogTitle>
          <DialogDescription>名称只能用字母/数字/下划线/短横线/点；同名下版本自动递增。</DialogDescription>
        </DialogHeader>
        <div class="grid gap-4">
          <div class="grid gap-2">
            <Label for="strategy-name">策略名</Label>
            <Input id="strategy-name" v-model="strategyForm.name" placeholder="adaptive-nn" />
          </div>
          <div class="grid gap-2">
            <Label for="strategy-payload">策略载荷（JSON）</Label>
            <Textarea id="strategy-payload" v-model="strategyForm.payload" rows="7" class="font-mono text-xs" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="strategyVisible = false">取消</Button>
          <Button :disabled="saving" @click="submitStrategy">{{ saving ? '保存中…' : '保存' }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="confirmVisible">
      <DialogContent class="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{{ confirmLabel }}</DialogTitle>
          <DialogDescription>{{ confirmDescription }}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" @click="confirmVisible = false">取消</Button>
          <Button :disabled="publishing" @click="runConfirm">{{ publishing ? '下发中…' : '确认下发' }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { toast } from '@/lib/toast'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { getDevices } from '@/api/device'
import {
  createModel,
  createParameter,
  createStrategy,
  getModels,
  getParameters,
  getPublishables,
  getStrategies,
  publishModel,
  publishParameter,
  publishStrategy
} from '@/api/publish'
import { canWrite } from '@/stores/auth'
import { formatTime } from '@/utils/format'

const STATUS_CLASS = {
  DRAFT: 'border-transparent bg-slate-200 text-slate-700',
  PUBLISHED: 'border-transparent bg-amber-100 text-amber-800',
  ACTIVE: 'border-transparent bg-emerald-100 text-emerald-800',
  SUPERSEDED: 'border-slate-300 bg-transparent text-slate-500'
}
const statusClass = (status) => STATUS_CLASS[status] || STATUS_CLASS.DRAFT

const devices = ref([])
const deviceId = ref(null)
const parameters = ref([])
const models = ref([])
const strategies = ref([])
const publishables = ref({})
const loading = ref(false)
const saving = ref(false)
const publishing = ref(false)

const parameterVisible = ref(false)
const parameterText = ref('{\n  "kp": 1.2,\n  "ki": 0.05,\n  "kd": 0.3\n}')
const modelVisible = ref(false)
const modelForm = reactive({ modelName: '', artifactUrl: '', metadata: '{\n  "framework": "pytorch"\n}' })
const strategyVisible = ref(false)
const strategyForm = reactive({ name: '', payload: '{\n  "controller": "NN_ADAPTIVE",\n  "eventTriggered": true\n}' })
const confirmVisible = ref(false)
const confirmLabel = ref('')
const confirmDescription = ref('')
let confirmAction = null

const maxParameterVersion = computed(() =>
  parameters.value.reduce((max, item) => Math.max(max, item.version), 0)
)

const compact = (value) => {
  if (value === null || value === undefined) return '-'
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return text.length > 120 ? `${text.slice(0, 120)}…` : text
}

const parseJsonObject = (text, label) => {
  let parsed
  try {
    parsed = JSON.parse(text)
  } catch (error) {
    toast.error(`${label}不是合法 JSON`)
    return null
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    toast.error(`${label}必须是 JSON 对象`)
    return null
  }
  return parsed
}

const load = async () => {
  if (!deviceId.value) return
  loading.value = true
  try {
    const [paramRes, modelRes, strategyRes, activeRes] = await Promise.all([
      getParameters(deviceId.value, { limit: 50 }),
      getModels(deviceId.value, { limit: 50 }),
      getStrategies({ limit: 50 }),
      getPublishables(deviceId.value)
    ])
    parameters.value = paramRes.data || []
    models.value = modelRes.data || []
    strategies.value = strategyRes.data || []
    publishables.value = activeRes.data || {}
  } catch (error) {
    toast.error(error.response?.data?.error || '加载失败')
  } finally {
    loading.value = false
  }
}

const reload = () => load()

const openParameterDialog = () => {
  parameterVisible.value = true
}
const openModelDialog = () => {
  modelForm.modelName = ''
  modelForm.artifactUrl = ''
  modelForm.metadata = '{\n  "framework": "pytorch"\n}'
  modelVisible.value = true
}
const openStrategyDialog = () => {
  strategyForm.name = ''
  strategyForm.payload = '{\n  "controller": "NN_ADAPTIVE",\n  "eventTriggered": true\n}'
  strategyVisible.value = true
}

const submitParameter = async () => {
  const payload = parseJsonObject(parameterText.value, '参数载荷')
  if (!payload) return
  saving.value = true
  try {
    await createParameter(deviceId.value, payload)
    toast.success('参数版本已保存（DRAFT）')
    parameterVisible.value = false
    await load()
  } catch (error) {
    toast.error(error.response?.data?.error || '保存失败')
  } finally {
    saving.value = false
  }
}

const submitModel = async () => {
  if (!modelForm.modelName.trim()) {
    toast.warning('模型名必填')
    return
  }
  const metadata = modelForm.metadata.trim() ? parseJsonObject(modelForm.metadata, '元数据') : null
  if (modelForm.metadata.trim() && !metadata) return
  saving.value = true
  try {
    await createModel(deviceId.value, {
      modelName: modelForm.modelName.trim(),
      artifactUrl: modelForm.artifactUrl.trim() || null,
      metadata
    })
    toast.success('模型版本已保存（DRAFT）')
    modelVisible.value = false
    await load()
  } catch (error) {
    toast.error(error.response?.data?.error || '保存失败')
  } finally {
    saving.value = false
  }
}

const submitStrategy = async () => {
  if (!strategyForm.name.trim()) {
    toast.warning('策略名必填')
    return
  }
  const payload = parseJsonObject(strategyForm.payload, '策略载荷')
  if (!payload) return
  saving.value = true
  try {
    await createStrategy({ name: strategyForm.name.trim(), payload })
    toast.success('策略版本已保存（DRAFT）')
    strategyVisible.value = false
    await load()
  } catch (error) {
    toast.error(error.response?.data?.error || '保存失败')
  } finally {
    saving.value = false
  }
}

const askPublish = (kind, item) => {
  const device = devices.value.find((row) => row.id === deviceId.value)
  if (!device) {
    toast.warning('先选择目标设备')
    return
  }
  const label = kind === 'parameter' ? `参数 v${item.version}` : kind === 'model' ? `${item.modelName} v${item.version}` : `${item.name} v${item.version}`
  confirmLabel.value = `下发${label}`
  confirmDescription.value = `下发到 ${device.deviceCode}（${device.name}）？边缘端回执成功后该版本才会被标记为生效。`
  confirmAction = async () => {
    if (kind === 'parameter') return publishParameter(deviceId.value, item.version)
    if (kind === 'model') return publishModel(deviceId.value, item.modelName, item.version)
    return publishStrategy(deviceId.value, item.name, item.version)
  }
  confirmVisible.value = true
}

const runConfirm = async () => {
  if (!confirmAction) return
  publishing.value = true
  try {
    const response = await confirmAction()
    const data = response.data || {}
    toast.success(`已下发 messageId=${String(data.messageId || '').slice(0, 8)}… 等待边缘端回执`)
    confirmVisible.value = false
    await load()
  } catch (error) {
    toast.error(error.response?.data?.error || '下发失败')
  } finally {
    publishing.value = false
  }
}

onMounted(async () => {
  try {
    const { data } = await getDevices()
    devices.value = data || []
    deviceId.value = devices.value.length ? devices.value[0].id : null
  } catch (error) {
    toast.error(error.response?.data?.error || '设备列表加载失败')
  }
  await load()
})
</script>
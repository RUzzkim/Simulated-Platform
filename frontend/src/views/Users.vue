<template>
  <div class="flex flex-col gap-6 p-1">
    <div class="flex flex-wrap items-center gap-3">
      <div>
        <h2 class="text-xl font-semibold tracking-tight">账号管理</h2>
        <p class="text-muted-foreground text-sm">
          ADMIN 管账号与全部操作，OPERATOR 可注册设备/下发指令，VIEWER 只读 · 共 {{ users.length }} 个账号
          <span v-if="pendingCount" class="text-amber-600">· {{ pendingCount }} 个待审批</span>
        </p>
      </div>
      <div class="ml-auto">
        <Button size="sm" @click="openCreate">
          <UserPlus />
          新建账号
        </Button>
      </div>
    </div>

    <Card class="gap-0 py-0">
      <CardContent class="px-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead class="w-[60px] pl-6">ID</TableHead>
              <TableHead class="w-[160px]">用户名</TableHead>
              <TableHead class="w-[140px]">显示名</TableHead>
              <TableHead class="w-[170px]">角色</TableHead>
              <TableHead class="w-[100px]">状态</TableHead>
              <TableHead class="w-[90px]">启用</TableHead>
              <TableHead class="w-[160px]">最近登录</TableHead>
              <TableHead class="w-[200px] pr-6 text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="row in users" :key="row.id" :class="row.status === 'PENDING' ? 'bg-amber-50/60' : ''">
              <TableCell class="text-muted-foreground pl-6 tabular-nums">{{ row.id }}</TableCell>
              <TableCell class="font-medium">
                {{ row.username }}
                <span v-if="row.id === currentUserId" class="text-muted-foreground text-xs">
                  （当前账号）
                </span>
              </TableCell>
              <TableCell>{{ row.displayName || '-' }}</TableCell>
              <TableCell>
                <!-- 待审批：角色可在“通过”前调整；已批/已驳回：沿用原有即时改角色逻辑 -->
                <Select
                  v-if="row.status === 'PENDING'"
                  :model-value="pendingRoleFor(row)"
                  @update:model-value="(role) => (pendingRoles[row.id] = role)"
                >
                  <SelectTrigger class="w-[150px]" size="sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem v-for="role in roles" :key="role" :value="role">{{ role }}</SelectItem>
                  </SelectContent>
                </Select>
                <Select
                  v-else
                  :model-value="row.role"
                  :disabled="row.id === currentUserId || row.status === 'REJECTED'"
                  @update:model-value="(role) => askRoleChange(row, role)"
                >
                  <SelectTrigger class="w-[150px]" size="sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem v-for="role in roles" :key="role" :value="role">{{ role }}</SelectItem>
                  </SelectContent>
                </Select>
              </TableCell>
              <TableCell>
                <Badge :class="statusClass(row.status)">{{ statusLabel(row.status) }}</Badge>
              </TableCell>
              <TableCell>
                <Switch
                  :model-value="row.enabled"
                  :disabled="row.id === currentUserId || row.status !== 'APPROVED'"
                  @update:model-value="(enabled) => toggleEnabled(row, enabled)"
                />
              </TableCell>
              <TableCell class="text-muted-foreground tabular-nums">
                {{ formatTime(row.lastLoginAt) }}
              </TableCell>
              <TableCell class="pr-6 text-right">
                <template v-if="row.status === 'PENDING'">
                  <Button variant="ghost" size="sm" class="text-emerald-700" @click="approve(row)">通过</Button>
                  <Button variant="ghost" size="sm" class="text-red-600" @click="askReject(row)">驳回</Button>
                </template>
                <Button v-else variant="ghost" size="sm" @click="openReset(row)">重置密码</Button>
              </TableCell>
            </TableRow>
            <TableRow v-if="!users.length">
              <TableCell colspan="8" class="text-muted-foreground h-24 text-center">暂无账号</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>

    <Dialog v-model:open="createVisible">
      <DialogContent class="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>新建账号</DialogTitle>
          <DialogDescription>密码至少 8 位；角色决定能看到哪些页面、能不能下发指令。ADMIN 直接建号无需审批。</DialogDescription>
        </DialogHeader>
        <div class="grid gap-4">
          <div class="grid gap-2">
            <Label for="new-username">用户名</Label>
            <Input id="new-username" v-model="createForm.username" placeholder="zhangsan" />
          </div>
          <div class="grid gap-2">
            <Label for="new-display">显示名</Label>
            <Input id="new-display" v-model="createForm.displayName" placeholder="张三" />
          </div>
          <div class="grid gap-2">
            <Label>角色</Label>
            <Select v-model="createForm.role">
              <SelectTrigger class="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="role in roles" :key="role" :value="role">{{ role }}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="grid gap-2">
            <Label for="new-password">初始密码</Label>
            <Input
              id="new-password"
              v-model="createForm.password"
              type="password"
              placeholder="至少 8 位"
              @keyup.enter="submitCreate"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="createVisible = false">取消</Button>
          <Button :disabled="saving" @click="submitCreate">{{ saving ? '保存中…' : '保存' }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="resetVisible">
      <DialogContent class="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>重置密码</DialogTitle>
          <DialogDescription>
            为 {{ resetTarget.username || '-' }} 设置新密码（至少 8 位）。
          </DialogDescription>
        </DialogHeader>
        <div class="grid gap-2">
          <Label for="reset-password">新密码</Label>
          <Input
            id="reset-password"
            v-model="resetPassword"
            type="password"
            placeholder="至少 8 位"
            @keyup.enter="submitReset"
          />
        </div>
        <DialogFooter>
          <Button variant="outline" @click="resetVisible = false">取消</Button>
          <Button :disabled="saving" @click="submitReset">{{ saving ? '提交中…' : '提交' }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="roleConfirmVisible">
      <DialogContent class="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>确认变更角色</DialogTitle>
          <DialogDescription>
            把 {{ roleTarget.username || '-' }} 的角色改为 {{ pendingRole }}？
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" @click="cancelRoleChange">取消</Button>
          <Button @click="confirmRoleChange">确认</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="rejectVisible">
      <DialogContent class="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>驳回注册申请</DialogTitle>
          <DialogDescription>
            确认驳回 {{ rejectTarget.username || '-' }} 的注册申请？该账号将无法登录。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" @click="rejectVisible = false">取消</Button>
          <Button variant="destructive" @click="confirmReject">驳回</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { toast } from '@/lib/toast'
import { UserPlus } from 'lucide-vue-next'
import { approveUser, createUser, getUsers, rejectUser, resetUserPassword, updateUser } from '../api/user'
import { auth } from '../stores/auth'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatTime } from '../utils/format'

const roles = ['ADMIN', 'OPERATOR', 'VIEWER']
const STATUS_LABEL = { PENDING: '待审批', APPROVED: '已批准', REJECTED: '已驳回' }
const STATUS_CLASS = {
  PENDING: 'border-transparent bg-amber-100 text-amber-800',
  APPROVED: 'border-transparent bg-emerald-100 text-emerald-800',
  REJECTED: 'border-transparent bg-red-100 text-red-700'
}

const users = ref([])
const saving = ref(false)
const createVisible = ref(false)
const resetVisible = ref(false)
const resetPassword = ref('')
const resetTarget = ref({})
const roleConfirmVisible = ref(false)
const roleTarget = ref({})
const pendingRole = ref('')
const rejectVisible = ref(false)
const rejectTarget = ref({})
// 待审批行上，管理员可在“通过”前临时调整角色（未持久化，通过时随请求提交）
const pendingRoles = reactive({})
const createForm = reactive({ username: '', displayName: '', role: 'OPERATOR', password: '' })
const currentUserId = auth.user?.id

const pendingCount = computed(() => users.value.filter((u) => u.status === 'PENDING').length)

const statusLabel = (status) => STATUS_LABEL[status] || status
const statusClass = (status) => STATUS_CLASS[status] || STATUS_CLASS.APPROVED
const pendingRoleFor = (row) => pendingRoles[row.id] || row.role

const load = async () => {
  try {
    const { data } = await getUsers()
    users.value = data
  } catch (error) {
    toast.error(error.response?.data?.error || '加载账号失败')
  }
}

const openCreate = () => {
  Object.assign(createForm, { username: '', displayName: '', role: 'OPERATOR', password: '' })
  createVisible.value = true
}

const submitCreate = async () => {
  if (!createForm.username.trim() || createForm.password.length < 8) {
    toast.warning('请填写用户名，密码至少 8 位')
    return
  }
  saving.value = true
  try {
    await createUser({ ...createForm, username: createForm.username.trim() })
    toast.success('账号已创建')
    createVisible.value = false
    await load()
  } catch (error) {
    toast.error(error.response?.data?.error || '创建失败')
  } finally {
    saving.value = false
  }
}

const askRoleChange = (row, role) => {
  if (role === row.role) return
  roleTarget.value = row
  pendingRole.value = role
  roleConfirmVisible.value = true
}

const cancelRoleChange = async () => {
  roleConfirmVisible.value = false
  // 角色下拉是受控的，取消后重新拉一次，确保显示回到库里的值
  await load()
}

const confirmRoleChange = async () => {
  roleConfirmVisible.value = false
  try {
    await updateUser(roleTarget.value.id, { role: pendingRole.value })
    toast.success('角色已更新')
  } catch (error) {
    toast.error(error.response?.data?.error || '更新失败')
  } finally {
    await load()
  }
}

const toggleEnabled = async (row, enabled) => {
  try {
    await updateUser(row.id, { enabled })
    toast.success(enabled ? '账号已启用' : '账号已停用')
  } catch (error) {
    toast.error(error.response?.data?.error || '更新失败')
  } finally {
    await load()
  }
}

const approve = async (row) => {
  try {
    await approveUser(row.id, { role: pendingRoleFor(row) })
    toast.success(`已通过 ${row.username} 的注册（${pendingRoleFor(row)}）`)
    delete pendingRoles[row.id]
  } catch (error) {
    toast.error(error.response?.data?.error || '审批失败')
  } finally {
    await load()
  }
}

const askReject = (row) => {
  rejectTarget.value = row
  rejectVisible.value = true
}

const confirmReject = async () => {
  rejectVisible.value = false
  try {
    await rejectUser(rejectTarget.value.id)
    toast.success(`已驳回 ${rejectTarget.value.username} 的申请`)
  } catch (error) {
    toast.error(error.response?.data?.error || '驳回失败')
  } finally {
    await load()
  }
}

const openReset = (row) => {
  resetTarget.value = row
  resetPassword.value = ''
  resetVisible.value = true
}

const submitReset = async () => {
  if (resetPassword.value.length < 8) {
    toast.warning('密码至少 8 位')
    return
  }
  saving.value = true
  try {
    await resetUserPassword(resetTarget.value.id, resetPassword.value)
    toast.success('密码已重置')
    resetVisible.value = false
  } catch (error) {
    toast.error(error.response?.data?.error || '重置失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

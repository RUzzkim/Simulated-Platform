<template>
  <div class="flex flex-col gap-6 p-1">
    <div class="flex flex-wrap items-center gap-3">
      <Button variant="outline" size="sm" @click="router.push('/')">
        <ArrowLeft />
        返回列表
      </Button>
      <div>
        <h2 class="text-xl font-semibold tracking-tight">设备详情</h2>
        <p class="text-muted-foreground text-sm">
          {{ device.deviceCode || '-' }} · 名称按 UTF-8 写入，可用于修正历史乱码数据
        </p>
      </div>
      <div class="ml-auto flex items-center gap-2">
        <Badge :class="statusClass(device.status)">{{ device.status || '-' }}</Badge>
        <Button v-if="canWrite()" variant="outline" size="sm" @click="openRename">
          <Pencil />
          重命名
        </Button>
      </div>
    </div>

    <Card>
      <CardContent>
        <div class="grid gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-4">
          <div class="min-w-0">
            <div class="text-muted-foreground text-xs">设备编号</div>
            <div class="mt-1 truncate text-sm font-medium">{{ device.deviceCode || '-' }}</div>
          </div>
          <div class="min-w-0">
            <div class="text-muted-foreground text-xs">设备名称</div>
            <div class="mt-1 truncate text-sm font-medium">{{ device.name || '-' }}</div>
          </div>
          <div class="min-w-0">
            <div class="text-muted-foreground text-xs">状态</div>
            <div class="mt-1">
              <Badge :class="statusClass(device.status)">{{ device.status || '-' }}</Badge>
            </div>
          </div>
          <div v-if="isEdge" class="min-w-0">
            <div class="text-muted-foreground text-xs">仿真实例（边端）</div>
            <div class="mt-1 truncate font-mono text-sm font-medium">{{ device.simulationId }}</div>
          </div>
          <div class="min-w-0">
            <div class="text-muted-foreground text-xs">最近上报</div>
            <div class="mt-1 text-sm font-medium tabular-nums">{{ formatTime(device.updatedAt) }}</div>
          </div>
        </div>
      </CardContent>
    </Card>

    <Card v-if="health">
      <CardHeader>
        <CardTitle>健康评分</CardTitle>
        <CardDescription>
          近 {{ health.window?.hours }} 小时 · 综合分 = 可用性×0.25 + 故障×0.35 + 遥测×0.40
        </CardDescription>
        <CardAction>
          <Badge :class="gradeClass(health.grade)" class="text-sm">{{ health.grade }} 级</Badge>
        </CardAction>
      </CardHeader>
      <CardContent class="flex flex-col gap-5">
        <div class="flex flex-wrap items-center gap-x-10 gap-y-4">
          <div class="flex items-baseline gap-2">
            <span class="text-4xl font-bold tabular-nums" :class="scoreText(health.score)">{{ health.score }}</span>
            <span class="text-muted-foreground text-sm">/ 100</span>
          </div>
          <div class="grid flex-1 gap-3 sm:grid-cols-3" style="min-width: 260px">
            <div>
              <div class="text-muted-foreground mb-1 text-xs">可用性</div>
              <SubScore :value="health.availability" />
            </div>
            <div>
              <div class="text-muted-foreground mb-1 text-xs">故障</div>
              <SubScore :value="health.faultHealth" />
            </div>
            <div>
              <div class="text-muted-foreground mb-1 text-xs">遥测</div>
              <SubScore :value="health.telemetryHealth" />
            </div>
          </div>
        </div>
        <div v-if="health.topAnomalyJoints?.length" class="flex flex-wrap items-center gap-2">
          <span class="text-muted-foreground text-xs">异常关节：</span>
          <Badge
            v-for="j in health.topAnomalyJoints"
            :key="j.joint"
            class="border-transparent bg-amber-100 text-amber-800"
          >
            {{ j.joint }} · {{ j.anomalyPoints }} 次 · 峰值 {{ j.maxAbsZ }}σ
          </Badge>
        </div>
        <div v-if="health.faultCounts?.length" class="flex flex-wrap items-center gap-2">
          <span class="text-muted-foreground text-xs">窗口内故障：</span>
          <Badge v-for="f in health.faultCounts" :key="f.level" variant="outline">
            {{ f.level }} × {{ f.count }}
          </Badge>
        </div>
        <p v-if="health.notes?.length" class="text-muted-foreground text-xs leading-relaxed">
          {{ health.notes.join('；') }}
        </p>
      </CardContent>
    </Card>

    <Card v-if="trend">
      <CardHeader>
        <CardTitle>趋势预测（力矩）</CardTitle>
        <CardDescription>
          近 {{ trendWindow }} 小时 · 每关节 effort 分桶回归求斜率，用基线上界（均值+3σ）外推「照此趋势多久到危险线」
        </CardDescription>
      </CardHeader>
      <CardContent class="flex flex-col gap-4">
        <p v-if="!trend.sufficient" class="text-muted-foreground text-xs">
          样本较少（{{ trend.framesScanned }} 帧），趋势仅供参考。
        </p>
        <Table v-if="trend.trends?.length">
          <TableHeader>
            <TableRow>
              <TableHead>关节</TableHead>
              <TableHead>当前力矩</TableHead>
              <TableHead>斜率(单位/时)</TableHead>
              <TableHead>基线上界</TableHead>
              <TableHead>预计到上界</TableHead>
              <TableHead>结论</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="row in trend.trends"
              :key="row.joint"
              :class="row.hoursToUpper != null ? 'bg-amber-50' : ''"
            >
              <TableCell class="font-medium">{{ row.joint }}</TableCell>
              <TableCell class="tabular-nums">{{ row.current }}</TableCell>
              <TableCell class="tabular-nums" :class="row.slopePerHour > 0 ? 'text-red-600' : 'text-emerald-600'">
                {{ row.slopePerHour > 0 ? '+' : '' }}{{ row.slopePerHour }}
              </TableCell>
              <TableCell class="tabular-nums">{{ row.upperBound }}</TableCell>
              <TableCell class="tabular-nums">
                {{ row.hoursToUpper != null ? row.hoursToUpper + ' 小时' : '—' }}
              </TableCell>
              <TableCell class="text-muted-foreground text-xs">{{ row.projection }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <p v-else class="text-muted-foreground py-6 text-center text-sm">窗口内暂无可用于趋势分析的遥测数据</p>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>最新遥测</CardTitle>
        <CardDescription>每 2 秒刷新 · 关节数 {{ joints.length }}</CardDescription>
      </CardHeader>
      <CardContent class="flex flex-col gap-4">
        <div class="grid gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-4">
          <div class="min-w-0">
            <div class="text-muted-foreground text-xs">上报时间</div>
            <div class="mt-1 text-sm font-medium tabular-nums">{{ formatTime(telemetry.reportedAt) }}</div>
          </div>
          <div class="min-w-0">
            <div class="text-muted-foreground text-xs">运行状态</div>
            <div class="mt-1 text-sm font-medium">{{ telemetry.state || '-' }}</div>
          </div>
          <div class="min-w-0">
            <div class="text-muted-foreground text-xs">控制模式</div>
            <div class="mt-1 text-sm font-medium">{{ telemetry.controlMode || '-' }}</div>
          </div>
          <div class="min-w-0">
            <div class="text-muted-foreground text-xs">关节数</div>
            <div class="mt-1 text-sm font-medium tabular-nums">{{ joints.length }}</div>
          </div>
        </div>

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>关节</TableHead>
              <TableHead>位置</TableHead>
              <TableHead>速度</TableHead>
              <TableHead>力矩</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="joint in joints" :key="joint.name">
              <TableCell class="font-medium">{{ joint.name }}</TableCell>
              <TableCell class="tabular-nums">{{ joint.position }}</TableCell>
              <TableCell class="tabular-nums">{{ joint.velocity }}</TableCell>
              <TableCell class="tabular-nums">{{ joint.effort }}</TableCell>
            </TableRow>
            <TableRow v-if="!joints.length">
              <TableCell colspan="4" class="text-muted-foreground h-16 text-center">
                暂无关节数据
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>位置历史曲线</CardTitle>
        <CardDescription>每 10 秒刷新 · {{ historySeries.length }} 个{{ historyDownsample ? '均值点' : '采样点' }}</CardDescription>
        <CardAction>
          <div class="flex items-center gap-2">
            <Label for="history-downsample" class="text-muted-foreground text-xs">降采样(均值)</Label>
            <Switch
              id="history-downsample"
              :model-value="historyDownsample"
              @update:model-value="onHistoryDownsample"
            />
          </div>
          <Select :model-value="historyRange" @update:model-value="onHistoryRange">
            <SelectTrigger class="w-[150px]" size="sm">
              <SelectValue placeholder="选择区间" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="15m">最近 15 分钟</SelectItem>
              <SelectItem value="1h">最近 1 小时</SelectItem>
              <SelectItem value="6h">最近 6 小时</SelectItem>
              <SelectItem value="all">全部</SelectItem>
            </SelectContent>
          </Select>
        </CardAction>
      </CardHeader>
      <CardContent>
        <div ref="historyRef" class="h-[300px] w-full"></div>
        <p v-if="!historySeries.length" class="text-muted-foreground py-8 text-center text-sm">
          所选区间暂无遥测数据
        </p>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>故障统计</CardTitle>
        <CardDescription>每 30 秒刷新 · 共 {{ stats.total || 0 }} 条</CardDescription>
        <CardAction>
          <Select :model-value="statsRange" @update:model-value="onStatsRange">
            <SelectTrigger class="w-[150px]" size="sm">
              <SelectValue placeholder="选择区间" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="24h">近 24 小时</SelectItem>
              <SelectItem value="7d">近 7 天</SelectItem>
              <SelectItem value="all">全部</SelectItem>
            </SelectContent>
          </Select>
        </CardAction>
      </CardHeader>
      <CardContent>
        <div class="flex flex-col gap-3 lg:flex-row">
          <div ref="levelRef" class="h-[240px] min-w-0 flex-1"></div>
          <div ref="typeRef" class="h-[240px] min-w-0 flex-1"></div>
          <div ref="dayRef" class="h-[240px] min-w-0 flex-1"></div>
        </div>
        <p v-if="!stats.total" class="text-muted-foreground py-8 text-center text-sm">
          所选区间暂无故障事件
        </p>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>边缘接入</CardTitle>
        <CardDescription>MQTT 客户端证书（按 CN 取账号，下方账号/口令为兜底）与 HTTP 上报令牌，供边（ROS2）/端（Gazebo 仿真）接入</CardDescription>
        <CardAction>
          <Badge v-if="credential" :variant="credential.status === 'ACTIVE' ? 'secondary' : 'outline'">
            {{ credential.status }}
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent class="flex flex-col gap-4">
        <div class="flex flex-wrap items-center gap-2">
          <Button v-if="canWrite()" size="sm" :disabled="credentialSaving" @click="issueCredential">
            {{ credential ? '轮换凭据' : '签发凭据' }}
          </Button>
          <Button variant="outline" size="sm" :disabled="!credential" @click="loadCredential">
            刷新
          </Button>
          <Button
            v-if="canWrite()"
            variant="destructive"
            size="sm"
            :disabled="!credential || credential.status !== 'ACTIVE'"
            @click="revokeCredential"
          >
            吊销
          </Button>
        </div>

        <div v-if="credential" class="grid gap-x-8 gap-y-4 lg:grid-cols-2">
          <div class="min-w-0">
            <div class="text-muted-foreground text-xs">MQTT 账号</div>
            <div class="mt-1 flex items-center gap-2">
              <code class="bg-muted rounded px-1.5 py-0.5 font-mono text-xs">{{ credential.mqttUsername }}</code>
              <Button variant="ghost" size="sm" class="h-6 px-2 text-xs" @click="copy(credential.mqttUsername)">
                复制
              </Button>
            </div>
          </div>
          <div class="min-w-0">
            <div class="text-muted-foreground text-xs">MQTT 密码</div>
            <div class="mt-1 flex items-center gap-2">
              <code class="bg-muted rounded px-1.5 py-0.5 font-mono text-xs">{{ credential.mqttPassword }}</code>
              <Button variant="ghost" size="sm" class="h-6 px-2 text-xs" @click="copy(credential.mqttPassword)">
                复制
              </Button>
            </div>
          </div>
          <div class="min-w-0">
            <div class="text-muted-foreground text-xs">Broker</div>
            <div class="mt-1 text-sm">{{ credential.brokerHost }}:{{ credential.brokerPort }}（TLS）</div>
          </div>
          <div class="min-w-0">
            <div class="text-muted-foreground text-xs">令牌到期</div>
            <div class="mt-1 text-sm tabular-nums">{{ credential.tokenExpiresAt }}</div>
          </div>
          <div class="min-w-0">
            <div class="text-muted-foreground text-xs">签发 / 轮换</div>
            <div class="mt-1 text-sm tabular-nums">
              {{ formatTime(credential.rotatedAt || credential.issuedAt) }}
            </div>
          </div>
          <div class="min-w-0">
            <div class="text-muted-foreground text-xs">可发布 Topic</div>
            <div class="mt-1 font-mono text-xs break-all">{{ credential.publishTopics.join(' , ') }}</div>
          </div>
          <div class="min-w-0">
            <div class="text-muted-foreground text-xs">可订阅 Topic</div>
            <div class="mt-1 font-mono text-xs break-all">{{ credential.subscribeTopics.join(' , ') }}</div>
          </div>
          <div class="min-w-0 lg:col-span-2">
            <div class="text-muted-foreground text-xs">edge token</div>
            <div class="mt-1 flex flex-wrap items-center gap-2">
              <code class="bg-muted max-w-[620px] rounded px-1.5 py-0.5 font-mono text-xs break-all">{{ credential.edgeToken }}</code>
              <Button variant="ghost" size="sm" class="h-6 px-2 text-xs" @click="copy(credential.edgeToken)">
                复制
              </Button>
            </div>
          </div>
        </div>
        <p v-else class="text-muted-foreground py-8 text-center text-sm">尚未签发接入凭据</p>

        <p class="text-muted-foreground text-xs leading-relaxed">
          HTTP 上报通道（无需 MQTT）：<code class="bg-muted rounded px-1 py-0.5 font-mono text-[11px]">POST /api/edge/telemetry | /heartbeat | /event | /cmd-ack</code>，
          指令用 <code class="bg-muted rounded px-1 py-0.5 font-mono text-[11px]">GET /api/edge/commands</code> 主动拉取，请求头带
          <code class="bg-muted rounded px-1 py-0.5 font-mono text-[11px]">Authorization: Bearer &lt;edge token&gt;</code>；
          MQTT 通道已开双向认证，需用 <code class="bg-muted rounded px-1 py-0.5 font-mono text-[11px]">server/issue-edge-cert.ps1 -DeviceCode &lt;设备编号&gt;</code> 签发的客户端证书连接：
          <code class="bg-muted rounded px-1 py-0.5 font-mono text-[11px]">--cafile ca.crt --cert edge-&lt;编号&gt;.crt --key edge-&lt;编号&gt;.key -p 8883</code>
          （用户名自动取证书 CN = 设备编号，上面的账号/口令仅作兜底）。
          完整示例见 <code class="bg-muted rounded px-1 py-0.5 font-mono text-[11px]">server/mock-edge-http.ps1</code>。
        </p>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>指令下发</CardTitle>
        <CardDescription>{{ isEdge ? '下发到边端 simulation 主题，边端暂不回 ack' : '下发后等待边缘端 cmd_ack 回执' }}</CardDescription>
      </CardHeader>
      <CardContent class="flex flex-col gap-4">
        <template v-if="isEdge">
          <div class="flex flex-wrap items-end gap-4">
            <div class="grid gap-2">
              <Label>指令类型</Label>
              <Select v-model="edgeForm.cmdType">
                <SelectTrigger class="w-[160px]">
                  <SelectValue placeholder="选择类型" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="type in edgeCmdTypes" :key="type" :value="type">{{ type }}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div class="grid gap-2">
              <Label for="edge-speed">速度 (0–5)</Label>
              <Input
                id="edge-speed"
                v-model="edgeForm.speed"
                class="w-[110px]"
                type="number"
                min="0"
                max="5"
                step="0.1"
              />
            </div>
            <div class="pb-1">
              <Button v-if="canWrite()" :disabled="sending" @click="submitCommand">
                {{ sending ? '下发中…' : '下发' }}
              </Button>
              <span v-else class="text-muted-foreground text-sm">当前角色为只读，不能下发指令</span>
            </div>
          </div>
          <div v-if="edgeForm.cmdType === 'MOVE_JOINT'" class="grid gap-2">
            <Label>关节目标（rad，6 个）</Label>
            <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <div v-for="(value, index) in edgeForm.jointTarget" :key="index" class="grid gap-1">
                <span class="text-muted-foreground text-xs">joint_{{ index + 1 }}</span>
                <Input v-model="edgeForm.jointTarget[index]" class="font-mono text-xs" type="number" step="0.01" />
              </div>
            </div>
          </div>
          <p class="text-muted-foreground text-xs">
            下发到 simulation/{{ device.simulationId }}/command，字段严格对齐边端 RobotCommand（不带 messageId/version）；
            边端目前不回 ack，记录会停在 PENDING。
          </p>
        </template>
        <div v-else class="flex flex-wrap items-end gap-4">
          <div class="grid gap-2">
            <Label>指令类型</Label>
            <Select v-model="commandForm.cmdType">
              <SelectTrigger class="w-[160px]">
                <SelectValue placeholder="选择类型" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="type in cmdTypes" :key="type" :value="type">{{ type }}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="grid gap-2">
            <Label for="command-version">版本</Label>
            <Input
              id="command-version"
              class="w-[110px]"
              type="number"
              min="1"
              :model-value="String(commandForm.version)"
              @update:model-value="onVersionInput"
            />
          </div>
          <div class="grid min-w-[320px] flex-1 gap-2">
            <Label for="command-payload">参数(JSON)</Label>
            <Textarea id="command-payload" v-model="commandForm.payload" rows="2" class="font-mono text-xs" />
          </div>
          <div class="pb-1">
            <Button v-if="canWrite()" :disabled="sending" @click="submitCommand">
              {{ sending ? '下发中…' : '下发' }}
            </Button>
            <span v-else class="text-muted-foreground text-sm">当前角色为只读，不能下发指令</span>
          </div>
        </div>

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead class="w-[280px]">messageId</TableHead>
              <TableHead class="w-[120px]">类型</TableHead>
              <TableHead class="w-[130px]">目标</TableHead>
              <TableHead class="w-[120px]">下发人</TableHead>
              <TableHead class="w-[80px]">版本</TableHead>
              <TableHead class="w-[110px]">结果</TableHead>
              <TableHead class="w-[180px]">下发时间</TableHead>
              <TableHead class="w-[180px]">回执时间</TableHead>
              <TableHead>说明</TableHead>
              <TableHead class="w-[90px]">效果</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="row in commands" :key="row.messageId">
              <TableCell class="font-mono text-xs">{{ row.messageId }}</TableCell>
              <TableCell>{{ row.cmdType }}</TableCell>
              <TableCell class="font-mono text-xs">{{ row.targetRobotId || '-' }}</TableCell>
              <TableCell>{{ row.issuedByName || '-' }}</TableCell>
              <TableCell class="tabular-nums">{{ row.version }}</TableCell>
              <TableCell>
                <Badge :class="resultClass(row.result)">{{ row.result || 'PENDING' }}</Badge>
              </TableCell>
              <TableCell class="text-muted-foreground tabular-nums">{{ formatTime(row.issuedAt) }}</TableCell>
              <TableCell class="text-muted-foreground tabular-nums">{{ formatTime(row.acknowledgedAt) }}</TableCell>
              <TableCell class="text-muted-foreground">{{ row.resultDetail || '-' }}</TableCell>
              <TableCell>
                <Button variant="ghost" size="sm" class="h-6 px-2 text-xs" @click="openEffect(row)">看效果</Button>
              </TableCell>
            </TableRow>
            <TableRow v-if="!commands.length">
              <TableCell colspan="10" class="text-muted-foreground h-16 text-center">暂无指令记录</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>故障事件</CardTitle>
        <CardDescription>每 5 秒刷新 · 最近 {{ faults.length }} 条</CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead class="w-[180px]">发生时间</TableHead>
              <TableHead class="w-[180px]">类型</TableHead>
              <TableHead class="w-[110px]">等级</TableHead>
              <TableHead>详情</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="row in faults" :key="row.id">
              <TableCell class="text-muted-foreground tabular-nums">{{ formatTime(row.occurredAt) }}</TableCell>
              <TableCell>{{ row.eventType }}</TableCell>
              <TableCell>
                <Badge :class="levelClass(row.level)">{{ row.level }}</Badge>
              </TableCell>
              <TableCell class="text-muted-foreground">{{ row.detail || '-' }}</TableCell>
            </TableRow>
            <TableRow v-if="!faults.length">
              <TableCell colspan="4" class="text-muted-foreground h-16 text-center">暂无故障事件</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>

    <Dialog v-model:open="renameVisible">
      <DialogContent class="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>重命名设备</DialogTitle>
          <DialogDescription>名称按 UTF-8 写入，可用于修正历史乱码数据。</DialogDescription>
        </DialogHeader>
        <div class="grid gap-2">
          <Label for="rename-name">设备名称</Label>
          <Input
            id="rename-name"
            v-model="renameForm.name"
            placeholder="机械臂一号"
            @keyup.enter="submitRename"
          />
        </div>
        <DialogFooter>
          <Button variant="outline" @click="renameVisible = false">取消</Button>
          <Button :disabled="renaming" @click="submitRename">{{ renaming ? '保存中…' : '保存' }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="effectVisible">
      <DialogContent class="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>下发效果分析</DialogTitle>
          <DialogDescription>
            对比该指令生效时刻前后各 {{ effect?.windowMinutes || 30 }} 分钟的关节力矩（effort）变化。
          </DialogDescription>
        </DialogHeader>
        <p v-if="effectLoading" class="text-muted-foreground py-8 text-center text-sm">分析中…</p>
        <div v-else-if="effect" class="flex flex-col gap-4">
          <div class="rounded-md border p-3 text-sm">
            <span class="font-medium">结论：</span>{{ effect.verdict }}
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>关节</TableHead>
                <TableHead>下发前均值</TableHead>
                <TableHead>下发后均值</TableHead>
                <TableHead>变化</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="j in effectJointRows" :key="j.joint">
                <TableCell class="font-medium">{{ j.joint }}</TableCell>
                <TableCell class="tabular-nums">{{ j.before != null ? j.before : '—' }}</TableCell>
                <TableCell class="tabular-nums">{{ j.after != null ? j.after : '—' }}</TableCell>
                <TableCell
                  class="tabular-nums"
                  :class="j.delta > 0 ? 'text-red-600' : j.delta < 0 ? 'text-emerald-600' : ''"
                >
                  {{ j.delta != null ? (j.delta > 0 ? '+' : '') + j.delta : '—' }}
                </TableCell>
              </TableRow>
              <TableRow v-if="!effectJointRows.length">
                <TableCell colspan="4" class="text-muted-foreground h-16 text-center">无对比数据</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
        <p v-else class="text-muted-foreground py-8 text-center text-sm">暂无数据</p>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from '@/lib/toast'
import * as echarts from 'echarts'
import { ArrowLeft, Pencil } from 'lucide-vue-next'
import {
  getCommands,
  getDevice,
  getFaultEvents,
  getFaultStatistics,
  getLatestTelemetry,
  getTelemetrySeries,
  renameDevice,
  sendCommand
} from '../api/device'
import { issueCredentials, getCredentials, revokeCredentials } from '../api/credential'
import { getDeviceHealth, getDeviceTrend, getCommandEffect } from '../api/analysis'
import SubScore from '@/components/SubScore.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { canWrite } from '@/stores/auth'
import { formatClock, formatTime, isoBefore, parseJson } from '../utils/format'

const route = useRoute()
const router = useRouter()
const deviceId = route.params.id

const cmdTypes = ['PARAMETER', 'STRATEGY', 'MODEL', 'CONFIG']
const edgeCmdTypes = ['START', 'STOP', 'MOVE_HOME', 'MOVE_JOINT']
const historyWindows = { '15m': 15 * 60 * 1000, '1h': 60 * 60 * 1000, '6h': 6 * 60 * 60 * 1000 }
const statsWindows = { '24h': 24 * 60 * 60 * 1000, '7d': 7 * 24 * 60 * 60 * 1000 }

const device = ref({})
const telemetry = ref({})
const commands = ref([])
const faults = ref([])
const historySeries = ref([])
const stats = ref({ total: 0, byLevel: [], byType: [], byDay: [] })
const historyRange = ref('1h')
// 降采样：按等时间分桶取均值，避免原始采样密度把曲线挤成一团（接口 downsample=true）
const historyDownsample = ref(true)
const statsRange = ref('24h')
const sending = ref(false)
const renaming = ref(false)
const renameVisible = ref(false)
const commandForm = reactive({ cmdType: 'PARAMETER', version: 1, payload: '{}' })
const edgeForm = reactive({ cmdType: 'START', speed: 1, jointTarget: ['0', '0', '0', '0', '0', '0'] })
const renameForm = reactive({ name: '' })
const credential = ref(null)
const credentialSaving = ref(false)
const health = ref(null)
const healthWindow = ref(24)
const trend = ref(null)
const trendWindow = ref(24)
const effectVisible = ref(false)
const effectLoading = ref(false)
const effect = ref(null)

const historyRef = ref(null)
const levelRef = ref(null)
const typeRef = ref(null)
const dayRef = ref(null)
const charts = {}

let telemetryTimer = null
let slowTimer = null
let historyTimer = null
let statsTimer = null
let healthTimer = null
let trendTimer = null

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

const joints = computed(() => parseJson(telemetry.value.jointPayload) || [])
// 绑定了 simulationId 的设备 = 边端（simulation 契约），指令走 motion 通道
const isEdge = computed(() => !!device.value.simulationId)

const STATUS_CLASS = {
  ONLINE: 'border-transparent bg-emerald-100 text-emerald-800',
  RUNNING: 'border-transparent bg-emerald-100 text-emerald-800',
  OFFLINE: 'border-transparent bg-slate-200 text-slate-600'
}

const RESULT_CLASS = {
  SUCCESS: 'border-transparent bg-emerald-100 text-emerald-800',
  FAILED: 'border-transparent bg-red-100 text-red-700',
  PENDING: 'border-transparent bg-amber-100 text-amber-800'
}

const LEVEL_CLASS = {
  INFO: 'border-transparent bg-slate-200 text-slate-700',
  WARNING: 'border-transparent bg-amber-100 text-amber-800',
  ERROR: 'border-transparent bg-red-100 text-red-700',
  FATAL: 'border-transparent bg-red-600 text-white'
}

const statusClass = (status) => STATUS_CLASS[status] || 'border-transparent bg-amber-100 text-amber-800'
const resultClass = (result) => RESULT_CLASS[result] || 'border-transparent bg-slate-200 text-slate-700'
const levelClass = (level) => LEVEL_CLASS[level] || 'border-transparent bg-slate-200 text-slate-700'

const onHistoryRange = (value) => {
  historyRange.value = value
  loadHistory()
}

const onHistoryDownsample = (value) => {
  historyDownsample.value = value
  loadHistory()
}

const onStatsRange = (value) => {
  statsRange.value = value
  loadStats()
}

const onVersionInput = (value) => {
  commandForm.version = Math.max(1, Number(value) || 1)
}

const ensureChart = (key, element) => {
  if (!element) return null
  if (!charts[key]) {
    charts[key] = echarts.init(element)
  }
  return charts[key]
}

const resizeCharts = () => Object.values(charts).forEach((chart) => chart.resize())

const loadTelemetry = async () => {
  const { data } = await getLatestTelemetry(deviceId)
  telemetry.value = data || {}
}

const loadSlow = async () => {
  const [deviceRes, commandRes, faultRes] = await Promise.all([
    getDevice(deviceId),
    getCommands(deviceId, { page: 0, size: 10 }),
    getFaultEvents({ deviceId, page: 0, size: 10 })
  ])
  device.value = deviceRes.data
  commands.value = commandRes.data
  faults.value = faultRes.data
}

const loadHistory = async () => {
  const windowMs = historyWindows[historyRange.value]
  const params = { limit: 300, downsample: historyDownsample.value }
  if (windowMs) params.from = isoBefore(windowMs)
  const { data } = await getTelemetrySeries(deviceId, params)
  historySeries.value = data || []
  await nextTick()
  renderHistory()
  charts.history?.resize()
}

const renderHistory = () => {
  const chart = ensureChart('history', historyRef.value)
  if (!chart) return
  const frames = historySeries.value.map((frame) => ({
    clock: formatClock(frame.reportedAt),
    joints: parseJson(frame.jointPayload) || []
  }))
  const names = [...new Set(frames.flatMap((frame) => frame.joints.map((joint) => joint.name)))]
  chart.setOption(
    {
      tooltip: { trigger: 'axis' },
      legend: { type: 'scroll', top: 0 },
      grid: { left: 56, right: 24, top: 40, bottom: 32 },
      xAxis: { type: 'category', boundaryGap: false, data: frames.map((frame) => frame.clock) },
      yAxis: { type: 'value', name: '位置' },
      series: names.map((name) => ({
        name,
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: frames.map((frame) => {
          const joint = frame.joints.find((item) => item.name === name)
          return joint ? joint.position : null
        })
      }))
    },
    true
  )
}

const loadHealth = async () => {
  try {
    const { data } = await getDeviceHealth(deviceId, { windowHours: healthWindow.value })
    health.value = data
  } catch (e) {
    // 健康分析失败不影响详情主流程
  }
}

const loadTrend = async () => {
  try {
    const { data } = await getDeviceTrend(deviceId, { windowHours: trendWindow.value, buckets: 12 })
    trend.value = data
  } catch (e) {
    // 趋势分析失败不影响详情主流程
  }
}

const openEffect = async (row) => {
  effect.value = null
  effectVisible.value = true
  effectLoading.value = true
  try {
    const { data } = await getCommandEffect(row.id, { metric: 'effort', windowMinutes: 30 })
    effect.value = data
  } catch (error) {
    toast.error(error.response?.data?.error || '效果分析失败')
    effectVisible.value = false
  } finally {
    effectLoading.value = false
  }
}

// 把 before/after 两个数组按关节名对齐成一张表，delta = after - before
const effectJointRows = computed(() => {
  if (!effect.value) return []
  const beforeMap = new Map((effect.value.before || []).map((s) => [s.joint, s.mean]))
  const afterMap = new Map((effect.value.after || []).map((s) => [s.joint, s.mean]))
  const joints = [...new Set([...beforeMap.keys(), ...afterMap.keys()])]
  return joints.map((joint) => {
    const before = beforeMap.has(joint) ? beforeMap.get(joint) : null
    const after = afterMap.has(joint) ? afterMap.get(joint) : null
    const delta = before != null && after != null ? Math.round((after - before) * 1000) / 1000 : null
    return { joint, before, after, delta }
  })
})

const loadStats = async () => {
  const windowMs = statsWindows[statsRange.value]
  const params = { deviceId }
  if (windowMs) params.from = isoBefore(windowMs)
  const { data } = await getFaultStatistics(params)
  stats.value = data || { total: 0, byLevel: [], byType: [], byDay: [] }
  await nextTick()
  renderStats()
  Object.values(charts).forEach((chart) => chart.resize())
}

const renderStats = () => {
  const byLevel = stats.value.byLevel || []
  const byType = stats.value.byType || []
  const byDay = stats.value.byDay || []

  const levelChart = ensureChart('level', levelRef.value)
  if (levelChart) {
    levelChart.setOption(
      {
        title: { text: '按等级', left: 'center', textStyle: { fontSize: 13, fontWeight: 'normal' } },
        tooltip: { trigger: 'item' },
        legend: { bottom: 0, type: 'scroll' },
        color: ['#909399', '#e6a23c', '#f56c6c', '#c45656', '#409eff'],
        series: [
          {
            type: 'pie',
            radius: ['42%', '66%'],
            center: ['50%', '48%'],
            label: { formatter: '{b} {c}' },
            data: byLevel.map((item) => ({ name: item.key, value: item.count }))
          }
        ]
      },
      true
    )
  }

  const typeChart = ensureChart('type', typeRef.value)
  if (typeChart) {
    typeChart.setOption(
      {
        title: { text: '按类型', left: 'center', textStyle: { fontSize: 13, fontWeight: 'normal' } },
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        grid: { left: 8, right: 24, top: 40, bottom: 8, containLabel: true },
        xAxis: { type: 'value', minInterval: 1 },
        yAxis: { type: 'category', data: byType.map((item) => item.key) },
        series: [
          {
            type: 'bar',
            barMaxWidth: 18,
            itemStyle: { color: '#409eff' },
            data: byType.map((item) => item.count)
          }
        ]
      },
      true
    )
  }

  const dayChart = ensureChart('day', dayRef.value)
  if (dayChart) {
    dayChart.setOption(
      {
        title: { text: '按日期', left: 'center', textStyle: { fontSize: 13, fontWeight: 'normal' } },
        tooltip: { trigger: 'axis' },
        grid: { left: 44, right: 24, top: 40, bottom: 28 },
        xAxis: { type: 'category', data: byDay.map((item) => item.key) },
        yAxis: { type: 'value', minInterval: 1 },
        series: [
          {
            type: 'bar',
            barMaxWidth: 24,
            itemStyle: { color: '#e6a23c' },
            data: byDay.map((item) => item.count)
          }
        ]
      },
      true
    )
  }
}

const openRename = () => {
  renameForm.name = device.value.name || ''
  renameVisible.value = true
}

const submitRename = async () => {
  if (!renameForm.name.trim()) {
    toast.error('设备名称不能为空')
    return
  }
  renaming.value = true
  try {
    await renameDevice(deviceId, renameForm.name.trim())
    toast.success('已保存')
    renameVisible.value = false
    await loadSlow()
  } catch (error) {
    toast.error(error.response?.data?.error || '保存失败')
  } finally {
    renaming.value = false
  }
}

const submitCommand = async () => {
  let body
  if (isEdge.value) {
    // 边端：只认 START/STOP/MOVE_HOME/MOVE_JOINT，jointTarget 固定 6 个、speed 取 0–5
    const speed = Number(edgeForm.speed)
    if (!Number.isFinite(speed) || speed < 0 || speed > 5) {
      toast.error('速度必须在 0–5 之间')
      return
    }
    body = { cmdType: edgeForm.cmdType, speed }
    if (edgeForm.cmdType === 'MOVE_JOINT') {
      const jointTarget = edgeForm.jointTarget.map((value) => Number(value))
      if (jointTarget.some((value) => !Number.isFinite(value))) {
        toast.error('关节目标必须是 6 个数值')
        return
      }
      body.jointTarget = jointTarget
    }
  } else {
    let payload
    try {
      payload = JSON.parse(commandForm.payload)
    } catch (error) {
      toast.error('参数不是合法 JSON')
      return
    }
    body = { cmdType: commandForm.cmdType, version: commandForm.version, payload }
  }
  sending.value = true
  try {
    const { data } = await sendCommand(deviceId, body)
    toast[data.result === 'FAILED' ? 'error' : 'success'](
      data.result === 'FAILED' ? `下发失败：${data.resultDetail || ''}` : '指令已下发，等待回执'
    )
    await loadSlow()
  } catch (error) {
    toast.error(error.response?.data?.error || '下发失败')
  } finally {
    sending.value = false
  }
}

const loadCredential = async () => {
  try {
    const { data } = await getCredentials(deviceId)
    credential.value = data
  } catch (error) {
    if (error.response?.status === 403) {
      credential.value = null
      return
    }
    toast.error(error.response?.data?.error || '查询接入凭据失败')
  }
}

const issueCredential = async () => {
  credentialSaving.value = true
  try {
    const { data } = await issueCredentials(deviceId)
    credential.value = data
    toast.success('凭据已签发，请复制到边缘端/仿真端配置')
  } catch (error) {
    toast.error(error.response?.data?.error || '签发失败')
  } finally {
    credentialSaving.value = false
  }
}

const revokeCredential = async () => {
  credentialSaving.value = true
  try {
    const { data } = await revokeCredentials(deviceId)
    credential.value = data
    toast.success('凭据已吊销，旧令牌立即失效')
  } catch (error) {
    toast.error(error.response?.data?.error || '吊销失败')
  } finally {
    credentialSaving.value = false
  }
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

onMounted(() => {
  loadTelemetry()
  loadCredential()
  loadSlow()
  loadHistory()
  loadStats()
  loadHealth()
  loadTrend()
  telemetryTimer = setInterval(loadTelemetry, 2000)
  slowTimer = setInterval(loadSlow, 5000)
  historyTimer = setInterval(loadHistory, 10000)
  statsTimer = setInterval(loadStats, 30000)
  healthTimer = setInterval(loadHealth, 30000)
  trendTimer = setInterval(loadTrend, 60000)
  window.addEventListener('resize', resizeCharts)
})

onUnmounted(() => {
  clearInterval(telemetryTimer)
  clearInterval(slowTimer)
  clearInterval(historyTimer)
  clearInterval(statsTimer)
  clearInterval(healthTimer)
  clearInterval(trendTimer)
  window.removeEventListener('resize', resizeCharts)
  Object.values(charts).forEach((chart) => chart.dispose())
})
</script>
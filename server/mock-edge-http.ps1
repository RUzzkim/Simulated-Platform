param(
  # 演示「端」（Gazebo 仿真桥接脚本）走纯 HTTP 通道上报：适合只有 HTTP、不方便接 MQTT 的场景
  [string]$BaseUrl = "http://127.0.0.1:8090",
  [string]$DeviceId = "robot-001",
  # 设备详情页「边缘接入」里的 edge token；留空时若设置了 ADMIN_PASSWORD 会自动登录并读取
  [string]$EdgeToken = $env:MQTT_EDGE_TOKEN,
  [int]$Iterations = 10,
  [int]$IntervalSeconds = 2,
  [string]$AdminUsername = $(if ($env:ADMIN_USERNAME) { $env:ADMIN_USERNAME } else { "admin" }),
  [string]$AdminPassword = $env:ADMIN_PASSWORD,
  [switch]$EmitFault,
  [switch]$AckCommands
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)

function New-Timestamp {
  (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}

function Invoke-JsonApi {
  param(
    [string]$Method,
    [string]$Path,
    [hashtable]$Headers,
    $Body
  )
  $uri = "$BaseUrl$Path"
  if ($null -eq $Body) {
    return Invoke-RestMethod -Uri $uri -Method $Method -Headers $Headers
  }
  # 显式转 UTF-8 字节：PowerShell 5.1 直接传字符串会按 ANSI 编码，中文载荷会变 ?
  $bytes = [Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Depth 6 -Compress))
  return Invoke-RestMethod -Uri $uri -Method $Method -Headers $Headers `
    -ContentType "application/json; charset=utf-8" -Body $bytes
}

function Get-EdgeTokenFromCloud {
  if (-not $AdminPassword) {
    throw "缺少 edge token：请在设备详情页「边缘接入」复制 edgeToken，或设置 `$env:ADMIN_PASSWORD 让脚本自动读取"
  }
  $login = Invoke-JsonApi -Method Post -Path "/api/auth/login" -Headers @{} `
    -Body @{ username = $AdminUsername; password = $AdminPassword }
  $adminHeaders = @{ Authorization = "Bearer $($login.token)" }
  $device = (Invoke-JsonApi -Method Get -Path "/api/devices" -Headers $adminHeaders) |
    Where-Object { $_.deviceCode -eq $DeviceId } | Select-Object -First 1
  if (-not $device) { throw "云平台里找不到设备 $DeviceId" }
  $credential = Invoke-JsonApi -Method Get -Path "/api/devices/$($device.id)/credentials" -Headers $adminHeaders
  if (-not $credential -or -not $credential.edgeToken) {
    Write-Host "[端] 设备 $DeviceId 还没有凭据，正在签发…"
    $credential = Invoke-JsonApi -Method Post -Path "/api/devices/$($device.id)/credentials" -Headers $adminHeaders
  }
  Write-Host "[端] 已从云平台读取设备 $DeviceId 的 edge token（有效期至 $($credential.tokenExpiresAt)）"
  return $credential.edgeToken
}

if (-not $EdgeToken) { $EdgeToken = Get-EdgeTokenFromCloud }
$headers = @{ Authorization = "Bearer $EdgeToken" }

$me = Invoke-JsonApi -Method Get -Path "/api/edge/me" -Headers $headers
Write-Host "HTTP 模拟端启动：device=$($me.deviceCode) id=$($me.deviceId) broker 上报为 MQTT 等价通道"
Write-Host "  可订阅：$($me.subscribeTopics -join ', ')"
Write-Host "  可发布：$($me.publishTopics -join ', ')"

$acked = 0
try {
  for ($i = 1; $i -le $Iterations; $i++) {
    $timestamp = New-Timestamp

    $telemetry = @{
      messageId   = [guid]::NewGuid().ToString()
      deviceId    = $DeviceId
      timestamp   = $timestamp
      state       = "RUNNING"
      controlMode = "ADAPTIVE"
      joints      = @(
        @{ name = "joint_1"; position = ([math]::Round(12.5 + $i * 0.1, 3)); velocity = 0.4; effort = 1.2 },
        @{ name = "joint_2"; position = ([math]::Round(-8.2 - $i * 0.1, 3)); velocity = 0.1; effort = 0.9 }
      )
      endEffector = @{ x = 0.31; y = -0.05; z = 0.42; roll = 0.0; pitch = 1.57; yaw = 0.0 }
    }
    $accepted = Invoke-JsonApi -Method Post -Path "/api/edge/telemetry" -Headers $headers -Body $telemetry

    $heartbeat = @{
      messageId   = [guid]::NewGuid().ToString()
      deviceId    = $DeviceId
      timestamp   = $timestamp
      status      = "ONLINE"
      cpu         = 12.5
      memory      = 40.0
      edgeVersion = "0.1.0-http"
    }
    Invoke-JsonApi -Method Post -Path "/api/edge/heartbeat" -Headers $headers -Body $heartbeat | Out-Null

    if ($EmitFault -and $i -eq 2) {
      $fault = @{
        messageId = [guid]::NewGuid().ToString()
        deviceId  = $DeviceId
        timestamp = $timestamp
        type      = "TORQUE_ABNORMAL"
        level     = "WARNING"
        detail    = "HTTP 模拟端 joint_2 力矩异常"
        context   = @{ joint = "joint_2"; torque = 3.7 }
      }
      Invoke-JsonApi -Method Post -Path "/api/edge/event" -Headers $headers -Body $fault | Out-Null
      Write-Host "[端] 已上报故障事件 TORQUE_ABNORMAL"
    }

    if ($AckCommands) {
      # MQTT 通道是订阅推送 cmd；HTTP 通道主动拉取，再把执行结果回执
      $pending = (Invoke-JsonApi -Method Get -Path "/api/edge/commands?limit=5" -Headers $headers) |
        Where-Object { $_.result -eq "PENDING" }
      foreach ($command in $pending) {
        $ack = @{
          messageId = $command.messageId
          deviceId  = $DeviceId
          timestamp = New-Timestamp
          result    = "SUCCESS"
          detail    = "HTTP mock edge applied command"
        }
        Invoke-JsonApi -Method Post -Path "/api/edge/cmd-ack" -Headers $headers -Body $ack | Out-Null
        $acked++
        Write-Host "[端] 指令回执成功：$($command.messageId)（$($command.cmdType)）"
      }
    }

    Write-Host "[端] $i/$Iterations 已上报遥测与心跳（reportedAt=$($accepted.reportedAt)）"
    if ($i -lt $Iterations) { Start-Sleep -Seconds $IntervalSeconds }
  }
} finally {
  Write-Host "HTTP 模拟端已停止（回执指令 $acked 条）"
}
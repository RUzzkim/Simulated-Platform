param(
  [string]$DeviceId = "robot-001",
  [int]$Iterations = 30,
  [int]$IntervalSeconds = 1,
  [string]$Container = "robot-mosquitto-local",
  [int]$Port = 8883,
  [string]$CaFile = "/mosquitto/config/certs/ca.crt",
  # 阶段 4 双向认证：broker 要求客户端证书，默认用 server/issue-edge-cert.ps1 签发的设备证书
  [string]$CertFile = "",
  [string]$KeyFile = "",
  # 严格 ACL 下边缘端必须用自己的设备账号（详情页「边缘接入」签发，或 provision-mqtt.ps1 输出）
  [string]$Username = $(if ($env:MQTT_DEVICE_USERNAME) { $env:MQTT_DEVICE_USERNAME } else { $env:MQTT_SERVICE_USERNAME }),
  [string]$Password = $(if ($env:MQTT_DEVICE_PASSWORD) { $env:MQTT_DEVICE_PASSWORD } else { $env:MQTT_SERVICE_PASSWORD }),
  [switch]$EmitFault
)

$ErrorActionPreference = 'Stop'

# 保证中文载荷以 UTF-8 传给 mosquitto_pub（PowerShell 5.1 默认用 ANSI 编码）
# 必须写 $global:，脚本作用域的 $OutputEncoding 对原生命令 stdin 不生效，中文会被压成 '?'
$global:OutputEncoding = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)

# 双向认证：证书路径在 broker 容器内（./certs 挂载到 /mosquitto/config/certs）
if (-not $CertFile) { $CertFile = "/mosquitto/config/certs/edge/edge-$DeviceId.crt" }
if (-not $KeyFile) { $KeyFile = "/mosquitto/config/certs/edge/edge-$DeviceId.key" }
$certOk = docker exec $Container sh -c "test -f $CertFile -a -f $KeyFile && echo ok"
if ($certOk -ne "ok") {
  throw "broker 已开启双向认证，但容器里找不到客户端证书：$CertFile / $KeyFile；先运行 server\issue-edge-cert.ps1 -DeviceCode $DeviceId"
}
# require_certificate + use_identity_as_username 时身份取自证书 CN，-u/-P 只是兜底
$AuthArgs = @()
if ($Username) { $AuthArgs = @("-u", $Username, "-P", $Password) }
Write-Host "[edge] TLS: cafile=$CaFile cert=$CertFile 身份=$(if ($Username) { $Username } else { "证书 CN" })"

function Publish-Mqtt([string]$Topic, [string]$Payload) {
  $pubArgs = @("exec", "-i", $Container, "mosquitto_pub", "-h", "localhost", "-p", "$Port", "--cafile", $CaFile, "--cert", $CertFile, "--key", $KeyFile, "-q", "1", "-t", $Topic, "-s") + $AuthArgs
  $Payload | & docker @pubArgs
  if ($LASTEXITCODE -ne 0) {
    throw "mosquitto_pub 发布失败：$Topic"
  }
}

function New-Timestamp {
  (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}

# 订阅云端下发的 cmd，并回 cmd_ack，模拟边缘端执行成功
$ackJob = Start-Job -ScriptBlock {
  param($Container, $DeviceId, $Username, $Password, $Port, $CaFile, $CertFile, $KeyFile)

  $global:OutputEncoding = New-Object Text.UTF8Encoding($false)

  $subArgs = @("exec", $Container, "mosquitto_sub", "-h", "localhost", "-p", "$Port", "--cafile", $CaFile, "--cert", $CertFile, "--key", $KeyFile, "-q", "1", "-t", "robot/$DeviceId/cmd", "-v")
  if ($Username) { $subArgs += @("-u", $Username, "-P", $Password) }
  & docker @subArgs |
    ForEach-Object {
      $payload = ($_ -split ' ', 2)[1]
      $messageId = $null
      try { $messageId = ($payload | ConvertFrom-Json).messageId } catch { }

      $ack = @{
        messageId = $messageId
        cmdId     = $messageId
        deviceId  = $DeviceId
        timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        result    = "SUCCESS"
        detail    = "mock edge applied command"
      } | ConvertTo-Json -Compress

      $ackArgs = @("exec", "-i", $Container, "mosquitto_pub", "-h", "localhost", "-p", "$Port", "--cafile", $CaFile, "--cert", $CertFile, "--key", $KeyFile, "-q", "1", "-t", "robot/$DeviceId/cmd_ack", "-s")
      if ($Username) { $ackArgs += @("-u", $Username, "-P", $Password) }
      $ack | & docker @ackArgs
      Write-Host "[edge] cmd_ack 已回执：$messageId"
    }
} -ArgumentList $Container, $DeviceId, $Username, $Password, $Port, $CaFile, $CertFile, $KeyFile

Write-Host "模拟边缘端启动：device=$DeviceId iterations=$Iterations interval=${IntervalSeconds}s"

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
    } | ConvertTo-Json -Depth 6 -Compress

    Publish-Mqtt "robot/$DeviceId/telemetry" $telemetry

    $heartbeat = @{
      messageId   = [guid]::NewGuid().ToString()
      deviceId    = $DeviceId
      timestamp   = $timestamp
      status      = "ONLINE"
      cpu         = 12.5
      memory      = 40.0
      edgeVersion = "0.1.0"
    } | ConvertTo-Json -Compress

    Publish-Mqtt "robot/$DeviceId/heartbeat" $heartbeat

    if ($EmitFault -and $i -eq 2) {
      $fault = @{
        messageId = [guid]::NewGuid().ToString()
        deviceId  = $DeviceId
        timestamp = $timestamp
        type      = "TORQUE_ABNORMAL"
        level     = "WARNING"
        detail    = "mock joint_2 力矩异常"
        context   = @{ joint = "joint_2"; torque = 3.7 }
      } | ConvertTo-Json -Depth 4 -Compress

      Publish-Mqtt "robot/$DeviceId/event" $fault
    }

    Write-Host "[edge] $i/$Iterations 已上报遥测与心跳"
    if ($i -lt $Iterations) { Start-Sleep -Seconds $IntervalSeconds }
  }
} finally {
  Stop-Job $ackJob -ErrorAction SilentlyContinue
  Remove-Job $ackJob -Force -ErrorAction SilentlyContinue
  Write-Host "模拟边缘端已停止"
}
param(
  [string]$DeviceId = "robot-001",
  [int]$Count = 3,
  [int]$IntervalSeconds = 1,
  [int]$Port = 8883,
  [string]$CaFile = "/mosquitto/config/certs/ca.crt",
  [string]$Username = $(if ($env:MQTT_DEVICE_USERNAME) { $env:MQTT_DEVICE_USERNAME } else { $env:MQTT_SERVICE_USERNAME }),
  [string]$Password = $(if ($env:MQTT_DEVICE_PASSWORD) { $env:MQTT_DEVICE_PASSWORD } else { $env:MQTT_SERVICE_PASSWORD })
)

$host.ui.RawUI.WindowTitle = "MQTT telemetry publisher"
$payload = @{
  deviceId = $DeviceId
  timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
  state = "RUNNING"
  joints = @(
    @{ name = "joint_1"; position = 12.5; velocity = 0.4 },
    @{ name = "joint_2"; position = -8.2; velocity = 0.1 }
  )
} | ConvertTo-Json -Depth 5

for ($index = 0; $index -lt $Count; $index++) {
  Write-Host "Publishing message $($index + 1)/$Count"
  docker exec robot-mosquitto-local mosquitto_pub `
    -h localhost -p $Port --cafile $CaFile `
    -u $Username -P $Password `
    -t "robot/$DeviceId/telemetry" `
    -m $payload
  if ($index -lt $Count - 1) { Start-Sleep -Seconds $IntervalSeconds }
}

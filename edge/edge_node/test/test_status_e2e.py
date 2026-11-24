"""端到端验证：STOP 指令 → 边端状态推断 → MQTT state → 云端收到 STOPPED

复用边端真实 StateProcessor（含 set_command_status），
验证状态推断结果能正确通过 MQTT 到达云端。
"""
import json
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import paho.mqtt.client as mqtt
from edge_node.processor.state_processor import StateProcessor

BROKER = "localhost"
PORT = 1883
SIM_ID = "SIM-001"
ROBOT_ID = "ROBOT-001"

# 边端真实状态处理器
processor = StateProcessor(SIM_ID, ROBOT_ID, default_status="RUNNING", max_torque=50.0)

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="status-inference-test")
client.connect(BROKER, PORT, keepalive=60)
client.loop_start()

# 模拟收到 STOP 指令 → 状态应为 STOPPED
processor.set_command_status("STOP")
state_stopped = processor.from_joint_state(
    position=[0.1] * 6, velocity=[0.0] * 6, effort=[10.0] * 6,
    stamp_nanosec=int(time.time() * 1e9),
)
print(f"[TEST] after STOP -> status={state_stopped.status}", flush=True)
client.publish(f"simulation/{SIM_ID}/state", json.dumps(state_stopped.to_dict()), qos=1)

time.sleep(0.5)

# 模拟收到 START 指令 → 状态应为 RUNNING
processor.set_command_status("START")
state_running = processor.from_joint_state(
    position=[0.2] * 6, velocity=[0.1] * 6, effort=[12.0] * 6,
    stamp_nanosec=int(time.time() * 1e9),
)
print(f"[TEST] after START -> status={state_running.status}", flush=True)
client.publish(f"simulation/{SIM_ID}/state", json.dumps(state_running.to_dict()), qos=1)

time.sleep(0.5)

# 模拟力矩超限 → 状态应为 ERROR（优先级最高，即使已 START）
state_error = processor.from_joint_state(
    position=[0.2] * 6, velocity=[0.1] * 6, effort=[60.0, 10, 10, 10, 10, 10],
    stamp_nanosec=int(time.time() * 1e9),
)
print(f"[TEST] torque exceed -> status={state_error.status}", flush=True)
client.publish(f"simulation/{SIM_ID}/state", json.dumps(state_error.to_dict()), qos=1)

time.sleep(1)
client.loop_stop()
client.disconnect()
print("[TEST] done", flush=True)

import json
import os
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from edge_node.mqtt.mqtt_client import MqttClient

sys.path.insert(0, os.path.dirname(__file__))
from simulation_simulator import RobotSimulator


class PublishRecorder:
    def __init__(self):
        self.calls = []

    def publish(self, topic, payload, qos):
        self.calls.append((topic, json.loads(payload), qos))


def test_safe_stop_command_uses_existing_simulator_stop_contract():
    client = MqttClient.__new__(MqttClient)
    client._simulation_id = 'SIM-001'
    client._command_topic = 'simulation/SIM-001/command'
    client._qos = 1
    client._lock = threading.Lock()
    client._client = PublishRecorder()

    client.publish_stop_command('ROBOT-001')

    topic, payload, qos = client._client.calls[0]
    assert topic == 'simulation/SIM-001/command'
    assert payload['simulationId'] == 'SIM-001'
    assert payload['robotId'] == 'ROBOT-001'
    assert payload['cmdType'] == 'STOP'
    assert qos == 1


def test_simulator_stop_cancels_the_safe_servo_target():
    simulator = RobotSimulator.__new__(RobotSimulator)
    simulator._lock = threading.Lock()
    simulator._plan = object()
    simulator._cmd_target = [1.0] * 6
    simulator._safe_mode = True
    simulator._safe_live = [0.1] * 6
    simulator.joints = [SimpleNamespace(q=0.2 + index) for index in range(6)]
    simulator.processor = SimpleNamespace(set_command_status=lambda cmd_type: None)

    message = SimpleNamespace(payload=json.dumps({'cmdType': 'STOP'}).encode())
    simulator._on_command(None, None, message)

    assert simulator._plan is None
    assert simulator._cmd_target == [joint.q for joint in simulator.joints]
    assert simulator._safe_mode is False
    assert simulator._safe_live is None

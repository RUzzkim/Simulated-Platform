"""MQTT 消息解析冒烟测试：不依赖真实 broker，直接驱动 on_message 回调"""
import sys
import os
import json
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from edge_node.mqtt.mqtt_client import MqttClient


def _make_client(on_command=None, on_config=None):
    client = MqttClient(
        broker_url='tcp://localhost:1883',
        client_id='test-edge',
        simulation_id='SIM-001',
        state_topic='simulation/SIM-001/state',
        heartbeat_topic='simulation/SIM-001/heartbeat',
        command_topic='simulation/SIM-001/command',
        config_topic='simulation/SIM-001/config',
        on_command=on_command,
        on_config=on_config,
    )
    return client


def test_command_callback_parses_correctly():
    received = {}

    def on_command(cmd):
        received['cmd'] = cmd

    client = _make_client(on_command=on_command)
    payload = json.dumps({
        'commandId': 'CMD-ABC12345',
        'simulationId': 'SIM-001',
        'robotId': 'ROBOT-001',
        'cmdType': 'MOVE_JOINT',
        'timestamp': 1760000000123,
        'jointTarget': [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        'speed': 1.0,
    })
    msg = MagicMock()
    msg.topic = 'simulation/SIM-001/command'
    msg.payload = payload.encode('utf-8')
    client._on_message(None, None, msg)

    assert 'cmd' in received
    cmd = received['cmd']
    assert cmd.command_id == 'CMD-ABC12345'
    assert cmd.cmd_type == 'MOVE_JOINT'
    assert cmd.joint_target == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]


def test_command_invalid_payload_does_not_raise():
    client = _make_client()
    msg = MagicMock()
    msg.topic = 'simulation/SIM-001/command'
    msg.payload = b'not-json'
    # 不应抛异常
    client._on_message(None, None, msg)


def test_config_callback():
    received = {}

    def on_config(cfg):
        received['cfg'] = cfg

    client = _make_client(on_config=on_config)
    payload = json.dumps({
        'controlMode': 'POSITION',
        'controlRate': 50.0,
        'algorithmParams': {'kp': 10},
        'simParams': {'gravity': 9.81},
    })
    msg = MagicMock()
    msg.topic = 'simulation/SIM-001/config'
    msg.payload = payload.encode('utf-8')
    client._on_message(None, None, msg)

    assert 'cfg' in received
    assert received['cfg'].control_mode == 'POSITION'
    assert received['cfg'].control_rate == 50.0


def test_publish_state_serialization():
    """验证 publish_state 序列化后的 JSON 字段与云端契约一致"""
    from edge_node.model.messages import RobotState
    client = _make_client()
    state = RobotState(
        simulation_id='SIM-001', robot_id='ROBOT-001',
        timestamp=1760000000123,
        joint_position=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        joint_velocity=[0.01, 0.02, 0.03, 0.04, 0.05, 0.06],
        joint_torque=[1, 2, 3, 4, 5, 6],
        status='RUNNING',
    )
    captured = {}
    client._client.publish = MagicMock(side_effect=lambda topic, payload, qos: captured.update({
        'topic': topic, 'payload': payload, 'qos': qos}))

    client.publish_state(state)
    data = json.loads(captured['payload'])
    assert captured['topic'] == 'simulation/SIM-001/state'
    assert captured['qos'] == 1
    assert data['simulationId'] == 'SIM-001'
    assert data['robotId'] == 'ROBOT-001'
    assert data['status'] == 'RUNNING'
    assert len(data['jointPosition']) == 6
    assert len(data['jointVelocity']) == 6
    assert len(data['jointTorque']) == 6


if __name__ == '__main__':
    import traceback
    tests = [v for k, v in globals().items() if k.startswith('test_') and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} tests passed")
    sys.exit(0 if passed == len(tests) else 1)

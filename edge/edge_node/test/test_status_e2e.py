"""通过本机 MQTT broker 验证边缘状态处理与状态发布链路。"""
import json
import os
from queue import Queue
import sys
import threading
import uuid

import paho.mqtt.client as mqtt
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from edge_node.mqtt.mqtt_client import MqttClient
from edge_node.processor.state_processor import StateProcessor

BROKER = os.environ.get('MQTT_TEST_BROKER', 'localhost')
PORT = int(os.environ.get('MQTT_TEST_PORT', '1883'))


def test_command_and_simulation_state_reach_independent_state_subscriber():
    suffix = uuid.uuid4().hex
    simulation_id = 'SIM-001'
    robot_id = 'ROBOT-001'
    topic_prefix = f'test/status-e2e/{suffix}/simulation/{simulation_id}'
    command_topic = f'{topic_prefix}/command'
    sim_state_topic = f'{topic_prefix}/sim_state'
    state_topic = f'{topic_prefix}/state'
    heartbeat_topic = f'{topic_prefix}/heartbeat'
    processor = StateProcessor(simulation_id, robot_id, default_status='RUNNING', max_torque=50.0)
    received_states = Queue()
    command_ready = threading.Event()
    edge_ready = threading.Event()
    edge_subscriptions = []
    subscriber_ready = threading.Event()
    edge = None
    publisher = None
    subscriber = None

    def on_command(command):
        processor.set_command_status(command.cmd_type)
        command_ready.set()

    def on_sim_state(data):
        state = processor.from_joint_state(
            position=data['jointPosition'],
            velocity=data['jointVelocity'],
            effort=data['jointTorque'],
            stamp_nanosec=data['timestamp'] * 1_000_000,
        )
        edge.publish_state(state)

    def on_edge_subscribe(client, userdata, mid, granted_qos):
        edge_subscriptions.append(granted_qos)
        if len(edge_subscriptions) == 3:
            edge_ready.set()

    def on_subscriber_connect(client, userdata, flags, rc):
        if rc == 0:
            client.subscribe(state_topic, qos=1)

    def on_subscriber_subscribe(client, userdata, mid, granted_qos):
        subscriber_ready.set()

    def on_state_message(client, userdata, message):
        received_states.put(json.loads(message.payload.decode('utf-8')))

    try:
        edge = MqttClient(
            broker_url=f'tcp://{BROKER}:{PORT}',
            client_id=f'edge-e2e-{suffix}',
            simulation_id=simulation_id,
            state_topic=state_topic,
            heartbeat_topic=heartbeat_topic,
            command_topic=command_topic,
            config_topic=f'{topic_prefix}/config',
            on_command=on_command,
            on_state=on_sim_state,
            upstream_state_topic=sim_state_topic,
        )
        edge._client.on_subscribe = on_edge_subscribe
        publisher = mqtt.Client(client_id=f'sim-e2e-{suffix}', protocol=mqtt.MQTTv311)
        subscriber = mqtt.Client(client_id=f'cloud-e2e-{suffix}', protocol=mqtt.MQTTv311)
        subscriber.on_connect = on_subscriber_connect
        subscriber.on_subscribe = on_subscriber_subscribe
        subscriber.on_message = on_state_message

        try:
            subscriber.connect(BROKER, PORT, keepalive=30)
        except OSError as exc:
            pytest.skip(f'MQTT broker unavailable at {BROKER}:{PORT}: {exc}')
        subscriber.loop_start()
        publisher.connect(BROKER, PORT, keepalive=30)
        publisher.loop_start()
        edge.connect()

        assert subscriber_ready.wait(5), 'independent state subscriber did not subscribe'
        assert edge_ready.wait(5), 'edge MQTT client did not finish subscribing'
        assert all(qos == (1,) for qos in edge_subscriptions)
        publisher.publish(command_topic, json.dumps({
            'commandId': f'CMD-{suffix}',
            'simulationId': simulation_id,
            'robotId': robot_id,
            'cmdType': 'STOP',
            'timestamp': 1760000000123,
        }), qos=1).wait_for_publish(timeout=5)
        assert command_ready.wait(5), 'edge client did not receive STOP command'

        base_state = {
            'timestamp': 1760000000123,
            'jointPosition': [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            'jointVelocity': [0.0] * 6,
            'jointTorque': [10.0] * 6,
        }
        publisher.publish(sim_state_topic, json.dumps(base_state), qos=1).wait_for_publish(timeout=5)
        stopped_state = received_states.get(timeout=5)
        assert stopped_state['status'] == 'STOPPED'
        assert stopped_state['jointPosition'] == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
        assert stopped_state['timestamp'] == 1760000000123
        error_state = dict(base_state, timestamp=1760000000133,
                           jointTorque=[60.0, 10.0, 10.0, 10.0, 10.0, 10.0])
        publisher.publish(sim_state_topic, json.dumps(error_state), qos=1).wait_for_publish(timeout=5)
        received_error_state = received_states.get(timeout=5)
        assert received_error_state['status'] == 'ERROR'
        assert received_error_state['jointTorque'] == [60.0, 10.0, 10.0, 10.0, 10.0, 10.0]
        assert received_error_state['timestamp'] == 1760000000133

        command_ready.clear()
        publisher.publish(command_topic, json.dumps({
            'commandId': f'CMD-START-{suffix}',
            'simulationId': simulation_id,
            'robotId': robot_id,
            'cmdType': 'START',
            'timestamp': 1760000000143,
        }), qos=1).wait_for_publish(timeout=5)
        assert command_ready.wait(5), 'edge client did not receive START command'
        running_state = dict(base_state, timestamp=1760000000143)
        publisher.publish(sim_state_topic, json.dumps(running_state), qos=1).wait_for_publish(timeout=5)
        received_running_state = received_states.get(timeout=5)
        assert received_running_state['status'] == 'RUNNING'
        assert received_running_state['timestamp'] == 1760000000143
        for state in (stopped_state, received_error_state, received_running_state):
            assert state['simulationId'] == simulation_id
            assert state['robotId'] == robot_id
    finally:
        for client in (edge._client if edge else None, publisher, subscriber):
            if client is not None:
                client.loop_stop()
                client.disconnect()

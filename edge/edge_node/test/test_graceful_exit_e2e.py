"""端到端验证：边端收到退出信号后执行 finally 收尾，把实验 Run 置为 INCOMPLETE。

依赖本机测试 broker（test/start_mqtt_broker.py，默认 localhost:1883）：
    py -B test/test_graceful_exit_e2e.py -v
broker 不可用时自动跳过。Windows 用 CTRL_BREAK_EVENT（SIGBREAK），POSIX 用 SIGINT。
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from queue import Empty, Queue

import paho.mqtt.client as mqtt
from jsonschema import Draft7Validator

BROKER = os.environ.get('MQTT_TEST_BROKER', 'localhost')
PORT = int(os.environ.get('MQTT_TEST_PORT', '1883'))
EDGE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CONFIG = os.path.join(EDGE_DIR, 'config', 'edge_config.yaml')
LIVE_SCHEMA = Path(EDGE_DIR) / 'docs' / 'contract' / 'v2_live_run.schema.json'
RUN_TOPIC = 'simulation/SIM-001/experiment_run'
SIM_STATE_TOPIC = 'simulation/SIM-001/sim_state'
# Windows 下 CTRL_C_EVENT 无法定向到进程组，只有 CTRL_BREAK_EVENT 可定向
EXIT_SIGNAL = signal.CTRL_BREAK_EVENT if hasattr(signal, 'SIGBREAK') else signal.SIGINT


def _await_run(received: Queue, run_id: str, status: str, timeout: float):
    """在已收到的 experiment_run 消息中等目标状态，返回 payload 或 None。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            payload = received.get(timeout=0.5)
        except Empty:
            continue
        if payload.get('run_id') != run_id:
            continue
        if (payload.get('task') or {}).get('status') == status:
            return payload
    return None


class GracefulExitE2ETest(unittest.TestCase):
    def test_graceful_stop_publishes_incomplete_run(self):
        run_id = uuid.uuid4().hex
        received: Queue = Queue()
        subscribed = threading.Event()

        def on_connect(client, userdata, flags, reason_code, properties):
            if reason_code == 0:
                client.subscribe(RUN_TOPIC, qos=1)

        def on_subscribe(client, userdata, mid, granted_qos, properties):
            subscribed.set()

        def on_message(client, userdata, message):
            try:
                received.put(json.loads(message.payload.decode('utf-8')))
            except (ValueError, UnicodeDecodeError):
                pass

        observer = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                               client_id=f'graceful-observer-{run_id[:8]}')
        observer.on_connect = on_connect
        observer.on_subscribe = on_subscribe
        observer.on_message = on_message
        try:
            observer.connect(BROKER, PORT, keepalive=30)
        except OSError as exc:
            self.skipTest(f'MQTT broker unavailable at {BROKER}:{PORT}: {exc}')

        publisher = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                client_id=f'graceful-sim-{run_id[:8]}')
        env = os.environ.copy()
        env.update({
            'MQTT_BROKER_URL': f'tcp://{BROKER}:{PORT}',
            'EDGE_RUN_ID': run_id,
            'EDGE_SCENARIO_ID': 'ONLINE-GRACEFUL',
            'EDGE_RUN_SPLIT': 'online',
        })
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        handle, log_path = tempfile.mkstemp(prefix='edge-graceful-', suffix='.log')
        os.close(handle)
        edge = None
        try:
            observer.loop_start()
            self.assertTrue(subscribed.wait(10), 'observer did not subscribe experiment_run')
            publisher.connect(BROKER, PORT, keepalive=30)
            publisher.loop_start()

            with open(log_path, 'w', encoding='utf-8') as log:
                edge = subprocess.Popen(
                    [sys.executable, '-B', '-m', 'edge_node.main', '--config', CONFIG],
                    cwd=EDGE_DIR, env=env, stdout=log, stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                )
                # 边端收到首帧 sim_state 后才发布 Run，持续推送正常状态直至观察到 IN_PROGRESS
                running = None
                deadline = time.time() + 30
                while time.time() < deadline:
                    publisher.publish(SIM_STATE_TOPIC, json.dumps({
                        'timestamp': 1760000000000,
                        'jointPosition': [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
                        'jointVelocity': [0.0] * 6,
                        'jointTorque': [1.0] * 6,
                    }), qos=1)
                    running = _await_run(received, run_id, 'IN_PROGRESS', 1.0)
                    if running is not None:
                        break
                log.flush()
                self.assertIsNotNone(
                    running,
                    'edge did not publish an IN_PROGRESS run:\n'
                    + _read(log_path))

                edge.send_signal(EXIT_SIGNAL)
                try:
                    returncode = edge.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    self.fail('edge did not exit after graceful signal:\n' + _read(log_path))
                self.assertEqual(returncode, 0, 'edge exit code %s, expected graceful exit' % returncode)

                incomplete = _await_run(received, run_id, 'INCOMPLETE', 20)
                self.assertIsNotNone(
                    incomplete,
                    'edge did not publish INCOMPLETE run on graceful stop:\n' + _read(log_path))
                self.assertEqual(incomplete['run_id'], run_id)
                self.assertEqual(incomplete['contract_version'], '2.0.0')
                self.assertEqual(incomplete['simulation']['simulation_id'], 'SIM-001')
                # 实时部分 Run 必须符合独立的辅助 schema（契约 2.0.0 §10）
                live_validator = Draft7Validator(
                    json.loads(LIVE_SCHEMA.read_text(encoding='utf-8')))
                self.assertEqual([], list(live_validator.iter_errors(running)))
                self.assertEqual([], list(live_validator.iter_errors(incomplete)))

            log_text = _read(log_path)
            self.assertIn('边端节点已退出', log_text, 'edge did not reach the shutdown epilogue')
            self.assertNotIn('发布 OFFLINE 心跳失败', log_text, 'OFFLINE heartbeat was rejected')
        finally:
            if edge is not None and edge.poll() is None:
                edge.kill()
                edge.wait()
            for client in (publisher, observer):
                client.loop_stop()
                client.disconnect()
            if os.path.exists(log_path):
                os.unlink(log_path)


def _read(path: str) -> str:
    with open(path, encoding='utf-8', errors='replace') as handle:
        return handle.read()


if __name__ == '__main__':
    unittest.main()

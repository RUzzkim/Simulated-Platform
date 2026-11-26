"""一键演示：实时边端从 MOVE_JOINT 到 JOINT_LOCKED 检测、容错决策与优雅退出。

流程：
  1) 启动边端子进程（无 ROS 2 模式，走 MQTT 链路），开启任务恢复（TASK_RECOVERY_ENABLED=true）
  2) 发布 MOVE_JOINT，让边端持有任务目标
  3) 以 50Hz 发布 J0 位置锁定 + 12.5N·m 力矩的 sim_state，触发 JOINT_LOCKED
  4) 用 cloud-service 证书订阅 experiment_run / experiment_event，打印 FAULT 与 DECISION
  5) CTRL_BREAK（POSIX 为 SIGINT）优雅停止边端，确认 Run 最终为 INCOMPLETE

依赖本机 Docker 栈（broker 8884 双向 TLS）。用法：
  py test/experiments/live_decision_demo.py

前端查看：http://127.0.0.1:8091/experiments
"""
import argparse
import json
import os
import signal
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import paho.mqtt.client as mqtt

ROOT = Path(__file__).resolve().parents[4]
EDGE_DIR = Path(__file__).resolve().parents[2]
CERTS = ROOT / 'deploy' / 'certs'
EXIT_SIGNAL = signal.CTRL_BREAK_EVENT if hasattr(signal, 'SIGBREAK') else signal.SIGINT


def parse_broker(url):
    host_port = url.split('://', 1)[-1]
    host, _, port = host_port.partition(':')
    return host, int(port or 8884), url.startswith(('ssl://', 'mqtts://', 'tls://'))


def make_client(client_id, args, cert, key):
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    host, port, secure = parse_broker(args.broker)
    if secure:
        context = ssl.create_default_context(cafile=str(args.ca))
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(cert), str(key))
        client.tls_set_context(context)
    return client, host, port


def read_log(path):
    try:
        return Path(path).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


def publish_state(client, args, position, velocity, torque):
    client.publish(f'simulation/{args.simulation_id}/sim_state', json.dumps({
        'simulationId': args.simulation_id,
        'robotId': args.robot_id,
        'jointPosition': position,
        'jointVelocity': velocity,
        'jointTorque': torque,
        'stampNanosec': time.time_ns(),
    }), qos=1)


def publish_for(client, args, position, velocity, torque, seconds, rate=50.0):
    deadline = time.perf_counter() + seconds
    interval = 1.0 / rate
    while time.perf_counter() < deadline:
        publish_state(client, args, position, velocity, torque)
        time.sleep(interval)


def wait_until(predicate, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    return None


def main():
    parser = argparse.ArgumentParser(description='实时边端故障决策一键演示')
    parser.add_argument('--broker', default='ssl://127.0.0.1:8884')
    parser.add_argument('--ca', default=str(CERTS / 'ca.crt'))
    parser.add_argument('--cert', default=str(CERTS / 'edge' / 'edge-SIM-001.crt'))
    parser.add_argument('--key', default=str(CERTS / 'edge' / 'edge-SIM-001.key'))
    parser.add_argument('--observer-cert', default=str(CERTS / 'cloud-service.crt'),
                        help='需要读取 experiment_run/experiment_event 的凭据（云端服务身份）')
    parser.add_argument('--observer-key', default=str(CERTS / 'cloud-service.key'))
    parser.add_argument('--config', default=str(EDGE_DIR / 'config' / 'edge_config.yaml'))
    parser.add_argument('--simulation-id', default='SIM-001')
    parser.add_argument('--robot-id', default='ROBOT-001')
    parser.add_argument('--run-id', default='')
    parser.add_argument('--target', default='0.4,0.2,-0.3,0.1,0.2,0.1', help='MOVE_JOINT 目标关节角')
    parser.add_argument('--locked-joint', type=int, default=0)
    parser.add_argument('--lock-torque', type=float, default=12.5, help='锁定关节合成力矩 N·m')
    args = parser.parse_args()

    args.target = [float(value) for value in args.target.split(',')]
    run_id = args.run_id or uuid.uuid4().hex
    pending = {'runs': [], 'events': []}
    lock = threading.Lock()
    subscribed = threading.Event()

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            client.subscribe(f'simulation/{args.simulation_id}/experiment_run', qos=1)
            client.subscribe(f'simulation/{args.simulation_id}/experiment_event', qos=1)

    def on_subscribe(client, userdata, mid, granted_qos, properties):
        subscribed.set()

    def on_message(client, userdata, message):
        try:
            payload = json.loads(message.payload.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return
        if payload.get('run_id') != run_id:
            return
        bucket = 'runs' if message.topic.endswith('/experiment_run') else 'events'
        with lock:
            pending[bucket].append(payload)

    def snapshot(bucket):
        with lock:
            return list(pending[bucket])

    observer, host, port = make_client(f'demo-observer-{run_id[:8]}', args,
                                       args.observer_cert, args.observer_key)
    observer.on_connect = on_connect
    observer.on_subscribe = on_subscribe
    observer.on_message = on_message
    observer.connect(host, port, keepalive=30)
    observer.loop_start()
    if not subscribed.wait(10):
        raise SystemExit('观察端未能订阅 experiment_run/experiment_event')

    publisher, _, _ = make_client(f'demo-publisher-{run_id[:8]}', args, args.cert, args.key)
    publisher.connect(host, port, keepalive=30)
    publisher.loop_start()

    env = os.environ.copy()
    env.update({
        'MQTT_BROKER_URL': args.broker,
        'EDGE_MQTT_CA_CERTS': args.ca,
        'EDGE_MQTT_CERTFILE': args.cert,
        'EDGE_MQTT_KEYFILE': args.key,
        'EDGE_RUN_ID': run_id,
        'EDGE_SCENARIO_ID': 'ONLINE-DECISION',
        'EDGE_RUN_SPLIT': 'online',
        # 任务恢复规划器决定是否产生 RECOVER/STOP 决策；默认配置为 false
        'TASK_RECOVERY_ENABLED': 'true',
    })
    handle, log_path = tempfile.mkstemp(prefix='edge-demo-', suffix='.log')
    os.close(handle)
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    edge = None
    exit_code = 1
    try:
        with open(log_path, 'w', encoding='utf-8') as log:
            edge = subprocess.Popen(
                [sys.executable, '-B', '-m', 'edge_node.main', '--config', args.config],
                cwd=str(EDGE_DIR), env=env, stdout=log, stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
        print(f'[1/5] 边端已启动 run_id={run_id}\n      日志 {log_path}')

        if not wait_until(lambda: 'MQTT 已连接' in read_log(log_path), 20):
            raise SystemExit('边端未连接 broker：\n' + read_log(log_path))

        healthy_q = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
        publish_for(publisher, args, healthy_q, [0.0] * 6, [1.0] * 6, 1.0)
        if not wait_until(lambda: any(
                r.get('task', {}).get('status') == 'IN_PROGRESS' for r in snapshot('runs')), 10):
            raise SystemExit('边端未发布 IN_PROGRESS Run')
        print('[2/5] Run 已登记为 IN_PROGRESS，发送 MOVE_JOINT')

        publisher.publish(f'simulation/{args.simulation_id}/command', json.dumps({
            'commandId': f'DEMO-{run_id[:8]}',
            'simulationId': args.simulation_id,
            'robotId': args.robot_id,
            'cmdType': 'MOVE_JOINT',
            'timestamp': int(time.time() * 1000),
            'jointTarget': args.target,
        }), qos=1)
        time.sleep(0.5)

        joint = args.locked_joint
        locked_q = list(healthy_q)
        locked_tau = [1.0] * 6
        locked_tau[joint] = args.lock_torque
        print(f'[3/5] 注入 J{joint} 卡滞：位置锁定 + 力矩 {args.lock_torque}N·m')
        publish_for(publisher, args, locked_q, [0.0] * 6, locked_tau, 3.0)

        fault = wait_until(lambda: next(
            (e for e in snapshot('events') if e.get('event_type') == 'FAULT'), None), 10)
        if fault is None:
            raise SystemExit('未观察到 FAULT 事件：\n' + read_log(log_path)[-3000:])
        print(f"[4/5] FAULT {fault.get('fault_type')} joint=J{fault.get('joint_index')} "
              f"sim_time={fault.get('sim_time_s')}s")

        decision = None
        deadline = time.time() + 15
        while time.time() < deadline and decision is None:
            publish_for(publisher, args, locked_q, [0.0] * 6, locked_tau, 0.2)
            decision = next((e for e in snapshot('events') if e.get('event_type') == 'DECISION'), None)
        if decision is None:
            raise SystemExit('未观察到 DECISION 事件：\n' + read_log(log_path)[-3000:])
        print(f"[5/5] DECISION {decision.get('action')}/{decision.get('reason')} "
              f"reachability={decision.get('reachability_status')} "
              f"sim_time={decision.get('sim_time_s')}s")

        edge.send_signal(EXIT_SIGNAL)
        try:
            returncode = edge.wait(timeout=30)
        except subprocess.TimeoutExpired:
            raise SystemExit('边端未在 30s 内退出：\n' + read_log(log_path)[-3000:])
        if returncode != 0:
            raise SystemExit(f'边端退出码 {returncode}，非优雅退出')
        incomplete = wait_until(lambda: next(
            (r for r in snapshot('runs') if r.get('task', {}).get('status') == 'INCOMPLETE'), None), 15)
        if incomplete is None:
            raise SystemExit('Run 未更新为 INCOMPLETE')
        print('      边端优雅退出，Run 状态 INCOMPLETE')
        print(f'DEMO PASS  run_id={run_id}')
        exit_code = 0
    finally:
        if edge is not None and edge.poll() is None:
            edge.kill()
            edge.wait()
        publisher.loop_stop()
        publisher.disconnect()
        observer.loop_stop()
        observer.disconnect()
    return exit_code


if __name__ == '__main__':
    sys.exit(main())

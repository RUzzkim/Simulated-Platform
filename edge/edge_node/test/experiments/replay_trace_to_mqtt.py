"""把官方任务恢复实验的原始轨迹按 100Hz 回放到 MQTT sim_state，用于端→边→云链路验证。

可选 --summary/--run-id：先把契约 2.0.0 的 Run 记录和故障/决策事件发布到
simulation/{sim}/experiment_run 与 /experiment_event，再回放 sim_state 曲线。
只读取 run_task_recovery.py 产出的 summary.json / *.csv.gz，不改动轨迹内容。
"""
import argparse
import csv
import gzip
import hashlib
import json
import ssl
import time
from pathlib import Path

import paho.mqtt.client as mqtt

ALGORITHM_VERSIONS = {'off': 'v0.0.0', 'v1': 'v1.0.0', 'v2': 'v2.0.0'}


def load_rows(path):
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit('empty trace')
    return rows


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reachability(action, reason):
    if action == 'RECOVER':
        return 'REACHABLE', reason or 'TARGET_REACHED'
    if action == 'STOP':
        return 'NO_FEASIBLE_PLAN', reason or 'NO_FEASIBLE_PLAN'
    return 'NOT_ASSESSED', None


def task_status(run):
    if not run['fault_injected']:
        return 'NOT_APPLICABLE'
    if run['recovered']:
        return 'RECOVERED'
    if run['safe_stopped']:
        return 'SAFE_STOPPED'
    return 'FAILED'


def decision_reason(rows, action):
    for row in rows:
        if (row.get('action') or '') == action and row.get('reason'):
            return row['reason']
    return 'TARGET_REACHED' if action == 'RECOVER' else ('NO_FEASIBLE_PLAN' if action == 'STOP' else None)


def build_run(summary, run, trace_path, started_at_ms, simulation_id, robot_id):
    rows = load_rows(trace_path)
    action = run.get('action')
    reason = decision_reason(rows, action)
    reach_status, reach_reason = reachability(action, reason)
    latency = run.get('fault_detection_latency_ms')
    fault_onset = run['fault_onset_s']
    return {
        'contract_version': '2.0.0',
        'run_id': run['run_id'],
        'algorithm_version': ALGORITHM_VERSIONS.get(run['strategy'], 'v0.0.0'),
        'started_at_ms': started_at_ms,
        'simulation': {
            'simulation_id': simulation_id,
            'robot_id': robot_id,
            'plant': 'python-6r',
            'control_hz': 100,
            'duration_s': 8.0,
        },
        'scenario': {
            'scenario_id': run['scenario'],
            'split': 'validation',
            'seed': run['seed'],
            'task_goal_rad': run['task_goal_rad'],
            'description': run['description'],
        },
        'fault': {
            'type': 'JOINT_LOCKED',
            'joint_index': run['fault_joint'],
            'joint_name': f"J{run['fault_joint']}",
            'injected_at_s': fault_onset,
            'detected_at_s': None if latency is None else round(fault_onset + latency / 1000.0, 6),
            'detection_latency_ms': latency,
            'confirmed': latency is not None,
        },
        'reachability': {
            'status': reach_status,
            'reason': reach_reason,
            'planner_position_error_m': None,
        },
        'strategy': run['strategy'],
        'decision': {
            'action': action,
            'reason': reason,
            'at_s': run.get('decision_s'),
        },
        'task': {
            'status': task_status(run),
            'final_ee_error_m': run.get('final_ee_error_m'),
            'recovery_time_s': run.get('recovery_time_s'),
            'stop_time_s': run.get('stop_time_s'),
            'peak_fault_joint_torque_nm': run.get('peak_fault_joint_torque_nm'),
            'max_joint_speed_rad_s': run.get('max_joint_speed_rad_s'),
            'max_joint_torque_nm': run.get('max_joint_torque_nm'),
        },
        'trace': {
            'path': Path(trace_path).name,
            'sha256': sha256_file(trace_path),
            'frame_count': len(rows),
            'sample_rate_hz': 100,
        },
        'source_sha256': summary['meta'].get('source_sha256', {}),
    }


def build_events(rows, run, started_at_ms):
    events = []
    fault_onset = run['fault_onset_s']
    fault_emitted = False
    last_decision = None
    for row in rows:
        sim_t = float(row['t_s'])
        stamp = started_at_ms + round(sim_t * 1000)
        event_type = row.get('event_type') or ''
        if event_type and not fault_emitted:
            events.append({
                'contract_version': '2.0.0',
                'run_id': run['run_id'],
                'event_type': 'FAULT',
                'timestamp': stamp,
                'sim_time_s': sim_t,
                'fault_type': event_type,
                'joint_index': int(row['event_joint']) if row.get('event_joint') not in ('', None) else run['fault_joint'],
                'action': None,
                'reason': None,
                'reachability_status': None,
                'detail': f"injected at {fault_onset:.2f}s, detected at {sim_t:.2f}s",
            })
            fault_emitted = True
        action = row.get('action') or ''
        reason = row.get('reason') or ''
        if action and (action, reason) != last_decision:
            status, _ = reachability(action, reason)
            events.append({
                'contract_version': '2.0.0',
                'run_id': run['run_id'],
                'event_type': 'DECISION',
                'timestamp': stamp,
                'sim_time_s': sim_t,
                'fault_type': event_type or 'JOINT_LOCKED',
                'joint_index': run['fault_joint'],
                'action': action,
                'reason': reason or None,
                'reachability_status': status,
                'detail': None,
            })
            last_decision = (action, reason)
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('trace')
    ap.add_argument('--broker', default='ssl://127.0.0.1:8884')
    ap.add_argument('--ca', required=True)
    ap.add_argument('--cert', required=True)
    ap.add_argument('--key', required=True)
    ap.add_argument('--topic', default='simulation/SIM-001/sim_state')
    ap.add_argument('--rate', type=float, default=100.0)
    ap.add_argument('--summary', help='官方实验 summary.json；提供后先发布 Run 与事件')
    ap.add_argument('--run-id', help='summary 中的 run_id')
    ap.add_argument('--started-at-ms', type=int, default=0,
                    help='Run 时间基准（毫秒）；默认取当前时间回推 8 秒')
    ap.add_argument('--simulation-id', default='SIM-001')
    ap.add_argument('--robot-id', default='ROBOT-001')
    args = ap.parse_args()

    rows = load_rows(args.trace)
    summary = None
    run = None
    if args.summary:
        if not args.run_id:
            raise SystemExit('--summary 需要同时指定 --run-id')
        summary = json.loads(Path(args.summary).read_text(encoding='utf-8'))
        run = next((item for item in summary['runs'] if item['run_id'] == args.run_id), None)
        if run is None:
            raise SystemExit(f'run_id not found in summary: {args.run_id}')
    started_at_ms = args.started_at_ms or int(time.time() * 1000) - 8000

    host_port = args.broker.split('://', 1)[-1]
    host, _, port = host_port.partition(':')
    secure = args.broker.startswith(('ssl://', 'mqtts://', 'tls://'))
    client = mqtt.Client(client_id='v2-trace-replay', protocol=mqtt.MQTTv311)
    if secure:
        ctx = ssl.create_default_context(cafile=args.ca)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(args.cert, args.key)
        client.tls_set_context(ctx)
    client.connect(host, int(port or 8884), keepalive=60)
    client.loop_start()

    if run is not None:
        run_record = build_run(summary, run, args.trace, started_at_ms,
                               args.simulation_id, args.robot_id)
        client.publish(f'simulation/{args.simulation_id}/experiment_run',
                       json.dumps(run_record, ensure_ascii=False), qos=1).wait_for_publish()
        events = build_events(rows, run, started_at_ms)
        for event in events:
            client.publish(f'simulation/{args.simulation_id}/experiment_event',
                           json.dumps(event, ensure_ascii=False), qos=1).wait_for_publish()
        print(f'published run {run["run_id"]} with {len(events)} events')

    interval = 1.0 / args.rate
    # 有 Run 记录时，遥测时间戳必须落在同一个 Run 时间窗内，否则按 run_id 查曲线为空。
    epoch_base_ms = started_at_ms if run is not None else int(time.time() * 1000)
    start = time.perf_counter()
    for k, row in enumerate(rows):
        # 边端要求毫秒级 Unix 时间戳；轨迹里的 t_s 是相对时间，叠加回放起始 epoch。
        stamp_ns = (epoch_base_ms + int(float(row['t_s']) * 1000)) * 1_000_000
        payload = {
            'simulationId': args.simulation_id,
            'robotId': args.robot_id,
            'jointPosition': [float(row[f'q{i}']) for i in range(6)],
            'jointVelocity': [float(row[f'qd{i}']) for i in range(6)],
            'jointTorque': [float(row[f'tau{i}']) for i in range(6)],
            'stampNanosec': stamp_ns,
        }
        client.publish(args.topic, json.dumps(payload), qos=1)
        target_t = start + (k + 1) * interval
        delay = target_t - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
    time.sleep(0.5)
    client.loop_stop()
    client.disconnect()
    print(f'published {len(rows)} rows in {time.perf_counter() - start:.2f}s')


if __name__ == '__main__':
    main()

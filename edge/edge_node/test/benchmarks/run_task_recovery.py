"""三策略单关节卡滞实验，导出可复核逐控制周期数据。"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import sys
import uuid

from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from edge_node.fault.detector import CompositeFaultDetector
from edge_node.fault.tolerant import FaultTolerantController
from edge_node.model.messages import RobotState, ROBOT_STATUS_RUNNING
from run_comparison import DT, HOME, TS, EE_TOL, _ee_dist, _plant_for
from scenarios import TrajectoryReference, build_scenarios

DWELL_S = 0.25
STOP_DEADLINE_S = 2.0
STOP_SPEED_RAD_S = 0.05
MAX_TAU_NM = 50.0
MAX_SAFE_SPEED_RAD_S = 2.0 * 0.98
MAX_FAULT_TORQUE_MEAN_NM = 15.0
TRACE_FIELDS = (
    'run_id', 'scenario', 'strategy', 'step', 'command_t_s', 't_s',
    'fault_active', 'event_type', 'event_joint', 'action', 'reason',
    *(f'cmd{i}' for i in range(6)), *(f'ref{i}' for i in range(6)),
    'ee_error_m', 'q0', 'q1', 'q2', 'q3', 'q4', 'q5',
    'qd0', 'qd1', 'qd2', 'qd3', 'qd4', 'qd5',
    'tau0', 'tau1', 'tau2', 'tau3', 'tau4', 'tau5',
)


def score(sc, samples):
    """评定连续保持到运行结束的任务恢复或实测安全停稳。"""
    max_joint_torque = max((abs(x) for row in samples for x in row['tau']), default=0.0)
    max_joint_speed = max((abs(x) for row in samples for x in row['qd']), default=0.0)
    fault_torques = [abs(row['tau'][sc.fault_joint]) for row in samples if row['fault_active']]
    fault_torque_mean = sum(fault_torques) / len(fault_torques) if fault_torques else 0.0
    bounded = all(abs(x) <= limit for row in samples
                  for field, limit in [('q', math.pi), ('qd', MAX_SAFE_SPEED_RAD_S), ('tau', MAX_TAU_NM)]
                  for x in row[field])
    stop = next((row['command_t_s'] for row in samples if row['action'] == 'STOP'), None)
    confirmed = next((row['command_t_s'] for row in samples if row['fault_active']
                      and row['event_type'] == 'JOINT_LOCKED' and row['event_joint'] == sc.fault_joint), None)
    recovery_start = stop_start = None
    for row in samples:
        if row['fault_active'] and row['ee_error_m'] <= EE_TOL:
            if recovery_start is None:
                recovery_start = row['t_s']
        else:
            recovery_start = None
        if row['fault_active'] and row['action'] == 'STOP' and max(map(abs, row['qd'])) <= STOP_SPEED_RAD_S:
            if stop_start is None:
                stop_start = row['t_s']
        else:
            stop_start = None
    end = samples[-1]['t_s'] if samples else 0.0
    recovered = (bounded and fault_torque_mean < MAX_FAULT_TORQUE_MEAN_NM
                 and stop is None and recovery_start is not None
                 and end - recovery_start >= DWELL_S - 1e-9)
    settled_duration = None if stop_start is None or stop is None else stop_start - stop
    stopped_safe = (bounded and fault_torque_mean < MAX_FAULT_TORQUE_MEAN_NM
                    and settled_duration is not None
                    and settled_duration + DWELL_S <= STOP_DEADLINE_S + 1e-9
                    and end - stop_start >= DWELL_S - 1e-9)
    return {
        'fault_detection_latency_ms': None if confirmed is None else round((confirmed - sc.fault_onset) * 1000, 3),
        'decision_s': next((r['command_t_s'] for r in samples if r['action']), None),
        'action': samples[-1]['action'] if samples else None,
        'recovery_time_s': round(recovery_start + DWELL_S - sc.fault_onset, 4) if recovered else None,
        'peak_fault_joint_torque_nm': max((abs(r['tau'][sc.fault_joint]) for r in samples if r['fault_active']), default=None),
        'mean_fault_joint_torque_nm': round(fault_torque_mean, 6),
        'recovered': recovered,
        'safe_stopped': stopped_safe,
        'stop_time_s': round(settled_duration, 4) if stopped_safe and settled_duration is not None else None,
        'final_ee_error_m': round(samples[-1]['ee_error_m'], 6) if samples else None,
        'max_joint_speed_rad_s': round(max_joint_speed, 6),
        'max_joint_torque_nm': round(max_joint_torque, 6),
    }


def run_case(sc, strategy, output_dir):
    if strategy not in {'off', 'v1', 'v2'}:
        raise ValueError('strategy must be off, v1 or v2')
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    plant = _plant_for(sc)
    ref = TrajectoryReference('p2p', q0=HOME, q1=sc.target, v_max=sc.ref_vmax)
    detector = CompositeFaultDetector()
    ftc = FaultTolerantController(task_recovery=True) if strategy == 'v2' else (
        FaultTolerantController(task_recovery=False) if strategy == 'v1' else None
    )
    j = sc.fault_joint
    onset, off = sc.fault_onset, sc.fault_onset + sc.fault_duration
    lock_position = None
    samples = []
    trace_path = output_dir / f'{run_id}.csv.gz'
    with gzip.open(trace_path, 'wt', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=TRACE_FIELDS)
        writer.writeheader()
        for k in range(int(sc.duration / DT)):
            command_time = k * DT
            t = (k + 1) * DT
            q_d, _ = ref.sample(command_time)
            fault_active = onset <= command_time < off
            state = RobotState('SIM-001', 'ROBOT-001', TS, list(plant.q), list(plant.qd),
                               list(plant.tau), ROBOT_STATUS_RUNNING)
            event = detector.detect_event(state) if ftc is not None else None
            if ftc is not None:
                ftc.update_fault(event)
                if strategy == 'v2':
                    safe_target = ftc.compensate(state, list(q_d), task_goal=list(sc.target))
                else:
                    safe_target = ftc.compensate(state, list(q_d))
            else:
                safe_target = list(q_d)
            tau = plant.pd_servo(safe_target)
            plant.step(tau, DT)
            if fault_active:
                if lock_position is None:
                    lock_position = plant.q[j]
                plant.q[j] = lock_position
                plant.qd[j] = 0.0
            else:
                lock_position = None
            action = ftc.last_recovery_decision.action if ftc and ftc.last_recovery_decision else None
            reason = ftc.last_recovery_decision.reason if ftc and ftc.last_recovery_decision else None
            sample = {
                'run_id': run_id, 'scenario': sc.name, 'strategy': strategy,
                'step': k, 'command_t_s': command_time, 't_s': t,
                'fault_active': fault_active,
                'event_type': event.fault_type if event else None,
                'event_joint': event.joint_index if event else None,
                'action': action, 'reason': reason,
                'ee_error_m': _ee_dist(plant.q, sc.target),
                'q': list(plant.q), 'qd': list(plant.qd), 'tau': list(plant.tau),
            }
            samples.append(sample)
            record = {key: sample.get(key) for key in TRACE_FIELDS if key in sample}
            record.update({f'q{i}': sample['q'][i] for i in range(6)})
            record.update({f'qd{i}': sample['qd'][i] for i in range(6)})
            record.update({f'tau{i}': sample['tau'][i] for i in range(6)})
            record.update({f'cmd{i}': safe_target[i] for i in range(6)})
            record.update({f'ref{i}': q_d[i] for i in range(6)})
            writer.writerow(record)
    steady_samples = samples[int((sc.duration - 1.0) / DT):]
    legacy_ee_rms = math.sqrt(sum(sample['ee_error_m'] ** 2 for sample in steady_samples)
                              / len(steady_samples)) if steady_samples else 0.0
    result = {
        'run_id': run_id, 'scenario': sc.name, 'description': sc.description,
        'fault_joint': j, 'fault_onset_s': onset, 'seed': sc.seed, 'task_goal_rad': sc.target,
        'strategy': strategy, 'trace': trace_path.name, **score(sc, samples),
        'ee_final_m': round(legacy_ee_rms, 5),
    }
    return result


def main():
    parser = argparse.ArgumentParser(description='单关节卡滞三策略任务恢复基准')
    parser.add_argument('--output-dir', default=str(Path(__file__).parents[1] / 'reports' / 'task_recovery'))
    parser.add_argument('--json', default=None)
    parser.add_argument('--scenario', default=None, help='指定一个场景名，默认运行全部 JOINT_LOCKED 场景')
    args = parser.parse_args()
    scenarios = [sc for sc in build_scenarios()[1] if sc.fault_type == 'JOINT_LOCKED']
    if args.scenario:
        scenarios = [sc for sc in scenarios if sc.name == args.scenario]
        if not scenarios:
            parser.error(f'unknown JOINT_LOCKED scenario: {args.scenario}')
    rows = [run_case(sc, strategy, args.output_dir)
            for sc in scenarios for strategy in ('off', 'v1', 'v2')]
    result = {
        'meta': {
            'sample_rate_hz': int(1 / DT), 'scenarios': len(scenarios),
            'paired_runs': len(scenarios), 'stop_deadline_s': STOP_DEADLINE_S,
            'stop_speed_rad_s': STOP_SPEED_RAD_S, 'dwell_s': DWELL_S,
            'ee_position_tolerance_m': EE_TOL, 'max_joint_torque_nm': MAX_TAU_NM,
            'plant_velocity_limit_rad_s': 2.0,
            'max_scored_velocity_rad_s': MAX_SAFE_SPEED_RAD_S,
            'max_fault_joint_mean_torque_nm': MAX_FAULT_TORQUE_MEAN_NM,
        },
        'summary': {
            strategy: {
                'runs': sum(row['strategy'] == strategy for row in rows),
                'recovered': sum(row['strategy'] == strategy and row['recovered'] for row in rows),
                'safely_stopped': sum(row['strategy'] == strategy and row['safe_stopped'] for row in rows),
            } for strategy in ('off', 'v1', 'v2')
        },
        'runs': rows,
    }
    output = Path(args.json) if args.json else Path(args.output_dir) / 'summary.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result['meta'], ensure_ascii=False))
    print(json.dumps(result['summary'], ensure_ascii=False))
    print(f'逐次结果: {output.resolve()}')


if __name__ == '__main__':
    main()

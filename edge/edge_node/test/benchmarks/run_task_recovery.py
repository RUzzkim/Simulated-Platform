"""三策略单关节卡滞实验，导出可复核逐控制周期数据。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import gzip
import json
import math
import os
import random
import statistics
import sys
import uuid
from dataclasses import replace

from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from edge_node.fault.detector import CompositeFaultDetector
from edge_node.fault.tolerant import FaultTolerantController
from edge_node.model.messages import RobotState, ROBOT_STATUS_RUNNING
from run_comparison import DT, HOME, TS, EE_TOL, _ee_dist, _plant_for
from scenarios import TrajectoryReference, build_task_recovery_scenarios

DWELL_S = 0.25
STOP_DEADLINE_S = 2.0
STOP_SPEED_RAD_S = 0.05
MAX_TAU_NM = 50.0
MAX_SAFE_SPEED_RAD_S = 2.0 * 0.98
MAX_FAULT_TORQUE_MEAN_NM = 15.0
RECOVERY_MAX_VELOCITY_RAD_S = 1.0
RECOVERY_MAX_ACCELERATION_RAD_S2 = 2.0
TRACE_FIELDS = (
    'run_id', 'scenario', 'strategy', 'step', 'command_t_s', 't_s',
    'fault_active', 'event_type', 'event_joint', 'action', 'reason',
    *(f'cmd{i}' for i in range(6)), *(f'ref{i}' for i in range(6)),
    'ee_error_m', 'q0', 'q1', 'q2', 'q3', 'q4', 'q5',
    'qd0', 'qd1', 'qd2', 'qd3', 'qd4', 'qd5',
    'tau0', 'tau1', 'tau2', 'tau3', 'tau4', 'tau5',
    'sensor_tau0', 'sensor_tau1', 'sensor_tau2',
    'sensor_tau3', 'sensor_tau4', 'sensor_tau5',
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
    nominal_end = sc.fault_onset if sc.fault_duration > 0.0 else sc.duration
    false_alarm = next((row for row in samples if row['command_t_s'] < nominal_end
                        and row['event_type'] is not None), None)
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
        'false_alarm_during_nominal': false_alarm is not None,
        'first_false_alarm_type': None if false_alarm is None else false_alarm['event_type'],
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


def sensor_torque_readings(base_readings, joint_index, lock_reading_nm, fault_active,
                           noise_sigma_nm, rng, nominal_reading_nm=None):
    readings = list(base_readings)
    if fault_active:
        readings[joint_index] = lock_reading_nm
    elif nominal_reading_nm is not None:
        readings[joint_index] = nominal_reading_nm
    if noise_sigma_nm:
        readings[joint_index] += rng.gauss(0.0, noise_sigma_nm)
    return readings


def run_case(sc, strategy, output_dir, sensor_torque_noise_sigma_nm=0.0, noise_seed=0,
             nominal_sensor_torque_nm=None):
    if strategy not in {'off', 'v1', 'v2'}:
        raise ValueError('strategy must be off, v1 or v2')
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    plant = _plant_for(sc)
    ref = TrajectoryReference('p2p', q0=HOME, q1=sc.target, v_max=sc.ref_vmax)
    detector = CompositeFaultDetector()
    ftc = FaultTolerantController(
        task_recovery=True,
        control_dt=DT,
        recovery_max_velocity=RECOVERY_MAX_VELOCITY_RAD_S,
        recovery_max_acceleration=RECOVERY_MAX_ACCELERATION_RAD_S2,
    ) if strategy == 'v2' else (
        FaultTolerantController(task_recovery=False) if strategy == 'v1' else None
    )
    j = sc.fault_joint
    onset, off = sc.fault_onset, sc.fault_onset + sc.fault_duration
    base_scenario_name = sc.name.split('#TQ', 1)[0].split('#NOFAULT', 1)[0]
    scenario_seed = int.from_bytes(
        hashlib.sha256(base_scenario_name.encode('utf-8')).digest()[:8], 'big'
    )
    rng = random.Random(scenario_seed ^ int(noise_seed))
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
            measurement_fault_active = (k > 0 and onset <= (k - 1) * DT < off)
            sensor_tau = sensor_torque_readings(
                plant.tau, j, sc.lock_reaction_torque, measurement_fault_active,
                sensor_torque_noise_sigma_nm, rng, nominal_sensor_torque_nm,
            )
            state = RobotState('SIM-001', 'ROBOT-001', TS, list(plant.q), list(plant.qd),
                               sensor_tau, ROBOT_STATUS_RUNNING)
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
                plant.tau[j] = sc.lock_reaction_torque
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
                'sensor_tau': sensor_tau,
            }
            samples.append(sample)
            record = {key: sample.get(key) for key in TRACE_FIELDS if key in sample}
            record.update({f'q{i}': sample['q'][i] for i in range(6)})
            record.update({f'qd{i}': sample['qd'][i] for i in range(6)})
            record.update({f'tau{i}': sample['tau'][i] for i in range(6)})
            record.update({f'sensor_tau{i}': sample['sensor_tau'][i] for i in range(6)})
            record.update({f'cmd{i}': safe_target[i] for i in range(6)})
            record.update({f'ref{i}': q_d[i] for i in range(6)})
            writer.writerow(record)
    steady_samples = samples[int((sc.duration - 1.0) / DT):]
    legacy_ee_rms = math.sqrt(sum(sample['ee_error_m'] ** 2 for sample in steady_samples)
                              / len(steady_samples)) if steady_samples else 0.0
    result = {
        'run_id': run_id, 'scenario': sc.name, 'description': sc.description,
        'fault_joint': j, 'fault_onset_s': onset, 'seed': sc.seed, 'task_goal_rad': sc.target,
        'lock_reaction_torque_nm': sc.lock_reaction_torque,
        'sensor_torque_noise_sigma_nm': sensor_torque_noise_sigma_nm,
        'noise_seed': noise_seed,
        'nominal_sensor_torque_nm': nominal_sensor_torque_nm,
        'fault_injected': sc.fault_duration > 0.0 and onset < sc.duration,
        'strategy': strategy, 'trace': trace_path.name, **score(sc, samples),
        'ee_final_m': round(legacy_ee_rms, 5),
    }
    return result


def summarize_runs(rows, strategy):
    strategy_rows = [row for row in rows if row['strategy'] == strategy]
    fault_rows = [
        row for row in strategy_rows
        if row.get('fault_injected', '#NOFAULT' not in row.get('scenario', ''))
    ]
    control_rows = [
        row for row in strategy_rows
        if not row.get('fault_injected', '#NOFAULT' not in row.get('scenario', ''))
    ]
    detected_rows = [row for row in fault_rows if row.get('fault_detection_latency_ms') is not None]
    recovered_rows = [row for row in fault_rows if row.get('recovered', False)]
    stopped_rows = [row for row in fault_rows if row.get('safe_stopped', False)]
    no_fault_false_alarms = sum(row.get('false_alarm_during_nominal', False)
                                for row in control_rows)
    all_false_alarms = sum(row.get('false_alarm_during_nominal', False)
                           for row in strategy_rows)
    detector_available = strategy in {'v1', 'v2'}

    def mean(rows_to_average, field, digits=3):
        values = [row[field] for row in rows_to_average if row.get(field) is not None]
        return round(sum(values) / len(values), digits) if values else None

    def median(rows_to_average, field, digits=3):
        values = [row[field] for row in rows_to_average if row.get(field) is not None]
        return round(statistics.median(values), digits) if values else None

    return {
        'runs': len(strategy_rows),
        'fault_runs': len(fault_rows),
        'no_fault_control_runs': len(control_rows),
        'recovered': sum(row.get('recovered', False) for row in fault_rows),
        'recovery_rate': round(len(recovered_rows) / len(fault_rows), 4) if fault_rows else None,
        'safely_stopped': sum(row.get('safe_stopped', False) for row in fault_rows),
        'safe_stop_rate': round(len(stopped_rows) / len(fault_rows), 4) if fault_rows else None,
        'faults_detected': len(detected_rows) if detector_available else None,
        'faults_missed': len(fault_rows) - len(detected_rows) if detector_available else None,
        'detection_rate': round(len(detected_rows) / len(fault_rows), 4)
        if detector_available and fault_rows else None,
        'false_alarms': all_false_alarms if detector_available else None,
        'false_alarm_rate': round(no_fault_false_alarms / len(control_rows), 4)
        if detector_available and control_rows else None,
        'no_fault_false_alarms': no_fault_false_alarms if detector_available else None,
        'pre_fault_false_alarms': sum(row.get('false_alarm_during_nominal', False)
                                      for row in fault_rows) if detector_available else None,
        'mean_fault_detection_latency_ms': mean(detected_rows, 'fault_detection_latency_ms'),
        'median_fault_detection_latency_ms': median(detected_rows, 'fault_detection_latency_ms'),
        'mean_recovery_time_s': mean(recovered_rows, 'recovery_time_s'),
        'median_recovery_time_s': median(recovered_rows, 'recovery_time_s'),
        'mean_safe_stop_time_s': mean(stopped_rows, 'stop_time_s'),
    }


def build_summary(rows, split, scenario_count, output_dir):
    source_root = Path(__file__).parents[2]
    repository_root = source_root.parents[1]
    source_files = {
        'edge_node/fault/recovery.py': source_root / 'edge_node' / 'fault' / 'recovery.py',
        'edge_node/fault/tolerant.py': source_root / 'edge_node' / 'fault' / 'tolerant.py',
        'benchmarks/run_task_recovery.py': Path(__file__),
        'benchmarks/scenarios.py': Path(__file__).with_name('scenarios.py'),
        'benchmarks/plant.py': Path(__file__).with_name('plant.py'),
        'benchmarks/run_comparison.py': Path(__file__).with_name('run_comparison.py'),
        'config/edge_config.yaml': source_root / 'config' / 'edge_config.yaml',
    }
    source_hashes = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in source_files.items()
    }
    try:
        raw_directory = Path(output_dir).resolve().relative_to(repository_root).as_posix()
    except ValueError:
        raw_directory = str(Path(output_dir).resolve())
    lock_torque_levels = sorted({
        float(row['lock_reaction_torque_nm']) for row in rows
    })
    noise_levels = sorted({
        float(row.get('sensor_torque_noise_sigma_nm', 0.0)) for row in rows
    })
    noise_seeds = sorted({int(row.get('noise_seed', 0)) for row in rows})
    summary_by_lock_torque = {
        str(torque): {
            strategy: summarize_runs(
                [row for row in rows if float(row['lock_reaction_torque_nm']) == torque],
                strategy,
            ) for strategy in ('off', 'v1', 'v2')
        } for torque in lock_torque_levels
    }
    summary_by_torque_and_noise = {
        str(torque): {
            str(noise): {
                strategy: summarize_runs(
                    [row for row in rows
                     if float(row['lock_reaction_torque_nm']) == torque
                     and float(row.get('sensor_torque_noise_sigma_nm', 0.0)) == noise],
                    strategy,
                ) for strategy in ('off', 'v1', 'v2')
            } for noise in noise_levels
        } for torque in lock_torque_levels
    }
    return {
        'meta': {
            'sample_rate_hz': int(1 / DT), 'scenarios': scenario_count,
            'split': split,
            'paired_runs': scenario_count, 'stop_deadline_s': STOP_DEADLINE_S,
            'stop_speed_rad_s': STOP_SPEED_RAD_S, 'dwell_s': DWELL_S,
            'ee_position_tolerance_m': EE_TOL, 'max_joint_torque_nm': MAX_TAU_NM,
            'plant_velocity_limit_rad_s': 2.0,
            'max_scored_velocity_rad_s': MAX_SAFE_SPEED_RAD_S,
            'max_fault_joint_mean_torque_nm': MAX_FAULT_TORQUE_MEAN_NM,
            'lock_reaction_torque_levels_nm': lock_torque_levels,
            'sensor_torque_noise_sigma_levels_nm': noise_levels,
            'sensor_torque_noise_seeds': noise_seeds,
            'recovery_max_velocity_rad_s': RECOVERY_MAX_VELOCITY_RAD_S,
            'recovery_max_acceleration_rad_s2': RECOVERY_MAX_ACCELERATION_RAD_S2,
            'raw_directory': raw_directory,
            'source_sha256': source_hashes,
        },
        'summary': {
            strategy: summarize_runs(rows, strategy) for strategy in ('off', 'v1', 'v2')
        },
        'summary_by_lock_reaction_torque': summary_by_lock_torque,
        'summary_by_lock_torque_and_noise_sigma': summary_by_torque_and_noise,
        'runs': rows,
    }


def main():
    parser = argparse.ArgumentParser(description='单关节卡滞三策略任务恢复基准')
    parser.add_argument('--output-dir', default=str(Path(__file__).parents[1] / 'reports' / 'task_recovery'))
    parser.add_argument('--json', default=None)
    parser.add_argument('--split', choices=('development', 'exploratory', 'validation'), default='development',
                        help='实验划分。validation 在本轮运行前冻结，不代表盲测。')
    parser.add_argument('--scenario', nargs='+', default=None,
                        help='指定一个或多个场景名，默认运行所选划分的全部场景')
    parser.add_argument('--lock-reaction-torques', nargs='+', type=float, default=None,
                        help='合成卡滞力矩读数敏感性扫值（0 至 15 N·m）')
    parser.add_argument('--sensor-torque-noise-sigmas', nargs='+', type=float, default=[0.0],
                        help='故障关节力矩传感器高斯噪声标准差（N·m）')
    parser.add_argument('--sensor-noise-seeds', nargs='+', type=int, default=[42],
                        help='传感器噪声随机种子，用于配对复现实验')
    parser.add_argument('--include-no-fault-controls', action='store_true',
                        help='增加相同轨迹但不注入故障的误报对照')
    args = parser.parse_args()
    scenarios = build_task_recovery_scenarios(args.split)
    if args.scenario:
        requested_scenarios = set(args.scenario)
        available_scenarios = {scenario.name for scenario in scenarios}
        unknown_scenarios = sorted(requested_scenarios - available_scenarios)
        if unknown_scenarios:
            parser.error(f'unknown JOINT_LOCKED scenarios: {", ".join(unknown_scenarios)}')
        scenarios = [scenario for scenario in scenarios if scenario.name in requested_scenarios]
    if args.lock_reaction_torques is not None:
        torque_levels = sorted(set(args.lock_reaction_torques))
        if any(not math.isfinite(torque) or not 0.0 < torque < MAX_FAULT_TORQUE_MEAN_NM
               for torque in torque_levels):
            parser.error('lock reaction torques must be finite and between 0 and 15 N·m')
        scenarios = [
            replace(
                scenario,
                name=f'{scenario.name}#TQ{torque:g}',
                lock_reaction_torque=torque,
            )
            for torque in torque_levels for scenario in scenarios
        ]
    if args.include_no_fault_controls:
        scenarios += [
            replace(
                scenario, name=f'{scenario.name}#NOFAULT',
                fault_onset=scenario.duration + 1.0, fault_duration=0.0,
            )
            for scenario in scenarios
        ]
    noise_levels = sorted(set(args.sensor_torque_noise_sigmas))
    if any(not math.isfinite(sigma) or sigma < 0.0 for sigma in noise_levels):
        parser.error('sensor torque noise sigmas must be finite and non-negative')
    noise_seeds = sorted(set(args.sensor_noise_seeds))
    rows = [
        run_case(sc, strategy, args.output_dir, sigma, seed)
        for sc in scenarios for sigma in noise_levels for seed in noise_seeds
        for strategy in ('off', 'v1', 'v2')
    ]
    scenario_count = len(scenarios) * len(noise_levels) * len(noise_seeds)
    result = build_summary(rows, args.split, scenario_count, args.output_dir)
    output = Path(args.json) if args.json else Path(args.output_dir) / 'summary.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result['meta'], ensure_ascii=False))
    print(json.dumps(result['summary'], ensure_ascii=False))
    print(f'逐次结果: {output.resolve()}')


if __name__ == '__main__':
    main()

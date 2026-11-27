import csv
import gzip
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent / 'benchmarks'))

import run_comparison
from scenarios import build_scenarios


def frame(k, error=0.01, speed=0.01, action=None):
    return {
        't_s': (k + 1) / 100, 'command_t_s': k / 100,
        'fault_active': True, 'ee_error_m': error, 'action': action,
        'q': [0.0] * 6, 'qd': [speed] * 6, 'tau': [0.0] * 6,
        'event_type': None, 'event_joint': None, 'reason': None,
    }


def test_recovery_requires_final_dwell_and_safe_joint_states():
    from run_task_recovery import score
    sc = build_scenarios()[1][0]
    samples = [frame(k) for k in range(35)]
    assert score(sc, samples)['recovered']
    samples[-1]['ee_error_m'] = 0.12
    assert not score(sc, samples)['recovered']
    samples[-1]['ee_error_m'] = 0.01
    samples[0]['tau'][2] = 51.0
    assert not score(sc, samples)['recovered']
    samples[0]['tau'][2] = 0.0
    samples[0]['qd'][2] = 1.97
    assert not score(sc, samples)['recovered']
    samples[0]['qd'][2] = 0.0
    for row in samples:
        row['tau'][sc.fault_joint] = 15.1
    assert not score(sc, samples)['recovered']


def test_score_flags_detector_events_before_the_physical_fault_starts():
    from run_task_recovery import score

    sc = build_scenarios()[1][0]
    samples = [frame(k, error=0.2) for k in range(35)]
    samples[10]['event_type'] = 'JOINT_LOCKED'
    samples[10]['event_joint'] = sc.fault_joint

    result = score(sc, samples)

    assert result['false_alarm_during_nominal'] is True
    assert result['first_false_alarm_type'] == 'JOINT_LOCKED'


def test_sensor_noise_changes_only_the_detected_torque_reading():
    import random
    from run_task_recovery import sensor_torque_readings

    physical_torque = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    measured = sensor_torque_readings(physical_torque, 2, 12.5, True, 0.5, random.Random(42))

    assert physical_torque == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert measured[:2] == [1.0, 2.0]
    assert measured[2] != 12.5
    assert measured[3:] == [4.0, 5.0, 6.0]
    assert sensor_torque_readings(physical_torque, 2, 12.5, True, 0.5, random.Random(42)) == measured
    nominal = sensor_torque_readings(physical_torque, 2, 12.5, False, 0.0, random.Random(42))
    assert nominal == physical_torque


def test_stop_requires_timely_measured_settling_and_excludes_recovery():
    from run_task_recovery import score
    sc = build_scenarios()[1][0]
    samples = [frame(k, speed=0.1 if k < 30 else 0.01, action='STOP') for k in range(75)]
    row = score(sc, samples)
    assert row['safe_stopped'] and not row['recovered']
    assert row['stop_time_s'] == 0.31  # First low-speed measurement minus STOP command time.
    samples[-1]['qd'][0] = 0.2
    assert not score(sc, samples)['safe_stopped']
    slow = [frame(k, speed=0.1 if k < 210 else 0.01, action='STOP') for k in range(240)]
    assert not score(sc, slow)['safe_stopped']


def test_paired_runs_preserve_legacy_metrics_and_export_frame_alignment(tmp_path):
    from run_task_recovery import run_case
    sc = build_scenarios()[1][0]
    legacy = run_comparison.run_fault(sc, False)
    rows = [run_case(sc, strategy, tmp_path) for strategy in ('off', 'v1', 'v2')]
    assert rows[0]['ee_final_m'] == legacy['ee_final_m']
    assert len({row['run_id'] for row in rows}) == 3
    assert not rows[0]['safe_stopped']
    for row in rows:
        with gzip.open(tmp_path / row['trace'], 'rt', encoding='utf-8', newline='') as stream:
            trace = list(csv.DictReader(stream))
        assert len(trace) == 800
        assert float(trace[0]['command_t_s']) == 0.0
        assert float(trace[-1]['t_s']) == 8.0
        assert row['run_id'] == trace[-1]['run_id']
        assert all(float(rec['qd0']) == 0.0 for rec in trace if rec['fault_active'] == 'True')
    assert rows[2]['fault_detection_latency_ms'] is not None
    assert rows[2]['fault_detection_latency_ms'] >= 0.0


def test_sensor_noise_does_not_change_open_loop_plant_dynamics(tmp_path):
    from run_task_recovery import run_case

    scenario = build_scenarios()[1][0]
    baseline = run_case(scenario, 'off', tmp_path, 0.0, 42)
    noisy = run_case(scenario, 'off', tmp_path, 0.5, 42)

    def read_trace(result):
        with gzip.open(tmp_path / result['trace'], 'rt', encoding='utf-8', newline='') as stream:
            return list(csv.DictReader(stream))

    baseline_trace = read_trace(baseline)
    noisy_trace = read_trace(noisy)

    for physical_field in ('q0', 'q1', 'q2', 'q3', 'q4', 'q5',
                           'qd0', 'qd1', 'qd2', 'qd3', 'qd4', 'qd5',
                           'tau0', 'tau1', 'tau2', 'tau3', 'tau4', 'tau5'):
        assert [row[physical_field] for row in noisy_trace] == [
            row[physical_field] for row in baseline_trace
        ]
    assert any(row['sensor_tau0'] != baseline_row['sensor_tau0']
               for row, baseline_row in zip(noisy_trace, baseline_trace))


def test_online_signal_filter_mode_records_filtered_state_and_preserves_raw_sensor_values(tmp_path):
    from run_task_recovery import run_case

    scenario = build_scenarios()[1][0]
    result = run_case(
        scenario, 'v1', tmp_path, sensor_torque_noise_sigma_nm=3.0, noise_seed=42,
        signal_filter_enabled=True,
    )

    assert result['signal_filter_enabled'] is True
    with gzip.open(tmp_path / result['trace'], 'rt', encoding='utf-8', newline='') as stream:
        trace = list(csv.DictReader(stream))

    joint = scenario.fault_joint
    assert trace[0][f'state_tau{joint}'] == trace[0][f'sensor_tau{joint}']
    assert any(row[f'state_tau{joint}'] != row[f'sensor_tau{joint}'] for row in trace[1:])
    assert any(row[f'state_q{joint}'] != row[f'q{joint}'] for row in trace[1:])


def test_run_records_configured_lock_torque_threshold(tmp_path):
    from run_task_recovery import run_case

    scenario = build_scenarios()[1][0]
    result = run_case(scenario, 'v1', tmp_path, lock_torque_threshold=8.5)

    assert result['lock_torque_threshold_nm'] == 8.5


def test_run_records_j0_geometric_stop_reason_and_lower_bound(tmp_path):
    from run_task_recovery import run_case
    from scenarios import build_task_recovery_scenarios

    scenario = next(
        scenario for scenario in build_task_recovery_scenarios('validation')
        if scenario.name == 'VALIDATION-LOCK-J0#s3T2'
    )
    result = run_case(scenario, 'v2', tmp_path)

    assert result['action'] == 'STOP'
    assert result['decision_reason'] == 'GEOMETRICALLY_UNREACHABLE'
    assert abs(result['position_error_lower_bound_m'] - 0.051001394) < 1e-9

    with gzip.open(tmp_path / result['trace'], 'rt', encoding='utf-8', newline='') as stream:
        trace = list(csv.DictReader(stream))

    stop_rows = [row for row in trace if row['action'] == 'STOP']
    assert stop_rows
    assert all(row['reason'] == 'GEOMETRICALLY_UNREACHABLE' for row in stop_rows)
    assert all(abs(float(row['position_error_lower_bound_m']) - 0.051001394) < 1e-9 for row in stop_rows)


def test_run_rejects_non_positive_lock_torque_threshold(tmp_path):
    import pytest
    from run_task_recovery import run_case

    scenario = build_scenarios()[1][0]
    with pytest.raises(ValueError, match='lock_torque_threshold'):
        run_case(scenario, 'v1', tmp_path, lock_torque_threshold=0.0)


def test_joint_lock_fault_has_detectable_reaction_torque_without_exceeding_score_limit(tmp_path):
    from run_task_recovery import run_case
    from scenarios import build_task_recovery_scenarios

    sc = next(
        scenario for scenario in build_task_recovery_scenarios('exploratory')
        if scenario.name == 'EXPLORATORY-LOCK-J2#s1T2'
    )
    result = run_case(sc, 'v2', tmp_path)

    assert result['fault_detection_latency_ms'] is not None
    assert 10.0 < result['mean_fault_joint_torque_nm'] < 15.0


def test_scoring_checks_position_and_only_counts_post_stop_samples():
    from run_task_recovery import score
    sc = build_scenarios()[1][0]
    samples = [frame(k, action='STOP' if k >= 70 else None) for k in range(75)]
    assert not score(sc, samples)['safe_stopped']
    samples = [frame(k) for k in range(50)]
    samples[0]['q'][2] = 3.2
    assert not score(sc, samples)['recovered']
    samples[0]['q'][2] = float('nan')
    assert not score(sc, samples)['recovered']


def test_exploratory_scenarios_are_separate_from_development_targets():
    from scenarios import build_task_recovery_scenarios

    development = build_task_recovery_scenarios('development')
    exploratory = build_task_recovery_scenarios('exploratory')

    assert len(development) == len(exploratory) == 24
    assert {tuple(sc.target) for sc in development}.isdisjoint(
        {tuple(sc.target) for sc in exploratory}
    )
    assert {sc.fault_joint for sc in exploratory} == {0, 1, 2, 3}
    assert len({sc.name for sc in exploratory}) == len(exploratory)


def test_validation_scenarios_are_frozen_and_separate_from_prior_targets():
    from scenarios import build_task_recovery_scenarios

    development = build_task_recovery_scenarios('development')
    exploratory = build_task_recovery_scenarios('exploratory')
    validation = build_task_recovery_scenarios('validation')

    assert len(validation) == 24
    assert {tuple(sc.target) for sc in validation}.isdisjoint(
        {tuple(sc.target) for sc in development + exploratory}
    )
    assert {sc.fault_joint for sc in validation} == {0, 1, 2, 3}
    assert {sc.fault_onset for sc in validation} == {0.4, 0.8, 1.2}
    assert all(sc.lock_reaction_torque == 12.5 for sc in validation)


def test_run_records_lock_reaction_torque_and_summary_groups_sensitivity_levels(tmp_path):
    from dataclasses import replace
    from run_task_recovery import build_summary, run_case
    from scenarios import build_task_recovery_scenarios

    scenario = replace(
        build_task_recovery_scenarios('validation')[0],
        lock_reaction_torque=11.0,
    )
    result = run_case(scenario, 'v2', tmp_path)

    assert result['lock_reaction_torque_nm'] == 11.0
    summary = build_summary([result], 'validation', 1, tmp_path)
    assert summary['meta']['lock_reaction_torque_levels_nm'] == [11.0]
    assert summary['summary_by_lock_reaction_torque']['11.0']['v2']['runs'] == 1


def test_sensitivity_summary_keeps_torque_noise_conditions_and_strategies_separate(tmp_path):
    from run_task_recovery import build_summary

    rows = [
        {'scenario': 'fault-a', 'fault_injected': True, 'fault_detection_latency_ms': None,
         'false_alarm_during_nominal': False, 'recovery_time_s': None,
         'lock_reaction_torque_nm': 11.0, 'sensor_torque_noise_sigma_nm': 0.0, 'strategy': 'off',
         'recovered': False, 'safe_stopped': False},
        {'scenario': 'fault-b', 'fault_injected': True, 'fault_detection_latency_ms': 105.0,
         'false_alarm_during_nominal': True, 'recovery_time_s': 1.3,
         'lock_reaction_torque_nm': 11.0, 'sensor_torque_noise_sigma_nm': 1.0, 'strategy': 'v2',
         'recovered': True, 'safe_stopped': False},
        {'scenario': 'control-a', 'fault_injected': False, 'fault_detection_latency_ms': None,
         'false_alarm_during_nominal': True, 'recovery_time_s': None,
         'lock_reaction_torque_nm': 11.0, 'sensor_torque_noise_sigma_nm': 1.0, 'strategy': 'v2',
         'recovered': False, 'safe_stopped': False},
        {'scenario': 'control-b', 'fault_injected': False, 'fault_detection_latency_ms': None,
         'false_alarm_during_nominal': False, 'recovery_time_s': None,
         'lock_reaction_torque_nm': 11.0, 'sensor_torque_noise_sigma_nm': 1.0, 'strategy': 'v2',
         'recovered': False, 'safe_stopped': False},
        {'scenario': 'fault-c', 'fault_injected': True, 'fault_detection_latency_ms': None,
         'false_alarm_during_nominal': False, 'recovery_time_s': None,
         'lock_reaction_torque_nm': 14.0, 'sensor_torque_noise_sigma_nm': 0.0, 'strategy': 'v1',
         'recovered': True, 'safe_stopped': False},
        {'scenario': 'fault-d', 'fault_injected': True, 'fault_detection_latency_ms': 112.0,
         'false_alarm_during_nominal': False, 'recovery_time_s': None,
         'lock_reaction_torque_nm': 14.0, 'sensor_torque_noise_sigma_nm': 1.0, 'strategy': 'v2',
         'recovered': False, 'safe_stopped': True},
    ]
    summary = build_summary(rows, 'validation', 2, tmp_path)

    assert summary['meta']['lock_reaction_torque_levels_nm'] == [11.0, 14.0]
    assert summary['meta']['sensor_torque_noise_sigma_levels_nm'] == [0.0, 1.0]
    grouped = summary['summary_by_lock_reaction_torque']
    assert grouped['11.0']['v2']['runs'] == 3
    assert grouped['11.0']['v2']['fault_runs'] == 1
    assert grouped['11.0']['v2']['no_fault_control_runs'] == 2
    assert grouped['11.0']['v2']['recovered'] == 1
    assert grouped['14.0']['v1']['fault_runs'] == 1
    assert grouped['14.0']['v1']['recovered'] == 1
    assert grouped['14.0']['v2']['safely_stopped'] == 1
    joint_groups = summary['summary_by_lock_torque_and_noise_sigma']
    assert joint_groups['11.0']['0.0']['off']['runs'] == 1
    noisy_v2 = joint_groups['11.0']['1.0']['v2']
    assert noisy_v2['runs'] == 3
    assert noisy_v2['fault_runs'] == 1
    assert noisy_v2['faults_detected'] == 1
    assert noisy_v2['faults_missed'] == 0
    assert noisy_v2['false_alarms'] == 2
    assert noisy_v2['no_fault_control_runs'] == 2
    assert noisy_v2['no_fault_false_alarms'] == 1
    assert noisy_v2['false_alarm_rate'] == 0.5
    assert noisy_v2['mean_fault_detection_latency_ms'] == 105.0
    assert noisy_v2['mean_recovery_time_s'] == 1.3
    assert joint_groups['14.0']['0.0']['v1']['recovered'] == 1
    assert joint_groups['14.0']['1.0']['v2']['safely_stopped'] == 1
    overall_v2 = summary['summary']['v2']
    assert overall_v2['fault_runs'] == 2
    assert overall_v2['faults_missed'] == 0


def test_summary_records_hashes_for_algorithm_and_benchmark_sources(tmp_path):
    from run_task_recovery import build_summary

    summary = build_summary([], 'development', 0, tmp_path)

    assert set(summary['meta']['source_sha256']) == {
        'edge_node/config/config_manager.py',
        'edge_node/fault/recovery.py',
        'edge_node/fault/tolerant.py',
        'edge_node/processor/signal_filter.py',
        'benchmarks/run_task_recovery.py',
        'benchmarks/scenarios.py',
        'benchmarks/plant.py',
        'benchmarks/run_comparison.py',
        'config/edge_config.yaml',
    }
    assert all(len(value) == 64 for value in summary['meta']['source_sha256'].values())
    assert summary['meta']['raw_directory'] == str(tmp_path.resolve())

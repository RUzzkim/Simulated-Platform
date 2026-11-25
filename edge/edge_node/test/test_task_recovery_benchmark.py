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

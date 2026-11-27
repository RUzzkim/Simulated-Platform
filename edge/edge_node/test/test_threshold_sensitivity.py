import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'benchmarks'))

from run_threshold_sensitivity import build_run_plan
from scenarios import Scenario


def test_run_plan_reuses_no_fault_controls_once_per_threshold_noise_and_seed():
    scenarios = [
        Scenario(name='case-a', category='fault', description='joint lock'),
        Scenario(name='case-b', category='fault', description='joint lock', fault_joint=1),
    ]

    plan = list(build_run_plan(
        scenarios=scenarios,
        thresholds=(8.5, 10.0),
        torque_levels=(8.0, 9.0),
        noise_levels=(0.0, 1.5),
        noise_seeds=(42, 43),
    ))

    assert len(plan) == 144
    controls = [row for row in plan if not row['scenario'].fault_duration > 0.0]
    fault_runs = [row for row in plan if row['scenario'].fault_duration > 0.0]
    assert len(controls) == 48
    assert len(fault_runs) == 96

    for threshold in (8.5, 10.0):
        threshold_controls = [row for row in controls if row['threshold'] == threshold]
        assert len(threshold_controls) == 24
        assert {row['noise_sigma'] for row in threshold_controls} == {0.0, 1.5}
        assert len({(row['scenario'].name, row['noise_sigma'], row['noise_seed'], row['strategy'])
                    for row in threshold_controls}) == 24


def test_run_plan_pairs_same_fault_case_across_thresholds_and_keeps_fault_torque_groups():
    scenario = Scenario(
        name='case-a', category='fault', description='joint lock',
        fault_joint=2, fault_onset=0.8, fault_duration=20.0,
    )

    plan = list(build_run_plan(
        scenarios=[scenario],
        thresholds=(8.5, 10.0),
        torque_levels=(8.0, 9.0),
        noise_levels=(0.0,),
        noise_seeds=(42, 43),
    ))

    fault_runs = [row for row in plan if row['scenario'].fault_duration > 0.0]
    assert len(fault_runs) == 24
    for threshold in (8.5, 10.0):
        threshold_runs = [row for row in fault_runs if row['threshold'] == threshold]
        assert {(row['scenario'].lock_reaction_torque, row['noise_seed'], row['strategy'])
                for row in threshold_runs} == {
                    (torque, seed, strategy)
                    for torque in (8.0, 9.0)
                    for seed in (42, 43)
                    for strategy in ('off', 'v1', 'v2')
                }

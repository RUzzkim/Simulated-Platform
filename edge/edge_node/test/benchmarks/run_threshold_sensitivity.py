"""Run paired JOINT_LOCKED threshold and sensor-noise sensitivity cases."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from run_task_recovery import build_summary, run_case
from scenarios import build_task_recovery_scenarios


STRATEGIES = ('off', 'v1', 'v2')


def build_run_plan(scenarios, thresholds, torque_levels, noise_levels, noise_seeds):
    """Yield fault runs and one matched nominal control per threshold/noise/seed."""
    for threshold in thresholds:
        for noise_sigma in noise_levels:
            for noise_seed in noise_seeds:
                for scenario in scenarios:
                    control = replace(
                        scenario,
                        name=f'{scenario.name}#NOFAULT#SIGMA{noise_sigma:g}',
                        fault_onset=scenario.duration + 1.0,
                        fault_duration=0.0,
                        lock_reaction_torque=0.0,
                    )
                    for strategy in STRATEGIES:
                        yield {
                            'scenario': control,
                            'strategy': strategy,
                            'threshold': threshold,
                            'noise_sigma': noise_sigma,
                            'noise_seed': noise_seed,
                        }

                for torque in torque_levels:
                    for scenario in scenarios:
                        fault_case = replace(
                            scenario,
                            name=f'{scenario.name}#TQ{torque:g}#SIGMA{noise_sigma:g}',
                            lock_reaction_torque=torque,
                        )
                        for strategy in STRATEGIES:
                            yield {
                                'scenario': fault_case,
                                'strategy': strategy,
                                'threshold': threshold,
                                'noise_sigma': noise_sigma,
                                'noise_seed': noise_seed,
                            }


def run_experiment(scenarios, thresholds, torque_levels, noise_levels, noise_seeds,
                   output_root, json_dir, split):
    output_root = Path(output_root)
    json_dir = Path(json_dir)
    results = {}

    for threshold in thresholds:
        threshold_rows = []
        for run in build_run_plan(
                scenarios, (threshold,), torque_levels, noise_levels, noise_seeds):
            row = run_case(
                run['scenario'], run['strategy'],
                output_root / f'threshold-{threshold:g}',
                sensor_torque_noise_sigma_nm=run['noise_sigma'],
                noise_seed=run['noise_seed'],
                signal_filter_enabled=True,
                lock_torque_threshold=threshold,
            )
            row['threshold_nm'] = threshold
            threshold_rows.append(row)

        scenario_count = len(scenarios) * len(noise_levels) * len(noise_seeds) * (
            len(torque_levels) + 1
        )
        summary = build_summary(
            threshold_rows, split, scenario_count,
            output_root / f'threshold-{threshold:g}',
        )
        summary['meta']['source_sha256']['benchmarks/run_threshold_sensitivity.py'] = (
            hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        )
        summary['meta']['threshold_nm'] = threshold
        summary['meta']['control_design'] = (
            'one matched no-fault run per scenario, noise level, seed, and strategy; '
            'controls are not repeated for each injected-torque level'
        )
        json_dir.mkdir(parents=True, exist_ok=True)
        json_path = json_dir / f'threshold-{threshold:g}.json'
        json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        results[threshold] = summary
        print(json.dumps({
            'threshold_nm': threshold,
            'runs': len(threshold_rows),
            'summary': summary['summary'],
            'json': str(json_path.resolve()),
        }, ensure_ascii=False), flush=True)

    return results


def main():
    parser = argparse.ArgumentParser(description='卡滞检测阈值与力矩噪声配对敏感性实验')
    parser.add_argument('--split', choices=('development', 'exploratory', 'validation'),
                        default='validation')
    parser.add_argument('--thresholds', nargs='+', type=float, default=[8.5, 10.0])
    parser.add_argument('--lock-reaction-torques', nargs='+', type=float,
                        default=[8.0, 9.0, 10.0, 11.0])
    parser.add_argument('--sensor-noise-sigmas', nargs='+', type=float,
                        default=[0.0, 1.5, 3.0])
    parser.add_argument('--sensor-noise-seeds', nargs='+', type=int, default=[42])
    parser.add_argument('--output-root', default=(
        'edge/edge_node/test/reports/task_recovery/member-b-threshold-sensitivity-r1'
    ))
    parser.add_argument('--json-dir', default='docs/member-b-validation-threshold-sensitivity-r1')
    args = parser.parse_args()

    if any(not math.isfinite(t) or t <= 0.0 for t in args.thresholds):
        parser.error('thresholds must be finite and positive')
    if any(not math.isfinite(torque) or not 0.0 < torque < 15.0
           for torque in args.lock_reaction_torques):
        parser.error('lock reaction torques must be finite and between 0 and 15 N·m')
    if any(not math.isfinite(sigma) or sigma < 0.0 for sigma in args.sensor_noise_sigmas):
        parser.error('sensor noise sigmas must be finite and non-negative')
    if not args.sensor_noise_seeds:
        parser.error('at least one sensor noise seed is required')

    run_experiment(
        scenarios=build_task_recovery_scenarios(args.split),
        thresholds=sorted(set(args.thresholds)),
        torque_levels=sorted(set(args.lock_reaction_torques)),
        noise_levels=sorted(set(args.sensor_noise_sigmas)),
        noise_seeds=sorted(set(args.sensor_noise_seeds)),
        output_root=args.output_root,
        json_dir=args.json_dir,
        split=args.split,
    )


if __name__ == '__main__':
    main()

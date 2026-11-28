"""Validate and document the all-joints noisy repeat experiment."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import shutil
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
EDGE_NODE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EDGE_NODE_ROOT))
from edge_node.fault.kinematics import (  # noqa: E402
    DH_PARAMS,
    compute_pose,
    forward_kinematics,
)
from edge_node.fault.recovery import RecoveryPlanner  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_reachability import (  # noqa: E402
    j0_wrist_offset_bound,
    locked_j0_error_lower_bound,
)

EXPERIMENT = "member-b-all-joints-noise-geometry-guard-r2"
JOINT_NAMES = {
    0: "J0 基座回转轴",
    1: "J2 肩关节",
    2: "J3 肘关节",
    3: "J4 腕关节",
}
ROBOT_JOINT_NAMES = {
    0: "joint_1",
    1: "joint_2",
    2: "joint_3",
    3: "joint_4",
}
STRATEGIES = ("off", "v1", "v2")
NOISE_SEEDS = (42, 43, 44)
EXPECTED_FAULT_RUNS = 216
EXPECTED_CONTROL_RUNS = 216
EXPECTED_TRACE_ROWS = 800
LOCKED_JOINT_TOLERANCE_RAD = 1e-8
POSITION_SCORE_TOLERANCE_M = 0.05


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative_to_repository(path: Path) -> str:
    return path.resolve().relative_to(REPOSITORY_ROOT).as_posix()


def read_trace(path: Path, run: dict) -> tuple[list[dict[str, str]], str, int]:
    if not path.is_file():
        raise FileNotFoundError(f"missing ignored run trace: {path}")
    trace_hash = sha256_file(path)
    trace_bytes = path.stat().st_size
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != EXPECTED_TRACE_ROWS:
        raise ValueError(f"{path.name}: expected 800 rows, got {len(rows)}")
    if any(row["run_id"] != run["run_id"] for row in rows):
        raise ValueError(f"{path.name}: trace run_id does not match summary")
    if [int(row["step"]) for row in rows] != list(range(EXPECTED_TRACE_ROWS)):
        raise ValueError(f"{path.name}: trace steps are incomplete or unordered")
    for row in rows:
        for field in (
            "ee_error_m",
            *(f"q{index}" for index in range(6)),
            *(f"qd{index}" for index in range(6)),
            *(f"tau{index}" for index in range(6)),
        ):
            if not math.isfinite(float(row[field])):
                raise ValueError(f"{path.name}: non-finite value in {field}")
    if run["fault_injected"]:
        fault_joint = run["fault_joint"]
        locked_positions = [
            float(row[f"q{fault_joint}"])
            for row in rows
            if row["fault_active"] == "True"
        ]
        if not locked_positions:
            raise ValueError(f"{path.name}: no samples in the fault-active interval")
        if max(locked_positions) - min(locked_positions) > LOCKED_JOINT_TOLERANCE_RAD:
            raise ValueError(f"{path.name}: the injected locked joint moved")
    return rows, trace_hash, trace_bytes


def validate_summary(summary: dict) -> list[dict]:
    runs = summary.get("runs", [])
    if len(runs) != EXPECTED_FAULT_RUNS + EXPECTED_CONTROL_RUNS:
        raise ValueError(f"expected 432 runs, got {len(runs)}")
    if len({run["run_id"] for run in runs}) != len(runs):
        raise ValueError("run_id values are not unique")
    fault_runs = [run for run in runs if run["fault_injected"]]
    control_runs = [run for run in runs if not run["fault_injected"]]
    if len(fault_runs) != EXPECTED_FAULT_RUNS or len(control_runs) != EXPECTED_CONTROL_RUNS:
        raise ValueError("fault/control run counts do not match the frozen experiment design")
    if set(summary["meta"]["sensor_torque_noise_seeds"]) != set(NOISE_SEEDS):
        raise ValueError("noise seeds do not match the documented experiment design")
    for strategy in STRATEGIES:
        if sum(run["strategy"] == strategy for run in fault_runs) != 72:
            raise ValueError(f"expected 72 fault runs for {strategy}")
        if sum(run["strategy"] == strategy for run in control_runs) != 72:
            raise ValueError(f"expected 72 no-fault controls for {strategy}")
    pairing_counts: dict[tuple, int] = defaultdict(int)
    for run in runs:
        key = (run["scenario"], run["noise_seed"], run["fault_injected"])
        pairing_counts[key] += 1
    if len(pairing_counts) != 144 or any(count != 3 for count in pairing_counts.values()):
        raise ValueError("each scenario, noise seed, and fault state must have three strategy rows")
    strategy_sets = {
        (scenario, noise_seed, fault_injected): {
            run["strategy"]
            for run in runs
            if run["scenario"] == scenario
            and run["noise_seed"] == noise_seed
            and run["fault_injected"] == fault_injected
        }
        for scenario, noise_seed, fault_injected in pairing_counts
    }
    if any(set(strategies) != set(STRATEGIES) for strategies in strategy_sets.values()):
        raise ValueError("every scenario, noise seed, and fault state must include off, V1, and V2")
    fault_keys = {(run["scenario"], run["noise_seed"]) for run in fault_runs}
    control_keys = {
        (run["scenario"].removesuffix("#NOFAULT"), run["noise_seed"])
        for run in control_runs
    }
    if fault_keys != control_keys or any(not run["scenario"].endswith("#NOFAULT") for run in control_runs):
        raise ValueError("fault and no-fault runs are not paired by scenario and noise seed")
    for run in runs:
        if run["sensor_torque_noise_sigma_nm"] != 1.5 or not run["signal_filter_enabled"]:
            raise ValueError(f"{run['run_id']}: run configuration differs from the declared noisy repeat")
        if run["lock_reaction_torque_nm"] != 12.5 or run["lock_torque_threshold_nm"] != 10.0:
            raise ValueError(f"{run['run_id']}: lock-reaction configuration differs from the declared repeat")
    if summary["meta"]["scenarios"] != 144 or summary["meta"]["paired_runs"] != 144:
        raise ValueError("summary metadata does not match the 24-scenario paired design")
    return runs


def validate_source_hashes(summary: dict) -> dict[str, str]:
    current_hashes = {}
    for relative_path, expected_hash in summary["meta"]["source_sha256"].items():
        if relative_path.startswith("benchmarks/"):
            source_path = EDGE_NODE_ROOT / "test" / relative_path
        else:
            source_path = EDGE_NODE_ROOT / relative_path
        current_hash = sha256_file(source_path)
        if current_hash != expected_hash:
            raise ValueError(f"experiment source changed after run: {relative_path}")
        current_hashes[relative_path] = current_hash
    return current_hashes


def score_group(runs: list[dict]) -> dict:
    latencies = [
        run["fault_detection_latency_ms"]
        for run in runs
        if run["fault_detection_latency_ms"] is not None
    ]
    recovery_times = [run["recovery_time_s"] for run in runs if run["recovered"]]
    stop_times = [run["stop_time_s"] for run in runs if run["safe_stopped"]]
    return {
        "runs": len(runs),
        "faults_detected": len(latencies),
        "recovered": len(recovery_times),
        "safe_stops": len(stop_times),
        "mean_fault_detection_latency_ms": round(statistics.mean(latencies), 3) if latencies else None,
        "mean_recovery_time_s": round(statistics.mean(recovery_times), 3) if recovery_times else None,
        "mean_safe_stop_time_s": round(statistics.mean(stop_times), 3) if stop_times else None,
        "false_alarms": sum(bool(run["false_alarm_during_nominal"]) for run in runs),
    }


def summarize_cases(runs: list[dict]) -> list[dict]:
    fault_runs = [run for run in runs if run["fault_injected"]]
    by_scenario: dict[str, list[dict]] = defaultdict(list)
    for run in fault_runs:
        by_scenario[run["scenario"]].append(run)
    cases = []
    for scenario, scenario_runs in sorted(by_scenario.items()):
        exemplar = scenario_runs[0]
        by_strategy = {
            strategy: score_group([run for run in scenario_runs if run["strategy"] == strategy])
            for strategy in STRATEGIES
        }
        controls = [
            run
            for run in runs
            if not run["fault_injected"]
            and run["scenario"] == f"{scenario}#NOFAULT"
            and run["strategy"] in ("v1", "v2")
        ]
        if len(controls) != len(NOISE_SEEDS) * 2:
            raise ValueError(f"{scenario}: expected paired no-fault controls for V1 and V2")
        cases.append(
            {
                "scenario": scenario,
                "fault_joint_index_zero_based": exemplar["fault_joint"],
                "fault_onset_s": exemplar["fault_onset_s"],
                "task_goal_rad": exemplar["task_goal_rad"],
                "noise_seeds": sorted(run["noise_seed"] for run in scenario_runs if run["strategy"] == "v2"),
                "by_strategy": by_strategy,
                "matched_v1_v2_control_runs": len(controls),
                "matched_v1_v2_control_false_alarms": sum(
                    bool(run["false_alarm_during_nominal"]) for run in controls
                ),
            }
        )
    if len(cases) != 24:
        raise ValueError(f"expected 24 frozen fault scenarios, got {len(cases)}")
    return cases


def summarize_joints(runs: list[dict]) -> list[dict]:
    results = []
    for joint_index, joint_name in JOINT_NAMES.items():
        fault_runs = [
            run
            for run in runs
            if run["fault_injected"] and run["fault_joint"] == joint_index
        ]
        control_runs = [
            run
            for run in runs
            if not run["fault_injected"] and run["fault_joint"] == joint_index
        ]
        results.append(
            {
                "joint_index_zero_based": joint_index,
                "joint_name": joint_name,
                "fault_runs": len(fault_runs),
                "matched_control_runs_per_strategy": len(control_runs) // len(STRATEGIES),
                "by_strategy": {
                    strategy: score_group(
                        [run for run in fault_runs if run["strategy"] == strategy]
                    )
                    for strategy in STRATEGIES
                },
                "control_false_alarms_by_strategy": {
                    strategy: sum(
                        bool(run["false_alarm_during_nominal"])
                        for run in control_runs
                        if run["strategy"] == strategy
                    )
                    for strategy in ("v1", "v2")
                },
            }
        )
    return results


def summarize_j0_target_classes(runs: list[dict]) -> list[dict]:
    summaries = []
    for target_class in ("T1", "T2"):
        fault_runs = [
            run
            for run in runs
            if run["fault_injected"]
            and run["fault_joint"] == 0
            and run["scenario"].split("#TQ", 1)[0].endswith(target_class)
        ]
        if len(fault_runs) != 27:
            raise ValueError(f"J0 {target_class}: expected 27 fault-strategy runs")
        controls = {
            strategy: [
                run
                for run in runs
                if not run["fault_injected"]
                and run["fault_joint"] == 0
                and run["strategy"] == strategy
                and run["scenario"].removesuffix("#NOFAULT").split("#TQ", 1)[0].endswith(target_class)
            ]
            for strategy in ("v1", "v2")
        }
        if any(len(strategy_runs) != 9 for strategy_runs in controls.values()):
            raise ValueError(f"J0 {target_class}: expected nine matched controls per strategy")
        summaries.append(
            {
                "target_class": target_class,
                "fault_runs_per_strategy": 9,
                "by_strategy": {
                    strategy: {
                        **score_group([run for run in fault_runs if run["strategy"] == strategy]),
                        "fault_detection_count": sum(
                            run["fault_detection_latency_ms"] is not None
                            for run in fault_runs
                            if run["strategy"] == strategy
                        ),
                        "matched_controls": len(controls.get(strategy, [])),
                        "matched_control_false_alarms": sum(
                            bool(run["false_alarm_during_nominal"])
                            for run in controls.get(strategy, [])
                        ),
                    }
                    for strategy in STRATEGIES
                },
            }
        )
    return summaries


def locked_j0_cases(runs: list[dict], raw_directory: Path) -> list[dict]:
    results = []
    v2_runs = [
        run
        for run in runs
        if run["fault_injected"] and run["fault_joint"] == 0 and run["strategy"] == "v2"
    ]
    scenarios = sorted({run["scenario"] for run in v2_runs})
    if len(scenarios) != 6:
        raise ValueError(f"expected six J0 target and fault-onset cases, got {len(scenarios)}")
    wrist_offset_bound = j0_wrist_offset_bound(DH_PARAMS)
    planner = RecoveryPlanner()
    for scenario in scenarios:
        scenario_runs = [run for run in v2_runs if run["scenario"] == scenario]
        if {run["noise_seed"] for run in scenario_runs} != set(NOISE_SEEDS):
            raise ValueError(f"{scenario}: expected all three noise-seed repeats")
        locked_angles = []
        planner_diagnostics = []
        for run in scenario_runs:
            path = raw_directory / run["trace"]
            with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
                trace_rows = list(csv.DictReader(stream))
            positions = [
                float(row["q0"])
                for row in trace_rows
                if row["fault_active"] == "True"
            ]
            if not positions or max(positions) - min(positions) > LOCKED_JOINT_TOLERANCE_RAD:
                raise ValueError(f"{scenario}: J0 is not fixed during fault-active trace")
            locked_angles.append(positions[0])
            event_rows = [
                row
                for row in trace_rows
                if row["fault_active"] == "True"
                and row["event_type"] == "JOINT_LOCKED"
                and row["event_joint"] == "0"
            ]
            if not event_rows:
                raise ValueError(f"{scenario}: expected a confirmed J0 lock event")
            event_signature = {
                (row["action"], row["reason"])
                for row in event_rows
            }
            if len(event_signature) != 1:
                raise ValueError(f"{scenario}: J0 event changed during the locked interval")
            event_row = event_rows[0]
            diagnosis = planner.plan(
                current_q=[float(event_row[f"state_q{index}"]) for index in range(6)],
                current_qd=[float(event_row[f"state_qd{index}"]) for index in range(6)],
                target_pose=compute_pose(run["task_goal_rad"]),
                locked_joints=[0],
                preferred_q=run["task_goal_rad"],
            )
            if (
                (diagnosis.action, diagnosis.reason) != (event_row["action"], event_row["reason"])
                or diagnosis.action != run["action"]
            ):
                raise ValueError(f"{run['run_id']}: the event-state planner replay differs from the recorded decision")
            planner_diagnostics.append(
                {
                    "noise_seed": run["noise_seed"],
                    "decision": diagnosis.action,
                    "reason": diagnosis.reason,
                    "planner_reported_position_error_m": diagnosis.position_error,
                    "planner_search_error_m": (
                        None
                        if diagnosis.reason == "GEOMETRICALLY_UNREACHABLE"
                        else diagnosis.position_error
                    ),
                    "position_error_lower_bound_m": diagnosis.position_error_lower_bound,
                    "planner_position_tolerance_m": planner.position_tolerance,
                    "best_search_error_exceeds_score_tolerance": (
                        diagnosis.reason != "GEOMETRICALLY_UNREACHABLE"
                        and diagnosis.position_error > POSITION_SCORE_TOLERANCE_M
                    ),
                    "geometric_score_infeasibility_proven": (
                        diagnosis.position_error_lower_bound is not None
                        and diagnosis.position_error_lower_bound > POSITION_SCORE_TOLERANCE_M
                    ),
                    "iterations": diagnosis.iterations,
                }
            )
        if max(locked_angles) - min(locked_angles) > LOCKED_JOINT_TOLERANCE_RAD:
            raise ValueError(f"{scenario}: J0 locked angle changed across noise repeats")
        representative = scenario_runs[0]
        target_position, _ = forward_kinematics(representative["task_goal_rad"])
        bound = locked_j0_error_lower_bound(
            target_position, locked_angles[0], wrist_offset_bound
        )
        results.append(
            {
                "scenario": scenario,
                "noise_seeds": sorted(run["noise_seed"] for run in scenario_runs),
                "locked_j0_rad": round(locked_angles[0], 9),
                "target_position_m": [round(value, 9) for value in target_position],
                "target_tangential_projection_m": bound["tangential_target_m"],
                "distal_wrist_offset_bound_m": bound["wrist_offset_bound_m"],
                "minimum_position_error_lower_bound_m": bound["minimum_position_error_m"],
                "score_tolerance_m": bound["position_tolerance_m"],
                "geometrically_proven_unreachable_at_score_tolerance": bound["proven_unreachable"],
                "v2_recovered": sum(bool(run["recovered"]) for run in scenario_runs),
                "v2_safe_stops": sum(bool(run["safe_stopped"]) for run in scenario_runs),
                "v2_planner_diagnostics": planner_diagnostics,
                "planner_decision": planner_diagnostics[0]["decision"],
                "planner_reason": planner_diagnostics[0]["reason"],
                "planner_best_position_error_range_m": [
                    round(
                        min(
                            row["planner_search_error_m"]
                            for row in planner_diagnostics
                            if row["planner_search_error_m"] is not None
                        ),
                        9,
                    )
                    if any(row["planner_search_error_m"] is not None for row in planner_diagnostics)
                    else None,
                    round(
                        max(
                            row["planner_search_error_m"]
                            for row in planner_diagnostics
                            if row["planner_search_error_m"] is not None
                        ),
                        9,
                    )
                    if any(row["planner_search_error_m"] is not None for row in planner_diagnostics)
                    else None,
                ],
                "conclusion": (
                    "锁定关节后的末端位置误差下界超过评分容差，几何上证明不可达"
                    if bound["proven_unreachable"]
                    else "该误差下界不足以证明不可达，闭环结果见 v2_recovered"
                ),
            }
        )
    return results


def curate_replay_traces(runs: list[dict], raw_directory: Path, trace_directory: Path) -> list[dict]:
    selections = (
        (0, "VALIDATION-LOCK-J0#s1T1", "J0 recoverable target"),
        (0, "VALIDATION-LOCK-J0#s1T2", "J0 target proven unreachable under lock"),
        (0, "VALIDATION-LOCK-J0#s3T2", "J0 target marginally beyond the score tolerance after lock"),
        (1, "VALIDATION-LOCK-J1#s1T1", "J2 shoulder lock and recovery"),
        (2, "VALIDATION-LOCK-J2#s1T1", "J3 elbow lock and recovery"),
        (3, "VALIDATION-LOCK-J3#s1T1", "J4 wrist lock and recovery"),
    )
    trace_directory.mkdir(parents=True, exist_ok=True)
    selections_out = []
    for joint_index, scenario, label in selections:
        matches = [
            run
            for run in runs
            if run["fault_injected"]
            and run["fault_joint"] == joint_index
            and run["scenario"].startswith(f"{scenario}#TQ")
            and run["strategy"] == "v2"
            and run["noise_seed"] == 42
        ]
        if len(matches) != 1:
            raise ValueError(f"cannot select unique V2 replay for {scenario}")
        run = matches[0]
        source = raw_directory / run["trace"]
        destination = trace_directory / source.name
        shutil.copyfile(source, destination)
        selections_out.append(
            {
                "label": label,
                "run_id": run["run_id"],
                "scenario": run["scenario"],
                "joint_index_zero_based": joint_index,
                "trace_path": relative_to_repository(destination),
                "sha256": sha256_file(destination),
                "bytes": destination.stat().st_size,
            }
        )
    return selections_out


def compact_run_record(run: dict, trace_path: Path, trace_hash: str, trace_bytes: int) -> dict:
    return {
        key: run[key]
        for key in (
            "run_id",
            "scenario",
            "description",
            "fault_joint",
            "fault_onset_s",
            "seed",
            "task_goal_rad",
            "lock_reaction_torque_nm",
            "lock_torque_threshold_nm",
            "sensor_torque_noise_sigma_nm",
            "noise_seed",
            "signal_filter_enabled",
            "strategy",
            "fault_injected",
            "fault_detection_latency_ms",
            "false_alarm_during_nominal",
            "first_false_alarm_type",
            "decision_s",
            "action",
            "recovered",
            "safe_stopped",
            "recovery_time_s",
            "stop_time_s",
            "peak_fault_joint_torque_nm",
            "mean_fault_joint_torque_nm",
            "final_ee_error_m",
            "max_joint_speed_rad_s",
            "max_joint_torque_nm",
        )
    } | {
        "trace_path": relative_to_repository(trace_path),
        "trace_sha256": trace_hash,
        "trace_bytes": trace_bytes,
        "trace_rows": EXPECTED_TRACE_ROWS,
    }


def render_report(manifest: dict) -> str:
    config = manifest["configuration"]
    joint_rows = manifest["summary_by_joint"]
    overall = manifest["summary_by_strategy"]
    joint_table = [
        "| 故障关节 | 策略 | 检出 | 恢复评分通过 | 安全停稳通过 | 平均检出延迟 | 平均恢复用时 | 配对无故障误报 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for joint in joint_rows:
        control_count = joint["matched_control_runs_per_strategy"]
        for strategy in STRATEGIES:
            result = joint["by_strategy"][strategy]
            detection = (
                f"{result['faults_detected']}/{result['runs']}"
                if strategy != "off"
                else "不适用"
            )
            mean_latency = result["mean_fault_detection_latency_ms"]
            latency_text = "—" if mean_latency is None else f"{mean_latency:.1f} ms"
            mean_recovery = result["mean_recovery_time_s"]
            recovery_text = "—" if mean_recovery is None else f"{mean_recovery:.3f} s"
            false_alarms = (
                "不适用"
                if strategy == "off"
                else f"{joint['control_false_alarms_by_strategy'][strategy]}/{control_count}"
            )
            joint_table.append(
                f"| {joint['joint_name']}（索引 {joint['joint_index_zero_based']}） | {strategy} | "
                f"{detection} | {result['recovered']}/{result['runs']} | "
                f"{result['safe_stops']}/{result['runs']} | {latency_text} | "
                f"{recovery_text} | {false_alarms} |"
            )
    reach_table = [
        "| J0 工况 | 实测锁定角 | 几何误差下界 | 规划器动作 / 原因 | 搜索误差 | V2 结果 | 可达性证据 |",
        "|---|---:|---:|---|---:|---:|---|",
    ]
    for case in manifest["j0_locked_geometry"]:
        v2_result = f"恢复 {case['v2_recovered']}/3，停稳 {case['v2_safe_stops']}/3"
        proof = (
            "证明不可达"
            if case["geometrically_proven_unreachable_at_score_tolerance"]
            else "闭环实证可达" if case["v2_recovered"] else "可达性未定"
        )
        error_range = case["planner_best_position_error_range_m"]
        if error_range[0] is None:
            planner_error = "未搜索（几何判定）"
        else:
            error_low, error_high = error_range
            low_mm, high_mm = f"{error_low * 1000:.3f}", f"{error_high * 1000:.3f}"
            planner_error = f"{low_mm} mm" if low_mm == high_mm else f"{low_mm}–{high_mm} mm"
        reach_table.append(
            f"| `{case['scenario']}` | {case['locked_j0_rad']:.9f} rad | "
            f"{case['minimum_position_error_lower_bound_m'] * 1000:.3f} mm | "
            f"`{case['planner_decision']} / {case['planner_reason']}` | "
            f"{planner_error} | {v2_result} | {proof} |"
        )
    replay_table = [
        "| 回放内容 | run_id | 轨迹 |",
        "|---|---|---|",
    ]
    for replay in manifest["replay_traces"]:
        relative_path = Path(replay["trace_path"]).relative_to(Path("docs"))
        label = {
            "J0 recoverable target": "J0 可恢复目标",
            "J0 target proven unreachable under lock": "J0 锁定后几何不可达目标",
            "J0 target marginally beyond the score tolerance after lock": "J0 锁定后略超评分容差的目标",
            "J2 shoulder lock and recovery": "肩关节 J2 卡滞恢复",
            "J3 elbow lock and recovery": "肘关节 J3 卡滞恢复",
            "J4 wrist lock and recovery": "腕关节 J4 卡滞恢复",
        }[replay["label"]]
        replay_table.append(
            f"| {label} | `{replay['run_id']}` | "
            f"[CSV.gz]({relative_path.as_posix()}) |"
        )
    lines = [
        "# 成员 B · J0、J2–J4 含噪声卡滞恢复复核 r2",
        "",
        "日期为 2026-11-26。实验在仓库通用六轴标准 DH Python plant 上运行，覆盖 J0 基座回转、J2 肩、J3 肘和 J4 腕四个单关节卡滞位置。算法关节索引从 0 开始，分别对应模型 joint_1 至 joint_4。这里以实验方案中的 J0–J4 标注故障部位，其中模型 joint_2 对应机械臂肩关节 J2，模型 joint_3 对应肘关节 J3，模型 joint_4 对应腕关节 J4。",
        "",
        "## 实验设计与复核范围",
        "",
        f"冻结 validation 集有 24 个故障场景，每个关节覆盖两个点到点目标和三个注入时刻。每个场景使用噪声种子 { '、'.join(str(seed) for seed in config['sensor_torque_noise_seeds']) }，比较容错关闭、V1、V2，并为每种策略配对一条无故障对照。共 {manifest['fault_run_count']} 次故障运行和 {manifest['no_fault_control_run_count']} 次无故障对照。采样率为 {config['sample_rate_hz']} Hz，启用在线信号滤波，检测阈值为 {config['lock_torque_threshold_levels_nm'][0]:.1f} N·m，合成卡滞读数为 {config['lock_reaction_torque_levels_nm'][0]:.1f} N·m，故障关节读数叠加 σ={config['sensor_torque_noise_sigma_levels_nm'][0]:.1f} N·m 高斯噪声。",
        "",
        "噪声只作用于故障关节的传感器读数，不改变仿真对象的物理状态。每个工况的三个噪声种子是固定目标上的重复运行，不是三个独立目标。validation 场景此前已用于实验，因此本轮不是独立盲测。",
        "",
        f"恢复评分要求故障期间末端位置误差不超过 {config['ee_position_tolerance_m'] * 1000:.0f} mm，持续至少 {config['dwell_s']:.2f} s 并保持至运行结束。停稳评分要求 STOP 后所有关节速度不超过 {config['stop_speed_rad_s']:.2f} rad/s，连续保持同一时长，并在 {config['stop_deadline_s']:.1f} s 限时内达标。",
        "",
        "## 全局结果",
        "",
        "| 策略 | 恢复评分 | 安全停稳 | 故障检出 | 配对无故障误报（V1/V2） | 平均检出延迟 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for strategy in STRATEGIES:
        result = overall[strategy]
        detection = (
            f"{result['faults_detected']}/{result['fault_runs']}"
            if strategy != "off"
            else "不适用"
        )
        latency = result["mean_fault_detection_latency_ms"]
        latency_text = "—" if latency is None else f"{latency:.1f} ms"
        false_alarms = (
            "不适用"
            if strategy == "off"
            else f"{result['no_fault_control_false_alarms']}/{result['no_fault_control_runs']}"
        )
        lines.append(
            f"| {strategy} | {result['recovered']}/{result['fault_runs']} | "
            f"{result['safe_stops']}/{result['fault_runs']} | {detection} | "
            f"{false_alarms} | {latency_text} |"
        )
    lines.extend(
        [
            "",
            "## 按关节统计",
            "",
            *joint_table,
            "",
            "V2 在肩关节 J2、肘关节 J3、腕关节 J4（遥测 jointIndex 1–3）三个关节组各 18/18 达到恢复评分。J0 基座原始恢复评分为 9/18、停稳 9/18。以下将 J0 的 18 次运行按锁定角和几何可达性分类，并列出规划器决策与实际搜索误差；几何预判停止的工况注明未执行搜索。",
            "",
            "## J0 锁定角下的几何复核",
            "",
            *reach_table,
            "",
            "几何误差下界按目标位置到锁定 J0 所限定径向平面的切向距离，减去模型第 6 行 0.100 m 轴向偏距计算。第 5 行偏距沿径向平面内轴线，不贡献平面外位移。只有误差下界严格大于 0.050 m 恢复评分容差时，才证明目标在评分意义下不可达。更新后的规划器在满足几何证明条件时提前停止搜索，其余工况继续按数值搜索决策。可达目标 T1 的三组注入时刻共 9 次 V2 运行全部通过恢复评分，三个 T2 工况共 9 次 V2 运行均安全停稳。s3T2 的误差下界为 51.001 mm，仅比 50 mm 评分容差高 1.001 mm，对通用模型尺寸误差敏感。按无条件计分的 J0 恢复率仍是 9/18。",
            "",
            "## 代表性回放轨迹",
            "",
            *replay_table,
            "",
            "每条轨迹含 800 个控制周期的关节位置、速度、力矩、状态滤波读数、动作和故障标记。轨迹内容及 SHA-256 写入机器可读清单。",
            "",
            "## 重跑与边界",
            "",
            "机器可读清单列出全部 432 次运行的 run_id、评分结果、原始轨迹 SHA-256 和源码 SHA-256。以下命令先重跑三个策略和配对对照，生成本地原始轨迹，然后由汇总脚本复核源码版本、J0 锁定角下界、逐次轨迹、回放样例和本报告。原始 432 份 CSV.gz 轨迹保留在 Git 忽略的 reports 目录。",
            "",
            "~~~powershell",
            "py edge/edge_node/test/benchmarks/run_task_recovery.py --split validation --include-no-fault-controls --online-signal-filter --lock-reaction-torques 12.5 --sensor-torque-noise-sigmas 1.5 --sensor-noise-seeds 42 43 44 --output-dir edge/edge_node/test/reports/task_recovery/member-b-all-joints-noise-geometry-guard-r2 --json edge/edge_node/test/reports/task_recovery/member-b-all-joints-noise-geometry-guard-r2/summary.json",
            "py edge/edge_node/test/benchmarks/summarize_all_joints_repeat.py --summary edge/edge_node/test/reports/task_recovery/member-b-all-joints-noise-geometry-guard-r2/summary.json",
            "~~~",
            "",
            f"完整逐次清单：[manifest.json](experiments/{EXPERIMENT}/manifest.json)。运行汇总 JSON SHA-256 为 `{manifest['source_summary_sha256']}`。",
            "",
            "本轮只验证通用 DH 仿真模型，没有验证具体品牌机械臂、实体传感器或实体执行器。仅覆盖末端位置，没有覆盖末端姿态或抓取成功率。当前结果没有新增 Docker、ROS 2、MQTT 在线运行数据。J0 几何下界只适用于记录中的 DH 参数、目标和锁定角。",
            "",
        ]
    )
    return "\n".join(lines)


def build_artifacts(summary_path: Path, manifest_path: Path, report_path: Path, trace_directory: Path) -> dict:
    summary_path = summary_path.resolve()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    runs = validate_summary(summary)
    verified_source_hashes = validate_source_hashes(summary)
    raw_directory = REPOSITORY_ROOT / summary["meta"]["raw_directory"]
    trace_audits = []
    for run in runs:
        trace_path = raw_directory / run["trace"]
        _rows, trace_hash, trace_bytes = read_trace(trace_path, run)
        trace_audits.append(compact_run_record(run, trace_path, trace_hash, trace_bytes))
    summary_sha256 = sha256_file(summary_path)
    geometry = locked_j0_cases(runs, raw_directory)
    replay_traces = curate_replay_traces(runs, raw_directory, trace_directory)
    summary_by_strategy = {}
    for strategy in STRATEGIES:
        fault_results = [
            run for run in runs if run["fault_injected"] and run["strategy"] == strategy
        ]
        control_results = [
            run for run in runs if not run["fault_injected"] and run["strategy"] == strategy
        ]
        summary_by_strategy[strategy] = {
            **score_group(fault_results),
            "fault_runs": len(fault_results),
            "no_fault_control_runs": len(control_results),
            "no_fault_control_false_alarms": sum(
                bool(run["false_alarm_during_nominal"]) for run in control_results
            ),
        }
    manifest = {
        "experiment": EXPERIMENT,
        "date": "2026-11-26",
        "purpose": "Audit all-joint lock-recovery outcomes under filtered, noisy synthetic torque readings.",
        "model": "Repository generic six-axis standard-DH Python plant.",
        "limitations": [
            "Previously used validation scenarios and repeated noise seeds do not constitute an independent blind test.",
            "Torque noise affects only the synthetic fault-joint sensor reading, not plant physics.",
            "This is model-only evidence and does not validate a physical robot or a specific commercial arm.",
            "Only end-effector position is scored, not orientation or grasp success.",
            "Raw per-run traces are local files in the Git-ignored reports directory. Six hash-verified V2 replay traces are included in the documentation tree.",
        ],
        "configuration": {
            key: summary["meta"][key]
            for key in (
                "sample_rate_hz",
                "split",
                "signal_filter_enabled",
                "signal_filter_parameters",
                "lock_torque_threshold_levels_nm",
                "lock_reaction_torque_levels_nm",
                "sensor_torque_noise_sigma_levels_nm",
                "sensor_torque_noise_seeds",
                "ee_position_tolerance_m",
                "stop_speed_rad_s",
                "stop_deadline_s",
                "dwell_s",
                "recovery_max_velocity_rad_s",
                "recovery_max_acceleration_rad_s2",
            )
        },
        "source_summary_path": relative_to_repository(summary_path),
        "source_summary_sha256": summary_sha256,
        "source_sha256": verified_source_hashes
        | {
            "edge_node/fault/kinematics.py": sha256_file(EDGE_NODE_ROOT / "edge_node/fault/kinematics.py"),
            "benchmarks/validate_reachability.py": sha256_file(Path(__file__).with_name("validate_reachability.py")),
            "benchmarks/summarize_all_joints_repeat.py": sha256_file(Path(__file__)),
        },
        "raw_directory": relative_to_repository(raw_directory),
        "fault_run_count": sum(run["fault_injected"] for run in runs),
        "no_fault_control_run_count": sum(not run["fault_injected"] for run in runs),
        "unique_run_id_count": len({run["run_id"] for run in runs}),
        "trace_rows_per_run": EXPECTED_TRACE_ROWS,
        "summary_by_strategy": summary_by_strategy,
        "joint_index_mapping": {
            str(index): {"arm_joint_name": JOINT_NAMES[index], "model_joint_name": ROBOT_JOINT_NAMES[index]}
            for index in JOINT_NAMES
        },
        "summary_by_joint": summarize_joints(runs),
        "summary_by_j0_target_class": summarize_j0_target_classes(runs),
        "j0_locked_geometry": geometry,
        "replay_traces": replay_traces,
        "runs": trace_audits,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(render_report(manifest), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="核对并整理 J0、J2–J4 噪声重复实验")
    parser.add_argument(
        "--summary",
        type=Path,
        default=REPOSITORY_ROOT
        / "edge/edge_node/test/reports/task_recovery/member-b-all-joints-noise-geometry-guard-r2/summary.json",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPOSITORY_ROOT / f"docs/experiments/{EXPERIMENT}/manifest.json",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=REPOSITORY_ROOT / "docs/member-b-all-joints-repeat-validation-r2.md",
    )
    parser.add_argument(
        "--trace-directory",
        type=Path,
        default=REPOSITORY_ROOT / f"docs/experiments/{EXPERIMENT}/traces",
    )
    args = parser.parse_args()
    manifest = build_artifacts(args.summary, args.manifest, args.report, args.trace_directory)
    print(
        json.dumps(
            {
                "manifest": relative_to_repository(args.manifest),
                "report": relative_to_repository(args.report),
                "runs": len(manifest["runs"]),
                "unique_run_ids": manifest["unique_run_id_count"],
                "geometry_proven_unreachable": sum(
                    case["geometrically_proven_unreachable_at_score_tolerance"]
                    for case in manifest["j0_locked_geometry"]
                ),
                "replay_traces": len(manifest["replay_traces"]),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

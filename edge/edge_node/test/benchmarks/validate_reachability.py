"""Build kinematic reachability certificates from task-recovery traces."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(Path(__file__).parents[2]))
from edge_node.fault.kinematics import DH_PARAMS, forward_kinematics

REACHABLE_SCENARIO = "VALIDATION-LOCK-J0#s1T1"
UNREACHABLE_SCENARIO = "VALIDATION-LOCK-J0#s1T2"
POSITION_TOLERANCE_M = 0.05
LOCKED_JOINT_TOLERANCE_RAD = 1e-8


def certify_reachable_witness(witness_q, target_position, locked_joint, locked_position, tolerance):
    if not 0 <= locked_joint < 6 or len(witness_q) != 6 or len(target_position) != 3:
        raise ValueError("invalid witness or target dimensions")
    if tolerance <= 0.0:
        raise ValueError("position tolerance must be positive")
    actual_position, _ = forward_kinematics(witness_q)
    position_error = math.dist(actual_position, target_position)
    locked_error = abs(witness_q[locked_joint] - locked_position)
    if locked_error > LOCKED_JOINT_TOLERANCE_RAD:
        raise ValueError("witness moves the locked joint")
    if position_error > tolerance:
        raise ValueError("witness exceeds the target position tolerance")
    return {
        "witness_q_rad": [round(value, 9) for value in witness_q],
        "position_m": [round(value, 9) for value in actual_position],
        "position_error_m": round(position_error, 9),
        "locked_joint_index": locked_joint,
        "locked_position_rad": round(locked_position, 9),
        "locked_joint_error_rad": round(locked_error, 12),
        "position_tolerance_m": tolerance,
    }


def locked_j0_error_lower_bound(target_position, locked_angle, wrist_offset_bound):
    if len(target_position) != 3 or wrist_offset_bound < 0.0:
        raise ValueError("invalid target or wrist offset bound")
    x, y, _ = target_position
    tangent = -math.sin(locked_angle) * x + math.cos(locked_angle) * y
    lower_bound = max(0.0, abs(tangent) - wrist_offset_bound)
    return {
        "locked_j0_rad": round(locked_angle, 9),
        "tangential_target_m": round(tangent, 9),
        "wrist_offset_bound_m": wrist_offset_bound,
        "minimum_position_error_m": round(lower_bound, 9),
        "position_tolerance_m": POSITION_TOLERANCE_M,
        "proven_unreachable": lower_bound > POSITION_TOLERANCE_M,
    }


def j0_wrist_offset_bound(dh_params):
    """Bound out-of-plane reach with the final DH offset after the radial-plane links."""
    if len(dh_params) != 6 or any(len(row) != 4 for row in dh_params):
        raise ValueError("DH geometry must contain six standard DH rows")
    if abs(dh_params[0][0]) > 1e-12:
        raise ValueError("base theta offset must be zero for the locked-J0 angle bound")
    # d5 is along a radial-plane axis. Only the final d6 offset can add a
    # component normal to that plane, so bound it by its own link length.
    expected_alpha = (math.pi / 2.0, 0.0, 0.0, math.pi / 2.0)
    for index, expected in enumerate(expected_alpha):
        if not math.isclose(dh_params[index][3], expected, abs_tol=1e-12):
            raise ValueError("DH geometry no longer preserves the locked-J0 radial-plane")
    if any(abs(dh_params[index][1]) > 1e-12 for index in (1, 2, 3)):
        raise ValueError("pre-wrist DH offsets leave the locked-J0 radial-plane")
    if any(abs(dh_params[index][2]) > 1e-12 for index in (3, 4, 5)):
        raise ValueError("distal DH link lengths leave the locked-J0 radial-plane")
    return abs(dh_params[5][1])


def _base_scenario(scenario):
    scenario = scenario.removesuffix("#NOFAULT")
    return scenario.split("#TQ", 1)[0]


def _run(summary, scenario):
    matches = [
        row for row in summary["runs"]
        if _base_scenario(row["scenario"]) == scenario
        and row["strategy"] == "v2"
        and row["fault_injected"]
        and row.get("noise_seed", 42) == 42
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one V2 run for {scenario}, found {len(matches)}")
    return matches[0]


def _trace(summary, run):
    path = Path(summary["meta"]["raw_directory"]) / run["trace"]
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _locked_position(rows, joint_index):
    positions = [float(row[f"q{joint_index}"]) for row in rows if row["fault_active"] == "True"]
    if not positions or max(positions) - min(positions) > LOCKED_JOINT_TOLERANCE_RAD:
        raise ValueError("faulted joint is missing or moves during the locked interval")
    return positions[0]


def build_certificate(summary_path):
    summary_path = Path(summary_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    reachable_run = _run(summary, REACHABLE_SCENARIO)
    reachable_rows = _trace(summary, reachable_run)
    reachable_lock = _locked_position(reachable_rows, 0)
    reachable_target, _ = forward_kinematics(reachable_run["task_goal_rad"])
    candidates = [row for row in reachable_rows if row["fault_active"] == "True" and row["action"] == "RECOVER"]
    if not candidates or not reachable_run["recovered"]:
        raise ValueError("reachable scenario has no scored V2 recovery witness")
    witness_row = min(candidates, key=lambda row: float(row["ee_error_m"]))
    witness_q = [float(witness_row[f"q{index}"]) for index in range(6)]
    witness = certify_reachable_witness(witness_q, reachable_target, 0, reachable_lock, 0.02)
    reachable = {
        "scenario": REACHABLE_SCENARIO,
        "run_id": reachable_run["run_id"],
        "fault_onset_s": reachable_run["fault_onset_s"],
        "target_q_rad": reachable_run["task_goal_rad"],
        "target_position_m": [round(value, 9) for value in reachable_target],
        "locked_joint_index": 0,
        "locked_position_rad": round(reachable_lock, 9),
        "witness_sample_time_s": float(witness_row["t_s"]),
        "witness": witness,
        "action": reachable_run["action"],
        "recovered": reachable_run["recovered"],
        "recovery_time_s": reachable_run["recovery_time_s"],
        "final_position_error_m": reachable_run["final_ee_error_m"],
    }

    unreachable_run = _run(summary, UNREACHABLE_SCENARIO)
    unreachable_rows = _trace(summary, unreachable_run)
    unreachable_lock = _locked_position(unreachable_rows, 0)
    unreachable_target, _ = forward_kinematics(unreachable_run["task_goal_rad"])
    offset_bound = j0_wrist_offset_bound(DH_PARAMS)
    geometry = locked_j0_error_lower_bound(unreachable_target, unreachable_lock, offset_bound)
    if not geometry["proven_unreachable"]:
        raise ValueError("unreachable scenario lacks a geometric lower-bound proof")
    if unreachable_run["action"] != "STOP" or not unreachable_run["safe_stopped"]:
        raise ValueError("unreachable scenario did not safely stop under V2")
    stop_row = next((row for row in unreachable_rows if row["action"] == "STOP"), None)
    unreachable = {
        "scenario": UNREACHABLE_SCENARIO,
        "run_id": unreachable_run["run_id"],
        "fault_onset_s": unreachable_run["fault_onset_s"],
        "target_q_rad": unreachable_run["task_goal_rad"],
        "target_position_m": [round(value, 9) for value in unreachable_target],
        "locked_joint_index": 0,
        "locked_position_rad": round(unreachable_lock, 9),
        "geometry": geometry,
        "action": unreachable_run["action"],
        "reason": None if stop_row is None else stop_row["reason"],
        "safely_stopped": unreachable_run["safe_stopped"],
        "stop_time_s": unreachable_run["stop_time_s"],
    }

    no_fault_controls = []
    for scenario in (REACHABLE_SCENARIO, UNREACHABLE_SCENARIO):
        controls = [
            row for row in summary["runs"]
            if _base_scenario(row["scenario"]) == scenario
            and not row["fault_injected"]
            and row["strategy"] in ("off", "v1", "v2")
            and row.get("noise_seed", 42) == 42
        ]
        if len(controls) != 3:
            raise ValueError(f"expected three matched no-fault strategies for {scenario}")
        if any(row["false_alarm_during_nominal"] for row in controls):
            raise ValueError(f"detector raised a false alarm in no-fault control for {scenario}")
        no_fault_controls.extend(controls)

    source_root = Path(__file__).parents[2]
    hashes = {
        "kinematics.py": hashlib.sha256((source_root / "edge_node/fault/kinematics.py").read_bytes()).hexdigest(),
        "recovery.py": hashlib.sha256((source_root / "edge_node/fault/recovery.py").read_bytes()).hexdigest(),
        "run_task_recovery.py": hashlib.sha256(Path(__file__).with_name("run_task_recovery.py").read_bytes()).hexdigest(),
        "validate_reachability.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "summary.json": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
    }
    return {
        "method": "6R standard-DH forward kinematics and locked-J0 workspace bound",
        "scope": "end-effector position only",
        "position_tolerance_m": POSITION_TOLERANCE_M,
        "locked_joint_tolerance_rad": LOCKED_JOINT_TOLERANCE_RAD,
        "source_validation_summary": summary_path.as_posix(),
        "source_sha256": hashes,
        "reachable_case": reachable,
        "unreachable_case": unreachable,
        "strategy_runs": [
            row for row in summary["runs"]
            if row["fault_injected"]
            and _base_scenario(row["scenario"]) in (REACHABLE_SCENARIO, UNREACHABLE_SCENARIO)
            and row.get("noise_seed", 42) == 42
        ],
        "no_fault_controls": no_fault_controls,
    }


def render_report(certificate):
    reachable = certificate["reachable_case"]
    witness = reachable["witness"]
    unreachable = certificate["unreachable_case"]
    geometry = unreachable["geometry"]
    table = ["| 场景 | 策略 | 检测延迟 | 恢复 | 停稳 | 最终末端误差 | 峰值关节速度 |", "|---|---|---:|---:|---:|---:|---:|"]
    for run in certificate["strategy_runs"]:
        latency = run["fault_detection_latency_ms"]
        latency_text = "未检出" if latency is None else f"{latency} ms"
        recovered = "是" if run["recovered"] else "否"
        safely_stopped = "是" if run["safe_stopped"] else "否"
        table.append(f"| {run['scenario']} | {run['strategy']} | {latency_text} | {recovered} | {safely_stopped} | {run['final_ee_error_m']} m | {run['max_joint_speed_rad_s']} rad/s |")
    return (
        "# 成员 B · 卡滞后目标可达性验证\n\n"
        "本报告核查 J0 卡滞后目标能否在末端位置容差内到达。判据只覆盖末端位置，不评价姿态。\n\n"
        f"## 锁定约束下可达\n\n场景 `{reachable['scenario']}` 在 {reachable['fault_onset_s']:.2f} s 注入卡滞。V2 轨迹于 {reachable['witness_sample_time_s']:.2f} s 提供一组关节状态，J0 固定在 {reachable['locked_position_rad']:.9f} rad。正运动学末端误差为 {witness['position_error_m']:.6f} m，小于 {witness['position_tolerance_m']:.3f} m 见证容差，因此该关节向量证明目标在锁定约束下可达。闭环恢复耗时 {reachable['recovery_time_s']:.2f} s，最终误差 {reachable['final_position_error_m']:.6f} m。\n\n"
        f"## 锁定约束下不可达\n\n场景 `{unreachable['scenario']}` 在 {unreachable['fault_onset_s']:.2f} s 注入卡滞，锁定角为 {unreachable['locked_position_rad']:.9f} rad。固定 J0 后，DH 前五个坐标系的原点位于由基座锁定角确定的径向平面内。第 5 行轴向偏距沿平面内轴线，仅第 6 行轴向偏距贡献平面外位移，上限为 {geometry['wrist_offset_bound_m']:.3f} m。目标的切向投影为 {geometry['tangential_target_m']:.6f} m，末端位置误差至少为投影绝对值减去这一上限，即 {geometry['minimum_position_error_m']:.6f} m，大于 {geometry['position_tolerance_m']:.3f} m 评分容差。V2 输出 `{unreachable['action']}`，原因为 `{unreachable['reason']}`，并在 {unreachable['stop_time_s']:.2f} s 达到停稳评分。\n\n"
        "## 三策略配对复跑\n\n" + "\n".join(table) + "\n\n"
        "两种故障目标各有同轨迹无故障对照，六条关闭容错、V1、V2 无故障运行均无误报。无故障对照 run_id 已记录在证书 JSON。使用默认 10.0 N·m 检测阈值、合成卡滞读数 12.5 N·m、100 Hz 控制周期。\n\n"
        "## 适用范围\n\n可达结论是正运动学存在性证明。不可达结论是针对仓库通用 6R DH 模型和记录锁定角的几何下界。两个目标来自此前已用过的 validation 场景，本次只复核可达性和可复现性，不构成独立盲测或实体机械臂结论。不可达证明使用末端位置判据，没有评价末端姿态。\n\n"
        "复现命令：\n\n~~~powershell\n"
        "py edge/edge_node/test/benchmarks/run_task_recovery.py --split validation --scenario 'VALIDATION-LOCK-J0#s1T1' 'VALIDATION-LOCK-J0#s1T2' --include-no-fault-controls --output-dir edge/edge_node/test/reports/task_recovery/member-b-reachability-check-r2 --json edge/edge_node/test/reports/task_recovery/member-b-reachability-check-r2/summary.json\n"
        "py edge/edge_node/test/benchmarks/validate_reachability.py --summary edge/edge_node/test/reports/task_recovery/member-b-reachability-check-r2/summary.json\n"
        "py -m pytest -q edge/edge_node/test/test_reachability_certificate.py\n~~~\n\n"
        f"本轮汇总 JSON SHA-256：`{certificate['source_sha256']['summary.json']}`。可达见证与不可达下界使用该哈希对应的复跑数据。\n\n"
        "逐次 run_id、可达关节见证、几何误差下界和 SHA-256 见相邻 JSON。\n"
    )


def main():
    parser = argparse.ArgumentParser(description="核验 J0 锁定后的末端位置目标可达性")
    parser.add_argument("--summary", default="edge/edge_node/test/reports/task_recovery/member-b-reachability-check-r2/summary.json")
    parser.add_argument("--json", default="docs/member-b-reachability-certificate-r2.json")
    parser.add_argument("--report", default="docs/member-b-reachability-validation-r2.md")
    args = parser.parse_args()
    certificate = build_certificate(args.summary)
    Path(args.json).write_text(json.dumps(certificate, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.report).write_text(render_report(certificate), encoding="utf-8")
    print(json.dumps({"reachable": certificate["reachable_case"], "unreachable": certificate["unreachable_case"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

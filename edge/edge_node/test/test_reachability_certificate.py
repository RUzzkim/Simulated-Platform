import math
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "benchmarks")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from edge_node.fault.kinematics import DH_PARAMS, forward_kinematics
from validate_reachability import (
    build_certificate,
    certify_reachable_witness,
    locked_j0_error_lower_bound,
    j0_wrist_offset_bound,
    render_report,
)


def test_locked_j0_geometry_proves_target_outside_position_tolerance():
    target = [0.361938, -0.363366, 0.433349]
    certificate = locked_j0_error_lower_bound(target, -0.052781084, 0.2)
    assert math.isclose(certificate["tangential_target_m"], -0.3437658, abs_tol=1e-6)
    assert certificate["minimum_position_error_m"] > 0.05
    assert certificate["proven_unreachable"]


def test_fk_configuration_is_a_locked_joint_reachability_witness():
    witness_q = [0.028222729, 0.56493898, -0.257492593, -0.413681817, -2.302506024, 0.02266539]
    target_position = forward_kinematics([0.35, 0.55, -0.3, 0.2, -0.15, 0.1])[0]
    certificate = certify_reachable_witness(witness_q, target_position, 0, 0.028222729, 0.02)
    assert certificate["position_error_m"] <= 0.02
    assert certificate["locked_joint_error_rad"] == 0.0


def test_fk_configuration_is_rejected_when_faulted_joint_moves():
    witness_q = [0.03, 0.56493898, -0.257492593, -0.413681817, -2.302506024, 0.02266539]
    target_position = forward_kinematics([0.35, 0.55, -0.3, 0.2, -0.15, 0.1])[0]
    try:
        certify_reachable_witness(witness_q, target_position, 0, 0.028222729, 0.02)
    except ValueError as exc:
        assert "locked joint" in str(exc)
    else:
        raise AssertionError("a witness that moves the locked joint must be rejected")


def test_report_renders_fresh_benchmark_and_matched_controls(tmp_path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[3]
    summary_path = tmp_path / "summary.json"
    monkeypatch.chdir(repo_root)
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("benchmarks") / "run_task_recovery.py"),
            "--split", "validation",
            "--scenario", "VALIDATION-LOCK-J0#s1T1", "VALIDATION-LOCK-J0#s1T2",
            "--include-no-fault-controls",
            "--output-dir", str(tmp_path),
            "--json", str(summary_path),
        ],
        check=True,
    )
    certificate = build_certificate(summary_path)

    report = render_report(certificate)

    assert "None ms" not in report
    assert len(certificate["no_fault_controls"]) == 6
    assert all(not row["false_alarm_during_nominal"] for row in certificate["no_fault_controls"])
    undetected = [
        row for row in certificate["strategy_runs"]
        if row["fault_detection_latency_ms"] is None
    ]
    assert undetected


def test_dh_geometry_has_bounded_wrist_offset_for_locked_j0():
    assert math.isclose(j0_wrist_offset_bound(DH_PARAMS), 0.2)


def test_nonplanar_arm_geometry_invalidates_locked_j0_bound():
    changed = [list(row) for row in DH_PARAMS]
    changed[1][3] = 0.1

    try:
        j0_wrist_offset_bound(changed)
    except ValueError as exc:
        assert "radial-plane" in str(exc)
    else:
        raise AssertionError("changed shoulder twist must invalidate the planar bound")

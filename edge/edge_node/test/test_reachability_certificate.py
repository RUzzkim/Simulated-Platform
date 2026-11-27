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
    certificate = locked_j0_error_lower_bound(
        target, -0.052781084, j0_wrist_offset_bound(DH_PARAMS)
    )
    assert math.isclose(certificate["tangential_target_m"], -0.3437658, abs_tol=1e-6)
    assert math.isclose(
        certificate["minimum_position_error_m"], 0.2437658, abs_tol=1e-6
    )
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
    assert math.isclose(j0_wrist_offset_bound(DH_PARAMS), 0.1)


def test_base_dh_theta_offset_invalidates_locked_j0_angle_bound():
    changed = [list(row) for row in DH_PARAMS]
    changed[0][0] += 0.1

    try:
        j0_wrist_offset_bound(changed)
    except ValueError as exc:
        assert "base theta offset" in str(exc)
    else:
        raise AssertionError("a base theta offset must invalidate the unadjusted J0 angle bound")


def test_forward_kinematics_stays_within_the_locked_j0_wrist_offset_bound():
    locked_angles = (-0.49, -0.05, 0.30)
    healthy_joint_vectors = (
        (0.25, -0.40, 0.15, -2.10, 0.22),
        (-1.30, 1.05, 2.40, 0.35, -2.65),
        (2.20, -2.50, -1.80, 2.85, 1.60),
    )

    for locked_angle, healthy_angles in zip(locked_angles, healthy_joint_vectors):
        position, _ = forward_kinematics([locked_angle, *healthy_angles])
        tangential_position = (
            -math.sin(locked_angle) * position[0]
            + math.cos(locked_angle) * position[1]
        )
        assert abs(tangential_position) <= j0_wrist_offset_bound(DH_PARAMS) + 1e-12


def test_locked_j0_s3_t2_bound_identifies_infeasible_recovery_target():
    target = forward_kinematics([-0.6, 0.25, 0.45, -0.2, 0.3, -0.25])[0]
    offset_bound = j0_wrist_offset_bound(DH_PARAMS)

    certificate = locked_j0_error_lower_bound(target, -0.48851365, offset_bound)

    assert math.isclose(
        certificate["minimum_position_error_m"], 0.051001394, abs_tol=1e-9
    )
    assert certificate["minimum_position_error_m"] > certificate["position_tolerance_m"]
    assert certificate["proven_unreachable"]


def test_nonplanar_arm_geometry_invalidates_locked_j0_bound():
    for row_index in range(4):
        changed = [list(row) for row in DH_PARAMS]
        changed[row_index][3] += 0.1

        try:
            j0_wrist_offset_bound(changed)
        except ValueError as exc:
            assert "radial-plane" in str(exc)
        else:
            raise AssertionError(
                f"changed DH twist in row {row_index} must invalidate the planar bound"
            )

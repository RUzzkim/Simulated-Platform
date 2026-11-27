import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from edge_node.fault.kinematics import compute_pose
from edge_node.fault.recovery import RecoveryPlanner


def test_reachable_target_recovers_with_faulted_joint_locked():
    planner = RecoveryPlanner(position_tolerance=0.01, max_iterations=180)
    current = [0.1, -0.4, 0.5, 0.1, -0.2, 0.0]
    target = [0.2, -0.3, 0.4, 0.2, -0.1, 0.1]

    decision = planner.plan(current, [0.0] * 6, compute_pose(target), locked_joints=[0])

    assert decision.action == "RECOVER"
    assert decision.position_error <= planner.position_tolerance
    assert decision.target_q[0] == current[0]
    assert all(math.isfinite(value) for value in decision.target_q)


def test_unreachable_target_uses_safe_stop_target():
    planner = RecoveryPlanner(position_tolerance=0.005, max_iterations=80)
    current = [0.0, -0.4, 0.5, 0.0, -0.2, 0.0]
    unreachable_pose = [-0.8, 0.0, 0.4, 0.0, 0.0, 0.0]

    decision = planner.plan(current, [0.0] * 6, unreachable_pose, locked_joints=[0])

    assert decision.action == "STOP"
    assert decision.position_error > planner.position_tolerance
    assert decision.reason == "NO_FEASIBLE_PLAN"
    assert decision.target_q == current


def test_stop_target_brakes_using_velocity_and_holds_locked_joint():
    planner = RecoveryPlanner(max_deceleration=2.0)
    current = [0.0, -0.4, 0.5, 0.0, -0.2, 0.0]
    velocity = [0.0, 1.0, -2.0, 0.0, 0.0, 0.0]

    decision = planner.plan(current, velocity, [-0.8, 0.0, 0.4, 0.0, 0.0, 0.0], [0])

    assert decision.action == "STOP"
    assert decision.target_q[0] == current[0]
    assert decision.target_q[1] == current[1] + 0.25
    assert decision.target_q[2] == current[2] - 1.0


def test_invalid_locked_joint_index_is_rejected():
    planner = RecoveryPlanner()

    try:
        planner.plan([0.0] * 6, [0.0] * 6, [0.0] * 6, [-1])
    except ValueError as error:
        assert "locked joint" in str(error).lower()
    else:
        raise AssertionError("invalid fault joint should be rejected")


def test_recovery_search_uses_final_task_configuration_as_a_second_seed():
    planner = RecoveryPlanner(position_tolerance=0.02)
    goal = [0.8, 0.6, -0.5, 0.4, 0.3, 0.2]
    current = [0.8, 0.0, 0.0, 0.0, 0.0, 0.0]

    decision = planner.plan(
        current, [0.0] * 6, compute_pose(goal), [0], preferred_q=goal
    )

    assert decision.action == "RECOVER"
    assert decision.position_error <= planner.position_tolerance
    assert decision.target_q[0] == current[0]


def test_j0_geometric_unreachability_stops_before_numerical_search():
    planner = RecoveryPlanner()
    goal = [-0.6, 0.25, 0.45, -0.2, 0.3, -0.25]
    locked_j0 = -0.48851365
    current = [locked_j0, 0.2, -0.1, 0.3, 0.4, -0.2]
    target_pose = compute_pose(goal)

    def fail_if_search_starts(*_args, **_kwargs):
        raise AssertionError("a geometrically infeasible target should skip numerical search")

    planner._search_from_seed = fail_if_search_starts
    decision = planner.plan(
        current, [0.0] * 6, target_pose, locked_joints=[0], preferred_q=goal
    )

    assert decision.action == "STOP"
    assert decision.reason == "GEOMETRICALLY_UNREACHABLE"
    assert math.isclose(decision.position_error_lower_bound, 0.051001394, abs_tol=1e-9)
    assert decision.target_q == current


def test_j0_target_within_geometric_bound_still_uses_recovery_search():
    planner = RecoveryPlanner(max_iterations=1)
    goal = [0.35, 0.55, -0.3, 0.2, -0.15, 0.1]
    current = [goal[0], -0.4, 0.5, 0.1, -0.2, 0.0]

    decision = planner.plan(
        current, [0.0] * 6, compute_pose(goal), locked_joints=[0], preferred_q=goal
    )

    assert decision.reason != "GEOMETRICALLY_UNREACHABLE"
    assert decision.position_error_lower_bound <= 0.05


def test_j0_t2_fault_positions_are_classified_by_the_geometric_lower_bound():
    planner = RecoveryPlanner()
    goal = [-0.6, 0.25, 0.45, -0.2, 0.3, -0.25]
    target_pose = compute_pose(goal)
    lock_angles = (
        (-0.052781084, 0.243765786),
        (-0.259676353, 0.158249857),
        (-0.488513650, 0.051001394),
    )

    for locked_j0, expected_lower_bound in lock_angles:
        current = [locked_j0, 0.2, -0.1, 0.3, 0.4, -0.2]
        decision = planner.plan(
            current, [0.0] * 6, target_pose, locked_joints=[0], preferred_q=goal
        )

        assert decision.action == "STOP"
        assert decision.reason == "GEOMETRICALLY_UNREACHABLE"
        assert math.isclose(
            decision.position_error_lower_bound,
            expected_lower_bound,
            abs_tol=1e-9,
        )


def test_modified_dh_geometry_disables_j0_geometric_shortcut(monkeypatch):
    import edge_node.fault.recovery as recovery

    changed = [list(row) for row in recovery.DH_PARAMS]
    changed[3][3] += 0.1
    monkeypatch.setattr(recovery, "DH_PARAMS", changed)
    planner = RecoveryPlanner(max_iterations=1)
    goal = [-0.6, 0.25, 0.45, -0.2, 0.3, -0.25]
    current = [-0.48851365, 0.2, -0.1, 0.3, 0.4, -0.2]

    decision = planner.plan(
        current, [0.0] * 6, compute_pose(goal), locked_joints=[0], preferred_q=goal
    )

    assert decision.position_error_lower_bound is None


def test_base_theta_offset_disables_j0_geometric_shortcut(monkeypatch):
    import edge_node.fault.recovery as recovery

    changed = [list(row) for row in recovery.DH_PARAMS]
    changed[0][0] += 0.1
    monkeypatch.setattr(recovery, "DH_PARAMS", changed)
    planner = RecoveryPlanner(max_iterations=1)
    goal = [-0.6, 0.25, 0.45, -0.2, 0.3, -0.25]
    current = [-0.48851365, 0.2, -0.1, 0.3, 0.4, -0.2]

    decision = planner.plan(
        current, [0.0] * 6, compute_pose(goal), locked_joints=[0], preferred_q=goal
    )

    assert decision.position_error_lower_bound is None


def test_non_j0_joint_lock_does_not_use_j0_geometric_bound():
    planner = RecoveryPlanner()
    goal = [0.35, 0.55, -0.3, 0.2, -0.15, 0.1]
    current = [0.0, goal[1], -0.4, 0.1, -0.2, 0.0]

    decision = planner.plan(
        current, [0.0] * 6, compute_pose(goal), locked_joints=[1], preferred_q=goal
    )

    assert decision.action == "RECOVER"
    assert decision.position_error_lower_bound is None

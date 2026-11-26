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

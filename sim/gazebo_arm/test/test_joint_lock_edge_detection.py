import math
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "edge", "edge_node")),
)

from edge_node.fault.detector import CompositeFaultDetector
from edge_node.fault.tolerant import FaultTolerantController
from edge_node.model.messages import (
    FAULT_JOINT_LOCKED,
    ROBOT_STATUS_RUNNING,
    RobotState,
)
from edge_node.fault.kinematics import forward_kinematics
from edge_node.processor.signal_filter import RobotSignalFilter
from gazebo_arm.plant import RealtimePlant, configure_joint_lock


def _edge_signal_filter():
    return RobotSignalFilter(
        window_size=3,
        outlier_k=3.5,
        alpha_position=0.8,
        alpha_velocity=0.5,
        alpha_effort=0.5,
        min_sigma_position=0.002,
        min_sigma_velocity=0.01,
        min_sigma_effort=0.1,
    )


def test_simulated_joint_lock_is_detected_and_held_by_edge_controller():
    home = [0.0, 0.35, -0.72, 0.2, 0.0, 0.0]
    plant = RealtimePlant(home)
    configure_joint_lock(plant.faults, True, 2, 0.5, 12.5)
    plant.set_target([0.5, 0.85, -1.05, 0.45, 0.3, 0.4])

    detector = CompositeFaultDetector(window_size=20, persistence=5)
    controller = FaultTolerantController(active_replanning=False)
    signal_filter = _edge_signal_filter()
    first_timestamp = int(time.time() * 1000)
    detected_fault = None

    for tick in range(150):
        plant.step(0.01)
        position, velocity, torque = plant.state()
        position, velocity, torque, _ = signal_filter.filter(position, velocity, torque)
        state = RobotState(
            simulation_id="SIM-001",
            robot_id="ROBOT-001",
            timestamp=first_timestamp + tick * 10,
            joint_position=position,
            joint_velocity=velocity,
            joint_torque=torque,
            status=ROBOT_STATUS_RUNNING,
        )
        detected_fault = detector.detect_event(state)
        if detected_fault is not None:
            break

    assert detected_fault is not None
    assert detected_fault.fault_type == FAULT_JOINT_LOCKED
    assert detected_fault.joint_index == 1

    controller.update_fault(detected_fault)
    safe_target = controller.compensate(state, [0.8] * 6)

    assert safe_target[1] == position[1]
    assert safe_target != [0.8] * 6


def test_detected_lock_can_recover_reachable_target_or_stop_safely():
    detector = CompositeFaultDetector(window_size=20, persistence=5)
    signal_filter = _edge_signal_filter()
    home = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    timestamp = int(time.time() * 1000)
    detected_fault = None

    for tick in range(30):
        position, velocity, torque, _ = signal_filter.filter(
            list(home), [0.0] * 6, [0.0, 12.5, 0.0, 0.0, 0.0, 0.0],
        )
        state = RobotState(
            simulation_id="SIM-001",
            robot_id="ROBOT-001",
            timestamp=timestamp + tick * 10,
            joint_position=position,
            joint_velocity=velocity,
            joint_torque=torque,
            status=ROBOT_STATUS_RUNNING,
        )
        detected_fault = detector.detect_event(state)

    assert detected_fault is not None
    assert detected_fault.fault_type == FAULT_JOINT_LOCKED
    assert detected_fault.joint_index == 1

    reachable = FaultTolerantController(task_recovery=True, recovery_tolerance=0.005)
    reachable.update_fault(detected_fault)
    recover_target = [0.2, -0.1, 0.8, 0.0, -0.2, 0.0]
    reachable.compensate(state, home, task_goal=recover_target)
    assert reachable.last_recovery_decision.action == "RECOVER"

    unreachable = FaultTolerantController(task_recovery=True, recovery_tolerance=0.005)
    unreachable.update_fault(detected_fault)
    stop_target = [0.0, 3.141592653589793, 0.0, 0.0, 0.0, 0.0]
    unreachable.compensate(state, home, task_goal=stop_target)
    assert unreachable.last_recovery_decision.action == "STOP"


@pytest.mark.parametrize(
    "goal,expected_action",
    [
        ([0.2, -0.1, 0.8, 0.0, -0.2, 0.0], "RECOVER"),
        ([-1.106891, -2.193779, 0.948349, -2.686462, 0.225453, -0.843902], "STOP"),
    ],
)
def test_plant_handles_reachable_and_unreachable_targets_after_joint_lock(goal, expected_action):
    home = [0.0, 0.35, -0.72, 0.2, 0.0, 0.0]
    plant = RealtimePlant(home)
    configure_joint_lock(
        plant.faults, True, 2, 1.0, 12.5, after_first_command=True,
    )
    plant.set_target(goal)

    detector = CompositeFaultDetector(window_size=20, persistence=5)
    signal_filter = _edge_signal_filter()
    controller = FaultTolerantController(
        task_recovery=True,
        recovery_tolerance=0.005,
        control_dt=0.01,
        recovery_max_velocity=1.0,
        recovery_max_acceleration=2.0,
    )
    first_timestamp = int(time.time() * 1000)
    goal_position = None
    detected_joint_lock = False
    lock_position = None
    state = None

    for tick in range(800):
        plant.step(0.01)
        position, velocity, torque = plant.state()
        position, velocity, torque, _ = signal_filter.filter(position, velocity, torque)
        state = RobotState(
            simulation_id="SIM-001",
            robot_id="ROBOT-001",
            timestamp=first_timestamp + tick * 10,
            joint_position=position,
            joint_velocity=velocity,
            joint_torque=torque,
            status=ROBOT_STATUS_RUNNING,
        )
        fault = detector.detect_event(state)
        if fault is not None:
            detected_joint_lock = detected_joint_lock or fault.fault_type == FAULT_JOINT_LOCKED
            controller.update_fault(fault)
            if fault.fault_type == FAULT_JOINT_LOCKED and goal_position is None:
                goal_position, _ = forward_kinematics(goal)
                lock_position = plant.q[1]
        target = controller.compensate(state, goal, task_goal=goal) if detected_joint_lock else goal
        plant.set_target(target)

    final_position, _, _ = plant.state()
    final_end_effector_position, _ = forward_kinematics(final_position)

    assert detected_joint_lock
    assert controller.last_recovery_decision.action == expected_action
    assert lock_position is not None
    assert math.isclose(final_position[1], lock_position, abs_tol=1e-9)
    if expected_action == "RECOVER":
        assert math.dist(final_end_effector_position, goal_position) <= 0.005
    else:
        assert math.dist(final_end_effector_position, goal_position) > 0.02

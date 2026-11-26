import math
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gazebo_arm.plant import RealtimePlant, configure_joint_lock, parse_joint_positions


def test_parse_joint_positions_accepts_six_comma_separated_radians():
    positions = parse_joint_positions("0, 0.35, -0.72, 0.20, 0, 0")

    assert positions == [0.0, 0.35, -0.72, 0.2, 0.0, 0.0]


@pytest.mark.parametrize(
    "value",
    ["0, 0.1", "0, 0, 0, 0, 0, nan", "0, 0, 0, 0, 0, invalid"],
)
def test_parse_joint_positions_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        parse_joint_positions(value)


def test_configure_joint_lock_uses_one_based_arm_joint_number():
    plant = RealtimePlant([0.0] * 6)

    configure_joint_lock(plant.faults, True, 6, 0.5, 12.5)

    assert plant.faults.joint_lock_index == 5
    assert plant.faults.joint_lock_onset_s == 0.5
    assert plant.faults.joint_lock_reaction_torque_nm == 12.5


@pytest.mark.parametrize("joint_number", [0, 7, 2.5, True])
def test_configure_joint_lock_rejects_invalid_one_based_joint_number(joint_number):
    plant = RealtimePlant([0.0] * 6)

    with pytest.raises(ValueError):
        configure_joint_lock(plant.faults, True, joint_number, 0.0, 12.5)


def test_joint_lock_freezes_configured_joint_and_reports_reaction_torque():
    home = [0.0, 0.35, -0.72, 0.2, 0.0, 0.0]
    plant = RealtimePlant(home)
    plant.faults.configure_joint_lock(
        enabled=True, joint_index=0, onset_s=0.5, reaction_torque_nm=12.5,
    )
    plant.set_target([0.5, 0.85, -1.05, 0.45, 0.3, 0.4])

    for _ in range(40):
        plant.step(0.01)
    assert plant.faults._joint_lock_position is None

    for _ in range(60):
        plant.step(0.01)
    lock_position = plant.q[0]
    assert lock_position > home[0]

    plant.set_target([-0.6, 0.25, 0.45, -0.2, 0.3, -0.25])
    for _ in range(200):
        plant.step(0.01)

    q, qd, tau = plant.state()
    assert math.isclose(q[0], lock_position, abs_tol=1e-10)
    assert qd[0] == 0.0
    assert tau[0] == 12.5
    assert any(abs(q[index] - home[index]) > 0.05 for index in range(1, 6))


def test_joint_lock_is_disabled_by_default():
    plant = RealtimePlant([0.0, 0.35, -0.72, 0.2, 0.0, 0.0])
    plant.set_target([0.5, 0.35, -0.72, 0.2, 0.0, 0.0])

    for _ in range(100):
        plant.step(0.01)

    assert plant.q[0] > 0.1


def test_command_relative_lock_waits_for_motion_target_and_does_not_rearm():
    home = [0.0] * 6
    target = [0.1, 0.5, 0.0, 0.0, 0.0, 0.0]
    plant = RealtimePlant(home)
    configure_joint_lock(plant.faults, True, 2, 0.3, 12.5, after_first_command=True)

    plant.set_target(home)
    for _ in range(100):
        plant.step(0.01)
    assert plant.state()[2][1] != 12.5

    for _ in range(29):
        plant.set_target(target)
        plant.step(0.01)
    assert plant.state()[2][1] != 12.5

    plant.set_target(target)
    plant.step(0.01)
    q, qd, effort = plant.state()
    assert q[1] > 0.0
    assert qd[1] == 0.0
    assert effort[1] == 12.5


def test_joint_lock_captures_position_at_activation_boundary():
    target = [0.2, 0.5, 0.0, 0.0, 0.0, 0.0]
    baseline = RealtimePlant([0.0] * 6)
    locked = RealtimePlant([0.0] * 6)
    configure_joint_lock(locked.faults, True, 2, 0.3, 12.5)
    for plant in (baseline, locked):
        plant.set_target(target)
        for _ in range(30):
            plant.step(0.01)

    q, qd, effort = locked.state()
    assert q[1] == baseline.q[1]
    assert qd[1] == 0.0
    assert effort[1] == 12.5
    assert locked.tau == baseline.tau


@pytest.mark.parametrize(
    "joint_index,onset_s,reaction_torque_nm",
    [
        (-1, 0.0, 12.5), (6, 0.0, 12.5), (1, -0.1, 12.5),
        (1, 0.0, 0.0), (1, math.nan, 12.5), (1, 0.0, math.inf),
    ],
)
def test_joint_lock_rejects_invalid_configuration(joint_index, onset_s, reaction_torque_nm):
    plant = RealtimePlant([0.0] * 6)

    with pytest.raises(ValueError):
        plant.faults.configure_joint_lock(
            enabled=True, joint_index=joint_index, onset_s=onset_s,
            reaction_torque_nm=reaction_torque_nm,
        )

"""A fixed-step lock and B's timed detection lock are mutually exclusive."""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gazebo_arm.plant import RealtimePlant, configure_joint_lock


@pytest.mark.parametrize("a_first", [True, False])
def test_rejects_enabling_both_lock_modes(a_first):
    plant = RealtimePlant([0.0] * 6)
    if a_first:
        plant.lock_joint(1)
    configure_joint_lock(plant.faults, True, 2, 0.30, 12.5)
    with pytest.raises(ValueError, match="fault_lock_joint.*fault_joint_lock"):
        if a_first:
            plant.step(0.01)
        else:
            plant.lock_joint(1)

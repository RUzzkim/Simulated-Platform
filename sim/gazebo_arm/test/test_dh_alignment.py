"""Check the exported arm against the numerical twin's standard DH frames."""

import math
from pathlib import Path
import sys
import unittest

import numpy as np

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))
sys.path.insert(0, str(PACKAGE_ROOT.parent / "hydraulic-arm" / "python_twin"))

import hydraulic_arm_twin as twin
from gazebo_arm.end_effector import EndEffector, rotation
from gazebo_arm.scenarios import HOME


class DhAlignmentTest(unittest.TestCase):
    def test_urdf_pose_matches_numerical_twin(self):
        arm = EndEffector(PACKAGE_ROOT / "urdf" / "hydraulic_arm.urdf")
        poses = [[0.0] * 6, HOME]
        poses.extend([[math.pi / 4 if j == i else 0.0 for j in range(6)] for i in range(6)])
        for angles in poses:
            with self.subTest(angles=angles):
                expected_position = np.zeros(3)
                expected_orientation = np.eye(3)
                for i in range(6):
                    orientation, translation = twin._dh_frame(i, angles, twin.PARAMS)
                    expected_position += expected_orientation @ translation
                    expected_orientation = expected_orientation @ orientation
                pose = arm.pose(angles)
                np.testing.assert_allclose(pose[:3], expected_position, atol=1e-12, rtol=0)
                np.testing.assert_allclose(rotation(*pose[3:]), expected_orientation, atol=1e-12, rtol=0)

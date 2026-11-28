"""Forward kinematics for the six-joint hydraulic arm URDF."""

import math
import xml.etree.ElementTree as ET
from pathlib import Path


JOINT_NAMES = tuple(f"joint_{index}" for index in range(1, 7))
POSE_FIELDS = ("ee_x_m", "ee_y_m", "ee_z_m", "ee_roll_rad", "ee_pitch_rad", "ee_yaw_rad")


def rotation(roll, pitch, yaw):
    """URDF fixed-axis roll, pitch, yaw: Rz(yaw) Ry(pitch) Rx(roll)."""
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    return [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ]


def multiply(left, right):
    return [[sum(a * b for a, b in zip(row, col)) for col in zip(*right)] for row in left]


class EndEffector:
    """Pose of link_6 relative to base_link, using the URDF joint chain."""

    def __init__(self, urdf: Path):
        joints = {joint.find("child").attrib["link"]: joint for joint in ET.parse(urdf).getroot().findall("joint")}
        chain = []
        child = "link_6"
        while child != "base_link":
            joint = joints.pop(child)
            chain.append(joint)
            child = joint.find("parent").attrib["link"]
        self.origins = []
        self.limits = []
        names = []
        for joint in reversed(chain):
            kind = joint.attrib["type"]
            if kind == "revolute":
                if tuple(map(float, joint.find("axis").attrib["xyz"].split())) != (0, 0, 1):
                    raise ValueError(f"Expected local Z joint axis in {urdf}: {joint.attrib['name']}")
                names.append(joint.attrib["name"])
                limit = joint.find("limit").attrib
                self.limits.append((float(limit["lower"]), float(limit["upper"])))
            elif kind != "fixed":
                raise ValueError(f"Unexpected joint type in {urdf}: {kind}")
            origin = joint.find("origin").attrib
            xyz = tuple(map(float, origin.get("xyz", "0 0 0").split()))
            rpy = tuple(map(float, origin.get("rpy", "0 0 0").split()))
            self.origins.append((xyz, rotation(*rpy), kind == "revolute"))
        if tuple(names) != JOINT_NAMES:
            raise ValueError(f"Expected six ordered revolute joints in {urdf}: {names}")

    def pose(self, angles):
        if len(angles) != len(JOINT_NAMES):
            raise ValueError("End-effector pose requires six joint angles")
        orientation = rotation(0, 0, 0)
        position = [0.0, 0.0, 0.0]
        angles = iter(angles)
        for xyz, origin_rotation, revolute in self.origins:
            for index, row in enumerate(orientation):
                position[index] += sum(a * b for a, b in zip(row, xyz))
            orientation = multiply(orientation, origin_rotation)
            if revolute:
                orientation = multiply(orientation, rotation(0, 0, next(angles)))
        horizontal = math.hypot(orientation[0][0], orientation[1][0])
        pitch = math.atan2(-orientation[2][0], horizontal)
        if horizontal < 1e-10:
            roll = 0.0
            yaw = math.atan2(-orientation[0][1], orientation[1][1])
        else:
            roll = math.atan2(orientation[2][1], orientation[2][2])
            yaw = math.atan2(orientation[1][0], orientation[0][0])
        return (*position, roll, pitch, yaw)

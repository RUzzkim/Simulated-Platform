"""滑动窗口历史追踪工具

用于故障检测中对最近 N 帧关节状态做统计分析，
如检测关节卡死（位置变化量）、持续力矩过载等。
"""
from __future__ import annotations

import math
from collections import deque
from typing import Deque, List, Optional

from edge_node.model.messages import RobotState


class JointHistoryWindow:
    """单关节滑动窗口：缓存最近 N 帧的 position / velocity / torque"""

    def __init__(self, size: int):
        self.size = int(size)
        self.positions: Deque[float] = deque(maxlen=size)
        self.velocities: Deque[float] = deque(maxlen=size)
        self.torques: Deque[float] = deque(maxlen=size)

    def push(self, position: float, velocity: float, torque: float) -> None:
        self.positions.append(float(position))
        self.velocities.append(float(velocity))
        self.torques.append(float(torque))

    def __len__(self) -> int:
        return len(self.positions)

    @property
    def full(self) -> bool:
        return len(self.positions) >= self.size

    def position_range(self) -> float:
        """窗口内位置极差（max - min）"""
        if not self.positions:
            return 0.0
        return max(self.positions) - min(self.positions)

    def avg_abs_torque(self) -> float:
        """窗口内平均绝对力矩"""
        if not self.torques:
            return 0.0
        return sum(abs(t) for t in self.torques) / len(self.torques)

    def avg_abs_velocity(self) -> float:
        """窗口内平均绝对速度"""
        if not self.velocities:
            return 0.0
        return sum(abs(v) for v in self.velocities) / len(self.velocities)

    def clear(self) -> None:
        self.positions.clear()
        self.velocities.clear()
        self.torques.clear()


class StateHistoryWindow:
    """多关节滑动窗口管理器"""

    def __init__(self, n_joints: int, size: int):
        self.n_joints = n_joints
        self.joints: List[JointHistoryWindow] = [
            JointHistoryWindow(size) for _ in range(n_joints)
        ]
        self._last_timestamp_ms: Optional[int] = None

    def push(self, state: RobotState) -> None:
        for i in range(self.n_joints):
            self.joints[i].push(
                state.joint_position[i],
                state.joint_velocity[i],
                state.joint_torque[i],
            )
        self._last_timestamp_ms = state.timestamp

    @property
    def last_timestamp_ms(self) -> Optional[int]:
        return self._last_timestamp_ms

    def elapsed_since_last(self, now_ms: int) -> Optional[int]:
        """距上次状态更新的毫秒数"""
        if self._last_timestamp_ms is None:
            return None
        return now_ms - self._last_timestamp_ms

    def full(self) -> bool:
        return all(j.full for j in self.joints)

    def clear(self) -> None:
        for j in self.joints:
            j.clear()
        self._last_timestamp_ms = None

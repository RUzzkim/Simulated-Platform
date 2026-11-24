"""主动容错轨迹重规划器

当关节发生故障（卡死/传感器失效）时，利用剩余健康关节重规划目标，
使末端执行器仍尽量跟踪期望位姿。

核心算法：
  1. 正运动学计算当前末端位姿
  2. 计算任务空间误差 dx = x_desired - x_current
  3. 阻尼最小二乘（DLS）逆解，仅对健康关节列求解
  4. 叠加关节修正量，故障关节保持当前位置

与被动容错（FaultTolerantController）的区别：
  - 被动：故障关节保持，健康关节仍按原目标运动
  - 主动：故障关节保持，健康关节目标被重规划以补偿末端误差
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence

from edge_node.fault.kinematics import (
    compute_jacobian,
    compute_pose,
    dls_inverse,
)


class TrajectoryReplanner:
    """主动容错轨迹重规划器

    :param n_joints: 关节数
    :param damping: DLS 阻尼系数 λ
    :param step_size: 单步修正步长（0~1），越大越激进
    :param max_joint_step: 单关节单步最大变化量（rad），防止跳变
    :param joint_limits: 关节限位 [min, max] 列表，None 表示不限
    :param task_weights: 6D 任务空间权重 [x, y, z, rx, ry, rz]，None 表示等权
    """

    def __init__(
        self,
        n_joints: int = 6,
        damping: float = 0.05,
        step_size: float = 0.5,
        max_joint_step: float = 0.2,
        joint_limits: Optional[List[List[float]]] = None,
        task_weights: Optional[List[float]] = None,
    ):
        self.n_joints = n_joints
        self.damping = float(damping)
        self.step_size = float(step_size)
        self.max_joint_step = float(max_joint_step)
        self.joint_limits = joint_limits
        self.task_weights = task_weights or [1.0, 1.0, 1.0, 0.5, 0.5, 0.5]

    def _apply_weights(self, dx: List[float]) -> List[float]:
        return [dx[i] * self.task_weights[i] for i in range(6)]

    def _clamp_joint(self, idx: int, value: float) -> float:
        """关节限位钳制"""
        if self.joint_limits is not None and idx < len(self.joint_limits):
            lo, hi = self.joint_limits[idx]
            value = max(lo, min(hi, value))
        return value

    def replan(
        self,
        current_q: Sequence[float],
        desired_pose: Sequence[float],
        locked_joints: Optional[Sequence[int]] = None,
    ) -> List[float]:
        """重规划关节目标

        :param current_q: 当前关节位置
        :param desired_pose: 期望末端 6D 位姿 [x, y, z, roll, pitch, yaw]
        :param locked_joints: 锁定关节索引集合，这些关节保持 current_q 不变
        :return: 重规划后的关节目标（长度 = n_joints）
        """
        q = list(current_q)
        locked = set(locked_joints or [])

        # 1. 当前末端位姿
        current_pose = compute_pose(q)

        # 2. 任务空间误差
        dx = [desired_pose[i] - current_pose[i] for i in range(6)]
        dx = self._apply_weights(dx)

        # 误差很小时直接返回（避免抖动）
        err_norm = math.sqrt(sum(d * d for d in dx))
        if err_norm < 1e-6:
            return list(q)

        # 3. 雅可比
        J = compute_jacobian(q)

        # 4. DLS 逆解（锁定关节列被排除）
        dq = dls_inverse(J, dx, damping=self.damping, locked_joints=locked)

        # 5. 叠加修正量
        new_q = list(q)
        for i in range(self.n_joints):
            if i in locked:
                continue
            delta = dq[i] * self.step_size
            # 单步限幅
            if abs(delta) > self.max_joint_step:
                delta = math.copysign(self.max_joint_step, delta)
            new_q[i] = q[i] + delta
            new_q[i] = self._clamp_joint(i, new_q[i])

        return new_q

    def replan_from_target(
        self,
        current_q: Sequence[float],
        raw_target_q: Sequence[float],
        locked_joints: Optional[Sequence[int]] = None,
    ) -> List[float]:
        """从原始关节目标重规划（先将目标转为期望位姿，再求解）

        :param current_q: 当前关节位置
        :param raw_target_q: 原始目标关节位置（健康关节的期望）
        :param locked_joints: 锁定关节索引集合
        :return: 重规划后的关节目标
        """
        # 用原始目标的末端位姿作为期望
        desired_pose = compute_pose(raw_target_q)
        return self.replan(current_q, desired_pose, locked_joints)

    def end_effector_error(
        self,
        current_q: Sequence[float],
        desired_pose: Sequence[float],
    ) -> List[float]:
        """计算当前关节位置到期望位姿的任务空间误差"""
        current_pose = compute_pose(current_q)
        return [desired_pose[i] - current_pose[i] for i in range(6)]

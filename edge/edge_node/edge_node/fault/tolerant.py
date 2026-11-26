"""容错控制模块

在基础控制器输出目标位置后、发布到 ROS 2 之前，对目标做安全补偿。

补偿策略（按故障类型）：
  - JOINT_LOCKED        : 锁定关节保持当前位置（不与卡死力矩对抗）
  - SENSOR_INVALID      : 保持最后已知有效位置（传感器不可信，开环保持）
  - TORQUE_OVERLOAD     : 按比例缩小该关节的位置误差，降低力矩需求
  - VELOCITY_ANOMALY    : 对目标位置做变化率限幅（限速）
  - COMMUNICATION_TIMEOUT : 冻结控制（保持上次输出目标）

主动容错（active_replanning=True）：
  当有关节被锁定（卡死/传感器失效）时，利用剩余健康关节重规划目标，
  使末端执行器仍尽量跟踪期望位姿（DLS 逆运动学 + 关节锁定约束）。

故障状态维护：
  - 每个关节独立追踪当前激活的故障类型
  - 传感器无效时记录最后已知有效位置
  - 连续 recovery_frames 无故障则自动恢复
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Set

from edge_node.fault.replanner import TrajectoryReplanner
from edge_node.fault.recovery import RecoveryDecision, RecoveryPlanner
from edge_node.model.messages import (
    FAULT_COMM_TIMEOUT,
    FAULT_JOINT_LOCKED,
    FAULT_SENSOR_INVALID,
    FAULT_TORQUE_OVERLOAD,
    FAULT_VELOCITY_ANOMALY,
    FaultEvent,
    RobotState,
)


class FaultTolerantController:
    """容错控制器：对基础控制器输出做故障安全补偿

    :param n_joints: 关节数
    :param torque_overload_scale: 力矩过载时位置误差缩放系数（0~1），越小越保守
    :param velocity_clamp: 速度异常关节的单步最大位置变化量（rad）
    :param recovery_frames: 连续无故障帧数阈值，超过则该关节恢复正常控制
    :param active_replanning: 是否启用主动容错轨迹重规划
    :param replanning_damping: DLS 阻尼系数 λ
    :param replanning_step: 重规划单步修正步长（0~1）
    """

    def __init__(
        self,
        n_joints: int = 6,
        torque_overload_scale: float = 0.3,
        velocity_clamp: float = 0.05,
        recovery_frames: int = 10,
        active_replanning: bool = True,
        replanning_damping: float = 0.05,
        replanning_step: float = 0.5,
        task_recovery: bool = False,
        recovery_tolerance: float = 0.02,
        recovery_max_iterations: int = 160,
        recovery_max_deceleration: float = 2.0,
        control_dt: float = 0.01,
        recovery_max_velocity: float = 1.0,
        recovery_max_acceleration: float = 2.0,
    ):
        self.n_joints = n_joints
        self.torque_overload_scale = float(torque_overload_scale)
        self.velocity_clamp = float(velocity_clamp)
        self.recovery_frames = int(recovery_frames)
        self.active_replanning = bool(active_replanning)
        self.task_recovery = bool(task_recovery)
        if control_dt <= 0 or recovery_max_velocity <= 0 or recovery_max_acceleration <= 0:
            raise ValueError("recovery trajectory limits must be positive")
        self.control_dt = float(control_dt)
        self.recovery_max_velocity = float(recovery_max_velocity)
        self.recovery_max_acceleration = float(recovery_max_acceleration)
        self._recovery_planner: Optional[RecoveryPlanner] = (
            RecoveryPlanner(
                position_tolerance=recovery_tolerance,
                max_iterations=recovery_max_iterations,
                max_deceleration=recovery_max_deceleration,
            )
            if self.task_recovery else None
        )
        self._last_recovery_decision: Optional[RecoveryDecision] = None
        self._last_task_goal: Optional[List[float]] = None
        self._recovery_command: Optional[List[float]] = None
        self._recovery_velocity: List[float] = [0.0] * n_joints
        self._stuck_joints: Set[int] = set()

        # 主动容错轨迹重规划器
        self._replanner: Optional[TrajectoryReplanner] = None
        if self.active_replanning:
            self._replanner = TrajectoryReplanner(
                n_joints=n_joints,
                damping=replanning_damping,
                step_size=replanning_step,
            )

        # 每关节当前激活的故障类型集合
        self._active_faults: Dict[int, Set[str]] = {i: set() for i in range(n_joints)}
        # 每关节最后已知有效位置（传感器失效时用）
        self._last_good_position: Dict[int, float] = {i: 0.0 for i in range(n_joints)}
        # 每关节连续无故障帧数（用于恢复判定）
        self._clean_frames: Dict[int, int] = {i: 0 for i in range(n_joints)}
        # 上次输出的目标位置（通信超时时保持）
        self._last_target: Optional[List[float]] = None
        # 是否处于通信超时状态
        self._comm_timeout: bool = False

    # ---- 故障状态更新 ----

    def update_fault(self, fault: Optional[FaultEvent]) -> None:
        """根据最新故障事件更新内部故障状态"""
        if fault is None:
            # 无故障：所有关节累计 clean frames，达到阈值则清除故障
            for i in range(self.n_joints):
                self._clean_frames[i] += 1
                if self._clean_frames[i] >= self.recovery_frames:
                    self._active_faults[i].clear()
            self._comm_timeout = False
            return

        self._comm_timeout = (fault.fault_type == FAULT_COMM_TIMEOUT)

        if fault.fault_type == FAULT_COMM_TIMEOUT:
            # 通信超时是全局故障，不针对特定关节
            return

        joint = fault.joint_index
        if not (0 <= joint < self.n_joints):
            return

        self._active_faults[joint].add(fault.fault_type)
        if self.task_recovery and fault.fault_type == FAULT_JOINT_LOCKED:
            if joint not in self._stuck_joints and self._last_recovery_decision is not None:
                if self._last_recovery_decision.action == 'RECOVER':
                    self._last_recovery_decision = None
            self._stuck_joints.add(joint)
        self._clean_frames[joint] = 0

        # 传感器无效时记录当前位置为最后已知有效位置
        if fault.fault_type == FAULT_SENSOR_INVALID:
            pass  # 位置在 compensate 时从 state 取（仅对未失效关节）

    def record_valid_position(self, state: RobotState) -> None:
        """在传感器有效的帧，更新最后已知有效位置"""
        for i in range(self.n_joints):
            if FAULT_SENSOR_INVALID not in self._active_faults[i]:
                p = state.joint_position[i]
                try:
                    if not math.isnan(float(p)):
                        self._last_good_position[i] = float(p)
                except (TypeError, ValueError):
                    pass

    # ---- 补偿计算 ----

    def compensate(
        self,
        state: RobotState,
        raw_target: List[float],
        task_goal: Optional[List[float]] = None,
    ) -> List[float]:
        """对基础控制器输出的目标位置做故障安全补偿

        :param state: 当前机械臂状态
        :param raw_target: 基础控制器输出的原始目标关节位置
        :return: 补偿后的安全目标关节位置
        """
        # 先记录有效位置（传感器正常的关节）
        self.record_valid_position(state)

        # 通信超时：冻结输出
        if self._comm_timeout:
            if self._last_target is not None:
                return list(self._last_target)
            return list(raw_target)

        q = state.joint_position
        locked = self._locked_joints()

        normalized_goal = list(task_goal) if task_goal is not None else None
        if (
            self._last_recovery_decision is not None
            and self._last_recovery_decision.action == 'RECOVER'
            and normalized_goal is not None
            and normalized_goal != self._last_task_goal
        ):
            self._last_recovery_decision = None

        if self._last_recovery_decision is not None:
            self._last_target = self._next_recovery_command(q)
            return list(self._last_target)

        if (
            self._recovery_planner is not None
            and self._stuck_joints
        ):
            decision = self._recovery_planner.plan(
                current_q=q,
                current_qd=state.joint_velocity,
                target_pose=self._recovery_planner.target_pose(
                    normalized_goal if normalized_goal is not None else raw_target
                ),
                locked_joints=sorted(self._stuck_joints),
                preferred_q=normalized_goal,
            )
            self._last_recovery_decision = decision
            self._last_task_goal = normalized_goal
            self._recovery_command = list(q)
            self._recovery_velocity = [0.0] * self.n_joints
            self._last_target = self._next_recovery_command(q)
            return list(self._last_target)

        # 主动容错：有关节锁定时，重规划健康关节目标以补偿末端误差
        if locked and self._replanner is not None:
            try:
                replanned = self._replanner.replan_from_target(
                    current_q=q,
                    raw_target_q=raw_target,
                    locked_joints=locked,
                )
                safe_target = list(replanned)
            except Exception:
                # 运动学求解失败时回退到被动补偿
                safe_target = self._passive_compensate(q, raw_target)
        else:
            safe_target = self._passive_compensate(q, raw_target)

        self._last_target = list(safe_target)
        return safe_target

    def _next_recovery_command(self, current_q: List[float]) -> List[float]:
        decision = self._last_recovery_decision
        if decision is None or decision.action != 'RECOVER':
            return list(decision.target_q) if decision is not None else list(current_q)

        if self._recovery_command is None:
            self._recovery_command = list(current_q)
            self._recovery_velocity = [0.0] * self.n_joints

        next_command = list(self._recovery_command)
        next_velocity = list(self._recovery_velocity)
        max_velocity_step = self.recovery_max_acceleration * self.control_dt
        for index, target in enumerate(decision.target_q):
            if index in self._stuck_joints:
                next_command[index] = current_q[index]
                next_velocity[index] = 0.0
                continue
            distance = target - self._recovery_command[index]
            stopping_velocity = math.sqrt(
                2.0 * self.recovery_max_acceleration * abs(distance)
            )
            desired_velocity = math.copysign(
                min(self.recovery_max_velocity, stopping_velocity), distance
            ) if abs(distance) > 1e-12 else 0.0
            velocity_change = max(
                -max_velocity_step,
                min(max_velocity_step, desired_velocity - self._recovery_velocity[index]),
            )
            next_velocity[index] = self._recovery_velocity[index] + velocity_change
            next_command[index] = self._recovery_command[index] + next_velocity[index] * self.control_dt

        self._recovery_command = next_command
        self._recovery_velocity = next_velocity
        return list(next_command)

    def _locked_joints(self) -> List[int]:
        """返回当前被锁定的关节索引（卡死或传感器失效）"""
        locked = []
        for i in range(self.n_joints):
            faults = self._active_faults[i]
            if FAULT_JOINT_LOCKED in faults or FAULT_SENSOR_INVALID in faults:
                locked.append(i)
        return locked

    def _passive_compensate(
        self, q: List[float], raw_target: List[float]
    ) -> List[float]:
        """被动容错补偿（无主动重规划时的兜底策略）"""
        safe_target = list(raw_target)
        for i in range(self.n_joints):
            faults = self._active_faults[i]
            if not faults:
                continue

            # 优先级 1：关节卡死 → 保持当前位置
            if FAULT_JOINT_LOCKED in faults:
                safe_target[i] = float(q[i])
                continue

            # 优先级 2：传感器无效 → 保持最后已知有效位置
            if FAULT_SENSOR_INVALID in faults:
                safe_target[i] = self._last_good_position[i]
                continue

            # 优先级 3：力矩过载 → 缩小位置误差
            if FAULT_TORQUE_OVERLOAD in faults:
                error = float(raw_target[i]) - float(q[i])
                safe_target[i] = float(q[i]) + error * self.torque_overload_scale
                continue

            # 优先级 4：速度异常 → 目标变化率限幅
            if FAULT_VELOCITY_ANOMALY in faults and self._last_target is not None:
                prev = self._last_target[i]
                delta = float(raw_target[i]) - prev
                if abs(delta) > self.velocity_clamp:
                    delta = math.copysign(self.velocity_clamp, delta)
                safe_target[i] = prev + delta
                continue

        return safe_target

    # ---- 状态查询 ----

    @property
    def active_faults(self) -> Dict[int, Set[str]]:
        return {i: set(s) for i, s in self._active_faults.items()}

    @property
    def last_recovery_decision(self) -> Optional[RecoveryDecision]:
        return self._last_recovery_decision

    @property
    def has_any_fault(self) -> bool:
        return self._comm_timeout or any(s for s in self._active_faults.values())

    @property
    def requires_compensation(self) -> bool:
        """Whether an active fault or latched V2 task decision needs output handling."""
        return self.has_any_fault or self._last_recovery_decision is not None

    def is_joint_faulty(self, joint: int) -> bool:
        return bool(self._active_faults.get(joint))

    def reset(self) -> None:
        for i in range(self.n_joints):
            self._active_faults[i].clear()
            self._clean_frames[i] = 0
            self._last_good_position[i] = 0.0
        self._last_target = None
        self._last_recovery_decision = None
        self._last_task_goal = None
        self._recovery_command = None
        self._recovery_velocity = [0.0] * self.n_joints
        self._stuck_joints.clear()
        self._comm_timeout = False

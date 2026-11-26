"""单关节卡滞后的可达性评估、恢复目标和安全停止目标。"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Sequence

from edge_node.fault.kinematics import compute_jacobian, forward_kinematics
from edge_node.fault.kinematics import compute_pose


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    reason: str
    target_q: List[float]
    position_error: float
    iterations: int


class RecoveryPlanner:
    """搜索锁定故障关节后的末端位置解，搜索失败时生成制动目标。

    迭代搜索未找到解时只报告 NO_FEASIBLE_PLAN，不据此声称目标几何上不可达。
    本规划器评价末端位置，不评价目标姿态。
    """

    def __init__(
        self,
        position_tolerance: float = 0.02,
        max_iterations: int = 160,
        damping: float = 0.03,
        max_joint_step: float = 0.12,
        max_deceleration: float = 2.0,
        joint_limits: Sequence[Sequence[float]] | None = None,
    ) -> None:
        values = (position_tolerance, damping, max_joint_step, max_deceleration)
        if any(value <= 0 for value in values) or max_iterations <= 0:
            raise ValueError("planner parameters must be positive")
        self.position_tolerance = float(position_tolerance)
        self.max_iterations = int(max_iterations)
        self.damping = float(damping)
        self.max_joint_step = float(max_joint_step)
        self.max_deceleration = float(max_deceleration)
        self.joint_limits = (
            [list(limit) for limit in joint_limits]
            if joint_limits is not None else [[-math.pi, math.pi] for _ in range(6)]
        )
        if len(self.joint_limits) != 6 or any(
            len(limit) != 2 or limit[0] >= limit[1] for limit in self.joint_limits
        ):
            raise ValueError("joint_limits must contain six increasing min/max pairs")

    @staticmethod
    def target_pose(target_q: Sequence[float]) -> List[float]:
        return compute_pose(target_q)

    def plan(
        self,
        current_q: Sequence[float],
        current_qd: Sequence[float],
        target_pose: Sequence[float],
        locked_joints: Sequence[int],
        preferred_q: Sequence[float] | None = None,
    ) -> RecoveryDecision:
        q = self._validate_vector(current_q, 6, "current_q")
        qd = self._validate_vector(current_qd, 6, "current_qd")
        pose = self._validate_vector(target_pose, 6, "target_pose")
        locked = set(locked_joints)
        if any(not isinstance(index, int) or index < 0 or index >= 6 for index in locked):
            raise ValueError("invalid locked joint index")

        target_position = pose[:3]
        seeds = [list(q)]
        if preferred_q is not None:
            preferred = self._validate_vector(preferred_q, 6, "preferred_q")
            preferred = [q[index] if index in locked else max(
                self.joint_limits[index][0], min(self.joint_limits[index][1], preferred[index])
            ) for index in range(6)]
            if preferred != q:
                seeds.append(preferred)

        best_q = list(q)
        best_error = self._position_error(q, target_position)
        total_iterations = 0
        for seed in seeds:
            q_candidate = list(seed)
            seed_error = self._position_error(seed, target_position)
            if seed_error < best_error:
                best_q, best_error = q_candidate, seed_error
            if seed_error <= self.position_tolerance:
                return RecoveryDecision("RECOVER", "TARGET_REACHED", q_candidate, seed_error, 0)

            damping = self.damping
            for iteration in range(1, self.max_iterations + 1):
                total_iterations += 1
                q_candidate, damping, improved = self._search_from_seed(
                    q_candidate, target_position, locked, damping
                )
                candidate_error = self._position_error(q_candidate, target_position)
                if candidate_error < best_error:
                    best_q, best_error = q_candidate, candidate_error
                if candidate_error <= self.position_tolerance:
                    return RecoveryDecision("RECOVER", "TARGET_REACHED", q_candidate, candidate_error, total_iterations)
                if not improved and damping > 10.0:
                    break

        return RecoveryDecision(
            "STOP", "NO_FEASIBLE_PLAN", self._braking_target(q, qd, locked), best_error, total_iterations
        )

    def _search_from_seed(self, q_candidate, target_position, locked, damping):
        jacobian = compute_jacobian(q_candidate)[:3]
        error = self._position_error_vector(q_candidate, target_position)
        delta = self._solve_step(jacobian, error, locked, damping)
        largest_step = max((abs(value) for value in delta), default=0.0)
        if largest_step > self.max_joint_step:
            scale = self.max_joint_step / largest_step
            delta = [value * scale for value in delta]

        for fraction in (1.0, 0.5, 0.25, 0.125):
            candidate = [
                q_candidate[index] if index in locked else max(
                    self.joint_limits[index][0],
                    min(
                        self.joint_limits[index][1],
                        q_candidate[index] + fraction * delta[index],
                    ),
                )
                for index in range(6)
            ]
            candidate_error = self._position_error(candidate, target_position)
            if candidate_error < self._position_error(q_candidate, target_position):
                return candidate, max(self.damping, damping / 1.5), True

        return q_candidate, damping * 2.0, False

    @staticmethod
    def _validate_vector(values: Sequence[float], length: int, name: str) -> List[float]:
        result = [float(value) for value in values]
        if len(result) != length or not all(math.isfinite(value) for value in result):
            raise ValueError(f"{name} must contain {length} finite values")
        return result

    @staticmethod
    def _position_error_vector(q: Sequence[float], target: Sequence[float]) -> List[float]:
        position, _ = forward_kinematics(q)
        return [target[index] - position[index] for index in range(3)]

    def _position_error(self, q: Sequence[float], target: Sequence[float]) -> float:
        error = self._position_error_vector(q, target)
        return math.sqrt(sum(value * value for value in error))

    def _solve_step(
        self,
        jacobian: Sequence[Sequence[float]],
        error: Sequence[float],
        locked: set[int],
        damping: float,
    ) -> List[float]:
        healthy = [index for index in range(6) if index not in locked]
        delta = [0.0] * 6
        if not healthy:
            return delta

        reduced = [[row[index] for index in healthy] for row in jacobian]
        normal = [
            [sum(reduced[row][i] * reduced[column][i] for i in range(len(healthy)))
             for column in range(3)]
            for row in range(3)
        ]
        for index in range(3):
            normal[index][index] += damping * damping
        dual = self._solve_3x3(normal, list(error))
        if dual is None:
            return delta
        for offset, joint in enumerate(healthy):
            delta[joint] = sum(reduced[row][offset] * dual[row] for row in range(3))
        return delta

    @staticmethod
    def _solve_3x3(matrix: List[List[float]], vector: List[float]) -> List[float] | None:
        augmented = [matrix[row][:] + [vector[row]] for row in range(3)]
        for column in range(3):
            pivot = max(range(column, 3), key=lambda row: abs(augmented[row][column]))
            if abs(augmented[pivot][column]) < 1e-12:
                return None
            augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
            divisor = augmented[column][column]
            augmented[column] = [value / divisor for value in augmented[column]]
            for row in range(3):
                if row == column:
                    continue
                factor = augmented[row][column]
                augmented[row] = [
                    augmented[row][index] - factor * augmented[column][index]
                    for index in range(4)
                ]
        return [augmented[row][3] for row in range(3)]

    def _braking_target(
        self, current_q: Sequence[float], current_qd: Sequence[float], locked: set[int]
    ) -> List[float]:
        stopping_distance = [
            math.copysign(value * value / (2.0 * self.max_deceleration), value)
            for value in current_qd
        ]
        return [
            current_q[index] if index in locked else max(
                self.joint_limits[index][0],
                min(
                    self.joint_limits[index][1],
                    current_q[index] + stopping_distance[index],
                ),
            )
            for index in range(6)
        ]

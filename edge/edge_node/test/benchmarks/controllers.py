"""对比用控制器。

- PIDController：传统固定增益 PID（独立关节，带积分抗饱和）。代表项目书里的「传统 PID」基线。
- 自适应神经网络控制器直接复用生产代码 edge_node.control.AdaptiveNNController（compute_torque）。

两者输出关节力矩，驱动同一 RobotPlant，跟踪同一参考轨迹 → 公平对比跟踪误差与控制延迟。
"""
from __future__ import annotations

from typing import List, Optional, Sequence


class PIDController:
    """传统固定增益 PID（力矩输出，独立关节）。

    τ_i = Kp·e_i + Ki·∫e_i dt + Kd·ė_i ，积分带钳位抗饱和。
    增益按名义负载整定，且不含重力前馈——面对重力/摩擦/负载波动等未建模项，
    只能靠固定增益 + 积分缓慢补偿，这正是与自适应 NN 拉开差距的地方。
    """

    def __init__(
        self,
        n_joints: int = 6,
        kp: float = 100.0,
        ki: float = 20.0,
        kd: float = 25.0,
        integral_limit: float = 5.0,
        tau_limit: float = 50.0,
    ):
        self.n = n_joints
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.integral_limit = integral_limit
        self.tau_limit = tau_limit
        self.setpoint_q: List[float] = [0.0] * n_joints
        self.setpoint_qd: List[float] = [0.0] * n_joints
        self._integral: List[float] = [0.0] * n_joints

    def set_setpoint(self, q_d: Sequence[float],
                     q_d_dot: Optional[Sequence[float]] = None,
                     q_d_ddot: Optional[Sequence[float]] = None) -> None:
        self.setpoint_q = list(q_d)
        self.setpoint_qd = list(q_d_dot) if q_d_dot is not None else [0.0] * self.n

    def compute_torque(self, q: Sequence[float], q_dot: Sequence[float],
                       dt: float = 0.01) -> List[float]:
        tau = []
        for i in range(self.n):
            e = self.setpoint_q[i] - q[i]
            edot = self.setpoint_qd[i] - q_dot[i]
            self._integral[i] += e * dt
            self._integral[i] = max(-self.integral_limit,
                                    min(self.integral_limit, self._integral[i]))
            u = self.kp * e + self.ki * self._integral[i] + self.kd * edot
            tau.append(max(-self.tau_limit, min(self.tau_limit, u)))
        return tau

    def reset(self) -> None:
        self.setpoint_q = [0.0] * self.n
        self.setpoint_qd = [0.0] * self.n
        self._integral = [0.0] * self.n

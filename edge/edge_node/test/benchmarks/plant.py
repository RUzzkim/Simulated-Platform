"""共享 6R 机械臂物理被控对象（力矩输入）。

复刻 test/simulation_simulator.py 中已在 v2.3 报告验证过的动力学：
  M(q)·q̈ = τ_applied − τ_gravity(q) − τ_friction(q̇) − C(q,q̇)·q̇
与模拟器唯一的区别：本类接收**外部力矩** τ_applied（由被测控制器给出），
而不在内部跑 PD 伺服——这样 PID 与自适应 NN 两种控制器可驱动同一套被控对象做公平对比。

同时提供 pd_servo() 便于「位置接口 + 容错补偿」这条与云端部署一致的链路复用同一被控对象。
"""
from __future__ import annotations

import math
from typing import List, Sequence


def solve_linear(m: List[List[float]], b: List[float]) -> List[float]:
    """高斯消元（部分主元）求解 m·x = b，纯 Python（与模拟器一致）。"""
    n = len(b)
    a = [row[:] + [b[i]] for i, row in enumerate(m)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            raise ValueError('M(q) 矩阵奇异')
        a[col], a[piv] = a[piv], a[col]
        for r in range(col + 1, n):
            f = a[r][col] / a[col][col]
            for k in range(col, n + 1):
                a[r][k] -= f * a[col][k]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = a[i][n] - sum(a[i][k] * x[k] for k in range(i + 1, n))
        x[i] = s / a[i][i]
    return x


class RobotPlant:
    """6R 机械臂被控对象（力矩输入，含重力/非线性摩擦/关节耦合/科氏项）。"""

    V_EPS = 0.01

    def __init__(
        self,
        q0: Sequence[float] | None = None,
        inertia: float = 0.5,
        damping: float = 1.0,
        coulomb: float = 0.4,
        stribeck: float = 0.3,
        v_s: float = 0.05,
        gravity: Sequence[float] | None = None,
        coupling: Sequence[float] | None = None,
        v_limit: float = 2.0,
        coriolis: bool = True,
        payload_scale: float = 1.0,
    ):
        self.n = 6
        self.q = list(q0) if q0 is not None else [0.0] * 6
        self.qd = [0.0] * 6
        self.qdd = [0.0] * 6
        self.tau = [0.0] * 6            # 最近施加的关节力矩（作为力矩传感器读数）
        # payload_scale 模拟钢材重量波动：等效惯量与重力负载同步放大
        self.inertia = [inertia * payload_scale] * 6
        self.gravity = [g * payload_scale for g in (gravity if gravity is not None
                        else [0.0, 6.0, 4.0, 1.2, 0.4, 0.4])]
        self.coupling = list(coupling if coupling is not None
                             else [0.1, 0.08, 0.05, 0.03, 0.02])
        self.damping = damping
        self.coulomb = coulomb
        self.stribeck = stribeck
        self.v_s = v_s
        self.v_limit = v_limit
        self.coriolis = coriolis

    # ---- 负载项 ----
    def gravity_torque(self, i: int) -> float:
        return self.gravity[i] * math.cos(self.q[i])

    def friction_torque(self, i: int) -> float:
        v = self.qd[i]
        s = math.tanh(v / self.V_EPS)
        return (self.damping * v + self.coulomb * s
                + self.stribeck * math.exp(-(v / self.v_s) ** 2) * s)

    # ---- 积分一步（半隐式欧拉）----
    def step(self, tau_applied: Sequence[float], dt: float) -> None:
        n = self.n
        tau_g = [self.gravity_torque(i) for i in range(n)]
        tau_f = [self.friction_torque(i) for i in range(n)]
        m = [[0.0] * n for _ in range(n)]
        for i in range(n):
            m[i][i] = self.inertia[i]
        for k in range(n - 1):
            c = self.coupling[k] * math.cos(self.q[k] - self.q[k + 1])
            m[k][k + 1] = c
            m[k + 1][k] = c
        tau_c = [0.0] * n
        if self.coriolis:
            for k in range(n - 1):
                c = self.coupling[k]
                if c == 0.0:
                    continue
                s = c * math.sin(self.q[k] - self.q[k + 1])
                tau_c[k] += s * self.qd[k + 1] ** 2
                tau_c[k + 1] -= s * self.qd[k] ** 2
        net = [tau_applied[i] - tau_g[i] - tau_f[i] - tau_c[i] for i in range(n)]
        qdd = solve_linear(m, net)
        for i in range(n):
            self.qdd[i] = qdd[i]
            self.qd[i] = max(-self.v_limit, min(self.v_limit, self.qd[i] + qdd[i] * dt))
            self.q[i] += self.qd[i] * dt
        self.tau = [float(t) for t in tau_applied]

    def pd_servo(self, q_target: Sequence[float], kp: float = 50.0, kd: float = 10.0,
                 tau_limit: float = 50.0, gravity_comp: bool = True) -> List[float]:
        """位置接口内环 PD 伺服（含前馈重力补偿），返回力矩——与部署时仿真端内环一致。"""
        out = []
        for i in range(self.n):
            tau = kp * (q_target[i] - self.q[i]) - kd * self.qd[i]
            if gravity_comp:
                tau += self.gravity_torque(i)
            out.append(max(-tau_limit, min(tau_limit, tau)))
        return out

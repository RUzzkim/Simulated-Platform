"""自适应神经网络控制器（Adaptive Neural Network Controller）

针对 6 自由度机械臂的刚体动力学模型：
  M(q) q̈ + C(q, q̇) q̇ + G(q) = τ

设计思路（基于 RBF 网络的自适应控制）：
  1. 定义跟踪误差 e = q_d - q，ė = q̇_d - q̇
  2. 滤波误差 s = ė + Λ e （Λ > 0 对角）
  3. 参考速度 q̇_r = q̇_d + Λ e，参考加速度 q̈_r = q̈_d + Λ ė
  4. 未知动力学 f = M q̈_r + C q̇_r + G 由 RBF 网络逼近：f̂ = Ŵ^T φ(x)
  5. 控制律：τ = f̂ + K_d s （K_d > 0 对角）
  6. 自适应律：dŴ/dt = Γ (φ s^T - σ_w Ŵ) （Γ > 0 学习率，σ_w 泄漏项）

稳定性：Lyapunov 函数 V = ½ s^T M s + ½ tr(W̃^T Γ^{-1} W̃)，
      可证 V̇ = -s^T K_d s ≤ 0，闭环稳定且 s → 0。

输出接口：
  由于当前仿真端 joint_command 采用位置指令（Float64MultiArray），
  控制器采用级联结构：外环（本控制器）输出目标位置 q_target，
  内环（仿真端位置环）跟踪 q_target。外环控制律为：
    q_target = q_d + K_p e + K_d ė + f̂ / K_nominal
  其中 f̂ 为 RBF 网络对未知动力学的逼近，K_nominal = M_nominal·Λ²
  为名义刚度（力矩→位置缩放）。
  若后续仿真端切换为力矩控制，可直接使用 compute_torque() 的输出。
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence

from edge_node.control.rbf_network import RBFNetwork


class AdaptiveNNController:
    """自适应神经网络控制器

    实现基于 RBF 网络的机械臂自适应控制。不继承 BaseController，
    因为其接口需要 setpoint 与 dt，由控制循环直接调用。
    """

    def __init__(
        self,
        n_joints: int = 6,
        lambda_gain: float = 10.0,
        kd: float = 50.0,
        learning_rate: float = 0.1,
        leakage: float = 0.001,
        n_centers: int = 64,
        nominal_inertia: float = 1.0,
        position_range: float = 3.14,
        velocity_range: float = 2.0,
        dt: float = 0.01,
        seed: int = 42,
    ):
        self.n_joints = n_joints
        # Λ: 误差滤波增益（标量，对角矩阵）
        self.lambda_gain = lambda_gain
        # K_d: 阻尼增益（标量，对角矩阵）
        self.kd = kd
        # 名义惯量（用于力矩→位置转换）
        self.nominal_inertia = nominal_inertia
        # 输入归一化范围
        self.position_range = position_range
        self.velocity_range = velocity_range
        # 控制周期
        self.dt = dt

        # RBF 网络：输入 [q, q̇]（归一化后），输出 f̂ ∈ R^m
        self.nn = RBFNetwork(
            input_dim=2 * n_joints,
            output_dim=n_joints,
            n_centers=n_centers,
            learning_rate=learning_rate,
            leakage=leakage,
            seed=seed,
        )

        # 设定值（期望轨迹）
        self.setpoint_q: List[float] = [0.0] * n_joints
        self.setpoint_qd: List[float] = [0.0] * n_joints  # 期望速度
        self.setpoint_qdd: List[float] = [0.0] * n_joints  # 期望加速度

    def set_setpoint(
        self,
        q_d: Sequence[float],
        q_d_dot: Optional[Sequence[float]] = None,
        q_d_ddot: Optional[Sequence[float]] = None,
    ) -> None:
        """设定期望轨迹"""
        assert len(q_d) == self.n_joints
        self.setpoint_q = list(q_d)
        self.setpoint_qd = list(q_d_dot) if q_d_dot is not None else [0.0] * self.n_joints
        self.setpoint_qdd = list(q_d_ddot) if q_d_ddot is not None else [0.0] * self.n_joints

    def _normalize_input(self, q: Sequence[float], q_dot: Sequence[float]) -> List[float]:
        """将 [q, q̇] 归一化到 [-1, 1] 区间（RBF 中心在该区间分布）"""
        x: List[float] = []
        for qi in q:
            x.append(max(-1.0, min(1.0, qi / self.position_range)))
        for qdi in q_dot:
            x.append(max(-1.0, min(1.0, qdi / self.velocity_range)))
        return x

    def _forward_and_update(
        self, q: Sequence[float], q_dot: Sequence[float]
    ):
        """内部方法：执行 NN 前向 + 权重更新，返回 (f_hat, s, tau)

        - f_hat: RBF 对未知动力学的逼近 ∈ R^m
        - s: 滤波跟踪误差 ∈ R^m
        - tau: 控制力矩 τ = f̂ + K_d s ∈ R^m
        """
        # 跟踪误差
        e = [qd - qi for qd, qi in zip(self.setpoint_q, q)]
        e_dot = [qdd - qdi for qdd, qdi in zip(self.setpoint_qd, q_dot)]

        # 滤波误差 s = ė + Λ e
        s = [ed + self.lambda_gain * ei for ed, ei in zip(e_dot, e)]

        # RBF 前向（归一化输入）
        x = self._normalize_input(q, q_dot)
        f_hat = self.nn.forward(x)

        # 控制律: τ = f̂ + K_d s
        tau = [f + self.kd * si for f, si in zip(f_hat, s)]

        # 权重更新: dŴ/dt = Γ(φ s^T - σ_w Ŵ)
        self.nn.update_weights(x, s, self.dt)

        return f_hat, s, tau

    def compute_torque(
        self, q: Sequence[float], q_dot: Sequence[float]
    ) -> List[float]:
        """核心控制律：计算控制力矩 τ = f̂ + K_d s

        同时执行权重在线更新。
        """
        _, _, tau = self._forward_and_update(q, q_dot)
        return tau

    def compute_target_position(
        self, q: Sequence[float], q_dot: Sequence[float]
    ) -> List[float]:
        """计算目标关节位置（适配当前位置控制接口）

        对于位置控制接口（仿真端 inner position loop 跟踪 q_target），
        采用前馈 + PD + NN 补偿的形式直接输出目标位置：
          q_target = q_d + K_p e + K_d ė + f̂ / K_nominal

        其中：
          - K_p = Λ（位置误差增益，由误差滤波增益给出）
          - K_d = K_d / Λ（速度误差增益，保证临界阻尼附近）
          - f̂ 为 RBF 网络对未知动力学的逼近（力矩量纲）
          - K_nominal = M_nominal · Λ²（名义刚度，用于力矩→位置缩放）

        该调用内部会执行 NN 前向与权重更新。
        """
        e = [qd - qi for qd, qi in zip(self.setpoint_q, q)]
        e_dot = [qdd - qdi for qdd, qdi in zip(self.setpoint_qd, q_dot)]

        # 执行核心控制律（NN 前向 + 权重更新），取 f̂ 用于位置补偿
        f_hat, _, _ = self._forward_and_update(q, q_dot)

        # 外环位置控制增益（级联控制：外环带宽应远低于内环）
        # K_p 取较小值保证内环可稳定跟踪，K_d 取 2*sqrt(K_p) 实现临界阻尼
        kp = 1.0
        kd = 2.0 * math.sqrt(kp)
        # 力矩 → 位置 缩放（名义刚度）
        nominal_stiffness = self.nominal_inertia * self.lambda_gain ** 2
        nn_scale = 1.0 / max(nominal_stiffness, 1e-6)

        q_target = [
            qd + kp * ei + kd * edi + f * nn_scale
            for qd, ei, edi, f in zip(self.setpoint_q, e, e_dot, f_hat)
        ]
        # 饱和限制：目标位置不超过归一化范围，防止发散
        q_target = [
            max(-self.position_range, min(self.position_range, qt))
            for qt in q_target
        ]
        return q_target

    def reset(self) -> None:
        """重置控制器（清空权重、设定值归零）"""
        self.nn.reset()
        self.setpoint_q = [0.0] * self.n_joints
        self.setpoint_qd = [0.0] * self.n_joints
        self.setpoint_qdd = [0.0] * self.n_joints

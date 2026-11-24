"""RBF（径向基函数）神经网络模块（纯 Python 实现，无 numpy 依赖）

用于自适应控制中逼近机械臂未知动力学 f(q, qdot, qdot_r, qddot_r)。

网络结构：
  输入 x ∈ R^n（这里 n=12: [q(6), qdot(6)]）
  高斯核 φ_i(x) = exp(-||x - μ_i||^2 / (2 σ_i^2))
  输出 f̂ = W^T φ(x)，W ∈ R^{N×m}（m=6 关节）

权重自适应律（带泄漏项 σ_w 防止参数漂移）：
  dŴ/dt = Γ (φ s^T - σ_w Ŵ)
其中 s ∈ R^m 为滤波跟踪误差，Γ 为学习率。
"""
from __future__ import annotations

import math
import random
from typing import List, Optional, Sequence


class RBFNetwork:
    """固定中心、可调权重的 RBF 网络（纯 Python 列表实现）"""

    def __init__(
        self,
        input_dim: int,
        output_dim: int,
        n_centers: int = 64,
        centers: Optional[List[List[float]]] = None,
        widths: Optional[List[float]] = None,
        learning_rate: float = 0.01,
        leakage: float = 0.001,
        seed: int = 42,
    ):
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.n_centers = n_centers
        self.learning_rate = learning_rate
        self.leakage = leakage

        rng = random.Random(seed)

        # 中心：在 [-1, 1]^n 内均匀分布（输入应归一化到该范围）
        if centers is None:
            self.centers: List[List[float]] = [
                [rng.uniform(-1.0, 1.0) for _ in range(input_dim)]
                for _ in range(n_centers)
            ]
        else:
            self.centers = [list(row) for row in centers]
            assert len(self.centers) == n_centers
            assert all(len(c) == input_dim for c in self.centers)

        # 宽度：高斯核宽度
        if widths is None:
            w = 1.0 / math.sqrt(2.0 * n_centers)
            self.widths: List[float] = [w] * n_centers
        else:
            self.widths = list(widths)
            assert len(self.widths) == n_centers

        # 权重初始化为 0（自适应控制中通常从零开始）
        self.weights: List[List[float]] = [
            [0.0] * output_dim for _ in range(n_centers)
        ]

    def activate(self, x: Sequence[float]) -> List[float]:
        """计算 RBF 激活向量 φ(x) ∈ R^N"""
        assert len(x) == self.input_dim, f"输入维度应为 {self.input_dim}"
        phi = [0.0] * self.n_centers
        for i in range(self.n_centers):
            dist_sq = 0.0
            ci = self.centers[i]
            for j in range(self.input_dim):
                d = x[j] - ci[j]
                dist_sq += d * d
            phi[i] = math.exp(-dist_sq / (2.0 * self.widths[i] ** 2))
        return phi

    def forward(self, x: Sequence[float]) -> List[float]:
        """前向传播: f̂ = W^T φ(x) ∈ R^m"""
        phi = self.activate(x)
        out = [0.0] * self.output_dim
        for i in range(self.n_centers):
            wi = self.weights[i]
            phii = phi[i]
            for j in range(self.output_dim):
                out[j] += wi[j] * phii
        return out

    def update_weights(self, x: Sequence[float], filtered_error: Sequence[float], dt: float) -> None:
        """在线权重更新：dŴ/dt = Γ(φ s^T - σ_w Ŵ)

        :param x: 网络输入
        :param filtered_error: 滤波跟踪误差 s ∈ R^m
        :param dt: 控制周期（秒）
        """
        assert len(filtered_error) == self.output_dim
        phi = self.activate(x)
        s = filtered_error
        lr_dt = self.learning_rate * dt
        for i in range(self.n_centers):
            phii = phi[i]
            wi = self.weights[i]
            for j in range(self.output_dim):
                # 梯度项 φ_i * s_j，泄漏项 σ_w * W_ij
                dw = lr_dt * (phii * s[j] - self.leakage * wi[j])
                wi[j] += dw

    def reset(self) -> None:
        """重置权重（用于实验对比）"""
        for row in self.weights:
            for j in range(len(row)):
                row[j] = 0.0

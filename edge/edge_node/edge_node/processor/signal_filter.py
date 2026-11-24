"""信号滤波与离群点剔除模块（状态处理管线最前端的信号清洗）

三级流水线（每个关节的 position/velocity/effort 各一条独立通道）：
  1. MAD 稳健离群点剔除：用"历史窗口"的中值与中位绝对偏差（MAD）判定新样本，
     判为离群的帧在【输出端】用上一有效输出保持（尖峰不进输出）；但原始观测
     【仍入统计窗】——否则持续物理变化（如真实过载阶跃）会把统计基线锁死在旧值、
     永远无法穿透。奇数窗中值对单点尖峰天然免疫，统计量不会被一帧跳点带偏；
  2. 中值滤波：窗内取中值，去除脉冲噪声；
  3. EMA 指数平滑：y = α·median + (1-α)·y_prev，抑制高频测量噪声。

为什么用 MAD 而不是 3σ：均值/标准差本身会被尖峰污染，MAD 的崩溃点为 50%，
单个传感器跳点不会抬高阈值导致后续尖峰漏检。

关键设计约束（与故障检测的配合）：
  - 持续物理量变化（如真实力矩过载阶跃）必须快速穿透：离群判定只基于历史窗口，
    window=N 时中值最迟在第 N 个新样本后迁移到新水平，穿透延迟 ≤ (N-1) 帧
    （100Hz、N=3 时 ≤20ms），远小于故障检测 window(20)+persistence(5) 的确认时间；
  - 暖机期（窗口未填满）不剔除，避免冷启动误杀；
  - MAD=0（完全静止窗口）时退化为 min_sigma 下限，正常微小波动不被误判为离群。

纯 Python 无 numpy（与边端其他模块一致）。非线程安全：与状态回调同线程使用
（边端状态回调链为单线程，与 fault detector / state processor 同一假设）。
"""
from __future__ import annotations

from collections import deque
from typing import Deque, List, Optional, Tuple


def _median(xs: List[float]) -> float:
    """中值（输入会被排序，调用方传副本或 deque 转换结果）"""
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return 0.5 * (s[mid - 1] + s[mid])


class ChannelFilter:
    """单通道（某关节的某物理量）：MAD 离群剔除 → 中值 → EMA"""

    def __init__(self, window_size: int = 3, outlier_k: float = 3.5,
                 ema_alpha: float = 0.5, min_sigma: float = 0.01):
        if window_size < 2:
            raise ValueError("window_size 必须 ≥ 2")
        if not 0.0 < ema_alpha <= 1.0:
            raise ValueError("ema_alpha 必须在 (0, 1]")
        self.window_size = int(window_size)
        self.outlier_k = float(outlier_k)
        self.ema_alpha = float(ema_alpha)
        # MAD=0 时的退化尺度（各物理量单位不同，由上层按通道给定）
        self.min_sigma = float(min_sigma)
        # 原始观测窗口（含被判离群的帧；奇数窗中值对单帧尖峰免疫，
        # 且持续物理变化可把中值推到新水平）
        self._win: Deque[float] = deque(maxlen=self.window_size)
        self._last_out: Optional[float] = None
        self.outlier_count = 0

    def reset(self) -> None:
        self._win.clear()
        self._last_out = None
        self.outlier_count = 0

    def process(self, x: float) -> Tuple[float, bool]:
        """处理一个样本，返回 (滤波输出, 是否被判为离群并以保持值替代)"""
        x = float(x)

        # 暖机期：窗口未形成统计基线，不做剔除
        if len(self._win) < self.window_size:
            self._win.append(x)
            med = _median(list(self._win))
            if self._last_out is None:
                self._last_out = x
            else:
                self._last_out = self.ema_alpha * med + (1.0 - self.ema_alpha) * self._last_out
            return self._last_out, False

        # 离群判定仅基于历史窗口（不含当前样本）
        hist = list(self._win)
        med_hist = _median(hist)
        mad = _median([abs(v - med_hist) for v in hist])
        # MAD → 标准差的一致估计因子（正态分布 1.4826）；完全静止时用 min_sigma 兜底
        sigma = max(1.4826 * mad, self.min_sigma)
        is_outlier = abs(x - med_hist) > self.outlier_k * sigma

        # 原始观测始终入窗：持续阶跃时窗口中值在 N 帧内迁移到新水平（穿透保证）；
        # 单点尖峰处于奇数窗内时中值不受影响（脉冲免疫）
        self._win.append(x)

        if is_outlier:
            # 输出端保持上一有效值，尖峰不进 EMA
            self.outlier_count += 1
            return self._last_out, True

        med = _median(list(self._win))
        self._last_out = self.ema_alpha * med + (1.0 - self.ema_alpha) * self._last_out
        return self._last_out, False


class RobotSignalFilter:
    """6 关节 × 3 通道（position/velocity/effort）信号滤波组

    :param n_joints: 关节数（固定 6）
    :param window_size: 中值/统计窗口帧数（100Hz 下 N 帧 ≈ 10N ms 延迟）
    :param outlier_k: MAD 倍数阈值（越大越宽松；正态数据 3.5 误报率极低）
    :param alpha_position/alpha_velocity/alpha_effort: 各通道 EMA 系数
    :param min_sigma_*: 各通道 MAD=0 时的退化尺度（单位分别 rad/rad·s⁻¹/N·m）
    """

    def __init__(self, n_joints: int = 6, window_size: int = 3,
                 outlier_k: float = 3.5,
                 alpha_position: float = 0.8, alpha_velocity: float = 0.5,
                 alpha_effort: float = 0.5,
                 min_sigma_position: float = 0.002,
                 min_sigma_velocity: float = 0.01,
                 min_sigma_effort: float = 0.1):
        self.n_joints = int(n_joints)
        self._position = [ChannelFilter(window_size, outlier_k, alpha_position,
                                         min_sigma_position) for _ in range(self.n_joints)]
        self._velocity = [ChannelFilter(window_size, outlier_k, alpha_velocity,
                                         min_sigma_velocity) for _ in range(self.n_joints)]
        self._effort = [ChannelFilter(window_size, outlier_k, alpha_effort,
                                       min_sigma_effort) for _ in range(self.n_joints)]
        self.processed_frames = 0
        self.outlier_frames = 0          # 至少一个关节任一通道被剔的帧数
        self.outlier_by_joint = [0] * self.n_joints

    def reset(self) -> None:
        for chs in (self._position, self._velocity, self._effort):
            for ch in chs:
                ch.reset()
        self.processed_frames = 0
        self.outlier_frames = 0
        self.outlier_by_joint = [0] * self.n_joints

    def filter(self, position, velocity, effort
               ) -> Tuple[List[float], List[float], List[float], List[bool]]:
        """过滤一帧 6 轴状态

        :return: (滤波后 position, 滤波后 velocity, 滤波后 effort, 每关节离群标志)
                 离群标志为该关节三路通道任一被剔；标志仅用于诊断/日志，不改变帧序
        """
        fp: List[float] = [0.0] * self.n_joints
        fv: List[float] = [0.0] * self.n_joints
        fe: List[float] = [0.0] * self.n_joints
        joint_flags: List[bool] = [False] * self.n_joints
        for i in range(self.n_joints):
            fp[i], op = self._position[i].process(position[i])
            fv[i], ov = self._velocity[i].process(velocity[i])
            fe[i], oe = self._effort[i].process(effort[i])
            if op or ov or oe:
                joint_flags[i] = True
                self.outlier_by_joint[i] += 1
        self.processed_frames += 1
        if any(joint_flags):
            self.outlier_frames += 1
        return fp, fv, fe, joint_flags

    @property
    def stats(self) -> dict:
        """滤波统计（供运维诊断：长期 outlier_frames 占比高意味着传感器可能劣化）"""
        return {
            'processed_frames': self.processed_frames,
            'outlier_frames': self.outlier_frames,
            'outlier_by_joint': list(self.outlier_by_joint),
        }

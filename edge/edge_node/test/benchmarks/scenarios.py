"""钢铁后处理工段场景 / 故障库（可复现）。

分两类：
1. 控制对比场景（category='control'）：通过负载波动、摩擦/磨损、关节耦合、重力、
   轨迹快慢制造「模型失配 + 强扰动」，用于 PID vs 自适应 NN 的跟踪精度对比。
   对应工况：钢材重量波动、高温粉尘导致摩擦增大与执行器磨损、强耦合位姿。
2. 故障对比场景（category='fault'）：注入离散故障（力矩过载、关节卡死、传感器漂移失效、
   通信抖动/超时），用于容错控制 ON/OFF 的任务完成率与响应时间对比。
   对应工况：传感器高温漂移、执行器卡死、车间电磁干扰致通信抖动。

所有场景参数固定 + 显式 seed，逐次运行可复现。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


class TrajectoryReference:
    """参考轨迹发生器：点到点梯形速度（p2p）或正弦（sine），提供 q_d(t) 与 q̇_d(t)。"""

    def __init__(self, mode: str, q0: List[float], q1: Optional[List[float]] = None,
                 v_max: float = 1.0, a_max: float = 2.0,
                 amp: float = 0.5, freq: float = 0.2):
        self.mode = mode
        self.q0 = list(q0)
        self.q1 = list(q1) if q1 is not None else list(q0)
        self.amp = amp
        self.freq = freq
        self.d = [b - a for a, b in zip(self.q0, self.q1)]
        d_max = max((abs(x) for x in self.d), default=0.0)
        self._d_max = d_max
        self.done = d_max < 1e-9
        if not self.done:
            self._a = a_max
            self.v_peak = min(v_max, math.sqrt(a_max * d_max))
            self._t_a = self.v_peak / a_max
            d_a = 0.5 * a_max * self._t_a ** 2
            self.T = 2.0 * self._t_a + max(0.0, (d_max - 2.0 * d_a) / self.v_peak)
        else:
            self.v_peak = 0.0
            self.T = 0.0

    def _frac(self, t: float) -> Tuple[float, float]:
        """返回归一化位移 s(t)∈[0,1] 与其导数 ṡ(t)。"""
        if self.done:
            return 1.0, 0.0
        t = max(0.0, min(t, self.T))
        if t < self._t_a:
            return 0.5 * self._a * t * t / self._d_max, self._a * t / self._d_max
        t_d = self.T - t
        if t_d < self._t_a:
            return (1.0 - 0.5 * self._a * t_d * t_d / self._d_max,
                    self._a * t_d / self._d_max)
        return ((0.5 * self._a * self._t_a ** 2 + self.v_peak * (t - self._t_a)) / self._d_max,
                self.v_peak / self._d_max)

    def sample(self, t: float) -> Tuple[List[float], List[float]]:
        """返回 (q_d, q̇_d)。"""
        if self.mode == 'sine':
            w = 2 * math.pi * self.freq
            q = [self.q0[i] + self.amp * math.sin(w * t + i * 0.8) for i in range(6)]
            qd = [self.amp * w * math.cos(w * t + i * 0.8) for i in range(6)]
            return q, qd
        s, sdot = self._frac(t)
        q = [self.q0[i] + s * self.d[i] for i in range(6)]
        qd = [sdot * self.d[i] for i in range(6)]
        return q, qd


@dataclass
class Scenario:
    name: str
    category: str                       # 'control' | 'fault'
    description: str
    duration: float = 6.0
    # 被控对象参数
    payload_scale: float = 1.0
    coulomb: float = 0.4
    stribeck: float = 0.3
    coupling_scale: float = 1.0
    gravity_scale: float = 1.0
    # 参考轨迹
    ref_mode: str = 'p2p'               # 'p2p' | 'sine'
    target: List[float] = field(default_factory=lambda: [0.8, 0.6, -0.5, 0.4, 0.3, 0.2])
    ref_vmax: float = 1.0
    ref_amp: float = 0.5
    ref_freq: float = 0.2
    # 故障（category='fault' 时有效）
    fault_type: Optional[str] = None    # TORQUE_OVERLOAD/JOINT_LOCKED/SENSOR_INVALID/COMMUNICATION_TIMEOUT
    fault_joint: int = 0
    fault_onset: float = 2.5
    fault_duration: float = 2.0
    fault_magnitude: float = 60.0
    lock_reaction_torque: float = 12.5
    seed: int = 42


# 三个代表性作业目标（钢料搬运/喷号的点到点位姿）
_TARGETS = [
    [0.8, 0.6, -0.5, 0.4, 0.3, 0.2],
    [1.2, -0.8, 0.9, -0.6, 0.5, -0.4],
    [-0.7, 1.0, 0.6, 0.8, -0.5, 0.3],
]

# 控制对比工况：(名称, 说明, 覆盖参数)
_CONTROL_CONDITIONS = [
    ('nominal', '名义负载基线', {}),
    ('payload_light', '轻载钢件（等效惯量/重力×0.6）', {'payload_scale': 0.6}),
    ('payload_heavy', '重载钢件（×1.8）', {'payload_scale': 1.8}),
    ('payload_very_heavy', '超重钢坯（×2.5）', {'payload_scale': 2.5}),
    ('high_friction', '高温粉尘致摩擦增大', {'coulomb': 1.2, 'stribeck': 0.8}),
    ('worn_actuator', '执行器磨损（摩擦进一步增大）', {'coulomb': 1.6, 'stribeck': 1.0}),
    ('strong_coupling', '强关节耦合位姿', {'coupling_scale': 2.0}),
    ('heavy_gravity', '大重力负载臂展', {'gravity_scale': 1.5}),
]

_FAULT_TYPES = [
    ('JOINT_LOCKED', 0, '基座回转轴执行器卡死（关节锁定）'),
    ('JOINT_LOCKED', 1, '肩关节执行器卡死（关节锁定）'),
    ('JOINT_LOCKED', 2, '肘关节执行器卡死（关节锁定）'),
    ('JOINT_LOCKED', 3, '腕关节执行器卡死（关节锁定）'),
]


def build_scenarios() -> tuple[list[Scenario], list[Scenario]]:
    """构造控制对比与故障对比两组场景（各 24 个 → 合计 48 组对比）。"""
    control: list[Scenario] = []
    for cname, desc, overrides in _CONTROL_CONDITIONS:
        for ti, target in enumerate(_TARGETS):
            control.append(Scenario(
                name=f'{cname}#T{ti + 1}',
                category='control',
                description=desc,
                duration=6.0,
                ref_mode='p2p',
                target=list(target),
                ref_vmax=1.0,
                seed=42 + ti,
                **overrides,
            ))

    fault: list[Scenario] = []
    for ftype, fjoint, desc in _FAULT_TYPES:
        for si in range(3):
            for ti in range(2):
                fault.append(Scenario(
                    name=f'LOCK-J{fjoint}#s{si + 1}T{ti + 1}',
                    category='fault',
                    description=desc,
                    duration=8.0,
                    ref_mode='p2p',
                    target=list(_TARGETS[ti]),
                    ref_vmax=0.6,
                    fault_type=ftype,
                    fault_joint=fjoint,
                    fault_onset=0.3 + 0.15 * si,   # 作业早期即卡死 → 未完成的行程需容错补偿
                    fault_duration=20.0,          # 持久性执行器失效（覆盖至运行结束）
                    seed=100 + si,
                ))
    return control, fault


def build_task_recovery_scenarios(split: str = 'development') -> list[Scenario]:
    """Return deterministic development, exploratory, or validation cases."""
    targets = {
        'development': _TARGETS[:2],
        'exploratory': [
            [-0.45, 0.35, 0.25, -0.30, 0.20, -0.15],
            [0.55, -0.35, -0.20, 0.25, -0.25, 0.30],
        ],
        'validation': [
            [0.35, 0.55, -0.30, 0.20, -0.15, 0.10],
            [-0.60, 0.25, 0.45, -0.20, 0.30, -0.25],
        ],
    }
    if split not in targets:
        raise ValueError("split must be 'development', 'exploratory', or 'validation'")

    if split == 'development':
        return build_scenarios()[1]

    scenarios = []
    onsets = (0.4, 0.8, 1.2) if split == 'validation' else (0.3, 0.45, 0.6)
    for joint in range(4):
        description = _FAULT_TYPES[joint][2]
        for onset_index, onset in enumerate(onsets):
            for target_index, target in enumerate(targets[split]):
                scenarios.append(Scenario(
                    name=f'{split.upper()}-LOCK-J{joint}#s{onset_index + 1}T{target_index + 1}',
                    category='fault',
                    description=description,
                    duration=8.0,
                    ref_mode='p2p',
                    target=list(target),
                    ref_vmax=0.6,
                    fault_type='JOINT_LOCKED',
                    fault_joint=joint,
                    fault_onset=onset,
                    fault_duration=20.0,
                    seed=(300 if split == 'validation' else 200) + onset_index,
                ))
    return scenarios


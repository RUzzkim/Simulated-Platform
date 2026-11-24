"""故障检测模块

复合故障检测器 CompositeFaultDetector 实现以下检测项：

1. SENSOR_INVALID — 传感器数据无效（NaN / 越界），立即触发
2. VELOCITY_ANOMALY — 速度异常（|v| > max_velocity），立即触发
3. TORQUE_OVERLOAD — 持续力矩过载（窗口内平均 |τ| > torque_overload_threshold），需持续性判定
4. JOINT_LOCKED — 关节卡死（位置极差极小 且 平均力矩偏高），需持续性判定
5. COMMUNICATION_TIMEOUT — 状态数据超时未更新（外部调用 check_timeout）

持续性判定：非关键故障需连续 persistence 帧命中才上报，避免噪声误报。
"""
from __future__ import annotations

import math
import time
from typing import Dict, Optional

from edge_node.fault.sliding_window import StateHistoryWindow
from edge_node.model.messages import (
    FAULT_COMM_TIMEOUT,
    FAULT_JOINT_LOCKED,
    FAULT_SENSOR_INVALID,
    FAULT_TORQUE_OVERLOAD,
    FAULT_VELOCITY_ANOMALY,
    FAULT_SEVERITY_CRITICAL,
    FAULT_SEVERITY_ERROR,
    FAULT_SEVERITY_WARNING,
    FaultEvent,
    RobotState,
)


class FaultDetector:
    """故障检测器基类"""

    def detect(self, state: RobotState) -> Optional[str]:
        """返回故障类型字符串，无故障返回 None（兼容 phase1 接口）"""
        evt = self.detect_event(state)
        return evt.fault_type if evt else None

    def detect_event(self, state: RobotState) -> Optional[FaultEvent]:
        """返回故障事件对象，无故障返回 None"""
        return None


class NoOpFaultDetector(FaultDetector):
    """不做故障检测"""

    def detect_event(self, state: RobotState) -> Optional[FaultEvent]:
        return None


class CompositeFaultDetector(FaultDetector):
    """复合故障检测器

    :param n_joints: 关节数
    :param window_size: 滑动窗口大小（帧数）
    :param persistence: 非关键故障持续帧数阈值
    :param max_velocity: 速度上限（rad/s）
    :param position_limit: 位置绝对值上限（rad）
    :param torque_overload_threshold: 持续力矩过载阈值（N·m，窗口平均绝对值）
    :param lock_position_threshold: 关节卡死位置极差阈值（rad）
    :param lock_torque_threshold: 关节卡死力矩阈值（N·m，窗口平均绝对值）
    :param comm_timeout_ms: 通信超时阈值（毫秒）
    """

    def __init__(
        self,
        n_joints: int = 6,
        window_size: int = 20,
        persistence: int = 5,
        max_velocity: float = 3.0,
        position_limit: float = 6.28,
        torque_overload_threshold: float = 40.0,
        lock_position_threshold: float = 0.001,
        lock_torque_threshold: float = 10.0,
        comm_timeout_ms: int = 500,
    ):
        self.n_joints = n_joints
        self.window_size = window_size
        self.persistence = persistence
        self.max_velocity = max_velocity
        self.position_limit = position_limit
        self.torque_overload_threshold = torque_overload_threshold
        self.lock_position_threshold = lock_position_threshold
        self.lock_torque_threshold = lock_torque_threshold
        self.comm_timeout_ms = comm_timeout_ms

        self._history = StateHistoryWindow(n_joints, window_size)
        # 持续性计数器：{(fault_type, joint_index): consecutive_count}
        self._counters: Dict[tuple, int] = {}

    # ---- 内部辅助 ----

    def _bump(self, key: tuple) -> int:
        """递增持续性计数，返回当前计数"""
        c = self._counters.get(key, 0) + 1
        self._counters[key] = c
        return c

    def _reset(self, key: tuple) -> None:
        """重置持续性计数"""
        self._counters.pop(key, None)

    def _reset_all_for_joint(self, joint: int) -> None:
        """重置某关节所有持续性计数"""
        for ft in (FAULT_TORQUE_OVERLOAD, FAULT_JOINT_LOCKED):
            self._reset((ft, joint))

    @staticmethod
    def _is_nan(v: float) -> bool:
        try:
            return math.isnan(float(v))
        except (TypeError, ValueError):
            return True

    # ---- 各检测项 ----

    def _check_sensor_invalid(self, state: RobotState) -> Optional[FaultEvent]:
        """传感器数据无效：NaN 或越界"""
        for i in range(self.n_joints):
            p = state.joint_position[i]
            v = state.joint_velocity[i]
            t = state.joint_torque[i]
            if self._is_nan(p) or self._is_nan(v) or self._is_nan(t):
                return FaultEvent(
                    fault_type=FAULT_SENSOR_INVALID,
                    joint_index=i,
                    severity=FAULT_SEVERITY_CRITICAL,
                    timestamp=state.timestamp,
                    detail=f"joint {i} sensor data contains NaN",
                )
            if abs(p) > self.position_limit:
                return FaultEvent(
                    fault_type=FAULT_SENSOR_INVALID,
                    joint_index=i,
                    severity=FAULT_SEVERITY_ERROR,
                    timestamp=state.timestamp,
                    detail=f"joint {i} position {p:.3f} exceeds limit ±{self.position_limit}",
                )
        return None

    def _check_velocity_anomaly(self, state: RobotState) -> Optional[FaultEvent]:
        """速度异常：单帧 |v| 超过上限"""
        for i in range(self.n_joints):
            if abs(state.joint_velocity[i]) > self.max_velocity:
                return FaultEvent(
                    fault_type=FAULT_VELOCITY_ANOMALY,
                    joint_index=i,
                    severity=FAULT_SEVERITY_ERROR,
                    timestamp=state.timestamp,
                    detail=f"joint {i} velocity {state.joint_velocity[i]:.3f} exceeds limit ±{self.max_velocity}",
                )
        return None

    def _check_torque_overload(self, state: RobotState) -> Optional[FaultEvent]:
        """持续力矩过载：窗口内平均 |τ| 超过阈值，需持续性判定"""
        evt = None
        for i in range(self.n_joints):
            avg_t = self._history.joints[i].avg_abs_torque()
            key = (FAULT_TORQUE_OVERLOAD, i)
            if avg_t > self.torque_overload_threshold:
                cnt = self._bump(key)
                if cnt >= self.persistence:
                    evt = FaultEvent(
                        fault_type=FAULT_TORQUE_OVERLOAD,
                        joint_index=i,
                        severity=FAULT_SEVERITY_ERROR,
                        timestamp=state.timestamp,
                        detail=f"joint {i} sustained avg torque {avg_t:.1f} > {self.torque_overload_threshold}",
                    )
            else:
                self._reset(key)
        return evt

    def _check_joint_locked(self, state: RobotState) -> Optional[FaultEvent]:
        """关节卡死：窗口内位置极差极小 且 平均力矩偏高，需持续性判定"""
        evt = None
        for i in range(self.n_joints):
            pos_range = self._history.joints[i].position_range()
            avg_t = self._history.joints[i].avg_abs_torque()
            key = (FAULT_JOINT_LOCKED, i)
            if pos_range < self.lock_position_threshold and avg_t > self.lock_torque_threshold:
                cnt = self._bump(key)
                if cnt >= self.persistence:
                    evt = FaultEvent(
                        fault_type=FAULT_JOINT_LOCKED,
                        joint_index=i,
                        severity=FAULT_SEVERITY_CRITICAL,
                        timestamp=state.timestamp,
                        detail=(
                            f"joint {i} locked: pos range {pos_range:.5f} < "
                            f"{self.lock_position_threshold} while avg torque {avg_t:.1f} > "
                            f"{self.lock_torque_threshold}"
                        ),
                    )
            else:
                self._reset(key)
        return evt

    # ---- 对外接口 ----

    def detect_event(self, state: RobotState) -> Optional[FaultEvent]:
        """执行全部检测，返回最高优先级故障事件"""
        # 1. 传感器无效（立即，最高优先级）
        evt = self._check_sensor_invalid(state)
        if evt is not None:
            return evt

        # 更新历史窗口（用于持续性检测）
        self._history.push(state)

        # 2. 速度异常（立即）
        evt = self._check_velocity_anomaly(state)
        if evt is not None:
            return evt

        # 3. 持续力矩过载（需持续性）
        evt = self._check_torque_overload(state)
        if evt is not None:
            return evt

        # 4. 关节卡死（需持续性）
        evt = self._check_joint_locked(state)
        if evt is not None:
            return evt

        return None

    def check_timeout(self, now_ms: Optional[int] = None) -> Optional[FaultEvent]:
        """检查通信超时（需外部定时调用）"""
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        elapsed = self._history.elapsed_since_last(now_ms)
        if elapsed is not None and elapsed > self.comm_timeout_ms:
            return FaultEvent(
                fault_type=FAULT_COMM_TIMEOUT,
                joint_index=-1,
                severity=FAULT_SEVERITY_WARNING,
                timestamp=now_ms,
                detail=f"no state update for {elapsed}ms > {self.comm_timeout_ms}ms",
            )
        return None

    def reset(self) -> None:
        """重置历史窗口与持续性计数"""
        self._history.clear()
        self._counters.clear()

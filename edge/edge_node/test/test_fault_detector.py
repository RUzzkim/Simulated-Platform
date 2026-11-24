"""故障检测模块测试：传感器无效、速度异常、持续力矩过载、关节卡死、通信超时"""
import math
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from edge_node.fault.detector import CompositeFaultDetector, NoOpFaultDetector
from edge_node.fault.sliding_window import JointHistoryWindow, StateHistoryWindow
from edge_node.model.messages import (
    FAULT_COMM_TIMEOUT,
    FAULT_JOINT_LOCKED,
    FAULT_SENSOR_INVALID,
    FAULT_TORQUE_OVERLOAD,
    FAULT_VELOCITY_ANOMALY,
    FAULT_SEVERITY_CRITICAL,
    RobotState,
)

N_JOINTS = 6
TS = 1760000000123


def _state(position, velocity, torque, status='RUNNING', ts=TS):
    return RobotState(
        simulation_id='SIM-001',
        robot_id='ROBOT-001',
        timestamp=ts,
        joint_position=list(position),
        joint_velocity=list(velocity),
        joint_torque=list(torque),
        status=status,
    )


def _zero_state(**kwargs):
    return _state([0.0] * N_JOINTS, [0.0] * N_JOINTS, [0.0] * N_JOINTS, **kwargs)


# ---------- 滑动窗口测试 ----------

def test_joint_history_window_push_and_stats():
    w = JointHistoryWindow(size=5)
    w.push(1.0, 0.5, 10.0)
    w.push(2.0, 1.0, 20.0)
    assert len(w) == 2
    assert w.position_range() == 1.0
    assert abs(w.avg_abs_torque() - 15.0) < 1e-6
    assert abs(w.avg_abs_velocity() - 0.75) < 1e-6


def test_joint_history_window_circular():
    w = JointHistoryWindow(size=3)
    for p in [0.0, 1.0, 2.0, 3.0]:
        w.push(p, 0.0, 0.0)
    assert len(w) == 3
    # 最早的 0.0 被挤出，窗口内为 [1, 2, 3]
    assert w.position_range() == 2.0


def test_state_history_window_full():
    w = StateHistoryWindow(n_joints=6, size=3)
    assert not w.full()
    for i in range(3):
        s = _state([0.0] * 6, [0.0] * 6, [0.0] * 6)
        w.push(s)
    assert w.full()


# ---------- NoOp 检测器 ----------

def test_noop_detector_returns_none():
    d = NoOpFaultDetector()
    assert d.detect_event(_zero_state()) is None
    assert d.detect(_zero_state()) is None


# ---------- 传感器无效 ----------

def test_sensor_invalid_nan():
    d = CompositeFaultDetector(n_joints=N_JOINTS)
    s = _state([0.0, 0.0, math.nan, 0.0, 0.0, 0.0], [0.0] * 6, [0.0] * 6)
    evt = d.detect_event(s)
    assert evt is not None
    assert evt.fault_type == FAULT_SENSOR_INVALID
    assert evt.joint_index == 2
    assert evt.severity == FAULT_SEVERITY_CRITICAL


def test_sensor_invalid_position_overflow():
    d = CompositeFaultDetector(n_joints=N_JOINTS, position_limit=6.28)
    s = _state([7.0, 0, 0, 0, 0, 0], [0.0] * 6, [0.0] * 6)
    evt = d.detect_event(s)
    assert evt is not None
    assert evt.fault_type == FAULT_SENSOR_INVALID
    assert evt.joint_index == 0


def test_sensor_valid_passes():
    d = CompositeFaultDetector(n_joints=N_JOINTS)
    s = _state([0.1, 0.2, 0.3, 0.0, 0.0, 0.0], [0.0] * 6, [5.0] * 6)
    assert d.detect_event(s) is None


# ---------- 速度异常 ----------

def test_velocity_anomaly_immediate():
    d = CompositeFaultDetector(n_joints=N_JOINTS, max_velocity=3.0)
    s = _state([0.0] * 6, [0.0, 4.0, 0.0, 0.0, 0.0, 0.0], [0.0] * 6)
    evt = d.detect_event(s)
    assert evt is not None
    assert evt.fault_type == FAULT_VELOCITY_ANOMALY
    assert evt.joint_index == 1


# ---------- 持续力矩过载 ----------

def test_torque_overload_requires_persistence():
    d = CompositeFaultDetector(
        n_joints=N_JOINTS, window_size=10, persistence=3,
        torque_overload_threshold=40.0,
    )
    high = [45.0] * 6  # 超过阈值
    # 前 persistence-1 帧不应触发（位置需变化以避免关节卡死检测）
    for k in range(2):
        pos = [float(k) * 0.1] * 6
        s = _state(pos, [0.0] * 6, high)
        assert d.detect_event(s) is None
    # 第 persistence 帧触发
    s = _state([0.3] * 6, [0.0] * 6, high)
    evt = d.detect_event(s)
    assert evt is not None
    assert evt.fault_type == FAULT_TORQUE_OVERLOAD


def test_torque_overload_reset_after_recovery():
    d = CompositeFaultDetector(
        n_joints=N_JOINTS, window_size=10, persistence=3,
        torque_overload_threshold=40.0,
    )
    high = [45.0] * 6
    low = [10.0] * 6
    # 2 帧高力矩（未达 persistence），位置变化避免关节卡死
    for k in range(2):
        d.detect_event(_state([float(k) * 0.1] * 6, [0.0] * 6, high))
    # 1 帧低力矩（重置计数）
    d.detect_event(_state([0.3] * 6, [0.0] * 6, low))
    # 再 2 帧高力矩（计数从头开始，仍不触发）
    for k in range(2):
        pos = [0.4 + float(k) * 0.1] * 6
        assert d.detect_event(_state(pos, [0.0] * 6, high)) is None


# ---------- 关节卡死 ----------

def test_joint_locked_detection():
    d = CompositeFaultDetector(
        n_joints=N_JOINTS, window_size=10, persistence=3,
        lock_position_threshold=0.001, lock_torque_threshold=10.0,
    )
    # 关节 2 卡死：位置恒定 0.5，力矩持续偏高
    for _ in range(3):
        pos = [0.0, 0.0, 0.5, 0.0, 0.0, 0.0]
        tor = [5.0, 5.0, 20.0, 5.0, 5.0, 5.0]
        s = _state(pos, [0.0] * 6, tor)
        evt = d.detect_event(s)
    assert evt is not None
    assert evt.fault_type == FAULT_JOINT_LOCKED
    assert evt.joint_index == 2
    assert evt.is_critical


def test_joint_stationary_no_torque_not_locked():
    """关节静止但无力矩，不算卡死"""
    d = CompositeFaultDetector(
        n_joints=N_JOINTS, window_size=10, persistence=3,
        lock_position_threshold=0.001, lock_torque_threshold=10.0,
    )
    for _ in range(5):
        s = _state([0.0] * 6, [0.0] * 6, [0.0] * 6)
        assert d.detect_event(s) is None


# ---------- 通信超时 ----------

def test_comm_timeout():
    d = CompositeFaultDetector(n_joints=N_JOINTS, comm_timeout_ms=500)
    # 先推入一帧状态
    d.detect_event(_zero_state(ts=1000000000000))
    # 未超时
    assert d.check_timeout(now_ms=1000000000300) is None
    # 超时
    evt = d.check_timeout(now_ms=1000000000600)
    assert evt is not None
    assert evt.fault_type == FAULT_COMM_TIMEOUT
    assert evt.joint_index == -1


# ---------- 优先级：传感器无效 > 速度异常 ----------

def test_sensor_invalid_has_highest_priority():
    d = CompositeFaultDetector(n_joints=N_JOINTS, max_velocity=3.0)
    s = _state(
        [0.0, math.nan, 0.0, 0.0, 0.0, 0.0],
        [4.0, 4.0, 4.0, 4.0, 4.0, 4.0],
        [0.0] * 6,
    )
    evt = d.detect_event(s)
    # 即使所有关节超速，也应先报传感器无效
    assert evt.fault_type == FAULT_SENSOR_INVALID


# ---------- 正常工况无故障 ----------

def test_normal_operation_no_fault():
    d = CompositeFaultDetector(
        n_joints=N_JOINTS, window_size=10, persistence=3,
        max_velocity=3.0, torque_overload_threshold=40.0,
        lock_position_threshold=0.001, lock_torque_threshold=10.0,
    )
    import random
    random.seed(0)
    for _ in range(20):
        pos = [random.uniform(-1, 1) for _ in range(6)]
        vel = [random.uniform(-1, 1) for _ in range(6)]
        tor = [random.uniform(0, 20) for _ in range(6)]
        s = _state(pos, vel, tor)
        assert d.detect_event(s) is None


if __name__ == '__main__':
    import traceback
    tests = [v for k, v in globals().items() if k.startswith('test_') and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} tests passed")
    sys.exit(0 if passed == len(tests) else 1)

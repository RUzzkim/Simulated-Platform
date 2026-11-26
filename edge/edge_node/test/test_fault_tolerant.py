"""容错控制模块测试：关节卡死、传感器无效、力矩过载、速度异常、通信超时"""
import math
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from edge_node.fault.tolerant import FaultTolerantController
from edge_node.model.messages import (
    FAULT_COMM_TIMEOUT,
    FAULT_JOINT_LOCKED,
    FAULT_SENSOR_INVALID,
    FAULT_TORQUE_OVERLOAD,
    FAULT_VELOCITY_ANOMALY,
    FaultEvent,
    RobotState,
)

N_JOINTS = 6
TS = 1760000000123


def _state(position, velocity=None, torque=None, status='RUNNING'):
    return RobotState(
        simulation_id='SIM-001',
        robot_id='ROBOT-001',
        timestamp=TS,
        joint_position=list(position),
        joint_velocity=list(velocity) if velocity else [0.0] * N_JOINTS,
        joint_torque=list(torque) if torque else [0.0] * N_JOINTS,
        status=status,
    )


def _evt(fault_type, joint, severity='ERROR'):
    return FaultEvent(
        fault_type=fault_type,
        joint_index=joint,
        severity=severity,
        timestamp=TS,
    )


# ---------- 无故障时透传 ----------

def test_no_fault_passes_through():
    ftc = FaultTolerantController(n_joints=N_JOINTS)
    state = _state([0.1] * N_JOINTS)
    target = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    out = ftc.compensate(state, target)
    assert out == target


# ---------- 关节卡死 ----------

def test_joint_locked_holds_current_position():
    ftc = FaultTolerantController(n_joints=N_JOINTS, active_replanning=False)
    # 关节 2 卡死
    ftc.update_fault(_evt(FAULT_JOINT_LOCKED, 2))
    state = _state([0.0, 0.0, 0.5, 0.0, 0.0, 0.0])
    target = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    out = ftc.compensate(state, target)
    # 关节 2 保持当前位置 0.5，其余关节跟随目标
    assert out[2] == 0.5
    assert out[0] == 1.0
    assert out[5] == 1.0


def test_joint_locked_active_replanning():
    """主动重规划：锁定关节保持，健康关节被重规划以补偿末端误差"""
    ftc = FaultTolerantController(n_joints=N_JOINTS, active_replanning=True)
    ftc.update_fault(_evt(FAULT_JOINT_LOCKED, 2))
    state = _state([0.0, 0.0, 0.5, 0.0, 0.0, 0.0])
    target = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    out = ftc.compensate(state, target)
    # 关节 2 必须保持当前位置
    assert abs(out[2] - 0.5) < 1e-9
    # 健康关节被重规划（不等于原始目标）
    assert out[0] != 1.0 or out[1] != 1.0 or out[3] != 1.0


def test_v2_task_recovery_replans_reachable_target_after_lock():
    ftc = FaultTolerantController(
        n_joints=N_JOINTS, task_recovery=True, recovery_tolerance=0.005
    )
    ftc.update_fault(_evt(FAULT_JOINT_LOCKED, 0))
    current = [0.0, -0.4, 0.5, 0.0, -0.2, 0.0]
    velocity = [0.0, 1.0, -2.0, 0.0, 0.0, 0.0]
    state = _state(current, velocity=velocity)
    target = [0.2, -0.3, 0.4, 0.2, -0.1, 0.1]

    output = ftc.compensate(state, target)

    assert output[0] == current[0]
    assert output != target
    assert all(math.isfinite(value) for value in output)


def test_v2_uses_final_task_goal_and_keeps_recovery_after_unloading():
    ftc = FaultTolerantController(task_recovery=True, recovery_frames=1)
    current = [0.0, -0.4, 0.5, 0.0, -0.2, 0.0]
    goal = [0.0, -0.1, 0.8, 0.0, -0.2, 0.0]
    state = _state(current)
    ftc.update_fault(_evt(FAULT_JOINT_LOCKED, 0))
    command = ftc.compensate(state, current, task_goal=goal)
    for _ in range(1000):
        state = _state(command)
        command = ftc.compensate(state, current, task_goal=goal)
    from edge_node.fault.kinematics import forward_kinematics
    endpoint, _ = forward_kinematics(goal)
    reached, _ = forward_kinematics(command)
    assert math.dist(reached, endpoint) <= 0.04
    assert command[0] == current[0]
    ftc.update_fault(None)
    assert not ftc.has_any_fault
    assert ftc.requires_compensation
    followup = ftc.compensate(state, [1.0] * 6, task_goal=goal)
    assert followup != [1.0] * 6
    assert followup[0] == current[0]
    ftc.reset()
    assert not ftc.requires_compensation
    assert ftc.compensate(state, current, task_goal=goal) == current


def test_v2_safe_stop_stays_active_after_detector_clears():
    ftc = FaultTolerantController(task_recovery=True, recovery_frames=1)
    state = _state([0.0, -0.4, 0.5, 0.0, -0.2, 0.0], [0.0, 0.3, 0.0, 0.0, 0.0, 0.0])
    for joint in range(N_JOINTS):
        ftc.update_fault(_evt(FAULT_JOINT_LOCKED, joint))
    braking_target = ftc.compensate(state, state.joint_position, task_goal=[math.pi] + [0.0] * 5)
    assert ftc.last_recovery_decision.action == 'STOP'
    ftc.update_fault(None)
    assert ftc.requires_compensation
    assert ftc.compensate(state, [0.0] * 6) == braking_target
    assert ftc.compensate(state, [0.0] * 6, task_goal=[0.2] * 6) == braking_target
    ftc.reset()
    assert not ftc.requires_compensation


def test_v2_task_recovery_disabled_keeps_v1_behavior():
    ftc = FaultTolerantController(n_joints=N_JOINTS, task_recovery=False)
    v1 = FaultTolerantController(n_joints=N_JOINTS)
    ftc.update_fault(_evt(FAULT_JOINT_LOCKED, 0))
    v1.update_fault(_evt(FAULT_JOINT_LOCKED, 0))
    state = _state([0.2, 0.0, 0.0, 0.0, 0.0, 0.0])
    target = [1.0] * N_JOINTS

    output = ftc.compensate(state, target)
    v1_output = v1.compensate(state, target)

    assert output == v1_output


def test_v2_safe_stop_decision_is_latched_until_reset():
    ftc = FaultTolerantController(
        n_joints=N_JOINTS, task_recovery=True, recovery_tolerance=0.005
    )
    ftc.update_fault(_evt(FAULT_JOINT_LOCKED, 0))
    state = _state([0.0, -0.4, 0.5, 0.0, -0.2, 0.0])
    unreachable_target = [math.pi, 0.0, 0.0, 0.0, 0.0, 0.0]

    ftc.compensate(state, unreachable_target)
    next_output = ftc.compensate(state, [0.0] * N_JOINTS)

    assert ftc.last_recovery_decision.action == "STOP"
    assert next_output == state.joint_position


def test_v2_recovery_command_obeys_velocity_and_acceleration_limits():
    dt = 0.01
    max_velocity = 1.0
    max_acceleration = 2.0
    ftc = FaultTolerantController(
        n_joints=N_JOINTS,
        task_recovery=True,
        recovery_tolerance=0.005,
        control_dt=dt,
        recovery_max_velocity=max_velocity,
        recovery_max_acceleration=max_acceleration,
    )
    current = [0.0, -0.4, 0.5, 0.0, -0.2, 0.0]
    goal = [0.0, -0.1, 0.8, 0.0, -0.2, 0.0]
    state = _state(current)
    ftc.update_fault(_evt(FAULT_JOINT_LOCKED, 0))

    outputs = [ftc.compensate(state, current, task_goal=goal)]
    for _ in range(1000):
        state = _state(outputs[-1])
        outputs.append(ftc.compensate(state, current, task_goal=goal))

    for previous, current_command, following in zip(outputs, outputs[1:], outputs[2:]):
        velocity = [(b - a) / dt for a, b in zip(previous, current_command)]
        next_velocity = [(b - a) / dt for a, b in zip(current_command, following)]
        assert max(map(abs, velocity)) <= max_velocity + 1e-9
        assert max(abs(b - a) / dt for a, b in zip(velocity, next_velocity)) <= max_acceleration + 1e-8
    assert max(abs(a - b) for a, b in zip(outputs[-1], ftc.last_recovery_decision.target_q)) <= 0.02


# ---------- 传感器无效 ----------

def test_sensor_invalid_holds_last_good_position():
    ftc = FaultTolerantController(n_joints=N_JOINTS, active_replanning=False)
    # 先记录关节 3 的有效位置
    state1 = _state([0.0, 0.0, 0.0, 0.8, 0.0, 0.0])
    ftc.compensate(state1, [0.0] * N_JOINTS)
    # 关节 3 传感器失效
    ftc.update_fault(_evt(FAULT_SENSOR_INVALID, 3))
    state2 = _state([0.0, 0.0, 0.0, 9.9, 0.0, 0.0])  # 失效数据，不可信
    target = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    out = ftc.compensate(state2, target)
    # 关节 3 保持最后已知有效位置 0.8
    assert abs(out[3] - 0.8) < 1e-9
    assert out[0] == 1.0


# ---------- 力矩过载 ----------

def test_torque_overload_scales_error():
    scale = 0.3
    ftc = FaultTolerantController(n_joints=N_JOINTS, torque_overload_scale=scale)
    ftc.update_fault(_evt(FAULT_TORQUE_OVERLOAD, 1))
    # 关节 1 当前 0.0，目标 1.0，误差 1.0
    state = _state([0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    target = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    out = ftc.compensate(state, target)
    # 关节 1 目标 = 当前 + 误差 * scale = 0.0 + 1.0 * 0.3 = 0.3
    assert abs(out[1] - 0.3) < 1e-9
    assert out[0] == 1.0


# ---------- 速度异常 ----------

def test_velocity_anomaly_clamps_delta():
    clamp = 0.05
    ftc = FaultTolerantController(n_joints=N_JOINTS, velocity_clamp=clamp)
    # 先建立 last_target
    state0 = _state([0.0] * N_JOINTS)
    ftc.compensate(state0, [0.0] * N_JOINTS)
    # 关节 4 速度异常
    ftc.update_fault(_evt(FAULT_VELOCITY_ANOMALY, 4))
    state = _state([0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    target = [0.0, 0.0, 0.0, 0.0, 0.5, 0.0]  # 关节 4 跳变 0.5
    out = ftc.compensate(state, target)
    # 关节 4 变化被限幅到 clamp
    assert abs(out[4] - clamp) < 1e-9
    assert out[0] == 0.0


# ---------- 通信超时 ----------

def test_comm_timeout_freezes_output():
    ftc = FaultTolerantController(n_joints=N_JOINTS)
    # 先建立 last_target
    state0 = _state([0.0] * N_JOINTS)
    ftc.compensate(state0, [0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
    # 通信超时
    ftc.update_fault(_evt(FAULT_COMM_TIMEOUT, -1))
    state = _state([0.0] * N_JOINTS)
    target = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    out = ftc.compensate(state, target)
    # 输出冻结为上次目标
    assert out == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]


# ---------- 故障恢复 ----------

def test_fault_recovery_after_clean_frames():
    recovery = 3
    ftc = FaultTolerantController(n_joints=N_JOINTS, recovery_frames=recovery)
    ftc.update_fault(_evt(FAULT_JOINT_LOCKED, 0))
    assert ftc.is_joint_faulty(0)
    # 连续无故障帧
    for _ in range(recovery):
        ftc.update_fault(None)
    # 故障清除，控制恢复正常
    assert not ftc.is_joint_faulty(0)
    state = _state([0.0] * N_JOINTS)
    target = [1.0] * N_JOINTS
    out = ftc.compensate(state, target)
    assert out == target


def test_fault_not_recovered_before_threshold():
    ftc = FaultTolerantController(n_joints=N_JOINTS, recovery_frames=5)
    ftc.update_fault(_evt(FAULT_JOINT_LOCKED, 0))
    for _ in range(4):  # 还差 1 帧
        ftc.update_fault(None)
    assert ftc.is_joint_faulty(0)


# ---------- 故障优先级 ----------

def test_locked_takes_priority_over_overload():
    ftc = FaultTolerantController(n_joints=N_JOINTS, torque_overload_scale=0.3)
    ftc.update_fault(_evt(FAULT_JOINT_LOCKED, 0))
    ftc.update_fault(_evt(FAULT_TORQUE_OVERLOAD, 0))
    state = _state([0.5, 0.0, 0.0, 0.0, 0.0, 0.0])
    target = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    out = ftc.compensate(state, target)
    # 卡死优先级高于过载，应保持当前位置
    assert out[0] == 0.5


# ---------- 多关节独立故障 ----------

def test_multiple_joints_independent_faults():
    ftc = FaultTolerantController(
        n_joints=N_JOINTS, torque_overload_scale=0.5, active_replanning=False
    )
    ftc.update_fault(_evt(FAULT_JOINT_LOCKED, 0))
    ftc.update_fault(_evt(FAULT_TORQUE_OVERLOAD, 2))
    state = _state([0.1, 0.0, 0.0, 0.0, 0.0, 0.0])
    target = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    out = ftc.compensate(state, target)
    assert out[0] == 0.1           # 卡死：保持
    assert out[1] == 1.0           # 正常：跟随
    assert abs(out[2] - 0.5) < 1e-9  # 过载：误差 * 0.5
    assert out[5] == 1.0           # 正常：跟随


# ---------- has_any_fault ----------

def test_has_any_fault_flag():
    ftc = FaultTolerantController(n_joints=N_JOINTS)
    assert not ftc.has_any_fault
    ftc.update_fault(_evt(FAULT_TORQUE_OVERLOAD, 0))
    assert ftc.has_any_fault
    ftc.reset()
    assert not ftc.has_any_fault


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

"""运动学与主动容错轨迹重规划器测试

覆盖：
  - 正运动学（FK）零位姿与基本变换
  - 雅可比维度与有限差分一致性
  - DLS 逆运动学（无锁定 / 关节锁定）
  - 重规划器：末端误差收敛、锁定关节保持、关节限位
"""
import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from edge_node.fault.kinematics import (
    compute_jacobian,
    compute_pose,
    dls_inverse,
    forward_kinematics,
)
from edge_node.fault.replanner import TrajectoryReplanner


def approx(a, b, eps=1e-6):
    return abs(a - b) < eps


def all_approx(a, b, eps=1e-6):
    return all(approx(x, y, eps) for x, y in zip(a, b))


# ---------- 正运动学 ----------

def test_forward_kinematics_returns_position_and_rotation():
    q = [0.0] * 6
    pos, R = forward_kinematics(q)
    assert len(pos) == 3
    assert len(R) == 3 and len(R[0]) == 3
    # 零位姿时末端应有非零延伸
    assert math.hypot(pos[0], pos[1], pos[2]) > 0.3


def test_compute_pose_returns_6d():
    q = [0.1, -0.3, 0.5, 0.2, -0.1, 0.4]
    pose = compute_pose(q)
    assert len(pose) == 6


def test_forward_kinematics_j1_rotation():
    """J1 绕 z 轴旋转，应影响 x/y 不影响 z"""
    q0 = [0.0] * 6
    pos0, _ = forward_kinematics(q0)
    q1 = [math.pi / 2] + [0.0] * 5
    pos1, _ = forward_kinematics(q1)
    # z 不变
    assert approx(pos0[2], pos1[2], 1e-9)
    # J1=π/2 使 (x, y) → (-y, x)
    assert approx(pos0[0], pos1[1], 1e-9)
    assert approx(pos0[1], -pos1[0], 1e-9)


# ---------- 雅可比 ----------

def test_jacobian_dimensions():
    q = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    J = compute_jacobian(q)
    assert len(J) == 6
    for row in J:
        assert len(row) == 6


def test_jacobian_finite_difference_consistency():
    """验证数值微分雅可比与有限差分一致"""
    q = [0.1, -0.2, 0.15, 0.05, -0.1, 0.3]
    J = compute_jacobian(q, eps=1e-6)
    base = compute_pose(q)
    eps = 1e-4
    for j in range(6):
        perturbed = list(q)
        perturbed[j] += eps
        perturbed_pose = compute_pose(perturbed)
        for i in range(3):  # 仅检查位置部分（姿态在奇异处可能跳变）
            expected = (perturbed_pose[i] - base[i]) / eps
            assert approx(J[i][j], expected, 1e-3), f"J[{i}][{j}] diff"


# ---------- DLS 逆运动学 ----------

def test_dls_inverse_no_lock():
    J = compute_jacobian([0.1] * 6)
    dx = [0.01, 0.0, 0.0, 0.0, 0.0, 0.0]
    dq = dls_inverse(J, dx, damping=0.05)
    assert len(dq) == 6
    # 有 x 方向速度，健康关节应有非零解
    assert any(abs(d) > 1e-9 for d in dq)


def test_dls_inverse_locked_joints_zero():
    """锁定关节的 dq 必须为 0"""
    J = compute_jacobian([0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
    dx = [0.01, 0.01, 0.0, 0.0, 0.0, 0.0]
    locked = [0, 3]
    dq = dls_inverse(J, dx, damping=0.05, locked_joints=locked)
    assert approx(dq[0], 0.0)
    assert approx(dq[3], 0.0)
    # 健康关节应非零
    assert any(abs(dq[i]) > 1e-9 for i in range(6) if i not in locked)


def test_dls_inverse_damping_avoids_singularity():
    """在奇异位姿（全零关节）下 DLS 应能给出有界解"""
    J = compute_jacobian([0.0] * 6)
    dx = [0.1, 0.1, 0.1, 0.1, 0.1, 0.1]
    dq = dls_inverse(J, dx, damping=0.1)
    # 解应是有限的
    for d in dq:
        assert math.isfinite(d)
        assert abs(d) < 1e4  # 不会爆炸


# ---------- 轨迹重规划器 ----------

def test_replanner_reduces_error():
    """重规划后末端误差应减小"""
    replanner = TrajectoryReplanner(
        n_joints=6, damping=0.05, step_size=0.5
    )
    current_q = [0.0, -0.5, 0.5, 0.0, 0.0, 0.0]
    target_q = [0.3, -0.8, 0.9, 0.2, 0.1, 0.0]
    desired_pose = compute_pose(target_q)

    err_before = replanner.end_effector_error(current_q, desired_pose)
    err_norm_before = math.sqrt(sum(e * e for e in err_before))

    new_q = replanner.replan(current_q, desired_pose, locked_joints=None)
    err_after = replanner.end_effector_error(new_q, desired_pose)
    err_norm_after = math.sqrt(sum(e * e for e in err_after))

    assert err_norm_after < err_norm_before, (
        f"误差未减小: {err_norm_before:.4f} -> {err_norm_after:.4f}"
    )


def test_replanner_locked_joints_unchanged():
    """锁定关节在重规划后保持不变"""
    replanner = TrajectoryReplanner(n_joints=6, step_size=0.8)
    current_q = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    target_q = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
    desired_pose = compute_pose(target_q)
    locked = [2, 4]

    new_q = replanner.replan(current_q, desired_pose, locked_joints=locked)
    for i in locked:
        assert approx(new_q[i], current_q[i], 1e-9), f"关节 {i} 应保持锁定"


def test_replanner_replan_from_target():
    """replan_from_target 与手动调用 replan 等价"""
    replanner = TrajectoryReplanner(n_joints=6)
    current_q = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    target_q = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5]

    out1 = replanner.replan_from_target(current_q, target_q, locked_joints=None)
    desired_pose = compute_pose(target_q)
    out2 = replanner.replan(current_q, desired_pose, locked_joints=None)

    assert all_approx(out1, out2, 1e-9)


def test_replanner_joint_limits_respected():
    """关节限位钳制生效"""
    limits = [[-1.0, 1.0]] * 6
    replanner = TrajectoryReplanner(n_joints=6, joint_limits=limits, step_size=1.0)
    current_q = [0.0] * 6
    target_q = [2.0, 2.0, 2.0, 2.0, 2.0, 2.0]
    desired_pose = compute_pose(target_q)
    new_q = replanner.replan(current_q, desired_pose, locked_joints=None)
    for i in range(6):
        assert -1.0 - 1e-9 <= new_q[i] <= 1.0 + 1e-9


def test_replanner_iterative_convergence():
    """多次迭代重规划，末端误差持续下降"""
    replanner = TrajectoryReplanner(n_joints=6, damping=0.03, step_size=0.6)
    current_q = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    target_q = [0.2, -0.6, 0.8, 0.1, 0.0, 0.3]
    desired_pose = compute_pose(target_q)

    prev_norm = math.inf
    q = list(current_q)
    for _ in range(20):
        err = replanner.end_effector_error(q, desired_pose)
        norm = math.sqrt(sum(e * e for e in err))
        assert norm <= prev_norm + 1e-9  # 误差不上升
        prev_norm = norm
        q = replanner.replan(q, desired_pose, locked_joints=None)

    # 迭代 20 步后误差应显著下降
    err_final = replanner.end_effector_error(q, desired_pose)
    norm_final = math.sqrt(sum(e * e for e in err_final))
    assert norm_final < 0.05


# ---------- 容错控制器集成 ----------

def test_ftc_active_replanning_locked_joint_holds():
    """FTC 集成主动重规划：锁定关节保持，整体输出有效"""
    from edge_node.fault.tolerant import FaultTolerantController
    from edge_node.model.messages import FAULT_JOINT_LOCKED, FaultEvent, RobotState

    ftc = FaultTolerantController(n_joints=6, active_replanning=True)
    ftc.update_fault(FaultEvent(
        fault_type=FAULT_JOINT_LOCKED, joint_index=2,
        severity='ERROR', timestamp=1760000000123,
    ))
    q = [0.1, 0.2, 0.5, 0.3, 0.4, 0.5]
    state = RobotState(
        simulation_id='SIM-001', robot_id='ROBOT-001', timestamp=1760000000123,
        joint_position=q, joint_velocity=[0.0] * 6, joint_torque=[0.0] * 6,
        status='RUNNING',
    )
    target = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
    out = ftc.compensate(state, target)

    # 锁定关节保持
    assert approx(out[2], 0.5, 1e-9)
    # 输出长度正确
    assert len(out) == 6


if __name__ == '__main__':
    import traceback

    tests = [
        test_forward_kinematics_returns_position_and_rotation,
        test_compute_pose_returns_6d,
        test_forward_kinematics_j1_rotation,
        test_jacobian_dimensions,
        test_jacobian_finite_difference_consistency,
        test_dls_inverse_no_lock,
        test_dls_inverse_locked_joints_zero,
        test_dls_inverse_damping_avoids_singularity,
        test_replanner_reduces_error,
        test_replanner_locked_joints_unchanged,
        test_replanner_replan_from_target,
        test_replanner_joint_limits_respected,
        test_replanner_iterative_convergence,
        test_ftc_active_replanning_locked_joint_holds,
    ]

    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            passed += 1
        except Exception:
            print(f"FAIL {t.__name__}:")
            traceback.print_exc()

    print(f"\n{passed}/{len(tests)} tests passed")
    sys.exit(0 if passed == len(tests) else 1)

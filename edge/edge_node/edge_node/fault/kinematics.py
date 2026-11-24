"""6R 机械臂运动学模块（纯 Python，无 numpy 依赖）

包含：
  - 正运动学 FK：关节角 → 末端位姿（位置 + 旋转矩阵）
  - 几何雅可比：关节速度 → 末端速度（数值微分法）
  - 阻尼最小二乘 DLS 逆解：末端速度 → 关节速度（支持关节锁定约束）

使用通用 6R 机械臂 DH 参数，适用于仿真平台验证。
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

# ---- 矩阵运算工具（纯 Python）----

def _mat_mul(A: List[List[float]], B: List[List[float]]) -> List[List[float]]:
    """矩阵乘法 A(m×k) * B(k×n) → C(m×n)"""
    m, k = len(A), len(A[0])
    n = len(B[0])
    C = [[0.0] * n for _ in range(m)]
    for i in range(m):
        Ai = A[i]
        for t in range(k):
            a = Ai[t]
            if a == 0.0:
                continue
            Bt = B[t]
            Ci = C[i]
            for j in range(n):
                Ci[j] += a * Bt[j]
    return C


def _mat_vec(A: List[List[float]], v: List[float]) -> List[float]:
    """矩阵乘向量 A(m×n) * v(n) → 结果(m)"""
    m, n = len(A), len(A[0])
    result = [0.0] * m
    for i in range(m):
        s = 0.0
        Ai = A[i]
        for j in range(n):
            s += Ai[j] * v[j]
        result[i] = s
    return result


def _transpose(A: List[List[float]]) -> List[List[float]]:
    """矩阵转置"""
    m, n = len(A), len(A[0])
    return [[A[i][j] for i in range(m)] for j in range(n)]


def _identity(n: int) -> List[List[float]]:
    """n×n 单位矩阵"""
    I = [[0.0] * n for _ in range(n)]
    for i in range(n):
        I[i][i] = 1.0
    return I


def _solve_linear(A: List[List[float]], b: List[float]) -> Optional[List[float]]:
    """高斯消元法解线性方程组 Ax = b，A 为 n×n"""
    n = len(A)
    # 构造增广矩阵
    M = [row[:] + [b[i]] for i, row in enumerate(A)]

    for col in range(n):
        # 选主元
        max_row = col
        max_val = abs(M[col][col])
        for row in range(col + 1, n):
            if abs(M[row][col]) > max_val:
                max_val = abs(M[row][col])
                max_row = row
        if max_val < 1e-12:
            return None  # 奇异矩阵
        M[col], M[max_row] = M[max_row], M[col]

        pivot = M[col][col]
        for j in range(col, n + 1):
            M[col][j] /= pivot
        for row in range(n):
            if row == col:
                continue
            factor = M[row][col]
            if factor == 0.0:
                continue
            for j in range(col, n + 1):
                M[row][j] -= factor * M[col][j]

    return [M[i][n] for i in range(n)]


# ---- DH 参数（通用 6R 机械臂）----
# 顺序：theta, d, a, alpha（标准 DH）
# 单位：m / rad
DH_PARAMS: List[Tuple[float, float, float, float]] = [
    # theta_offset, d,      a,      alpha
    (0.0,       0.300,  0.000,  math.pi / 2),   # J1: 底座
    (0.0,       0.000,  0.300,  0.0),           # J2: 肩关节
    (0.0,       0.000,  0.250,  0.0),           # J3: 肘关节
    (0.0,       0.000,  0.000,  math.pi / 2),   # J4: 腕1
    (0.0,       0.100,  0.000, -math.pi / 2),   # J5: 腕2
    (0.0,       0.100,  0.000,  0.0),           # J6: 腕3
]


def _dh_matrix(theta: float, d: float, a: float, alpha: float) -> List[List[float]]:
    """计算单个 DH 变换矩阵"""
    ct, st = math.cos(theta), math.sin(theta)
    ca, sa = math.cos(alpha), math.sin(alpha)
    return [
        [ct,    -st * ca,  st * sa,  a * ct],
        [st,     ct * ca, -ct * sa,  a * st],
        [0.0,    sa,        ca,       d     ],
        [0.0,    0.0,       0.0,      1.0   ],
    ]


def forward_kinematics(joint_angles: Sequence[float]) -> Tuple[List[float], List[List[float]]]:
    """正运动学

    :param joint_angles: 6 个关节角（rad）
    :return: (末端位置 [x, y, z], 末端旋转矩阵 3×3)
    """
    T = _identity(4)
    for i, theta in enumerate(joint_angles):
        _, d, a, alpha = DH_PARAMS[i]
        T = _mat_mul(T, _dh_matrix(theta, d, a, alpha))

    pos = [T[0][3], T[1][3], T[2][3]]
    R = [[T[i][j] for j in range(3)] for i in range(3)]
    return pos, R


def _rotation_to_rpy(R: List[List[float]]) -> List[float]:
    """旋转矩阵 → ZYX 欧拉角 (roll, pitch, yaw)"""
    sy = math.sqrt(R[0][0] ** 2 + R[1][0] ** 2)
    singular = sy < 1e-6
    if not singular:
        roll = math.atan2(R[2][1], R[2][2])
        pitch = math.atan2(-R[2][0], sy)
        yaw = math.atan2(R[1][0], R[0][0])
    else:
        roll = math.atan2(-R[1][2], R[1][1])
        pitch = math.atan2(-R[2][0], sy)
        yaw = 0.0
    return [roll, pitch, yaw]


def compute_pose(joint_angles: Sequence[float]) -> List[float]:
    """计算末端 6D 位姿 [x, y, z, roll, pitch, yaw]"""
    pos, R = forward_kinematics(joint_angles)
    rpy = _rotation_to_rpy(R)
    return pos + rpy


def compute_jacobian(joint_angles: Sequence[float], eps: float = 1e-6) -> List[List[float]]:
    """几何雅可比（数值微分法）

    :param joint_angles: 6 个关节角
    :param eps: 有限差分步长
    :return: 6×6 雅可比矩阵 J[i][j]，行对应 [x, y, z, roll, pitch, yaw]，列对应关节
    """
    n = len(joint_angles)
    base = compute_pose(joint_angles)
    J = [[0.0] * n for _ in range(6)]

    for j in range(n):
        perturbed = list(joint_angles)
        perturbed[j] += eps
        perturbed_pose = compute_pose(perturbed)
        for i in range(6):
            J[i][j] = (perturbed_pose[i] - base[i]) / eps

    return J


def dls_inverse(
    J: List[List[float]],
    dx: List[float],
    damping: float = 0.1,
    locked_joints: Optional[Sequence[int]] = None,
) -> List[float]:
    """阻尼最小二乘逆运动学

    dq = J^T (J J^T + λ²I)^{-1} dx

    :param J: 6×n 雅可比
    :param dx: 6D 任务空间速度/误差 [x, y, z, rx, ry, rz]
    :param damping: 阻尼系数 λ
    :param locked_joints: 锁定关节索引集合，这些关节的 dq 强制为 0
    :return: n 维关节速度
    """
    n = len(J[0])
    locked = set(locked_joints or [])

    if locked:
        # 只保留健康关节列
        healthy = [j for j in range(n) if j not in locked]
        J_reduced = [[J[i][j] for j in healthy] for i in range(6)]
    else:
        healthy = list(range(n))
        J_reduced = J

    m = len(healthy)
    # J J^T + λ²I  (6×6)
    JJT = _mat_mul(J_reduced, _transpose(J_reduced))
    lam2 = damping * damping
    for i in range(6):
        JJT[i][i] += lam2

    # 解 (J J^T + λ²I) y = dx
    y = _solve_linear(JJT, dx)
    if y is None:
        # 奇异，返回零
        return [0.0] * n

    # dq_reduced = J_reduced^T * y
    JT = _transpose(J_reduced)
    dq_reduced = _mat_vec(JT, y)

    # 还原到全关节空间
    dq = [0.0] * n
    for idx, j in enumerate(healthy):
        dq[j] = dq_reduced[idx]
    return dq

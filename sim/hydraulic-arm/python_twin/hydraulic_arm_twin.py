"""液压机械臂动力学数值孪生（Hydraulic Arm Numerical Twin）

用途：验证液压机械臂动力学模型、执行器量级和自适应控制器。

模型结构（6 自由度串联，6 个关节均由阀控液压摆动马达驱动）：
   1) 机械臂刚体动力学   M(q)qdd + C(q,qd)qd + G(q) + F_f(qd) = tau
   2) 电液伺服阀二阶动力学   xvdd + 2*zeta*wn*xvd + wn^2*xv = wn^2*u
   3) 液压执行器压力动力学
          dP1/dt = (beta_e/V1)(Q1 - Dm*qd - Ct*(P1-P2))
          dP2/dt = (beta_e/V2)(-Q2 + Dm*qd - Ct*(P1-P2))
   4) 输出关节力矩   tau = Dm*(P1 - P2)

摩擦口径与 edge/edge_node/test/simulation_simulator.py 保持一致：
   粘性 + 库仑 + Stribeck，均用 tanh 平滑，避免仿真在零速抖振。

参数取值依据见 docs/parameter_sources.md，建模推导见 docs/model_derivation.md。
"""
from __future__ import annotations

import math
import os
import sys
import time

import numpy as np

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results")
SHARED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared")

# ---------------------------------------------------------------------------
# 1. 物理参数（与 params_hydraulic_arm.m 同源，改一处必须同步另一处）
# ---------------------------------------------------------------------------
PARAMS = {
    "n_joints": 6,
    # 标准 DH：a(m), alpha(rad), d(m)
    "dh": [
        (0.00, math.pi / 2, 0.18),
        (0.50, 0.00, 0.00),
        (0.45, 0.00, 0.00),
        (0.00, math.pi / 2, 0.12),
        (0.00, -math.pi / 2, 0.00),
        (0.00, 0.00, 0.08),
    ],
    # 连杆质量 kg / 质心（本体系，m）/ 惯量张量对角（kg*m^2，绕质心）
    # 注意：第 1 连杆本体系的 y 轴为竖直方向，故腰部质心偏移写在 y 上，
    #       使其位于回转轴线上，不产生绕 J1 的重力矩。
    "links": [
        {"m": 110.0, "com": (0.000, 0.090, 0.000), "I": (2.00, 2.00, 3.00), "Jm": 0.30},
        {"m": 55.0, "com": (0.250, 0.000, 0.000), "I": (0.30, 1.146, 1.146), "Jm": 0.60},
        {"m": 32.0, "com": (0.225, 0.000, 0.000), "I": (0.12, 0.540, 0.540), "Jm": 0.20},
        {"m": 12.0, "com": (0.000, 0.000, 0.030), "I": (0.020, 0.020, 0.025), "Jm": 0.05},
        {"m": 6.0, "com": (0.000, 0.000, 0.020), "I": (0.008, 0.008, 0.010), "Jm": 0.04},
        {"m": 5.0, "com": (0.000, 0.000, 0.030), "I": (0.005, 0.005, 0.007), "Jm": 0.03},
    ],
    "payload_mass": 30.0,      # 额定负载 kg，加载到末端连杆质心
    "payload_com": (0.10, 0.0, 0.08),
    "g": 9.81,
    # 液压系统（GB/T 2346-2003 公称压力系列取 25 MPa）
    "hyd": {
        "p_supply": 25.0e6,     # Pa
        "p_return": 1.0e6,      # Pa
        "beta_e": 1.0e9,        # Pa，油液体积弹性模量（含气量按 1% 估）
        "hose_vol_cm3": 15.0,   # cm^3，单腔管路与阀块容积
        "vol_per_disp": 2.0,    # 单腔容积 = hose_vol + vol_per_disp*Dm（约扫过 2 rad）
        "leak_coef": 1.0e-12,   # m^3/(s*Pa)，总阻尼系数（内泄漏 + 阀口压力流量系数）
        "kv": 6.3e-8,           # 阀流量系数，Q = kv*xv*sqrt(dP)
        "omega_n": 2.0 * math.pi * 60.0,   # rad/s，伺服阀固有频率 60 Hz
        "zeta": 0.7,                        # 伺服阀阻尼比
        # 摆动马达排量 cm^3/rev（GB/T 2348-2018 米制系列选型）
        "disp_cm3_rev": [250.0, 400.0, 160.0, 50.0, 40.0, 30.0],
    },
    # 摩擦：粘性 / 库仑 / Stribeck 附加 / Stribeck 速度 / 平滑系数
    "friction": {
        "viscous": [12.0, 25.0, 8.0, 2.5, 2.0, 1.2],
        "coulomb": [25.0, 40.0, 16.0, 5.0, 4.0, 3.0],
        "stribeck": [10.0, 18.0, 7.0, 2.0, 1.5, 1.0],
        "v_s": 0.05,
        "eps": 1.0e-3,
    },
    # 控制器：默认值与 edge/edge_node/config/edge_config.yaml 的 control 段一致
    "ctrl": {
        "lambda_gain": 10.0,
        "kd": 50.0,
        "learning_rate": 0.1,
        "leakage": 0.001,
        "n_centers": 64,
        "n_centers_tuned": 256,                   # 整定后的中心数
        "nominal_inertia": 1.0,
        "position_range": 3.14,
        "velocity_range": 2.0,
        "rbf_width": 1.0 / math.sqrt(2.0 * 64),   # 边端原值，见 docs 的偏差说明
        "bandwidth": 12.0,                        # rad/s，闭环带宽上限
        "bw_hyd_ratio": 0.25,                     # 闭环带宽 / 液压阻尼极点 之比上限
        "bw_hyd_ratio_j5": 0.25,                  # pdff_j5 下 J5 单独的带宽比（线性映射保留阻尼，可高于反解关节）
        "damping_ratio": 0.9,                     # 闭环期望阻尼比
        "lrate_tuned": 200.0,                     # 整定后 RBF 学习率
        "rbf_width_tuned": 0.60,                  # 整定后高斯核宽度
    },
    "sim": {"dt": 1.0e-3, "t_end": 8.0},
    "traj": {"t_move": 3.0, "t_hold": 1.0},
    "home": [0.0, 0.35, -0.72, 0.20, 0.0, 0.0],
    "target": [0.50, 0.85, -1.05, 0.45, 0.30, 0.40],
}


def motor_displacement(p):
    """摆动马达排量 Dm [m^3/rad]"""
    return np.array(p["hyd"]["disp_cm3_rev"]) * 1e-6 / (2.0 * math.pi)


def chamber_volumes(p):
    """单腔等效容积 [m^3]：管路容积 + 与排量成比例的腔室容积"""
    hyd = p["hyd"]
    dm_cm3 = np.array(hyd["disp_cm3_rev"]) / (2.0 * math.pi)
    return (hyd["hose_vol_cm3"] + hyd["vol_per_disp"] * dm_cm3) * 1e-6


def valve_torque_gain(p):
    """阀口静态力矩增益 K_u [N*m / 单位阀口开度]

    堵转（qd=0）时压力由进油流量与总阻尼的平衡决定：tau = (Dm*Kq/Ct)*xv。
    令 u = tau_cmd / K_u，执行器在小信号下即表现为单位增益的力矩源。
    """
    hyd = p["hyd"]
    kq = hyd["kv"] * math.sqrt(hyd["p_supply"] - hyd["p_return"])
    return motor_displacement(p) * kq / hyd["leak_coef"]


def actuator_torque_limit(p):
    """各关节最大输出力矩 T_max = (Ps - Pr) * Dm  [N*m]"""
    hyd = p["hyd"]
    dp = hyd["p_supply"] - hyd["p_return"]
    return dp * motor_displacement(p), motor_displacement(p)


def hydraulic_poles(p, m_diag):
    """液压固有频率 wh 与阻尼比 zeta_h

    (V/2beta) dPL/dt = Kq*xv - Dm*qd - Ct*PL,   M*qdd = Dm*PL
    => wh = sqrt(2*beta*Dm^2/(V*M)),   zeta_h = beta*Ct/(V*wh)
    """
    hyd = p["hyd"]
    dm = motor_displacement(p)
    vol = chamber_volumes(p)
    wh = np.sqrt(2.0 * hyd["beta_e"] * dm ** 2
                 / (vol * np.asarray(m_diag, dtype=float)))
    zeta = hyd["beta_e"] * hyd["leak_coef"] / (vol * wh)
    return wh, zeta


def hydraulic_damping_pole(p):
    """液压阻尼极点 2*beta*Ct/V [rad/s]，回路穿越频率的上限尺度"""
    hyd = p["hyd"]
    return 2.0 * hyd["beta_e"] * hyd["leak_coef"] / chamber_volumes(p)


# ---------------------------------------------------------------------------
# 2. 刚体动力学：递归牛顿-欧拉（RNEA），纯 numpy，无工具箱依赖
# ---------------------------------------------------------------------------
def _dh_frame(i, q, p):
    """第 i 个连杆的标准 DH 变换分量：R（本体系->父系）、pos（原点在父系中位置）"""
    a, alpha, d = p["dh"][i]
    theta = q[i]
    ct, st = math.cos(theta), math.sin(theta)
    ca, sa = math.cos(alpha), math.sin(alpha)
    rz = np.array([[ct, -st, 0.0], [st, ct, 0.0], [0.0, 0.0, 1.0]])
    rx = np.array([[1.0, 0.0, 0.0], [0.0, ca, -sa], [0.0, sa, ca]])
    return rz @ rx, np.array([a * ct, a * st, d])


def rnea(q, qd, qdd, p, gravity_on=True, payload=0.0):
    """递归牛顿-欧拉逆动力学：给定 (q, qd, qdd) 求 tau

    重力关闭且 qd=0、qdd=e_j 时，返回 M(q) 的第 j 列。
    """
    n = p["n_joints"]
    g = p["g"] if gravity_on else 0.0

    rots, poss = [], []
    for i in range(n):
        r, pos = _dh_frame(i, q, p)
        rots.append(r)
        poss.append(pos)

    z = np.array([0.0, 0.0, 1.0])
    w_prev, wd_prev = np.zeros(3), np.zeros(3)
    vd_prev = np.array([0.0, 0.0, g])       # Craig: vd_0 = -g0

    F, N, pci_all = [], [], []
    for i in range(n):
        link = p["links"][i]
        rt = rots[i].T
        pos = poss[i]
        m = link["m"] + (payload if i == n - 1 else 0.0)
        pci = np.array(link["com"], dtype=float)
        if i == n - 1 and payload > 0.0:
            pci = (pci * link["m"] + np.array(p["payload_com"]) * payload) / m
        # 关节轴在本体系中的方向 a = (0, sin(alpha), cos(alpha))，
        # 马达转子折算惯量按 Jm * a a^T 叠加到连杆惯量上
        axis = np.array([0.0, math.sin(p["dh"][i][1]), math.cos(p["dh"][i][1])])
        ici = np.diag(link["I"]) + link["Jm"] * np.outer(axis, axis)

        # 标准 DH：关节 i 绕 z_{i-1} 旋转，故先在父系叠加再旋到本体系
        w = rt @ (w_prev + z * qd[i])
        wd = rt @ (wd_prev + z * qdd[i] + np.cross(w_prev, z * qd[i]))
        vd = rt @ (np.cross(wd_prev, pos)
                   + np.cross(w_prev, np.cross(w_prev, pos)) + vd_prev)
        vd_ci = np.cross(wd, pci) + np.cross(w, np.cross(w, pci)) + vd
        F.append(m * vd_ci)
        N.append(ici @ wd + np.cross(w, ici @ w))
        pci_all.append(pci)
        w_prev, wd_prev, vd_prev = w, wd, vd

    tau = np.zeros(n)
    f_next, n_next = np.zeros(3), np.zeros(3)
    for i in range(n - 1, -1, -1):
        if i < n - 1:
            r_next, p_next = rots[i + 1], poss[i + 1]
            f = r_next @ f_next + F[i]
            nn = (r_next @ n_next + np.cross(pci_all[i], F[i])
                  + np.cross(p_next, r_next @ f_next) + N[i])
        else:
            f, nn = F[i], np.cross(pci_all[i], F[i]) + N[i]
        f_next, n_next = f, nn
        # 关节力矩 = 力矩矢量在关节轴 z_{i-1} 上的投影（换算到本体系）
        tau[i] = nn @ (rots[i].T @ z)
    return tau


def mass_matrix(q, p, payload=0.0):
    """数值惯量矩阵：逐列用 RNEA（关重力、qd=0、qdd=e_j）求取"""
    n = p["n_joints"]
    zero = np.zeros(n)
    cols = []
    for j in range(n):
        e = np.zeros(n)
        e[j] = 1.0
        cols.append(rnea(q, zero, e, p, gravity_on=False, payload=payload))
    return np.column_stack(cols)

def coriolis_plus_gravity(q, qd, p, payload=0.0):
    """一次 RNEA 调用同时得到 C(q,qd)qd + G(q)"""
    return rnea(q, qd, np.zeros(p["n_joints"]), p,
                gravity_on=True, payload=payload)


def friction_torque(qd, p):
    """粘性 + 库仑 + Stribeck（tanh 平滑），与边端 simulation_simulator.py 同口径"""
    f = p["friction"]
    qd = np.asarray(qd, dtype=float)
    s = np.tanh(qd / f["eps"])
    viscous = np.array(f["viscous"]) * qd
    coulomb = np.array(f["coulomb"]) * s
    stribeck = np.array(f["stribeck"]) * np.exp(-((qd / f["v_s"]) ** 2)) * s
    return viscous + coulomb + stribeck


def static_valve_inverse(tau, qd_ref, p):
    """静态阀口反解：把目标关节力矩 + 当前关节速度换算成阀口开度

    稳态流量平衡（以腔 1 为高压侧，p2 ~ Pr，p1 ~ Pr + |dP|）：

        q1 = Dm*qd + Ct*|dP|,   q1 = kv*xv*sqrt(Ps - p1)

    即供给侧要同时补上"马达位移流量"和"泄漏流量"。只反解泄漏项时，
    关节一动起来这部分流量就缺了，压力建不到目标值：实测 J2 命令 790 N*m
    只输出 585 N*m（qd = 0.096 rad/s 时位移流量已与泄漏流量同量级）。

    位移流量必须用**参考速度**而不是实测速度：实测速度回代到阀口开度上会
    形成 qd↑ -> 开度↑ -> 力矩↑ -> qd↑ 的正反馈，等于把液压系统的自然阻尼
    抵消掉。实测 J2 会在保持段自激到 qd = 0.58 rad/s、实收力矩 1060 N*m
    （命令值的两倍）。参考速度是纯前馈，不构成反馈回路。

    取线性增益 tau/Ku 的问题更早：工作压力越高输出力矩越不足，
    重载关节稳态差 15%~25%，闭环只能靠积分项慢慢补，而积分时间常数
    与作业时长同量级，补不动。

    反解后命令力矩与稳态输出力矩一致（零速数值校核 delivered/commanded = 1.0000，
    带速工况的残差由外环 PD 吸收）。

    代价：反解消掉了执行器原本"压力越高流量越被压制"的自然阻尼路径，闭环对
    液压谐振更敏感。实测在 bw_hyd_ratio = 0.25 下 J1/J2/J3/J5/J6 会把压力顶到
    Ps/Pr 饱和；降到 0.10 后六轴都不饱和。J5 的跟踪仍不如 PID，未定稿。
    """
    hyd = p["hyd"]
    dm = motor_displacement(p)
    dp = np.asarray(tau, dtype=float) / dm
    mag = np.abs(dp)
    # 供回压差余量，防 sqrt 取负；接近 Ps-Pr 时开度饱和到 1
    head = np.maximum(hyd["p_supply"] - hyd["p_return"] - mag, 1.0)
    flow = hyd["leak_coef"] * mag + dm * np.asarray(qd_ref, dtype=float)
    mag_xv = np.clip(flow / (hyd["kv"] * np.sqrt(head)), 0.0, 1.0)
    return np.sign(dp) * mag_xv


def arm_accel(q, qd, tau, p, payload=0.0):
    """M(q)qdd = tau - C(q,qd)qd - G(q) - F_f(qd)"""
    m = mass_matrix(q, p, payload)
    rhs = tau - coriolis_plus_gravity(q, qd, p, payload) - friction_torque(qd, p)
    return np.linalg.solve(m, rhs)


# ---------------------------------------------------------------------------
# 3. 液压执行器
# ---------------------------------------------------------------------------
class HydraulicActuator:
    """阀控液压摆动马达：伺服阀二阶动力学 + 两腔压力动力学 + 力矩输出"""

    def __init__(self, p):
        self.p = p
        self.t_max, self.disp = actuator_torque_limit(p)
        self.vol = chamber_volumes(p)   # 各关节单腔等效容积 [m^3]
        n = p["n_joints"]
        self.xv = np.zeros(n)          # 阀芯位移比 [-1, 1]
        self.xvd = np.zeros(n)
        # 初始两腔等压（负载压力为零），避免 t=0 出现力矩阶跃
        self.p1 = np.full(n, p["hyd"]["p_return"])
        self.p2 = np.full(n, p["hyd"]["p_return"])

    def step(self, u, qd, dt):
        """定步长 Euler 推进一格，返回关节力矩 tau"""
        hyd = self.p["hyd"]
        wn, zeta = hyd["omega_n"], hyd["zeta"]
        ps, pr, be = hyd["p_supply"], hyd["p_return"], hyd["beta_e"]
        v, ct, kv = self.vol, hyd["leak_coef"], hyd["kv"]

        u = np.clip(u, -1.0, 1.0)
        xvdd = wn * wn * (u - self.xv) - 2.0 * zeta * wn * self.xvd
        self.xvd = self.xvd + xvdd * dt
        self.xv = np.clip(self.xv + self.xvd * dt, -1.0, 1.2)

        flow = kv * self.xv
        q_in = np.maximum(flow, 0.0)
        q_out = np.maximum(-flow, 0.0)
        q1 = (q_in * np.sqrt(np.maximum(ps - self.p1, 0.0))
              + q_out * np.sqrt(np.maximum(self.p1 - pr, 0.0)))
        q2 = (q_out * np.sqrt(np.maximum(ps - self.p2, 0.0))
              + q_in * np.sqrt(np.maximum(self.p2 - pr, 0.0)))
        q1 = np.clip(q1, -0.05, 0.05)
        q2 = np.clip(q2, -0.05, 0.05)

        dp = self.p1 - self.p2
        p1d = (be / v) * (q1 - self.disp * qd - ct * dp)
        p2d = (be / v) * (-q2 + self.disp * qd - ct * dp)
        self.p1 = np.clip(self.p1 + p1d * dt, pr, ps)
        self.p2 = np.clip(self.p2 + p2d * dt, pr, ps)

        return self.disp * (self.p1 - self.p2)


# ---------------------------------------------------------------------------
# 4. 控制器
# ---------------------------------------------------------------------------
def operating_scales(p):
    """按作业轨迹幅值给出的输入归一化尺度 [rad, rad/s]

    边端用固定 position_range=3.14 / velocity_range=2.0 归一化，实际作业幅度只有
    零点几弧度，归一化后整条轨迹落在 [-1,1] 的极小角点里，RBF 中心几乎覆盖不到。
    这里改为按本作业的行程与峰值速度归一化，使工作区张满归一化空间。
    """
    q0 = np.array(p["home"], dtype=float)
    q1 = np.array(p["target"], dtype=float)
    d = np.abs(q1 - q0)
    pos = 1.15 * np.maximum(np.abs(q0), np.abs(q1)) + 1e-3
    vel = 1.15 * 1.875 * d / p["traj"]["t_move"] + 1e-3
    return pos, vel


def shared_centers(input_dim, n_centers):
    """读取两侧共用的 RBF 中心常量表，缺失时返回 None 由调用方回退。

    表格由 shared/make_rbf_centers.py 生成。
    """
    path = os.path.join(SHARED, "rbf_centers_%dx%d.csv" % (n_centers, input_dim))
    if not os.path.exists(path):
        return None
    table = np.loadtxt(path, delimiter=",")
    if table.shape != (n_centers, input_dim):
        raise ValueError("RBF center table %s has shape %s, expected %s"
                         % (path, table.shape, (n_centers, input_dim)))
    return table


class RBFNetwork:
    """固定中心 RBF 网络，结构对齐 edge_node/control/rbf_network.py

    中心点默认取自 shared/rbf_centers_<N>x<D>.csv；
    表格缺失时回退到 seed 随机中心（此时两侧结果不可逐点比较，只能比量级）。

    偏差说明：边端默认核宽 1/sqrt(2N)=0.0884，在 12 维输入空间里过窄，
    随机均匀中心下几乎所有 phi 都下溢为 0，网络实质不激活。整定工况改为
    0.60，使中心邻域能覆盖归一化输入空间。
    """

    def __init__(self, input_dim, output_dim, n_centers, learning_rate,
                 leakage, width, seed=42, centers=None):
        self.n_centers = n_centers
        self.lr = learning_rate
        self.leakage = leakage
        if centers is None:
            centers = shared_centers(input_dim, n_centers)
        if centers is None:
            rng = np.random.default_rng(seed)
            centers = rng.uniform(-1.0, 1.0, size=(n_centers, input_dim))
        self.centers = np.asarray(centers, dtype=float)
        self.widths = np.full(n_centers, width)
        self.weights = np.zeros((n_centers, output_dim))

    def activate(self, x):
        d = x[None, :] - self.centers
        return np.exp(-np.sum(d * d, axis=1) / (2.0 * self.widths ** 2))

    def forward(self, x):
        return self.activate(x) @ self.weights

    def update(self, x, s, dt):
        phi = self.activate(x)
        self.weights += self.lr * dt * (np.outer(phi, s)
                                        - self.leakage * self.weights)


class ANNController:
    """RBF 自适应神经网络控制器，控制律对齐 edge_node/control/adaptive_nn_controller.py

    e = q_d - q,  e_dot = qd_d - qd
    s = e_dot + Lambda*e
    tau = f_hat + Kd*s,   f_hat = W^T*phi(x),  x = 归一化 [q, qd]
    dW/dt = Gamma*(phi*s^T - sigma_w*W)

    tuned=True 时按液压量级整定：Kd 逐关节按等效惯量缩放、加大学习率与核宽。
    """

    def __init__(self, p, tuned=False, kd_diag=None, lambda_gain=None):
        c = p["ctrl"]
        self.n = p["n_joints"]
        lg = c["lambda_gain"] if lambda_gain is None else lambda_gain
        self.lambda_gain = np.asarray(lg, dtype=float)
        self.tuned = tuned
        if kd_diag is None:
            kd_diag = np.full(self.n, c["kd"])
        self.kd = np.asarray(kd_diag, dtype=float)
        lrate = c["lrate_tuned"] if tuned else c["learning_rate"]
        width = c["rbf_width_tuned"] if tuned else c["rbf_width"]
        n_centers = c["n_centers_tuned"] if tuned else c["n_centers"]
        if tuned:
            self.position_range, self.velocity_range = operating_scales(p)
        else:
            self.position_range = np.full(self.n, c["position_range"])
            self.velocity_range = np.full(self.n, c["velocity_range"])
        self.nn = RBFNetwork(2 * self.n, self.n, n_centers, lrate,
                             c["leakage"], width)
        self.last_s = np.zeros(self.n)

    def normalize(self, q, qd):
        return np.concatenate([
            np.clip(q / self.position_range, -1.0, 1.0),
            np.clip(qd / self.velocity_range, -1.0, 1.0),
        ])

    def control(self, q, qd, q_ref, qd_ref, dt):
        e = q_ref - q
        edot = qd_ref - qd
        s = edot + self.lambda_gain * e
        x = self.normalize(q, qd)
        f_hat = self.nn.forward(x)
        tau = f_hat + self.kd * s
        self.nn.update(x, s, dt)
        self.last_s = s
        return tau


class PIDController:
    """基线：重力前馈 + 关节空间 PID（对比用，带宽与整定 ANNC 取齐）

    液压阀口静态增益随负载压力变化（Kq = kv*sqrt(Ps-p1)），单靠前馈会有约 20%
    的稳态力矩偏差，故 PID 需要积分项消除稳态误差；积分项做了力矩限幅抗饱和。
    """

    def __init__(self, p, kp, kd, ki=None, t_max=None):
        self.kp = np.asarray(kp, dtype=float)
        self.kd = np.asarray(kd, dtype=float)
        n = p["n_joints"]
        self.ki = np.zeros(n) if ki is None else np.asarray(ki, dtype=float)
        self.t_max = np.full(n, np.inf) if t_max is None else np.asarray(
            t_max, dtype=float)
        self.integral = np.zeros(n)

    def control(self, q, qd, q_ref, qd_ref, dt, gravity=None):
        e = q_ref - q
        edot = qd_ref - qd
        self.integral += e * dt
        g = np.zeros_like(e) if gravity is None else gravity
        # 抗积分饱和：积分项不许超过执行器能力
        i_term = np.clip(self.ki * self.integral, -self.t_max, self.t_max)
        return self.kp * e + self.kd * edot + g + i_term


# ---------------------------------------------------------------------------
# 5. 参考轨迹：五次多项式（位置/速度/加速度连续），模拟一次搬运/喷号作业
# ---------------------------------------------------------------------------
def reference_trajectory(t, p):
    t_move = p["traj"]["t_move"]
    t_hold = p["traj"]["t_hold"]
    q0 = np.array(p["home"], dtype=float)
    q1 = np.array(p["target"], dtype=float)

    def quintic(u):
        return (10 * u ** 3 - 15 * u ** 4 + 6 * u ** 5,
                (30 * u ** 2 - 60 * u ** 3 + 30 * u ** 4) / t_move,
                (60 * u - 180 * u ** 2 + 120 * u ** 3) / t_move ** 2)

    if t < t_move:
        s, sd, sdd = quintic(t / t_move)
    elif t < t_move + t_hold:
        s, sd, sdd = 1.0, 0.0, 0.0
    elif t < 2 * t_move + t_hold:
        u = (t - t_move - t_hold) / t_move
        s1, sd1, sdd1 = quintic(u)
        s, sd, sdd = 1.0 - s1, -sd1, -sdd1
    else:
        s, sd, sdd = 0.0, 0.0, 0.0
    d = q1 - q0
    return q0 + d * s, d * sd, d * sdd
    return q0 + d * s, d * sd, d * sdd


# ---------------------------------------------------------------------------
# 6. 仿真主循环（半隐式 Euler，定步长 dt）
# ---------------------------------------------------------------------------
CONFIGS = ("pid", "annc_edge", "annc_tuned")

# 实验性可复现结构：PD + 重力前馈 + 静态阀口反解，无学习、无积分、无随机数。
#   pdff     : 全关节静态阀口反解 + 全局低带宽（重关节明显优于 PID，但 J5 变差）
#   pdff_j5  : 同 pdff，但腕摆 J5（index 4）改回线性阀口增益并单独整定带宽——
#              见 README §5。J5 又轻又快、线性增益已准确，反解反而消掉它需要的
#              液压自然阻尼；保留线性并让它用更高带宽，六轴才都不差于 PID。
# 数据与推导见 sim/hydraulic-arm/README.md，复现脚本 python_twin/valve_inverse_check.py。
VALVE_INVERSE_CONFIGS = ("pdff", "pdff_j5")
J5_INDEX = 4


def valve_inverse_mask(cfg, n):
    """逐关节阀口映射掩码：True 走静态反解，False 走线性增益 tau/Ku。

    重关节工作压力高，线性增益少出力 15%~25%，必须反解；J5（腕摆）又轻又快，
    线性增益已经准确，反解反而消掉它需要的液压自然阻尼，故保留线性。见 README §5。
    """
    if cfg == "pdff":
        return np.ones(n, dtype=bool)
    if cfg == "pdff_j5":
        mask = np.ones(n, dtype=bool)
        mask[J5_INDEX] = False
        return mask
    return np.zeros(n, dtype=bool)


def joint_bandwidth(p, m_home, ratio=None):
    """逐关节闭环带宽 [rad/s]

    受液压阻尼极点 2*beta*Ct/V 限制：穿越频率必须远离液压谐振峰，否则会激励
    液压振荡而失稳，故取 wc = min(bandwidth, ratio * 2*beta*Ct/V)。

    ratio 可为标量或 6 元素向量（逐关节带宽比），None 时取全局 bw_hyd_ratio。
    """
    c = p["ctrl"]
    r = c["bw_hyd_ratio"] if ratio is None else ratio
    return np.minimum(c["bandwidth"],
                      np.asarray(r, dtype=float) * hydraulic_damping_pole(p))


def build_controller(p, cfg, m_home, wc=None):
    """按配置构造控制器

    - pid        : 重力前馈 + 关节空间 PD（积分增益默认 0）
    - annc_edge  : 边端默认参数（Kd=50 统一、Lambda=10、学习率 0.1）
    - annc_tuned : 按液压量级整定（Kd_i = 2*zeta*M_ii*wc_i，Lambda_i = wc_i/(2*zeta)）
    - pdff       : 实验性的可复现结构（PD + 重力前馈 + 静态阀口反解，无积分）
    - pdff_j5    : 同 pdff，但 J5 用线性阀口增益并单独整定带宽（bw_hyd_ratio_j5）
    """
    c = p["ctrl"]
    m_diag = np.diag(m_home)
    if wc is None:
        ratio = np.full(p["n_joints"], c["bw_hyd_ratio"], dtype=float)
        if cfg == "pdff_j5":
            # J5 走线性映射保留了液压自然阻尼，可用比反解关节更高的带宽
            ratio[J5_INDEX] = c.get("bw_hyd_ratio_j5", c["bw_hyd_ratio"])
        wc = joint_bandwidth(p, m_home, ratio)
    zeta = c["damping_ratio"]
    if cfg == "pid":
        kp = m_diag * wc ** 2
        kd = m_diag * 2.0 * zeta * wc
        ki = kp * wc / 10.0          # 积分时间常数 10/wc
        t_max, _ = actuator_torque_limit(p)
        return PIDController(p, kp, kd, ki=ki, t_max=t_max)
    if cfg in ("pdff", "pdff_j5"):
        # 实验性可复现结构：PID 那一套 PD 增益 + 重力前馈 + 静态阀口反解。
        # 不用积分：静摩擦死区内误差不消失，积分会持续积累，突破静摩擦时把
        # 压力甩到 Ps/Pr 顶死形成极限环（实测 J2 振荡周期 0.15 s，与液压固有
        # 频率 40.7 rad/s 吻合）。静差改由阀口反解承担，它是确定性静态补偿。
        # 注意：本结构必须把 bw_hyd_ratio 从 0.25 降到约 0.10 才稳得住，
        # 准确的力矩接口把回路增益抬高了一个量级，原整定规则不再适用。
        kp = m_diag * wc ** 2
        kd = m_diag * 2.0 * zeta * wc
        ki = np.zeros(p["n_joints"])
        t_max, _ = actuator_torque_limit(p)
        return PIDController(p, kp, kd, ki=ki, t_max=t_max)
    if cfg == "annc_edge":
        return ANNController(p, tuned=False,
                             kd_diag=np.full(p["n_joints"], c["kd"]))
    if cfg == "annc_tuned":
        kd = m_diag * 2.0 * zeta * wc
        lam = wc / (2.0 * zeta)
        return ANNController(p, tuned=True, kd_diag=kd, lambda_gain=lam)
    raise ValueError(cfg)


def simulate(p, cfg, m_home, payload=None):
    dt = p["sim"]["dt"]
    n_steps = int(round(p["sim"]["t_end"] / dt))
    payload = p["payload_mass"] if payload is None else payload

    plant = HydraulicActuator(p)
    ctrl = build_controller(p, cfg, m_home)
    ku = valve_torque_gain(p)
    use_valve_inverse = cfg in VALVE_INVERSE_CONFIGS
    inv_mask = valve_inverse_mask(cfg, 6)   # 逐关节：True 走反解，False 走线性
    q = np.array(p["home"], dtype=float)
    qd = np.zeros(6)

    keys = ("q", "qd", "q_ref", "tau", "p1", "p2", "e_abs")
    log = {k: np.zeros((n_steps + 1, 6)) for k in keys}
    log["t"] = np.zeros(n_steps + 1)
    log["w_norm"] = np.zeros(n_steps + 1)
    log["s_norm"] = np.zeros(n_steps + 1)
    log["diverged"] = False
    log["cfg"] = cfg

    t0 = time.time()
    for k in range(n_steps + 1):
        t = k * dt
        q_ref, qd_ref, _ = reference_trajectory(t, p)

        if cfg in ("pid", "pdff", "pdff_j5"):
            # 只有这几个配置带重力前馈（曾试过 pdff_fric 变体额外前馈摩擦，
            # 实测没有稳定收益、J5 反而更差，已撤销）
            grav = coriolis_plus_gravity(q, np.zeros(6), p, payload)
            tau_cmd = ctrl.control(q, qd, q_ref, qd_ref, dt, gravity=grav)
        else:
            tau_cmd = ctrl.control(q, qd, q_ref, qd_ref, dt)

        # 力矩指令 -> 阀口开度：先按执行器能力限幅，再逐关节映射到阀口开度。
        # inv_mask 为 True 的关节走静态阀口反解，False 的走线性增益 tau/Ku。
        tau_lim = np.clip(tau_cmd, -plant.t_max, plant.t_max)
        if use_valve_inverse:
            u = np.where(inv_mask,
                         static_valve_inverse(tau_lim, qd_ref, p),
                         tau_lim / ku)
        else:
            u = tau_lim / ku
        tau = plant.step(u, qd, dt)
        qdd = arm_accel(q, qd, tau, p, payload)

        log["t"][k] = t
        log["q"][k] = q
        log["qd"][k] = qd
        log["q_ref"][k] = q_ref
        log["tau"][k] = tau
        log["p1"][k] = plant.p1
        log["p2"][k] = plant.p2
        log["e_abs"][k] = np.abs(q_ref - q)
        if cfg in ("annc_edge", "annc_tuned"):
            log["w_norm"][k] = np.linalg.norm(ctrl.nn.weights)
            log["s_norm"][k] = np.linalg.norm(ctrl.last_s)

        if not np.all(np.isfinite(q)):
            log["diverged"] = True
            log = {key: val[:k + 1] if isinstance(val, np.ndarray) and val.ndim > 0
                   else val for key, val in log.items()}
            break

        if k == n_steps:
            break
        q = q + qd * dt + 0.5 * qdd * dt * dt     # 半隐式 Euler
        qd = qd + qdd * dt

    log["wall_time"] = time.time() - t0
    log["peak_tau"] = np.max(np.abs(log["tau"]), axis=0)
    log["final_err"] = np.abs(log["q_ref"][-1] - log["q"][-1])
    return log


def check_gravity_holding(p):
    """静力矩校核：home 位姿下各关节需克服的重力矩 vs 执行器能力"""
    q = np.array(p["home"], dtype=float)
    tau_g = coriolis_plus_gravity(q, np.zeros(6), p, p["payload_mass"])
    t_max, _ = actuator_torque_limit(p)
    return tau_g, t_max


# ---------------------------------------------------------------------------
# 7. 出图与报告
# ---------------------------------------------------------------------------
JOINT_NAMES = ["J1 回转", "J2 大臂", "J3 小臂", "J4 腕转", "J5 腕摆", "J6 末端"]


def make_plots(p, logs, t_max):
    os.makedirs(RESULTS, exist_ok=True)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    annc = logs["annc_tuned"]
    pid = logs["pid"]

    fig, axes = plt.subplots(3, 2, figsize=(13, 10))
    for i, ax in enumerate(axes.ravel()):
        ax.plot(annc["t"], annc["q"][:, i], label="ANNC", lw=1.4, color="#0891b2")
        ax.plot(pid["t"], pid["q"][:, i], label="PID", lw=1.2, ls="--", color="#f59e0b")
        ax.plot(annc["t"], annc["q_ref"][:, i], label="desired", lw=1.0, ls=":",
                color="#64748b")
        ax.set_title(JOINT_NAMES[i] + " position tracking (rad)")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    fig.suptitle("Hydraulic manipulator joint tracking: ANNC vs PID", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "fig1_tracking.png"), dpi=140)
    plt.close(fig)

    fig, axes = plt.subplots(3, 2, figsize=(13, 10), sharex=True)
    for i, ax in enumerate(axes.ravel()):
        ax.plot(annc["t"], np.maximum(annc["e_abs"][:, i], 1e-12), color="#0891b2",
                lw=1.2, label="ANNC")
        ax.plot(pid["t"], np.maximum(pid["e_abs"][:, i], 1e-12), color="#f59e0b",
                lw=1.0, ls="--", label="PID")
        ax.axhline(0.01, color="#ef4444", lw=0.8, ls=":")
        ax.set_yscale("log")
        ax.set_title(JOINT_NAMES[i] + " tracking error |e| (rad)")
        ax.grid(alpha=0.3, which="both")
        ax.legend(fontsize=8)
    fig.suptitle("Tracking error convergence (log scale, red = 0.01 rad)", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "fig2_error.png"), dpi=140)
    plt.close(fig)

    fig, axes = plt.subplots(3, 2, figsize=(13, 10), sharex=True)
    for i, ax in enumerate(axes.ravel()):
        ax.plot(annc["t"], annc["tau"][:, i], color="#7c3aed", lw=1.2, label="ANNC")
        ax.axhline(t_max[i], color="#ef4444", lw=0.9, ls="--",
                   label="limit %.0f N*m" % t_max[i])
        ax.axhline(-t_max[i], color="#ef4444", lw=0.9, ls="--")
        ax.set_title(JOINT_NAMES[i] + " joint torque (N*m)")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    fig.suptitle("Joint torque and actuator saturation boundary", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "fig3_torque.png"), dpi=140)
    plt.close(fig)

    fig, axes = plt.subplots(3, 2, figsize=(13, 10), sharex=True)
    for i, ax in enumerate(axes.ravel()):
        ax.plot(annc["t"], annc["p1"][:, i] / 1e6, color="#dc2626", lw=1.1,
                label="P1 supply-side")
        ax.plot(annc["t"], annc["p2"][:, i] / 1e6, color="#2563eb", lw=1.1,
                label="P2 return-side")
        ax.set_title(JOINT_NAMES[i] + " chamber pressures (MPa)")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    fig.suptitle("Hydraulic actuator pressure response", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "fig4_pressure.png"), dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(annc["t"], annc["w_norm"], color="#059669", lw=1.5,
            label="ANNC tuned: ||W||_F")
    ax.plot(annc["t"], annc["s_norm"], color="#ea580c", lw=1.2,
            label="ANNC tuned: ||s||")
    edge = logs["annc_edge"]
    ax.plot(edge["t"], edge["w_norm"], color="#0891b2", lw=1.2, ls="--",
            label="ANNC edge-default: ||W||_F")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("norm")
    ax.set_title("RBF adaptive network convergence")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "fig5_convergence.png"), dpi=140)
    plt.close(fig)
    print("[plots] 5 figures written to " + os.path.normpath(RESULTS))


def write_report(p, logs, t_max, m_home, tau_g):
    os.makedirs(RESULTS, exist_ok=True)
    annc = logs["annc_tuned"]
    pid = logs["pid"]
    edge = logs["annc_edge"]

    def rms(log):
        return np.sqrt(np.mean(np.nan_to_num(log["e_abs"]) ** 2, axis=0))

    r_annc, r_pid, r_edge = rms(annc), rms(pid), rms(edge)
    imp = (1.0 - r_annc / np.maximum(r_pid, 1e-12)) * 100.0
    hdr = "| 关节 | " + " | ".join("J%d" % (i + 1) for i in range(6)) + " |"

    L = []
    L.append("# 液压机械臂动力学仿真报告")
    L.append("")
    L.append("> 本报告由 Python 数值孪生自动生成。方程与 `sim/hydraulic-arm/*.m` 一致，")
    L.append("")
    L.append("## 1 模型结构")
    L.append("")
    L.append("6 自由度串联机械臂，6 个关节均由**阀控液压摆动马达**驱动。")
    L.append("模型为三阶耦合系统：刚体动力学 + 伺服阀二阶动力学 + 两腔压力动力学。")
    L.append("")
    L.append("摩擦按粘性 + 库仑 + Stribeck 建模，与边端 `simulation_simulator.py` 同口径；")
    L.append("动力学用递归牛顿-欧拉（RNEA）数值求解，不依赖任何工具箱。")
    L.append("")
    L.append("## 2 执行器能力与静力矩校核")
    L.append("")
    L.append(hdr)
    L.append("|---|---|---|---|---|---|---|")
    L.append("| 排量 (cm^3/rev) | "
             + " | ".join("%.0f" % v for v in p["hyd"]["disp_cm3_rev"]) + " |")
    L.append("| 力矩上限 (N*m) | " + " | ".join("%.0f" % v for v in t_max) + " |")
    L.append("| home 静重力矩 (N*m) | "
             + " | ".join("%.0f" % v for v in tau_g) + " |")
    L.append("| 重力矩 / 能力 | "
             + " | ".join("%.2f" % (abs(g) / t) for g, t in zip(tau_g, t_max)) + " |")
    L.append("")
    L.append("系统压力 25 MPa、回油 1 MPa（GB/T 2346-2003 公称压力系列）；")
    L.append("摆动马达排量按 GB/T 2348-2018 米制系列选型。")
    L.append("")
    L.append("## 3 等效惯量与增益整定")
    L.append("")
    L.append("home 位姿下 M(q) 对角元 (kg*m^2)：")
    L.append("")
    L.append("`" + "  ".join("%8.1f" % v for v in np.diag(m_home)) + "`")
    L.append("")
    L.append("最大分量 %.1f kg*m^2，是边端名义惯量 %.1f kg*m^2 的 %.0f 倍。"
             % (np.max(np.diag(m_home)), p["ctrl"]["nominal_inertia"],
                np.max(np.diag(m_home)) / p["ctrl"]["nominal_inertia"]))
    L.append("")
    L.append("边端控制器的默认增益（Kd=50、Gamma=0.1）是按名义惯量 1.0 kg*m^2 整定的。")
    L.append("直接迁移到液压机械臂（等效惯量 10^2 kg*m^2 量级）时，闭环带宽只有")
    L.append("sqrt(Kd*Lambda/M) ~ 2 rad/s，且 RBF 学习率过小、核宽过窄，补偿项基本不起作用。")
    L.append("")
    L.append("整定工况按 Kd_i = 50 * M_ii(home) 逐关节缩放，使各关节闭环带宽统一到")
    L.append("%.0f rad/s；同时把 RBF 学习率提到 %.0f、核宽由 %.4f 提到 %.2f。"
             % (p["ctrl"]["bandwidth"], p["ctrl"]["lrate_tuned"],
                p["ctrl"]["rbf_width"], p["ctrl"]["rbf_width_tuned"]))
    L.append("")
    L.append("## 4 跟踪性能对比")
    L.append("")
    L.append(hdr)
    L.append("|---|---|---|---|---|---|---|")
    L.append("| PID 均方根误差 (rad) | " + " | ".join("%.4f" % v for v in r_pid) + " |")
    L.append("| ANNC(边端默认) 均方根误差 (rad) | "
             + " | ".join("%.4f" % v for v in r_edge) + " |")
    L.append("| ANNC(惯量整定) 均方根误差 (rad) | "
             + " | ".join("%.4f" % v for v in r_annc) + " |")
    L.append("| ANNC(整定) 相对 PID 改善 (%) | "
             + " | ".join("%.1f" % v for v in imp) + " |")
    L.append("| ANNC(整定) 末态误差 (rad) | "
             + " | ".join("%.4f" % v for v in annc["final_err"]) + " |")
    L.append("| ANNC(整定) 峰值力矩 (N*m) | "
             + " | ".join("%.0f" % v for v in annc["peak_tau"]) + " |")
    L.append("")
    for name, log in (("ANNC(整定)", annc), ("PID", pid), ("ANNC(边端默认)", edge)):
        flag = "  **发散**" if log.get("diverged") else ""
        L.append("- %s：用时 %.1f s，||W|| 终值 %.3f，||s|| 终值 %.5f%s"
                 % (name, log["wall_time"],
                    float(log["w_norm"][-1]) if log["w_norm"].size else 0.0,
                    float(log["s_norm"][-1]) if log["s_norm"].size else 0.0, flag))
    L.append("")
    L.append("## 5 图表")
    L.append("")
    L.append("- `fig1_tracking.png` 关节位置跟踪对比")
    L.append("- `fig2_error.png` 跟踪误差收敛曲线")
    L.append("- `fig3_torque.png` 关节力矩与饱和边界")
    L.append("- `fig4_pressure.png` 两腔压力响应")
    L.append("- `fig5_convergence.png` RBF 权重与滤波误差收敛曲线")
    L.append("")
    L.append("## 6 边界说明")
    L.append("")
    L.append("- 本报告为**仿真环境**结果，非真机实测；性能结论不得外推为现场指标。")
    L.append("- 压力动力学含内泄漏，未建模油液含气量、温升与管路动态。")
    L.append("- 参考轨迹为关节空间五次多项式，对应一次搬运/喷号作业的单程往返。")
    L.append("")
    path = os.path.join(RESULTS, "simulation_report.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    print("[report] written to " + os.path.normpath(path))


# ---------------------------------------------------------------------------
# 8. 入口
# ---------------------------------------------------------------------------
def main():
    p = PARAMS
    print("=" * 74)
    print("Hydraulic arm numerical twin v1.0")
    print("=" * 74)

    t_max, _ = actuator_torque_limit(p)
    print("[actuator] T_max (N*m)        = " + " ".join("%8.1f" % v for v in t_max))

    m_home = mass_matrix(np.array(p["home"]), p, p["payload_mass"])
    print("[inertia ] diag(M) @home      = "
          + " ".join("%8.1f" % v for v in np.diag(m_home)))

    tau_g, _ = check_gravity_holding(p)
    ratio = np.abs(tau_g) / t_max
    print("[gravity ] tau_g @home (N*m)  = " + " ".join("%8.1f" % v for v in tau_g))
    print("[gravity ] tau_g / T_max      = " + " ".join("%8.2f" % v for v in ratio))
    if np.any(ratio > 0.9):
        print("  !! WARNING: some joint is near its actuator limit")

    wh, zeta_h = hydraulic_poles(p, np.diag(m_home))
    print("[hyd     ] chamber vol (cm^3) = "
          + " ".join("%8.1f" % (v * 1e6) for v in chamber_volumes(p)))
    print("[hyd     ] omega_h  (rad/s)   = " + " ".join("%8.1f" % v for v in wh))
    print("[hyd     ] zeta_h            = " + " ".join("%8.3f" % v for v in zeta_h))
    print("[tuning  ] closed-loop wc    = "
          + " ".join("%8.2f" % v for v in joint_bandwidth(p, m_home)))
    print("[tuning  ] valve gain K_u    = "
          + " ".join("%8.0f" % v for v in valve_torque_gain(p)))

    if len(sys.argv) > 1 and sys.argv[1] == "--check-only":
        return None

    print("-" * 74)
    logs = {}
    for cfg in CONFIGS:
        logs[cfg] = simulate(p, cfg, m_home)
        log = logs[cfg]
        tag = "% -10s" % cfg
        if log.get("diverged"):
            print("[%s] DIVERGED at t=%.2f s" % (cfg, log["t"][-1]))
            continue
        r = np.sqrt(np.mean(log["e_abs"] ** 2, axis=0))
        print("[%s] %5.1f s  rms(e) = " % (cfg, log["wall_time"])
              + " ".join("%.4f" % v for v in r)
              + "   peak tau = " + " ".join("%.0f" % v for v in log["peak_tau"]))

    if not logs.get("pid") or logs["pid"].get("diverged"):
        print("!! PID baseline diverged, skip plots/report")
        return logs

    make_plots(p, logs, t_max)
    write_report(p, logs, t_max, m_home, tau_g)
    return logs


if __name__ == "__main__":
    main()

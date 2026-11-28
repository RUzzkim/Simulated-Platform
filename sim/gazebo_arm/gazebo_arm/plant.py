"""轻量实时仿真端：6R 机械臂物理 plant（纯 Python，无 numpy / 无 ROS 依赖）。

动力学镜像自 edge/edge_node/test/simulation_simulator.py v2.3（联调验证过、稳定的
参考仿真端模型）：每关节二阶 + 内环 PD(Kp/Kd) + 余弦重力 + 粘性/库仑/Stribeck 摩擦
+ 相邻关节 M(q) 惯量耦合 + 科氏项；目标经限速/限加速度参考跟随（在线梯形，
支持边端 100Hz 流式下发）。1kHz 子步半隐式积分。

**刻意不用** sim/hydraulic-arm 的液压孪生：那套在保持段有未解决的执行器欠阻尼
失稳（见其 README §4.5），不适合做需要长时间保持位姿的实时端。

plant 只管物理，不碰 ROS/MQTT。ROS2 封装见 plant_node.py。可独立冒烟：
    python plant.py
"""
from __future__ import annotations

import math
import random
from typing import List, Optional

N = 6
V_EPS = 0.01          # 库仑摩擦平滑尺度 (rad/s)
V_S = 0.05            # Stribeck 特征速度 (rad/s)


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


class FaultInjector:
    """可开关的故障/扰动注入库（默认全关 = 正常工况）。

    对齐项目书：端侧「模拟传感器异常、执行器故障、外部扰动」，为边端的自适应控制
    与事件触发容错、云端的健康/趋势分析制造可复现的异常工况。注入只改物理与读数，
    不碰控制逻辑本身。逐关节可配，便于只让某一关节劣化。

    - 传感器漂移：上报读数 = 真值 + drift_rate·t (+ 高斯噪声)，模拟高温粉尘下信号漂移。
    - 执行器磨损：实际出力打折 (gain<1) + 附加库仑摩擦，模拟磨损/卡涩导致的欠驱动。
    - 外部扰动：给动力学叠加外力矩，模拟工件重量波动/碰撞。
    """

    def __init__(self):
        self.sensor_drift_enabled = False
        self.sensor_drift_rate = [0.0] * N     # rad/s，逐关节位置漂移速率
        self.sensor_noise_std = 0.0            # 上报位置高斯噪声标准差 (rad)
        self.actuator_wear_enabled = False
        self.actuator_gain = [1.0] * N         # <1 表示出力衰减
        self.actuator_extra_friction = [0.0] * N  # 附加库仑摩擦 (N·m)
        self.disturbance_enabled = False
        self.disturbance_torque = [0.0] * N    # 叠加到动力学的外力矩 (N·m)
        self._t = 0.0

    def advance(self, dt: float) -> None:
        self._t += dt

    def gain(self, i: int) -> float:
        return self.actuator_gain[i] if self.actuator_wear_enabled else 1.0

    def extra_friction(self, i: int, v: float) -> float:
        if not self.actuator_wear_enabled:
            return 0.0
        return self.actuator_extra_friction[i] * math.tanh(v / V_EPS)

    def disturbance(self, i: int) -> float:
        return self.disturbance_torque[i] if self.disturbance_enabled else 0.0

    def sensor(self, q: List[float], qd: List[float], tau: List[float]):
        """把真实状态转成「传感器读数」：叠加漂移+噪声（默认关时原样返回）。"""
        if not self.sensor_drift_enabled:
            return list(q), list(qd), list(tau)
        out = []
        for i, qi in enumerate(q):
            val = qi + self.sensor_drift_rate[i] * self._t
            if self.sensor_noise_std > 0.0:
                val += random.gauss(0.0, self.sensor_noise_std)
            out.append(val)
        return out, list(qd), list(tau)

    @property
    def any_enabled(self) -> bool:
        return (self.sensor_drift_enabled or self.actuator_wear_enabled
                or self.disturbance_enabled)



def _solve(m: List[List[float]], b: List[float]) -> List[float]:
    """高斯消元（部分主元）解 m·x=b，纯 Python。"""
    n = len(b)
    a = [row[:] + [b[i]] for i, row in enumerate(m)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            raise ValueError("M(q) 奇异")
        a[col], a[piv] = a[piv], a[col]
        for r in range(n):
            if r == col:
                continue
            f = a[r][col] / a[col][col]
            for c in range(col, n + 1):
                a[r][c] -= f * a[col][c]
    return [a[i][n] / a[i][i] for i in range(n)]


class RefFollower:
    """多轴同步的限速/限加速度参考跟随器（梯形速度曲线的在线形式）。

    不用 simulation_simulator 的一次性 TrapezoidPlan：边端 adaptive_nn 控制循环
    100Hz 连续下发 joint_command，每次都从当前位置重规划会把 plan_t 反复归零，
    参考停在起点、臂不动。跟随器每个子步朝最新目标推进一次，对单次目标（等价梯形）
    和流式目标都成立。各轴限值按剩余距离占比缩放，静态目标下各轴同时到达。
    """

    def __init__(self, q0: List[float], v_max: float, a_max: float):
        self.r = list(q0)
        self.v = [0.0] * len(q0)
        self.v_max, self.a_max = v_max, a_max

    def step(self, target: List[float], h: float) -> List[float]:
        d = [t - r for t, r in zip(target, self.r)]
        d_max = max(abs(x) for x in d)
        for i, di in enumerate(d):
            w = abs(di) / d_max if d_max > 1e-12 else 0.0
            a = max(self.a_max * w, 1e-9)
            # 刹车曲线：剩余距离 |d| 内能以 a 减到 0 的最大速度
            v_des = math.copysign(min(self.v_max * w, math.sqrt(2.0 * a * abs(di))), di)
            self.v[i] += _clamp(v_des - self.v[i], -a * h, a * h)
            nxt = self.r[i] + self.v[i] * h
            if (target[i] - nxt) * di <= 0.0 and abs(self.v[i]) <= a * h * 2.0:
                nxt, self.v[i] = target[i], 0.0   # 到点吸附，防末端抖动
            self.r[i] = nxt
        return list(self.r)


class RealtimePlant:
    """6R 实时 plant：吃关节目标角，产出 (position, velocity, effort)。

    参数默认镜像 simulation_simulator 的轻量稳定模型；几何自 DH（URDF 同源）。
    """

    SUB = 10  # 每 tick 物理子步（tick 100Hz -> 物理 1kHz）

    def __init__(self, home: List[float], gravity: Optional[List[float]] = None,
                 coupling: Optional[List[float]] = None, kp: float = 50.0, kd: float = 10.0,
                 inertia: float = 0.5, viscous: float = 1.0, coulomb: float = 0.4,
                 stribeck: float = 0.3, v_limit: float = 2.0, tau_limit: float = 50.0,
                 v_max: float = 1.0, a_max: float = 2.0, gravity_comp: bool = True):
        self.q = list(home)
        self.qd = [0.0] * N
        self.tau = [0.0] * N
        self.home = list(home)
        self.gravity = gravity if gravity is not None else [0.0, 8.0, 4.0, 1.0, 0.5, 0.2]
        self.coupling = coupling if coupling is not None else [0.2, 0.15, 0.1, 0.05, 0.03]
        self.kp, self.kd, self.inertia = kp, kd, inertia
        self.viscous, self.coulomb, self.stribeck = viscous, coulomb, stribeck
        self.v_limit, self.tau_limit = v_limit, tau_limit
        self.v_max, self.a_max, self.gravity_comp = v_max, a_max, gravity_comp
        self._target = list(home)
        self._ref = RefFollower(home, v_max, a_max)
        self.faults = FaultInjector()   # 故障/扰动注入（默认全关）
        self._locked_joint: Optional[int] = None

    def lock_joint(self, joint_index: int) -> None:
        """在当前位置锁定一个关节，索引 0 对应 joint_1。"""
        if not 0 <= joint_index < N:
            raise ValueError("关节索引须为 0 至 5")
        if self._locked_joint is not None and self._locked_joint != joint_index:
            raise ValueError("仿真仅支持单关节卡滞")
        self._locked_joint = joint_index
        self.qd[joint_index] = 0.0

    def set_target(self, target: List[float]) -> None:
        """收到新关节目标：参考从当前参考点起限速/限加速度平滑逼近（可流式下发）。"""
        if len(target) != N or not all(math.isfinite(float(x)) for x in target):
            raise ValueError(f"关节目标须为 {N} 个有限数")
        self._target = [float(x) for x in target]

    def _mass_matrix(self) -> List[List[float]]:
        m = [[0.0] * N for _ in range(N)]
        for i in range(N):
            m[i][i] = self.inertia
        for k in range(N - 1):
            c = self.coupling[k] * math.cos(self.q[k] - self.q[k + 1])
            m[k][k + 1] += c
            m[k + 1][k] += c
        return m

    def step(self, dt: float) -> None:
        """推进一个发布 tick（内部 SUB 个子步）。"""
        h = dt / self.SUB
        fi = self.faults
        for _ in range(self.SUB):
            q_ref = self._ref.step(self._target, h)
            # 内环 PD + 可选重力前馈，限幅 -> 关节力矩（传感器读数）
            tau_net = [0.0] * N
            for i in range(N):
                tau = self.kp * (q_ref[i] - self.q[i]) - self.kd * self.qd[i]
                if self.gravity_comp:
                    tau += self.gravity[i] * math.cos(self.q[i])
                tau = _clamp(tau, -self.tau_limit, self.tau_limit)
                # 执行器磨损：实际出力打折（gain<1），上报即实际出力
                tau_act = fi.gain(i) * tau
                self.tau[i] = tau_act
                g = self.gravity[i] * math.cos(self.q[i])
                v = self.qd[i]
                s = math.tanh(v / V_EPS)
                fric = self.viscous * v + self.coulomb * s + self.stribeck * math.exp(-(v / V_S) ** 2) * s
                fric += fi.extra_friction(i, v)          # 磨损附加摩擦
                tau_net[i] = tau_act - g - fric + fi.disturbance(i)   # 外部扰动
            # 科氏项（相邻对，与 M 同源）
            for k in range(N - 1):
                c = self.coupling[k]
                tau_net[k] -= c * math.sin(self.q[k] - self.q[k + 1]) * self.qd[k + 1] ** 2
                tau_net[k + 1] += c * math.sin(self.q[k] - self.q[k + 1]) * self.qd[k] ** 2
            mass = self._mass_matrix()
            locked = self._locked_joint
            if locked is not None:
                # 固定轴的加速度为零，其余轴按约束后的惯量矩阵求解。
                for row in mass:
                    row[locked] = 0.0
                mass[locked] = [0.0] * N
                mass[locked][locked] = 1.0
                tau_net[locked] = 0.0
            qdd = _solve(mass, tau_net)
            for i in range(N):
                self.qd[i] = _clamp(self.qd[i] + qdd[i] * h, -self.v_limit, self.v_limit)
                self.q[i] += self.qd[i] * h
        fi.advance(dt)   # 漂移按 tick 累时

    def state(self):
        # 输出「传感器读数」：正常时即真值，注入传感器漂移时叠加漂移/噪声
        return self.faults.sensor(self.q, self.qd, self.tau)


if __name__ == "__main__":
    # 冒烟：① 单次目标；② 100Hz 重复下发同一目标（边端控制循环的实际用法）。
    # 两种都应收敛到目标并稳定保持，无发散。
    home = [0.0, 0.35, -0.72, 0.20, 0.0, 0.0]
    target = [0.5, 0.85, -1.05, 0.45, 0.30, 0.40]
    dt = 0.01
    for name, stream in (("单次下发", False), ("100Hz 流式下发", True)):
        p = RealtimePlant(home)
        p.set_target(target)
        for k in range(1000):      # 10 s
            if stream:
                p.set_target(target)
            p.step(dt)
        q, qd, tau = p.state()
        err = [round(target[i] - q[i], 4) for i in range(N)]
        print(f"[{name}] 10s 末位置误差 J1..J6:", err)
        print(f"[{name}] 末速度(应≈0):", [round(x, 4) for x in qd])
        print(f"[{name}] 末力矩:", [round(x, 2) for x in tau])
        assert max(abs(e) for e in err) < 0.05, f"{name}: 未收敛到目标"
        assert max(abs(v) for v in qd) < 0.02, f"{name}: 未稳定（速度未归零）"
    print("OK: 收敛到目标且稳定保持，无发散")

    # ③ 故障注入冒烟：正常 vs 三类注入，确认注入确实改变行为（供边端检测/容错）。
    def run_10s(configure):
        p = RealtimePlant(home)
        configure(p)
        for _ in range(1000):
            p.set_target(target)
            p.step(dt)
        q, _, tau = p.state()
        return q, tau

    q_norm, _ = run_10s(lambda p: None)

    def cfg_drift(p):
        p.faults.sensor_drift_enabled = True
        p.faults.sensor_drift_rate = [0.03, 0.0, 0.0, 0.0, 0.0, 0.0]  # J1 每秒漂 0.03rad
    q_drift, _ = run_10s(cfg_drift)
    drift = q_drift[0] - q_norm[0]
    print(f"[传感器漂移] J1 读数偏移 ≈ {drift:.3f} rad（≈0.3 期望）")
    assert drift > 0.2, "传感器漂移未生效"

    def cfg_wear(p):
        p.faults.actuator_wear_enabled = True
        p.faults.actuator_gain = [1, 1, 0.5, 1, 1, 1]              # J3 出力打五折
        p.faults.actuator_extra_friction = [0, 0, 3.0, 0, 0, 0]
    q_wear, _ = run_10s(cfg_wear)
    wear_err = abs(target[2] - q_wear[2])
    print(f"[执行器磨损] J3 末端跟踪误差 ≈ {wear_err:.3f} rad（正常≈0）")
    assert wear_err > 0.02, "执行器磨损未生效"

    def cfg_dist(p):
        p.faults.disturbance_enabled = True
        p.faults.disturbance_torque = [0, 6.0, 0, 0, 0, 0]        # J2 受 6N·m 外扰
    q_dist, _ = run_10s(cfg_dist)
    dist_err = abs(target[1] - q_dist[1])
    print(f"[外部扰动] J2 末端跟踪误差 ≈ {dist_err:.3f} rad（正常≈0）")
    assert dist_err > 0.02, "外部扰动未生效"
    print("OK: 三类故障/扰动注入均生效，且默认关闭时不影响正常收敛")

"""仿真端模拟器 v2.3：模拟真实仿真端行为（物理动力学 + 轨迹规划 + 指令闭环 + 故障注入）

对比 v1（盲发正弦）的改进：
1. 物理动力学：单关节二阶模型（等效惯量 + 粘滞摩擦），内环 PD 伺服
   （Kp=50, Kd=10，与联调时仿真端内环增益一致），1kHz 子步半隐式欧拉积分，
   力矩/速度限幅 —— 关节运动由物理仿真产生，可见真实的超调与调节时间。
2. 指令闭环：订阅云端 command 主题（模拟无 ROS 2 环境下"边端→仿真端"转发跳），
   支持完整指令语义：
   - MOVE_JOINT: 伺服跟踪 jointTarget，自然收敛
   - STOP:       目标置为当前位置，依靠 Kd 阻尼刹车 → 状态 STOPPED
   - MOVE_HOME:  回零位
   - START:      恢复 RUNNING（目标不变）
3. 实时调度：绝对时间步进，消除 time.sleep 累积漂移（与真实固定步长仿真一致）。
4. 故障注入：--fault overload 在运行中段向上报力矩叠加超限故障力矩，
   验证 ERROR 状态上报与恢复链路。
5. 重力与非线性摩擦（v2.1）：各关节余弦重力负载 + 粘性/库仑/Stribeck 摩擦；
   内环默认前馈重力补偿（--no-gravity-comp 关闭，可观察重力下垂稳态误差）。
6. 关节间耦合 M(q)·q̈（v2.2）：惯量矩阵对角为各关节 J_i，相邻关节非对角为
   c_ij·cos(q_i - q_j)（位置相关），每物理子步求解 6×6 方程组；
   --coupling 0,0,0,0,0 可退化解耦模型。
7. 梯形速度轨迹规划（v2.3）：MOVE_JOINT/MOVE_HOME 采用多轴同步梯形速度规划
   （加速-匀速-减速；小位移自动退化为三角形，全部关节按归一化位移比例同时启停），
   替代阶跃目标，消除速度/力矩冲击 —— 工业机器人标准运动生成方式；
   --traj step 回退阶跃行为（v2 语义）。
8. 科氏/离心项 C(q,q̇)·q̇（v2.3）：与 M(q) 同源的 Lagrangian 一致形式，
   相邻对 τ_c[k] += c_k·sin(q_k-q_{k+1})·q̇_{k+1}²、τ_c[k+1] -= c_k·sin(...)·q̇_k²；
   --no-coriolis 关闭后可对比轨迹差异。
9. 容错执行器闭环（MOVE_JOINT_SAFE）：边端无 ROS 2 模式下故障时下发安全目标，
   仿真端清除轨迹规划、按 --safe-vmax（默认 0.1rad/s 安全限速）平滑逼近，
   防止补偿目标阶跃振荡；resume=true 后重新梯形规划回云端原目标。
   安全指令为边端内部协议，不改变云端可见的运行状态推断。
10. 仍使用边端真实 StateProcessor / RobotState，JSON 契约与云端保持一致。
11. 传感器噪声注入（--sensor-noise/--sensor-spike-prob/--sensor-spike-mag/--noise-seed）：
    高斯白噪声 + 随机尖峰仅叠加在上报读数（不进动力学），同种子逐帧可复现，
    供边端信号滤波 ON/OFF 全链路对照；默认全 0 关闭。

示例：
    py test/simulation_simulator.py --mode hold --fault overload
    py test/simulation_simulator.py --mode sine --rate 100 --duration 10
    py test/simulation_simulator.py --traj trapezoid --plan-vmax 0.5 --plan-acc 2.0
"""
from __future__ import annotations

import argparse
import json
import math
import random
import ssl
import sys
import os
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import paho.mqtt.client as mqtt
from edge_node.processor.state_processor import StateProcessor


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _solve_linear(m, b):
    """高斯消元（部分主元）求解 n×n 线性方程组 m·x = b，纯 Python 无 numpy 依赖"""
    n = len(b)
    a = [row[:] + [b[i]] for i, row in enumerate(m)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            raise ValueError('M(q) 矩阵奇异')
        a[col], a[piv] = a[piv], a[col]
        for r in range(col + 1, n):
            f = a[r][col] / a[col][col]
            for k in range(col, n + 1):
                a[r][k] -= f * a[col][k]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = a[i][n] - sum(a[i][k] * x[k] for k in range(i + 1, n))
        x[i] = s / a[i][i]
    return x


class JointDynamics:
    """单关节二阶动力学 + PD 内环伺服（含重力与非线性摩擦）

    模型：J·qdd = τ_motor - τ_gravity(q) - τ_friction(qd)
    重力：τ_gravity = G·cos(q + φ)（G 为关节处于水平位姿时的峰值重力矩，
          基座回转轴 G=0，肩/肘关节最大 —— 与真实 6R 臂重力分布一致）
    摩擦：τ_friction = b·qd                          （粘性）
                        + Fc·tanh(qd/ε)              （库仑，tanh 平滑避免零速抖振）
                        + (Fs-Fc)·exp(-(qd/vs)²)·tanh(qd/ε)  （Stribeck 低速附加）
    伺服：τ_motor = Kp·(q_target - q) - Kd·qd，限幅后输出；
          可选前馈重力补偿（ros2_control feedforward 风格）
    """

    V_EPS = 0.01               # 库仑平滑尺度 (rad/s)

    def __init__(self, q0: float = 0.0, kp: float = 50.0, kd: float = 10.0,
                 inertia: float = 0.5, damping: float = 1.0,
                 v_limit: float = 2.0, tau_limit: float = 50.0,
                 gravity: float = 0.0, coulomb: float = 0.4,
                 stribeck: float = 0.3, v_s: float = 0.05):
        self.q = float(q0)          # 位置 (rad)
        self.qd = 0.0               # 速度 (rad/s)
        self.qdd = 0.0              # 加速度 (rad/s²，由 M(q)·q̈ = τ_net 求解)
        self.tau = 0.0              # 电机输出力矩（关节力矩传感器读数）(N·m)
        self.tau_g = 0.0            # 重力矩（外部负载）(N·m)
        self.tau_f = 0.0            # 摩擦力矩 (N·m)
        self.kp = kp
        self.kd = kd
        self.inertia = inertia
        self.damping = damping
        self.v_limit = v_limit
        self.tau_limit = tau_limit
        self.gravity = gravity
        self.coulomb = coulomb
        self.stribeck = stribeck
        self.v_s = v_s

    def gravity_torque(self) -> float:
        """重力矩：位置相关的余弦负载"""
        return self.gravity * math.cos(self.q)

    def friction_torque(self) -> float:
        """非线性摩擦：粘性 + 库仑 + Stribeck"""
        v = self.qd
        s = math.tanh(v / self.V_EPS)
        coulomb = self.coulomb * s
        stribeck = self.stribeck * math.exp(-(v / self.v_s) ** 2) * s
        return self.damping * v + coulomb + stribeck

    def motor_torque(self, q_target: float, gravity_comp: bool = False) -> float:
        """PD 内环电机力矩（可选前馈重力补偿），限幅后作为关节力矩传感器读数"""
        tau = self.kp * (q_target - self.q) - self.kd * self.qd
        if gravity_comp:
            tau += self.gravity_torque()   # 前馈重力补偿
        return _clamp(tau, -self.tau_limit, self.tau_limit)


class TrapezoidPlan:
    """多轴同步梯形速度轨迹规划（工业机器人标准点到点运动生成）

    所有关节共享同一归一化位移 profile s(t)∈[0,1]（按最大关节位移 d_max 归一），
    各关节参考位置 q_ref_i = q0_i + s(t)·d_i —— 全部关节同时启停（synchronized），
    速度按位移比例分配，避免阶跃目标带来的速度/力矩冲击。
    以 d_max 决定规划形状：
    - d_max ≥ v_max²/a：梯形（加速-匀速-减速），v_peak = v_max
    - 否则退化为三角形（无匀速段），v_peak = √(a·d_max) < v_max
    """

    def __init__(self, q0: list[float], q1: list[float],
                 v_max: float = 1.0, a_max: float = 2.0):
        self.q0 = list(q0)
        self.d = [b - a for a, b in zip(q0, q1)]
        d_max = max(abs(x) for x in self.d)
        self.done = d_max < 1e-9        # 无有效位移：视为已完成
        self.v_peak = 0.0
        self.T = 0.0
        if self.done:
            return
        self._a = a_max
        self._d_max = d_max
        self.v_peak = min(v_max, math.sqrt(a_max * d_max))
        self._t_a = self.v_peak / a_max                    # 加速/减速段时间
        d_a = 0.5 * a_max * self._t_a ** 2                 # 单侧加速段位移
        self.T = 2.0 * self._t_a + max(0.0, (d_max - 2.0 * d_a) / self.v_peak)

    def frac(self, t: float) -> float:
        """归一化位移 profile s(t)∈[0,1]（梯形速度曲线的积分，t 超界钳位）"""
        if self.done:
            return 1.0
        t = _clamp(t, 0.0, self.T)
        if t < self._t_a:                                  # 加速段
            return 0.5 * self._a * t * t / self._d_max
        t_d = self.T - t
        if t_d < self._t_a:                                # 减速段
            return 1.0 - 0.5 * self._a * t_d * t_d / self._d_max
        return (0.5 * self._a * self._t_a ** 2             # 匀速段
                + self.v_peak * (t - self._t_a)) / self._d_max

    def ref(self, t: float) -> list[float]:
        """t 时刻各关节参考位置（规划结束后保持在终点）"""
        f = self.frac(t)
        return [q + f * d for q, d in zip(self.q0, self.d)]


class RobotSimulator:
    """6R 机械臂仿真端模拟器"""

    SUB_STEPS = 10               # 每发布 tick 内的物理子步数（100Hz 发布 → 1kHz 物理）

    def __init__(self, args):
        self.args = args
        self.home = self._parse_home(args.home)
        # 原始状态发布主题（默认 sim_state：边端无 ROS 2 模式的上游状态源，
        # 与边端上报云端的 simulation/{sim_id}/state 分离，避免回环）
        self._state_topic = getattr(args, 'state_topic', None) \
            or f'simulation/{args.sim_id}/sim_state'
        gravity = self._parse6(args.gravity, '--gravity')
        # 相邻关节耦合系数 c_ij（对：(0,1)(1,2)(2,3)(3,4)(4,5)），
        # M(q) 非对角项 = c_ij·cos(q_i - q_j)，位置相关 —— 0 表示退化为解耦模型
        self._coupling = [float(x) for x in args.coupling.split(',')]
        if len(self._coupling) != 5:
            raise ValueError(f"--coupling 需要 5 个值（相邻关节对），实际 {len(self._coupling)} 个")
        self.joints = [JointDynamics(
            q0=q, kp=args.kp, kd=args.kd,
            v_limit=args.v_limit, tau_limit=args.tau_limit,
            gravity=g, coulomb=args.coulomb,
        ) for q, g in zip(self.home, gravity)]
        # 边端真实状态处理器（含力矩超限 ERROR 推断与指令状态推断）
        self.processor = StateProcessor(
            args.sim_id, args.robot_id,
            default_status='RUNNING', max_torque=args.tau_limit,
        )
        # 指令目标：None = 无指令（由 mode 决定默认目标源）；指令永远优先
        self._cmd_target: list[float] | None = None
        # 云端原目标（边端容错 SAFE 只改 _cmd_target；resume 时按此重新规划）
        self._origin_target: list[float] | None = None
        # 当前运动参数（CLI 默认，可被 MOVE_JOINT 消息内 planVmax/planAcc 覆盖）
        self._plan_vmax = args.plan_vmax
        self._plan_acc = args.plan_acc
        # 梯形速度轨迹规划状态（--traj trapezoid 时 MOVE_* 指令创建）
        self._plan: TrapezoidPlan | None = None
        self._plan_t0 = 0.0          # 规划起始时刻（run() 相对时间轴）
        # 容错安全模式：SAFE 目标经安全速度限幅平滑逼近（防止 10Hz 补偿目标阶跃振荡）
        self._safe_mode = False
        self._safe_live: list[float] | None = None
        self._t0 = time.monotonic()  # run() 相对时间基准（指令时间戳换算用）
        self._lock = threading.Lock()
        self._connected = threading.Event()
        self._pub_count = 0
        # 故障注入状态
        self._tau_fault = [0.0] * 6
        # 传感器噪声注入（仅叠加在上报读数，不进动力学——与 _tau_fault 同语义）
        self._noise_sigma = self._parse3(args.sensor_noise, '--sensor-noise')
        self._spike_mag = self._parse3(args.sensor_spike_mag, '--sensor-spike-mag')
        self._spike_prob = float(args.sensor_spike_prob)
        self._rng_noise = random.Random(args.noise_seed)

    @staticmethod
    def _parse6(s: str, name: str) -> list[float]:
        vals = [float(x) for x in s.split(',')]
        if len(vals) != 6:
            raise ValueError(f"{name} 需要 6 个值，实际 {len(vals)} 个")
        return vals

    @classmethod
    def _parse_home(cls, s: str) -> list[float]:
        return cls._parse6(s, '--home')

    @staticmethod
    def _parse3(s: str, name: str) -> list[float]:
        vals = [float(x) for x in s.split(',')]
        if len(vals) != 3:
            raise ValueError(f"{name} 需要 3 个值（position,velocity,effort），实际 {len(vals)} 个")
        return vals

    def _sensor_readings(self) -> tuple[list[float], list[float], list[float]]:
        """物理真值 → 传感器读数：叠加高斯白噪声 + 随机尖峰（三通道独立）

        仅用于上报，不反馈进动力学；同种子 + 同物理轨迹下噪声序列逐帧可复现
        （供滤波 ON/OFF 对照）。尖峰幅度在 0.7~1.3 倍配置值间随机、符号随机。
        """
        sig, mag, prob, rng = self._noise_sigma, self._spike_mag, self._spike_prob, self._rng_noise
        p_out, v_out, e_out = [], [], []
        for i, j in enumerate(self.joints):
            p = j.q + rng.gauss(0.0, sig[0])
            v = j.qd + rng.gauss(0.0, sig[1])
            e = j.tau + self._tau_fault[i] + rng.gauss(0.0, sig[2])
            if prob > 0.0:
                for k, base in enumerate((p, v, e)):
                    if rng.random() < prob:
                        base += rng.choice((-1.0, 1.0)) * mag[k] * (0.7 + 0.6 * rng.random())
                    if k == 0:
                        p = base
                    elif k == 1:
                        v = base
                    else:
                        e = base
            p_out.append(round(p, 4))
            v_out.append(round(v, 4))
            e_out.append(round(e, 2))
        return p_out, v_out, e_out

    def _physics_step(self, dt: float, target: list[float]) -> None:
        """推进一个物理子步（内环 1kHz）：M(q)·q̈ = τ_motor - τ_g - τ_f - C(q,q̇)·q̇

        M(q) 对角 = 各关节惯量 J_i，相邻关节非对角 = c_ij·cos(q_i - q_j)；
        C(q,q̇)q̇ 为与 M(q) 同源的科氏/离心项（动能交叉项经 Lagrange 方程求导）；
        耦合全零时退化为各关节独立积分（与 v2.1 行为一致）。
        """
        joints = self.joints
        # 1. 各关节电机力矩与外部负载
        for j, q_t in zip(joints, target):
            j.tau = j.motor_torque(q_t, gravity_comp=self.args.gravity_comp)
            j.tau_g = j.gravity_torque()
            j.tau_f = j.friction_torque()
        # 2. 组装 M(q)：对角惯量 + 相邻关节位置相关耦合
        n = len(joints)
        m = [[0.0] * n for _ in range(n)]
        for i, j in enumerate(joints):
            m[i][i] = j.inertia
        for k in range(n - 1):
            c = self._coupling[k] * math.cos(joints[k].q - joints[k + 1].q)
            m[k][k + 1] = c
            m[k + 1][k] = c
        # 3. 科氏/离心项：动能交叉项 c_k·cos(q_k-q_{k+1})·q̇_k·q̇_{k+1} 经
        #    Lagrange 方程求导 → τ_c[k] += c_k·sin(q_k-q_{k+1})·q̇_{k+1}²，
        #    τ_c[k+1] -= c_k·sin(q_k-q_{k+1})·q̇_k²（与 M(q) 使用同一组耦合系数）
        tau_c = [0.0] * n
        if self.args.coriolis:
            for k in range(n - 1):
                c = self._coupling[k]
                if c == 0.0:
                    continue
                s = c * math.sin(joints[k].q - joints[k + 1].q)
                tau_c[k] += s * joints[k + 1].qd ** 2
                tau_c[k + 1] -= s * joints[k].qd ** 2
        # 4. 求解 q̈ 并半隐式欧拉积分
        net = [j.tau - j.tau_g - j.tau_f - tc for j, tc in zip(joints, tau_c)]
        qdd = _solve_linear(m, net)
        for i, j in enumerate(joints):
            j.qdd = qdd[i]
            j.qd = _clamp(j.qd + qdd[i] * dt, -j.v_limit, j.v_limit)
            j.q += j.qd * dt

    # ---- MQTT ----
    def _on_connect(self, client, userdata, flags, rc, props=None):
        client.subscribe(f'simulation/{self.args.sim_id}/command', qos=1)
        print(f'[SIM] 已连接 broker，订阅指令主题 simulation/{self.args.sim_id}/command，'
              f'发布原始状态 {self._state_topic}', flush=True)
        self._connected.set()

    def _accept_target(self, target: list[float]) -> None:
        """接受新目标（须持锁调用）：trapezoid 模式从当前位置规划，step 模式直接阶跃"""
        # 云端新指令优先：退出容错安全模式
        self._safe_mode = False
        self._safe_live = None
        if self.args.traj == 'trapezoid':
            plan = TrapezoidPlan([j.q for j in self.joints], target,
                                 v_max=self._plan_vmax, a_max=self._plan_acc)
            self._plan = plan
            self._plan_t0 = time.monotonic() - self._t0
            if not plan.done:
                print(f'[SIM] 轨迹规划 T={plan.T:.2f}s v_peak={plan.v_peak:.2f} rad/s',
                      flush=True)
        else:
            self._plan = None
        self._cmd_target = target
        self._origin_target = list(target)

    def _on_command(self, client, userdata, msg):
        """模拟真实仿真端接收 joint_command（此处为云端指令经边端转发的等价桥接）"""
        try:
            d = json.loads(msg.payload)
        except (ValueError, UnicodeDecodeError):
            print(f'[SIM] 指令 JSON 解析失败: {msg.payload[:80]}', flush=True)
            return
        cmd_type = d.get('cmdType', '')
        # 边端容错安全指令（内部执行器闭环）：不改变云端可见的运行状态推断
        if cmd_type == 'MOVE_JOINT_SAFE':
            with self._lock:
                if d.get('resume'):
                    origin = self._origin_target
                    if origin is not None:
                        self._safe_mode = False
                        self._safe_live = None
                        self._accept_target(list(origin))
                        print(f'[SIM] 安全模式解除，恢复原目标轨迹 '
                              f'{[round(x, 3) for x in origin]}', flush=True)
                    else:
                        print('[SIM] 收到 resume 但无云端原目标，忽略', flush=True)
                    return
                target = d.get('jointTarget')
                if not isinstance(target, list) or len(target) != 6:
                    print(f'[SIM] MOVE_JOINT_SAFE jointTarget 非法: {target}', flush=True)
                    return
                # 直接伺服安全目标（不经梯形规划），以安全速度限速逼近；
                # _origin_target 保留云端原目标，供 resume 使用
                if not self._safe_mode:
                    self._safe_live = [j.q for j in self.joints]
                self._safe_mode = True
                self._plan = None
                self._cmd_target = [float(x) for x in target]
            print(f'[SIM] 容错安全目标（直接伺服）'
                  f'{[round(float(x), 3) for x in target]}', flush=True)
            return
        # 与边端一致：指令类型驱动状态推断（STOP→STOPPED，其余→RUNNING）
        self.processor.set_command_status(cmd_type)
        if cmd_type == 'MOVE_JOINT':
            target = d.get('jointTarget')
            if not isinstance(target, list) or len(target) != 6:
                print(f'[SIM] MOVE_JOINT jointTarget 非法: {target}', flush=True)
                return
            # 可选运动参数覆盖（云端下发）：planVmax/planAcc，须为正数
            with self._lock:
                for key, attr in (('planVmax', '_plan_vmax'), ('planAcc', '_plan_acc')):
                    if key in d and d[key] is not None:
                        try:
                            v = float(d[key])
                            if v <= 0:
                                raise ValueError
                            setattr(self, attr, v)
                        except (TypeError, ValueError):
                            print(f'[SIM] 忽略非法 {key}={d[key]}', flush=True)
                self._accept_target([float(x) for x in target])
            print(f'[SIM] 收到 MOVE_JOINT target='
                  f'{[round(float(x), 3) for x in target]} '
                  f'(vmax={self._plan_vmax} acc={self._plan_acc})', flush=True)
        elif cmd_type == 'MOVE_HOME':
            with self._lock:
                self._accept_target(list(self.home))
            print('[SIM] 收到 MOVE_HOME', flush=True)
        elif cmd_type == 'STOP':
            # 刹车：清除规划，目标置为当前位置，Kd 阻尼自然减速
            with self._lock:
                self._plan = None
                self._cmd_target = [j.q for j in self.joints]
            print('[SIM] 收到 STOP（阻尼刹车）', flush=True)
        elif cmd_type == 'START':
            print('[SIM] 收到 START（恢复 RUNNING）', flush=True)
        else:
            print(f'[SIM] 未知指令类型: {cmd_type}', flush=True)

    def _default_target(self, t: float) -> list[float]:
        """无指令时的默认目标源"""
        if self.args.mode == 'sine':
            return [self.home[i] + 0.5 * math.sin(2 * math.pi * 0.2 * t + i * 0.8)
                    for i in range(6)]
        return list(self.home)  # hold

    def _update_fault(self, t: float) -> None:
        """故障注入：在 [delay, delay+duration] 窗口内对关节 0 叠加超限力矩"""
        if self.args.fault != 'overload':
            return
        a, b = self.args.fault_delay, self.args.fault_delay + self.args.fault_duration
        self._tau_fault[0] = 60.0 if a <= t < b else 0.0

    def run(self) -> None:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id=f'sim-simulator-{os.getpid()}')
        client.on_connect = self._on_connect
        client.on_message = self._on_command
        if self.args.ca_cert or self.args.cert or self.args.key:
            ctx = ssl.create_default_context(cafile=self.args.ca_cert or None)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            if self.args.tls_insecure:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            if self.args.cert:
                ctx.load_cert_chain(self.args.cert, self.args.key or None)
            client.tls_set_context(ctx)
            print(f'[SIM] MQTT TLS 已启用 (ca={self.args.ca_cert} cert={self.args.cert})',
                  flush=True)
        client.connect(self.args.broker, self.args.port, keepalive=60)
        client.loop_start()
        if not self._connected.wait(timeout=10):
            print('[SIM] 连接 broker 超时，退出', flush=True)
            return

        dt = 1.0 / self.args.rate
        sub_dt = dt / self.SUB_STEPS
        t0 = time.monotonic()
        self._t0 = t0
        next_tick = t0
        last_report = t0
        print(f'[SIM] 仿真启动 mode={self.args.mode} rate={self.args.rate}Hz '
              f'fault={self.args.fault} home={self.home} '
              f'gravity={self.args.gravity} gcomp={self.args.gravity_comp} '
              f'coulomb={self.args.coulomb} traj={self.args.traj} '
              f'coriolis={self.args.coriolis}', flush=True)

        while True:
            t = time.monotonic() - t0
            if self.args.duration > 0 and t >= self.args.duration:
                break
            self._update_fault(t)

            # 目标选择：安全模式限速逼近 SAFE 目标；否则云端指令优先
            # （trapezoid 规划进行中则按规划插值），无指令按 mode 生成
            with self._lock:
                plan = self._plan
                plan_t0 = self._plan_t0
                cmd_target = self._cmd_target
                if self._safe_mode and self._safe_live is not None \
                        and cmd_target is not None:
                    step = self.args.safe_vmax * dt
                    live = self._safe_live
                    for i in range(6):
                        delta = cmd_target[i] - live[i]
                        live[i] += _clamp(delta, -step, step)
                    target = list(live)
                elif plan is not None:
                    target = plan.ref(t - plan_t0)
                elif cmd_target is not None:
                    target = cmd_target
                else:
                    target = self._default_target(t)

            # 物理积分（1kHz 子步，含 M(q) 耦合求解）
            for _ in range(self.SUB_STEPS):
                self._physics_step(sub_dt, target)

            # 上报状态（力矩 = 伺服力矩 + 注入故障力矩 + 传感器噪声，与真实传感器叠加一致）
            meas_p, meas_v, meas_e = self._sensor_readings()
            state = self.processor.from_joint_state(
                position=meas_p,
                velocity=meas_v,
                effort=meas_e,
                stamp_nanosec=int(time.time() * 1e9),
            )
            # 原始状态发到 sim_state（边端无 ROS 2 模式的上游状态源，
            # 与边端上报云端的 simulation/{sim_id}/state 分离，避免回环）
            client.publish(self._state_topic,
                           json.dumps(state.to_dict()), qos=1)
            self._pub_count += 1

            # 每秒打印一次摘要（含肩关节重力/摩擦分量，观察非线性负载）
            if time.monotonic() - last_report >= 1.0:
                last_report = time.monotonic()
                js = self.joints[1]  # 肩关节：重力负载最大
                print(f'[SIM] t={t:5.1f}s status={state.status} pub={self._pub_count} '
                      f'q0={self.joints[0].q:+.3f} qd0={self.joints[0].qd:+.3f} '
                      f'tau0={self.joints[0].tau + self._tau_fault[0]:+.1f} '
                      f'tau_g1={js.tau_g:+.1f} tau_f1={js.tau_f:+.2f}', flush=True)

            # 绝对时间步进，避免漂移；落后过多则重置基准
            next_tick += dt
            sleep = next_tick - time.monotonic()
            if sleep > 0:
                time.sleep(sleep)
            else:
                next_tick = time.monotonic()

        print(f'[SIM] 仿真结束，共发布 {self._pub_count} 条状态', flush=True)
        client.loop_stop()
        client.disconnect()


def parse_args():
    p = argparse.ArgumentParser(description='仿真端模拟器 v2.3（物理动力学 + 轨迹规划 + 指令闭环）')
    p.add_argument('--broker', default='localhost')
    p.add_argument('--port', type=int, default=1883)
    p.add_argument('--ca-cert', default=None, help='CA 证书（启用 TLS，如 deploy/certs/ca.crt）')
    p.add_argument('--cert', default=None, help='客户端证书（CN 必须 = simulationId）')
    p.add_argument('--key', default=None, help='客户端私钥')
    p.add_argument('--tls-insecure', action='store_true',
                   help='仅联调：跳过服务端证书/主机名校验')
    p.add_argument('--sim-id', default='SIM-001')
    p.add_argument('--robot-id', default='ROBOT-001')
    p.add_argument('--state-topic', default=None,
                   help='原始状态发布主题（默认 simulation/{sim-id}/sim_state，'
                        '边端无 ROS 2 模式订阅该主题作为 joint_states 等价通道）')
    p.add_argument('--rate', type=float, default=100.0, help='状态发布频率 Hz')
    p.add_argument('--mode', choices=['hold', 'sine'], default='hold',
                   help='无指令时的默认目标源：hold=保持零位，sine=正弦巡航')
    p.add_argument('--duration', type=float, default=0, help='运行秒数，0=无限')
    p.add_argument('--home', default='0,0,0,0,0,0', help='初始/零位关节角，逗号分隔')
    p.add_argument('--gravity', default='0,6,4,1.2,0.4,0.4',
                   help='各关节峰值重力矩 N·m（基座回转轴为 0，肩/肘最大）')
    p.add_argument('--gravity-comp', action=argparse.BooleanOptionalAction, default=True,
                   help='内环前馈重力补偿（--no-gravity-comp 关闭，观察重力下垂）')
    p.add_argument('--coulomb', type=float, default=0.4, help='库仑摩擦幅值 N·m')
    p.add_argument('--coupling', default='0.1,0.08,0.05,0.03,0.02',
                   help='相邻关节 M(q) 耦合系数（对：(0,1)(1,2)(2,3)(3,4)(4,5)），'
                        '非对角项=c_ij·cos(q_i-q_j)；传 0,0,0,0,0 退化解耦模型')
    p.add_argument('--traj', choices=['step', 'trapezoid'], default='trapezoid',
                   help='运动生成：trapezoid=多轴同步梯形速度规划（工业标准），'
                        'step=阶跃目标（v2 行为）')
    p.add_argument('--plan-vmax', type=float, default=1.0, help='梯形规划峰值速度 rad/s')
    p.add_argument('--plan-acc', type=float, default=2.0, help='梯形规划加速度 rad/s²')
    p.add_argument('--safe-vmax', type=float, default=0.1,
                   help='容错安全模式目标逼近限速 rad/s（MOVE_JOINT_SAFE 通道，防补偿阶跃振荡）')
    p.add_argument('--coriolis', action=argparse.BooleanOptionalAction, default=True,
                   help='科氏/离心项 C(q,q̇)·q̇（--no-coriolis 关闭，对比轨迹差异）')
    p.add_argument('--fault', choices=['none', 'overload'], default='none',
                   help='故障注入：overload=关节0叠加60N·m超限力矩')
    p.add_argument('--fault-delay', type=float, default=3.0)
    p.add_argument('--fault-duration', type=float, default=2.0)
    # 传感器噪声注入（仅上报读数；默认全 0=关闭，保持既有行为）
    p.add_argument('--sensor-noise', default='0,0,0',
                   help='高斯白噪声 σ，三通道 position,velocity,effort（rad,rad/s,N·m）')
    p.add_argument('--sensor-spike-prob', type=float, default=0.0,
                   help='每帧每通道出现随机尖峰的概率（0=关闭）')
    p.add_argument('--sensor-spike-mag', default='0,0,0',
                   help='尖峰幅度（0.7~1.3 倍随机、符号随机），三通道同 --sensor-noise 序')
    p.add_argument('--noise-seed', type=int, default=42, help='噪声 RNG 种子（对照可复现）')
    p.add_argument('--kp', type=float, default=50.0, help='内环位置增益')
    p.add_argument('--kd', type=float, default=10.0, help='内环速度阻尼')
    p.add_argument('--v-limit', type=float, default=2.0, help='关节速度限幅 rad/s')
    p.add_argument('--tau-limit', type=float, default=50.0, help='伺服力矩限幅 N·m')
    return p.parse_args()


if __name__ == '__main__':
    RobotSimulator(parse_args()).run()

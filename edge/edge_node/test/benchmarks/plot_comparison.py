#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 48 组对比测试的数据画成图（性能对比图表 + 算法收敛曲线），补计划书附录佐证。

读 test/reports/comparison_data.json 出聚合柱状图；另重跑 1~2 个代表场景抓每步误差
时间序列，画 PID vs 自适应 NN 的跟踪/收敛曲线。图存 test/reports/figures/。
坐标轴用英文标签，避免 matplotlib 中文缺字（报告正文用中文解释）。
"""
from __future__ import annotations

import json
import math
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt          # noqa: E402
import numpy as np                        # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..')))
sys.path.insert(0, HERE)
from plant import RobotPlant               # noqa: E402
from controllers import PIDController      # noqa: E402
from scenarios import TrajectoryReference, build_scenarios  # noqa: E402
from edge_node.control.adaptive_nn_controller import AdaptiveNNController  # noqa: E402

DATA = os.path.join(HERE, '..', 'reports', 'comparison_data.json')
OUT = os.path.join(HERE, '..', 'reports', 'figures')
DT = 0.01
HOME = [0.0] * 6
BASE_COUPLING = [0.1, 0.08, 0.05, 0.03, 0.02]
BASE_GRAVITY = [0.0, 6.0, 4.0, 1.2, 0.4, 0.4]
C_PD, C_NN, C_ON, C_OFF = '#d1495b', '#2e86ab', '#2a9d8f', '#e76f51'


def _rms(v):
    return math.sqrt(sum(x * x for x in v) / len(v)) if v else 0.0


def _plant(sc):
    return RobotPlant(q0=HOME, coulomb=sc.coulomb, stribeck=sc.stribeck,
                      payload_scale=sc.payload_scale,
                      coupling=[c * sc.coupling_scale for c in BASE_COUPLING],
                      gravity=[g * sc.gravity_scale for g in BASE_GRAVITY])


def run_series(sc, kind):
    """重跑一个控制场景，返回 (时间, 每步 RMS 跟踪误差)。"""
    plant = _plant(sc)
    ref = TrajectoryReference('p2p', HOME, sc.target, v_max=sc.ref_vmax)
    if kind == 'nn':
        ctrl = AdaptiveNNController(n_joints=6, dt=DT, seed=sc.seed)
    else:
        ctrl = PIDController(n_joints=6, kp=80.0, ki=0.0, kd=18.0)
    n = int(sc.duration / DT)
    ts, err = [], []
    for k in range(n):
        t = k * DT
        q_d, qd_d = ref.sample(t)
        ctrl.set_setpoint(q_d, qd_d)
        tau = ctrl.compute_torque(plant.q, plant.qd) if kind == 'nn' \
            else ctrl.compute_torque(plant.q, plant.qd, DT)
        plant.step(tau, DT)
        ts.append(t)
        err.append(_rms([q_d[i] - plant.q[i] for i in range(6)]))
    return ts, err


def fig_control(data):
    by = {}
    for r in data['control_rows']:
        by.setdefault(r['scenario'], {})[r['kind']] = r
    names = list(by)
    pid = [by[n]['pid']['rmse_rad'] for n in names]
    nn = [by[n]['nn']['rmse_rad'] for n in names]
    x = np.arange(len(names))
    w = 0.4
    fig, ax = plt.subplots(figsize=(15, 5))
    ax.bar(x - w / 2, pid, w, label='Fixed-gain PD (traditional)', color=C_PD)
    ax.bar(x + w / 2, nn, w, label='Adaptive NN', color=C_NN)
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=90, fontsize=7)
    ax.set_ylabel('Tracking RMSE (rad)')
    red = data['summary']['control']['rmse_reduction_pct_mean']
    ax.set_title(f'Control comparison: PD vs Adaptive NN across 24 scenarios '
                 f'(mean RMSE reduction {red}%)')
    ax.legend()
    fig.tight_layout()
    p = os.path.join(OUT, 'fig_control_pd_vs_nn.png')
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def fig_fault(data):
    s = data['summary']['fault']
    by = {}
    for r in data['fault_rows']:
        by.setdefault(r['scenario'], {})[r['ftc']] = r
    names = list(by)
    tq_on = [by[n]['on']['faultjoint_torque_mean'] for n in names]
    tq_off = [by[n]['off']['faultjoint_torque_mean'] for n in names]
    x = np.arange(len(names))
    w = 0.4
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(15, 5),
                                 gridspec_kw={'width_ratios': [1, 3]})
    # 左：完成率
    a1.bar(['FTC OFF', 'FTC ON'], [s['completion_off_pct'], s['completion_on_pct']],
           color=[C_OFF, C_ON])
    a1.set_ylabel('Safe-degradation completion rate (%)')
    a1.set_ylim(0, 100)
    a1.set_title(f'Task completion (+{s["completion_gain_pp"]}pp)')
    for i, v in enumerate([s['completion_off_pct'], s['completion_on_pct']]):
        a1.text(i, v + 2, f'{v}%', ha='center')
    # 右：故障关节力矩
    a2.bar(x - w / 2, tq_off, w, label='FTC OFF', color=C_OFF)
    a2.bar(x + w / 2, tq_on, w, label='FTC ON', color=C_ON)
    a2.axhline(15, ls='--', color='gray', lw=1, label='safe torque limit 15 N·m')
    a2.set_xticks(x)
    a2.set_xticklabels(names, rotation=90, fontsize=7)
    a2.set_ylabel('Failed-joint mean torque during fault (N·m)')
    a2.set_title('Locked-joint torque: OFF keeps fighting (~50), ON releases (~0)')
    a2.legend()
    fig.tight_layout()
    p = os.path.join(OUT, 'fig_fault_ftc_on_off.png')
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def fig_convergence():
    control, _ = build_scenarios()
    picks = [s for s in control if s.name in ('payload_heavy#T1', 'high_friction#T1')]
    fig, axes = plt.subplots(1, len(picks), figsize=(13, 5), squeeze=False)
    for ax, sc in zip(axes[0], picks):
        for kind, color, lab in (('pid', C_PD, 'Fixed-gain PD'), ('nn', C_NN, 'Adaptive NN')):
            ts, err = run_series(sc, kind)
            ax.plot(ts, err, color=color, label=lab, lw=1.6)
        ax.set_xlabel('Time (s)')
        ax.set_ylabel('Tracking RMSE (rad)')
        ax.set_title(sc.name)
        ax.legend()
        ax.grid(alpha=0.3)
    fig.suptitle('Trajectory tracking error over time: NN learns & converges below PD')
    fig.tight_layout()
    p = os.path.join(OUT, 'fig_convergence.png')
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def main():
    os.makedirs(OUT, exist_ok=True)
    data = json.load(open(DATA, encoding='utf-8'))
    outs = [fig_control(data), fig_fault(data), fig_convergence()]
    for p in outs:
        print('figure ->', os.path.abspath(p))


if __name__ == '__main__':
    main()

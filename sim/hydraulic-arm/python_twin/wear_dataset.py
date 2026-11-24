"""关节轻度磨损数据集生成器（不改主孪生，全部逻辑自包含）。

模拟减速器/关节轴承的缓慢轻度磨损：不立刻停机，但带来
  - 关节摩擦增大   -> 放大 friction 的 黏性/库仑/Stribeck 系数
  - 定位微小偏差   -> 闭环里自然涌现（记录位置误差 e）
  - 轨迹抖动       -> Stribeck 黏滑 + 注入的宽带扰动力矩
  - 振动/噪声上升  -> 注入随速度调制的轴承缺陷频率正弦 + 宽带噪声

在**连续往复轨迹**上仿真（持续运动，避开主 README §4.5 里保持段的执行器失稳），
批量导出每关节时序 + 磨损标签，供边端故障检测 / 云端分析 / ML 训练使用。

边界：仿真数据，非真机实测；特征物理上成立但幅值未对标真机；dt=1ms 频率上限 ~500Hz。
用法：python wear_dataset.py            # 跑默认批次，写到 ../results/wear_dataset/
      python wear_dataset.py --smoke    # 单条基线冒烟 + 稳定性检查
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hydraulic_arm_twin as t  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results", "wear_dataset")

# 每关节轴承缺陷特征频率 [Hz]（<500Hz Nyquist，取互不相同的值便于区分）
BEARING_FREQ = np.array([37.0, 43.0, 53.0, 61.0, 71.0, 83.0])
LEVELS = {"health": (0.0, 0.0), "light": (0.15, 0.35), "moderate": (0.5, 0.9)}


def continuous_reference(tt, p, period):
    """连续往复参考：home<->target 平滑正弦摆动，持续运动、不长时间保持。"""
    q0 = np.array(p["home"], float)
    q1 = np.array(p["target"], float)
    amp = q1 - q0
    w = 2.0 * np.pi / period
    s = 0.5 * (1.0 - np.cos(w * tt))
    sd = 0.5 * w * np.sin(w * tt)
    return q0 + amp * s, amp * sd


def worn_params(w_fric):
    """按逐关节磨损系数放大摩擦（黏性/库仑/Stribeck）。"""
    p = dict(t.PARAMS)
    fr = dict(t.PARAMS["friction"])
    scale = 1.0 + np.asarray(w_fric, float)
    fr["viscous"] = list(np.array(t.PARAMS["friction"]["viscous"]) * scale)
    fr["coulomb"] = list(np.array(t.PARAMS["friction"]["coulomb"]) * scale)
    fr["stribeck"] = list(np.array(t.PARAMS["friction"]["stribeck"]) * scale)
    p["friction"] = fr
    return p


def simulate_wear(w_vec, period, t_end, seed, cfg="pid", main_ratio=0.10):
    """在连续轨迹上跑一条含磨损的仿真，返回逐关节时序 dict。

    w_vec: 6 元素磨损向量（0=健康）；同时驱动摩擦放大与振动扰动幅值。
    振动扰动力矩 d_tau = w*(宽带白噪声 + 随|qd|调制的轴承缺陷正弦)，注入关节力矩。
    控制器用**名义参数**构造（不知道磨损），符合真实工况。
    """
    rng = np.random.default_rng(seed)
    p = worn_params(w_vec)                       # 摩擦按磨损放大
    p["sim"] = dict(t.PARAMS["sim"]); p["sim"]["t_end"] = t_end
    p["ctrl"] = dict(t.PARAMS["ctrl"]); p["ctrl"]["bw_hyd_ratio"] = main_ratio
    dt = p["sim"]["dt"]; n = int(round(t_end / dt))
    payload = p["payload_mass"]
    t_max = t.actuator_torque_limit(p)[0]
    tonal_amp = 0.010 * t_max                     # 满磨损时 ~1% 能力的谱线
    broad_sigma = 0.005 * t_max                   # 宽带噪声

    plant = t.HydraulicActuator(p)
    m_home = t.mass_matrix(np.array(p["home"]), p, payload)
    ctrl = t.build_controller(dict(t.PARAMS, ctrl=p["ctrl"]), cfg, m_home)  # 名义参数
    ku = t.valve_torque_gain(p)
    q = np.array(p["home"], float); qd = np.zeros(6)

    keys = ("t", "q", "q_ref", "e", "qd", "tau", "vib", "p1", "p2")
    log = {k: np.zeros((n + 1, 6)) if k != "t" else np.zeros(n + 1) for k in keys}
    w_vec = np.asarray(w_vec, float)
    for k in range(n + 1):
        tt = k * dt
        q_ref, qd_ref = continuous_reference(tt, p, period)
        grav = t.coriolis_plus_gravity(q, np.zeros(6), t.PARAMS, payload)
        tau_cmd = ctrl.control(q, qd, q_ref, qd_ref, dt, gravity=grav)
        tau_lim = np.clip(tau_cmd, -plant.t_max, plant.t_max)
        u = tau_lim / ku
        tau = plant.step(u, qd, dt)
        # 磨损振动/噪声扰动力矩（随速度调制的轴承缺陷谱线 + 宽带）
        d_tau = w_vec * (broad_sigma * rng.standard_normal(6)
                         + tonal_amp * (0.2 + np.abs(qd))
                         * np.sin(2 * np.pi * BEARING_FREQ * tt))
        qdd = t.arm_accel(q, qd, tau + d_tau, p, payload)
        log["t"][k] = tt; log["q"][k] = q; log["q_ref"][k] = q_ref
        log["e"][k] = q_ref - q; log["qd"][k] = qd; log["tau"][k] = tau
        log["vib"][k] = qdd; log["p1"][k] = plant.p1; log["p2"][k] = plant.p2
        if not np.all(np.isfinite(q)):
            for kk in log:
                log[kk] = log[kk][:k + 1]
            log["diverged"] = True
            return log
        if k == n:
            break
        q = q + qd * dt + 0.5 * qdd * dt * dt
        qd = qd + qdd * dt
    log["diverged"] = False
    return log


def features(log):
    """每关节几个概览特征，供快速体检/标签校验（非最终特征工程）。"""
    mv = log["t"] >= 0.5      # 跳过起步暂态
    e = log["e"][mv]; vib = log["vib"][mv]; tau = log["tau"][mv]
    return dict(
        e_rms=np.sqrt(np.mean(e ** 2, axis=0)),
        vib_rms=np.sqrt(np.mean(vib ** 2, axis=0)),
        tau_rms=np.sqrt(np.mean(tau ** 2, axis=0)),
        e_max=np.abs(e).max(axis=0),
    )


def hf_vib_rms(vib_col, fs=1000.0, f_lo=15.0):
    """振动通道 ≥f_lo Hz 分量的 rms（隔离轨迹加速度低频），磨损判别用。"""
    x = vib_col - np.mean(vib_col)
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1.0 / fs)
    m = f >= f_lo
    return np.sqrt(np.sum(np.abs(X[m]) ** 2) * 2) / len(x)


def degradation(joint, n_cycles, w_max, period, out_dir=OUT_DIR):
    """渐进磨损退化轨迹：磨损随运行周期缓慢增长（略加速），逐周期提特征。

    产出 (周期 -> 特征) 的退化趋势 —— 直接对应预测性维护 / 云端 TrendService：
    对上升趋势做回归外推"照此趋势多久到危险线"。
    """
    os.makedirs(out_dir, exist_ok=True)
    j = joint - 1
    rows = []
    for k in range(n_cycles):
        frac = k / max(n_cycles - 1, 1)
        w = w_max * frac ** 1.4                 # 略加速的磨损增长
        w_vec = np.zeros(6); w_vec[j] = w
        log = simulate_wear(w_vec, period, period, seed=7000 + k)
        f = features(log)
        rows.append(dict(cycle=k, wear=round(w, 4), diverged=int(log["diverged"]),
                         hf_vib=round(hf_vib_rms(log["vib"][:, j]), 4),
                         tau_rms=round(float(f["tau_rms"][j]), 3),
                         e_rms=round(float(f["e_rms"][j]), 5)))
        print("cycle %2d  w=%.3f  hf_vib=%.3f  tau_rms=%.2f  e_rms=%.4f%s"
              % (k, w, rows[-1]["hf_vib"], rows[-1]["tau_rms"], rows[-1]["e_rms"],
                 "  DIV" if log["diverged"] else ""))
    base = os.path.join(out_dir, "degradation_J%d" % joint)
    with open(base + ".csv", "w", newline="") as fp:
        wr = csv.DictWriter(fp, fieldnames=list(rows[0].keys())); wr.writeheader(); wr.writerows(rows)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        c = [r["cycle"] for r in rows]
        fig, ax = plt.subplots(1, 3, figsize=(12, 3.2))
        ax[0].plot(c, [r["hf_vib"] for r in rows], "o-"); ax[0].set_title("HF vib (>=15Hz) rms"); ax[0].set_xlabel("cycle")
        ax[1].plot(c, [r["tau_rms"] for r in rows], "o-", color="tab:orange"); ax[1].set_title("torque rms [N*m]"); ax[1].set_xlabel("cycle")
        ax[2].plot(c, [r["wear"] for r in rows], "o-", color="tab:green"); ax[2].set_title("true wear w"); ax[2].set_xlabel("cycle")
        fig.suptitle("J%d progressive wear degradation (n=%d, w_max=%.1f)" % (joint, n_cycles, w_max))
        fig.tight_layout(); fig.savefig(base + ".png", dpi=110); plt.close(fig)
        print("图: %s.png" % base)
    except Exception as ex:
        print("（跳过出图：%s）" % ex)
    print("退化轨迹 -> %s.csv" % base)
    return rows



def generate(joints, seeds, period, t_end, out_dir=OUT_DIR):
    os.makedirs(out_dir, exist_ok=True)
    rows = []; idx = 0
    plan = [("health", -1, s) for s in range(seeds)]
    for j in joints:
        for lvl in ("light", "moderate"):
            for s in range(seeds):
                plan.append((lvl, j, s))
    for lvl, j, s in plan:
        lo, hi = LEVELS[lvl]
        rng = np.random.default_rng(1000 + idx)
        w_vec = np.zeros(6)
        if j >= 0:
            w_vec[j] = rng.uniform(lo, hi)
        log = simulate_wear(w_vec, period, t_end, seed=2000 + idx)
        fname = "run_%04d.npz" % idx
        np.savez_compressed(
            os.path.join(out_dir, fname),
            t=log["t"], q=log["q"], q_ref=log["q_ref"], e=log["e"],
            qd=log["qd"], tau=log["tau"], vib=log["vib"], p1=log["p1"], p2=log["p2"],
            w_vec=w_vec, worn_joint=j + 1 if j >= 0 else 0, level=lvl, seed=2000 + idx)
        f = features(log)
        rows.append(dict(
            file=fname, level=lvl, worn_joint=(j + 1 if j >= 0 else 0),
            w=round(float(w_vec[j]) if j >= 0 else 0.0, 4),
            diverged=int(log["diverged"]),
            e_rms_worn=round(float(f["e_rms"][j]) if j >= 0 else float(f["e_rms"].max()), 5),
            vib_rms_worn=round(float(f["vib_rms"][j]) if j >= 0 else float(f["vib_rms"].max()), 4)))
        print("%-4d %-9s J%s w=%.3f  div=%d  e_rms=%.4f vib_rms=%.3f"
              % (idx, lvl, (j + 1 if j >= 0 else "-"), w_vec[j] if j >= 0 else 0.0,
                 log["diverged"], rows[-1]["e_rms_worn"], rows[-1]["vib_rms_worn"]))
        idx += 1
    with open(os.path.join(out_dir, "manifest.csv"), "w", newline="") as fp:
        wr = csv.DictWriter(fp, fieldnames=list(rows[0].keys())); wr.writeheader(); wr.writerows(rows)
    n_div = sum(r["diverged"] for r in rows)
    print("\n%d 条样本 -> %s   (发散 %d 条)" % (len(rows), out_dir, n_div))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="单条基线冒烟 + 全关节稳定性检查")
    ap.add_argument("--degradation", action="store_true", help="渐进磨损退化轨迹（预测性维护）")
    ap.add_argument("--joint", type=int, default=4, help="退化模式：磨损关节 1..6")
    ap.add_argument("--cycles", type=int, default=16, help="退化模式：运行周期数")
    ap.add_argument("--w-max", type=float, default=0.9, help="退化模式：终态磨损")
    ap.add_argument("--joints", default="1,2,3,4,5,6", help="批量模式：磨损关节(1..6)")
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--period", type=float, default=4.0, help="往复周期 s")
    ap.add_argument("--t-end", type=float, default=8.0)
    args = ap.parse_args()

    if args.smoke:
        log = simulate_wear(np.zeros(6), args.period, args.t_end, seed=0)
        f = features(log)
        print("基线(健康)连续轨迹 t_end=%.1f period=%.1f  diverged=%s"
              % (args.t_end, args.period, log["diverged"]))
        print("  全程 |e|max J1..J6:", " ".join("%.3f" % v for v in f["e_max"]))
        print("  e_rms   J1..J6:", " ".join("%.4f" % v for v in f["e_rms"]))
        bounded = np.all(f["e_max"] < 0.5) and not log["diverged"]
        print("  六轴连续轨迹%s" % ("有界，可用于批量生成 [OK]" if bounded else "仍有发散 [NG]（需缩短周期/换轨迹）"))
        # 磨损对比：J2 中度
        w = np.zeros(6); w[1] = 0.8
        lw = simulate_wear(w, args.period, args.t_end, seed=1); fw = features(lw)
        print("  J2 中度磨损(w=0.8) vs 健康: e_rms %.4f->%.4f  vib_rms %.3f->%.3f"
              % (f["e_rms"][1], fw["e_rms"][1], f["vib_rms"][1], fw["vib_rms"][1]))
        return

    joints = [int(x) - 1 for x in args.joints.split(",") if x.strip()]
    if args.degradation:
        degradation(args.joint, args.cycles, args.w_max, args.period)
        return
    generate(joints, args.seeds, args.period, args.t_end)


if __name__ == "__main__":
    main()



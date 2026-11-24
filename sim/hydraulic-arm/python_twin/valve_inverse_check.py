"""静态阀口反解 / 可复现结构的对照实验（不参与 results/ 主报告）

用法（在 python_twin 目录下）：

    python valve_inverse_check.py              # 默认 4 s 窗口，约 4~5 分钟
    python valve_inverse_check.py --t-end 0.2  # 冒烟用，只验证代码路径

对比三个配置：

    pid      现基线   线性阀口增益 u = tau/Ku + PD + 重力前馈 + 积分
    pdff     实验结构  全关节静态阀口反解 + PD + 重力前馈，无积分、无学习
    pdff_j5  改进结构  同 pdff，但 J5（腕摆）改回线性阀口增益 + 单独整定带宽

并把 bw_hyd_ratio 扫一遍（0.25 / 0.10 / 0.05）：准确的力矩接口把回路增益抬高了
一个量级，原"带宽 <= 0.25 * 液压阻尼极点"的整定规则不再适用，必须一起扫。
（pdff_j5 下 J5 恒用 bw_hyd_ratio_j5，不随扫描变化。）

判据：rms(e) 逐关节不差于 PID，且峰值力矩不顶到执行器上限（打 SAT!）。

实测结论（4 s 窗口）与推导见 ../README.md「可复现结构实验」一节。
"""
from __future__ import annotations

import argparse
import sys
import os

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hydraulic_arm_twin as t  # noqa: E402

RATIOS = (0.25, 0.10, 0.05)
CONFIGS = ("pid", "pdff", "pdff_j5")


def run(cfg, ratio, t_end):
    p = dict(t.PARAMS)
    p["sim"] = dict(t.PARAMS["sim"])
    p["sim"]["t_end"] = t_end
    p["ctrl"] = dict(t.PARAMS["ctrl"])
    p["ctrl"]["bw_hyd_ratio"] = ratio

    m_home = t.mass_matrix(np.array(p["home"]), p, p["payload_mass"])
    log = t.simulate(p, cfg, m_home)
    dt = p["sim"]["dt"]
    k_move = int(round(min(3.0, t_end) / dt))
    rms = np.sqrt(np.mean(log["e_abs"][: k_move + 1] ** 2, axis=0))
    peak = np.max(np.abs(log["tau"]), axis=0)
    limit = t.actuator_torque_limit(p)[0]
    return rms, peak, limit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--t-end", type=float, default=4.0,
                    help="仿真时长（s），默认 4.0 覆盖运动段 + 保持段")
    args = ap.parse_args()

    print("window: 0 ~ %.1f s   (运动段 0~3 s, 保持段 3~4 s)\n" % args.t_end)
    header = "ratio  cfg    rms(e) per joint J1..J6                        peak/sat"
    print(header)
    print("-" * len(header))

    for ratio in RATIOS:
        for cfg in CONFIGS:
            rms, peak, limit = run(cfg, ratio, args.t_end)
            sat = "".join("SAT " if v >= 0.98 * L else " .  "
                          for v, L in zip(peak, limit))
            print("%5.2f  %-5s  %s   |  %s"
                  % (ratio, cfg, " ".join("%6.3f" % v for v in rms), sat))
        print()

    print("判据：rms 逐关节不差于 pid，且不打 SAT。")
    print("pdff_j5 下 J5 恒用 bw_hyd_ratio_j5=%.2f（线性映射保留阻尼，可用高带宽）。"
          % t.PARAMS["ctrl"]["bw_hyd_ratio_j5"])


if __name__ == "__main__":
    main()
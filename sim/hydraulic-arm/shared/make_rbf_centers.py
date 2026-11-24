"""为 Python 仿真生成固定的 RBF 中心表。

用法（在 sim/hydraulic-arm/shared 目录下）：
    python make_rbf_centers.py

注意：重新生成会改变仿真结果，需要同步重跑 Python 孪生并更新
results/simulation_report.md。默认参数与 Python 孪生原用的
default_rng(42) 完全一致，因此重新生成不会改变现有报告数值。
"""
from __future__ import annotations

import os

import numpy as np

SEED = 42
INPUT_DIM = 12                      # 2 * n_joints
CENTER_COUNTS = (64, 256)           # 边端默认 / 整定工况

HERE = os.path.dirname(os.path.abspath(__file__))


def center_table(n_centers: int, input_dim: int, seed: int = SEED) -> np.ndarray:
    """与 Python 孪生 RBFNetwork 原实现等价的中心生成式。"""
    rng = np.random.default_rng(seed)
    return rng.uniform(-1.0, 1.0, size=(n_centers, input_dim))


def write_table(n_centers: int, input_dim: int) -> str:
    path = os.path.join(HERE, "rbf_centers_%dx%d.csv" % (n_centers, input_dim))
    c = center_table(n_centers, input_dim)
    # %.17g 保留 float64 精度。
    np.savetxt(path, c, delimiter=",", fmt="%.17g")
    return path


def main() -> None:
    for n in CENTER_COUNTS:
        path = write_table(n, INPUT_DIM)
        print("wrote %s" % os.path.normpath(path))


if __name__ == "__main__":
    main()

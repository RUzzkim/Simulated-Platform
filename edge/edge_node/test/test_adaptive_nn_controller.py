"""自适应神经网络控制器单元测试

覆盖：
  - RBF 网络：前向输出维度、权重更新有效性、边界值
  - 自适应 NN 控制器：力矩计算、目标位置计算、setpoint 设置
  - 闭环仿真：在简化 2 自由度模型上验证跟踪误差收敛
"""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from edge_node.control.rbf_network import RBFNetwork
from edge_node.control.adaptive_nn_controller import AdaptiveNNController


class TestRBFNetwork(unittest.TestCase):

    def test_output_dimension(self):
        net = RBFNetwork(input_dim=12, output_dim=6, n_centers=32, seed=0)
        x = [0.0] * 12
        out = net.forward(x)
        self.assertEqual(len(out), 6)

    def test_activate_dimension(self):
        net = RBFNetwork(input_dim=4, output_dim=2, n_centers=10, seed=0)
        phi = net.activate([0.1, -0.2, 0.3, -0.4])
        self.assertEqual(len(phi), 10)
        for v in phi:
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)

    def test_weights_change_after_update(self):
        net = RBFNetwork(input_dim=4, output_dim=2, n_centers=8, learning_rate=1.0, seed=0)
        x = [0.5, 0.5, 0.5, 0.5]
        s = [1.0, -1.0]
        w_before = [row[:] for row in net.weights]
        net.update_weights(x, s, dt=0.01)
        w_after = net.weights
        changed = any(
            abs(w_after[i][j] - w_before[i][j]) > 1e-12
            for i in range(8) for j in range(2)
        )
        self.assertTrue(changed, "权重应在 update 后发生变化")

    def test_zero_weights_give_zero_output(self):
        net = RBFNetwork(input_dim=6, output_dim=3, n_centers=16, seed=0)
        # 权重初始为 0
        out = net.forward([0.0] * 6)
        for v in out:
            self.assertAlmostEqual(v, 0.0, places=12)

    def test_reset(self):
        net = RBFNetwork(input_dim=4, output_dim=2, n_centers=8, seed=0)
        net.update_weights([0.1, 0.2, 0.3, 0.4], [1.0, 1.0], dt=0.1)
        net.reset()
        for row in net.weights:
            for w in row:
                self.assertAlmostEqual(w, 0.0, places=12)


class TestAdaptiveNNController(unittest.TestCase):

    def _make_controller(self, **kw):
        defaults = dict(
            n_joints=6, lambda_gain=5.0, kd=20.0, learning_rate=0.05,
            leakage=0.0, n_centers=32, nominal_inertia=1.0,
            position_range=3.14, velocity_range=2.0, dt=0.01, seed=0,
        )
        defaults.update(kw)
        return AdaptiveNNController(**defaults)

    def test_setpoint(self):
        ctl = self._make_controller()
        target = [0.5, 0.3, -0.2, 0.1, 0.0, -0.1]
        ctl.set_setpoint(target)
        self.assertEqual(ctl.setpoint_q, target)

    def test_compute_torque_shape(self):
        ctl = self._make_controller()
        ctl.set_setpoint([0.5] * 6)
        tau = ctl.compute_torque(q=[0.0] * 6, q_dot=[0.0] * 6)
        self.assertEqual(len(tau), 6)

    def test_compute_target_position_shape(self):
        ctl = self._make_controller()
        ctl.set_setpoint([0.5] * 6)
        q_target = ctl.compute_target_position(q=[0.0] * 6, q_dot=[0.0] * 6)
        self.assertEqual(len(q_target), 6)

    def test_zero_error_produces_small_target_offset(self):
        """当状态已经在 setpoint 上时，目标位置应接近当前位置"""
        ctl = self._make_controller()
        q = [0.3] * 6
        ctl.set_setpoint(q)  # setpoint == 当前位置
        q_target = ctl.compute_target_position(q=q, q_dot=[0.0] * 6)
        for i in range(6):
            # 误差为 0，目标位置应在当前位置附近（dt² 量级的偏移）
            self.assertLess(abs(q_target[i] - q[i]), 0.01)


class TestClosedLoopConvergence(unittest.TestCase):
    """在简化 2 自由度模型上验证闭环跟踪误差收敛

    仿真动力学（解耦，便于验证）：
      M_i q̈_i + B_i q̇_i = τ_i
    其中 M_i = 1, B_i = 0.5。
    控制器输出目标位置 q_target，仿真端用一个 PD 位置环跟踪：
      τ_i = Kp (q_target - q) - Kd q̇
    验证：跟踪误差 ||e|| 随时间下降。
    """

    def test_2dof_tracking_converges(self):
        n = 2
        ctl = AdaptiveNNController(
            n_joints=n, lambda_gain=5.0, kd=20.0, learning_rate=0.01,
            leakage=0.001, n_centers=50, nominal_inertia=1.0,
            position_range=3.14, velocity_range=3.0, dt=0.005, seed=1,
        )
        q_d = [0.5, -0.3]
        ctl.set_setpoint(q_d)

        # 仿真参数
        M = [1.0, 1.0]
        B = [0.5, 0.5]
        Kp_sim = 50.0    # 仿真端位置环增益
        Kd_sim = 10.0    # 仿真端速度阻尼

        q = [0.0, 0.0]
        q_dot = [0.0, 0.0]
        dt = 0.005
        steps = 6000

        initial_err = math.sqrt(sum((q_d[i] - q[i]) ** 2 for i in range(n)))
        final_err = initial_err

        for _ in range(steps):
            # 控制器计算目标位置
            q_target = ctl.compute_target_position(q, q_dot)
            # 仿真端 PD 位置环产生力矩
            tau = [Kp_sim * (q_target[i] - q[i]) - Kd_sim * q_dot[i] for i in range(n)]
            # 动力学积分
            for i in range(n):
                q_ddot = (tau[i] - B[i] * q_dot[i]) / M[i]
                q_dot[i] += q_ddot * dt
                q[i] += q_dot[i] * dt

        final_err = math.sqrt(sum((q_d[i] - q[i]) ** 2 for i in range(n)))
        # 误差应显著下降（收敛到初始误差的 10% 以内）
        self.assertLess(final_err, 0.1 * initial_err,
                        f"跟踪误差未收敛: initial={initial_err:.4f} final={final_err:.4f}")

    def test_setpoint_step_response(self):
        """阶跃响应：从 0 到目标位置，超调应有限且最终收敛"""
        n = 2
        ctl = AdaptiveNNController(
            n_joints=n, lambda_gain=5.0, kd=20.0, learning_rate=0.01,
            leakage=0.001, n_centers=50, nominal_inertia=1.0,
            position_range=3.14, velocity_range=3.0, dt=0.005, seed=2,
        )
        q_d = [1.0, 1.0]
        ctl.set_setpoint(q_d)

        M = [1.0, 1.0]
        B = [0.5, 0.5]
        Kp_sim = 50.0
        Kd_sim = 10.0

        q = [0.0, 0.0]
        q_dot = [0.0, 0.0]
        dt = 0.005
        steps = 8000

        max_q = [0.0] * n
        for _ in range(steps):
            q_target = ctl.compute_target_position(q, q_dot)
            tau = [Kp_sim * (q_target[i] - q[i]) - Kd_sim * q_dot[i] for i in range(n)]
            for i in range(n):
                q_ddot = (tau[i] - B[i] * q_dot[i]) / M[i]
                q_dot[i] += q_ddot * dt
                q[i] += q_dot[i] * dt
                max_q[i] = max(max_q[i], q[i])

        final_err = math.sqrt(sum((q_d[i] - q[i]) ** 2 for i in range(n)))
        self.assertLess(final_err, 0.05, f"阶跃响应未收敛，误差={final_err:.4f}")
        # 超调不超过 50%
        for i in range(n):
            overshoot = max_q[i] - q_d[i]
            self.assertLess(overshoot, 0.5 * abs(q_d[i]) + 0.05,
                            f"关节{i} 超调过大: {overshoot:.4f}")


if __name__ == '__main__':
    unittest.main()

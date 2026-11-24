# -*- coding: utf-8 -*-
"""信号滤波与离群点剔除模块单元测试

运行：py test/test_signal_filter.py
（纯标准库 unittest，无 numpy；固定随机种子保证可复现）
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from edge_node.processor.signal_filter import ChannelFilter, RobotSignalFilter


class TestChannelFilter(unittest.TestCase):

    def test_first_frame_passthrough(self):
        """首帧（暖机期）直通，不剔除"""
        ch = ChannelFilter(window_size=3, outlier_k=3.5, ema_alpha=0.5, min_sigma=0.1)
        y, out = ch.process(42.0)
        self.assertFalse(out)
        self.assertEqual(y, 42.0)

    def test_warmup_no_reject(self):
        """暖机期内即便出现大跳变也不剔除（统计基线未形成）"""
        ch = ChannelFilter(window_size=3, outlier_k=3.5, ema_alpha=1.0, min_sigma=0.1)
        outs = []
        for x in (0.0, 100.0, 0.0):  # 3 帧恰填满窗口
            _, out = ch.process(x)
            outs.append(out)
        self.assertNotIn(True, outs)

    def test_isolated_spike_rejected(self):
        """稳态中插入单帧尖峰：被识别、输出有界保持、尖峰不入统计"""
        ch = ChannelFilter(window_size=3, outlier_k=3.5, ema_alpha=0.5, min_sigma=0.1)
        for _ in range(6):
            ch.process(0.0)
        y_spike, out = ch.process(100.0)
        self.assertTrue(out, '单帧尖峰必须被判为离群')
        self.assertLess(abs(y_spike), 1.0, '尖峰帧输出应保持在基线附近（hold），实测 %f' % y_spike)
        self.assertEqual(ch.outlier_count, 1)
        # 尖峰后立即恢复正常采样，统计未被污染
        y_after, out_after = ch.process(0.0)
        self.assertFalse(out_after)
        self.assertLess(abs(y_after), 1.0)

    def test_min_sigma_guards_static_window(self):
        """MAD=0 的静止窗口：min_sigma 内的正常微小波动不被误剔"""
        ch = ChannelFilter(window_size=3, outlier_k=3.5, ema_alpha=1.0, min_sigma=0.1)
        for _ in range(5):
            ch.process(0.0)
        _, out = ch.process(0.05)  # < 3.5×0.1 = 0.35
        self.assertFalse(out)
        _, out_big = ch.process(5.0)  # 远超退化阈值
        self.assertTrue(out_big)

    def test_persistent_step_passes_through(self):
        """持续阶跃（真实物理变化，如力矩过载）必须在 ≤window 帧内穿透并收敛"""
        ch = ChannelFilter(window_size=3, outlier_k=3.5, ema_alpha=0.5, min_sigma=0.1)
        rejected_after_step = 0
        ys = []
        for t in range(50):
            x = 0.0 if t < 10 else 50.0
            y, out = ch.process(x)
            ys.append(y)
            if t >= 10 and out:
                rejected_after_step += 1
        # 仅阶跃起始 ≤(window-1) 帧允许被当离群，之后必须穿透
        self.assertLessEqual(rejected_after_step, 2,
                             '阶跃后被剔帧数 %d 超过 window-1=2' % rejected_after_step)
        self.assertAlmostEqual(ys[-1], 50.0, delta=0.5,
                               msg='EMA 稳态应收敛到阶跃值，实测 %f' % ys[-1])
        # 穿透延迟：阶跃第 4 帧（index 13）起中值已迁移，输出应已明显离开基线
        self.assertGreater(ys[13], 10.0, '阶跃穿透过慢，第4帧输出 %f' % ys[13])

    def test_no_drift_on_constant(self):
        """恒值信号长时间运行无漂移、无误剔"""
        ch = ChannelFilter(window_size=3, outlier_k=3.5, ema_alpha=0.5, min_sigma=0.01)
        y = None
        for _ in range(500):
            y, _ = ch.process(0.5)
        self.assertEqual(y, 0.5)
        self.assertEqual(ch.outlier_count, 0)

    def test_gaussian_noise_attenuation(self):
        """连续高斯噪声：EMA 输出方差相对原始显著降低
        理论先验：α=0.5 的 EMA 对白噪声方差比 ≈ α/(2-α)=1/3（降幅约 67%）"""
        random.seed(42)
        raw = [1.0 + random.gauss(0.0, 0.05) for _ in range(1000)]
        ch = ChannelFilter(window_size=3, outlier_k=8.0, ema_alpha=0.5, min_sigma=0.001)
        ys = [ch.process(x)[0] for x in raw]
        tail_raw = raw[300:]
        tail_out = ys[300:]
        var_raw = _variance(tail_raw)
        var_out = _variance(tail_out)
        reduction = 1.0 - var_out / var_raw
        self.assertGreater(reduction, 0.60,
                           '噪声方差降幅 %.1f%% < 60%%（raw var=%.5f out var=%.5f）'
                           % (reduction * 100, var_raw, var_out))

    def test_invalid_params(self):
        with self.assertRaises(ValueError):
            ChannelFilter(window_size=1)
        with self.assertRaises(ValueError):
            ChannelFilter(ema_alpha=0.0)
        with self.assertRaises(ValueError):
            ChannelFilter(ema_alpha=1.1)

    def test_reset(self):
        ch = ChannelFilter(window_size=3, ema_alpha=1.0, min_sigma=0.1)
        for _ in range(6):
            ch.process(0.0)
        ch.process(100.0)
        self.assertEqual(ch.outlier_count, 1)
        ch.reset()
        self.assertEqual(ch.outlier_count, 0)
        y, out = ch.process(7.0)  # reset 后首帧直通
        self.assertEqual(y, 7.0)
        self.assertFalse(out)


class TestRobotSignalFilter(unittest.TestCase):

    def _frame(self, p=0.0, v=0.0, e=0.0):
        return [p] * 6, [v] * 6, [e] * 6

    def test_six_joints_independent(self):
        """只有一个关节出现 effort 尖峰：仅该关节标志置位，其余轴值不受影响"""
        rf = RobotSignalFilter()
        for _ in range(6):
            rf.filter(*self._frame(e=1.0))
        p, v, e = self._frame(e=1.0)
        e[3] = 99.0  # 关节 3 单轴尖峰
        fp, fv, fe, flags = rf.filter(p, v, e)
        self.assertTrue(flags[3])
        self.assertFalse(any(flags[i] for i in range(6) if i != 3))
        self.assertAlmostEqual(fe[3], 1.0, delta=1.0)  # 保持基线
        for i in (0, 1, 2, 4, 5):
            self.assertAlmostEqual(fe[i], 1.0, delta=1e-9)

    def test_stats_counters(self):
        rf = RobotSignalFilter()
        for _ in range(6):
            rf.filter(*self._frame())
        # 注入 3 个稀疏的关节 2 位置尖峰（间隔 5 帧基线；
        # 尖峰密度必须远低于 MAD 50% 崩溃点，否则统计上不可区分基线与尖峰）
        for _ in range(3):
            for _ in range(5):
                rf.filter(*self._frame())
            p, v, e = self._frame()
            p[2] = 50.0
            rf.filter(p, v, e)
        self.assertEqual(rf.outlier_frames, 3)
        self.assertEqual(rf.outlier_by_joint[2], 3)
        self.assertEqual(rf.outlier_by_joint[0], 0)

    def test_output_shapes(self):
        rf = RobotSignalFilter(n_joints=6)
        fp, fv, fe, flags = rf.filter(*self._frame(p=0.1, v=0.2, e=0.3))
        self.assertEqual(len(fp), 6)
        self.assertEqual(len(fv), 6)
        self.assertEqual(len(fe), 6)
        self.assertEqual(len(flags), 6)

    def test_reset_clears_stats(self):
        rf = RobotSignalFilter()
        for _ in range(6):
            rf.filter(*self._frame())
        p, v, e = self._frame()
        p[0] = 99.0
        rf.filter(p, v, e)
        self.assertGreater(rf.outlier_frames, 0)
        rf.reset()
        self.assertEqual(rf.stats['processed_frames'], 0)
        self.assertEqual(rf.stats['outlier_frames'], 0)


def _variance(xs):
    n = len(xs)
    mean = sum(xs) / n
    return sum((x - mean) ** 2 for x in xs) / n


if __name__ == '__main__':
    unittest.main(verbosity=2)

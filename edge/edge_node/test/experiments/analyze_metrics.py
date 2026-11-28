"""汇总 V2.0 正式实验的控制周期、轨迹连续性与稳定性指标。

数据源：official-validation-r1/summary.json 及其引用的 CSV.GZ 原始轨迹。
注意：轨迹使用仿真时间，不含 MQTT 应用层序号或网络抓包信息；因此本脚本
计算的是仿真控制周期和轨迹缺帧，不能据此声称测得真实网络丢包或墙钟抖动。
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from collections import defaultdict
from pathlib import Path


STRATEGIES = ('off', 'v1', 'v2')


def percentile(values: list[float], probability: float) -> float | None:
    """线性插值分位数。"""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def fmt(value: float | None, digits: int = 3) -> str:
    return '-' if value is None else f'{value:.{digits}f}'


def distribution(values: list[float]) -> tuple[float | None, ...]:
    return percentile(values, 0.50), percentile(values, 0.95), max(values, default=None)


def read_run_metrics(run: dict, trace_path: Path, sample_rate_hz: int,
                     duration_s: float, limits: dict) -> dict:
    with gzip.open(trace_path, 'rt', encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError(f'空轨迹：{trace_path}')

    expected_frames = int(round(sample_rate_hz * duration_s))
    steps = [int(row['step']) for row in rows]
    if len(set(steps)) != len(steps) or steps != sorted(steps):
        raise ValueError(f'轨迹 step 重复或乱序：{trace_path}')
    if any(step < 0 or step >= expected_frames for step in steps):
        raise ValueError(f'轨迹 step 超出 [0, {expected_frames})：{trace_path}')
    if any(row['run_id'] != run['run_id'] or row['strategy'] != run['strategy']
           for row in rows):
        raise ValueError(f'轨迹与 manifest 的 run_id/strategy 不一致：{trace_path}')

    times = [float(row['t_s']) for row in rows]
    if any(current <= previous for previous, current in zip(times, times[1:])):
        raise ValueError(f'轨迹时间戳非严格递增：{trace_path}')
    periods_ms = [(current - previous) * 1000.0
                  for previous, current in zip(times, times[1:])]

    peak_speed = 0.0
    peak_torque = 0.0
    position_violations = 0
    speed_violations = 0
    torque_violations = 0
    terminal_speed_squares: list[float] = []
    terminal_start = times[-1] - 1.0
    for row, timestamp in zip(rows, times):
        positions = [abs(float(row[f'q{i}'])) for i in range(6)]
        speeds = [abs(float(row[f'qd{i}'])) for i in range(6)]
        torques = [abs(float(row[f'tau{i}'])) for i in range(6)]
        position_violations += sum(value > limits['position'] + 1e-12 for value in positions)
        speed_violations += sum(value > limits['speed'] + 1e-12 for value in speeds)
        torque_violations += sum(value > limits['torque'] + 1e-12 for value in torques)
        peak_speed = max(peak_speed, *speeds)
        peak_torque = max(peak_torque, *torques)
        if timestamp >= terminal_start - 1e-12:
            terminal_speed_squares.extend(value * value for value in speeds)

    return {
        'run_id': run['run_id'],
        'strategy': run['strategy'],
        'frames': len(rows),
        'expected_frames': expected_frames,
        'missing_frames': expected_frames - len(rows),
        'periods_ms': periods_ms,
        'peak_speed': peak_speed,
        'peak_torque': peak_torque,
        'terminal_speed_rms': math.sqrt(
            sum(terminal_speed_squares) / len(terminal_speed_squares)
        ) if terminal_speed_squares else None,
        'position_violations': position_violations,
        'speed_violations': speed_violations,
        'torque_violations': torque_violations,
        'bounded': not (position_violations or speed_violations or torque_violations),
    }


def render_report(metrics: list[dict], summary_path: str,
                  sample_rate_hz: int, duration_s: float, limits: dict) -> str:
    by_strategy: dict[str, list[dict]] = defaultdict(list)
    for metric in metrics:
        by_strategy[metric['strategy']].append(metric)

    lines = [
        '# V2.0 系统指标分布（validation-r1）',
        '',
        '## 0. 数据与口径',
        '',
        f'- 数据源：`{summary_path}`；共 {len(metrics)} 条 Run，'
        f'{sum(item["frames"] for item in metrics)} 帧原始轨迹。',
        f'- 每条 Run 目标时长 {duration_s:.1f}s、采样率 {sample_rate_hz}Hz，'
        f'应有 {int(round(sample_rate_hz * duration_s))} 帧。',
        '- **控制周期**：相邻轨迹帧 `t_s` 之差，属于仿真时间周期，不是边端 OS/ROS 2 墙钟调度周期。',
        '- **轨迹缺帧**：按 `step` 在应有区间内逐条核查，覆盖开头、中间和末尾缺失；'
        '缺帧率 = 缺帧数 / 应有帧数。它反映轨迹连续性，**不等同于 MQTT 网络丢包率**。',
        '- **稳定性**：全程检查 '
        f'`|q|≤{fmt(limits["position"], 2)}rad`、`|qd|≤{fmt(limits["speed"], 2)}rad/s`、'
        f'`|tau|≤{fmt(limits["torque"], 2)}N·m`；另计算末 1 秒全部 6 关节速度 RMS。',
        '- 周期分位数基于全部相邻帧间隔；峰值速度、峰值力矩和末 1 秒速度 RMS 先按 Run 计算，'
        '再对 Run 做 p50/p95/max 分布。分位数使用线性插值。',
        '',
        '## 1. 控制周期与轨迹连续性',
        '',
        '| 策略 | Run | 实收/应有帧 | 缺帧 | 缺帧率 | 周期 p50(ms) | p95(ms) | p99(ms) | max(ms) |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for strategy in (*STRATEGIES, '全部'):
        selected = metrics if strategy == '全部' else by_strategy[strategy]
        periods = [period for item in selected for period in item['periods_ms']]
        frames = sum(item['frames'] for item in selected)
        expected = sum(item['expected_frames'] for item in selected)
        missing = sum(item['missing_frames'] for item in selected)
        lines.append(
            f'| {strategy} | {len(selected)} | {frames}/{expected} | {missing} | '
            f'{missing / expected * 100:.4f}% | {fmt(percentile(periods, 0.50))} | '
            f'{fmt(percentile(periods, 0.95))} | {fmt(percentile(periods, 0.99))} | '
            f'{fmt(max(periods, default=None))} |'
        )

    lines.extend([
        '',
        '## 2. 稳定性',
        '',
        '### 2.1 安全边界',
        '',
        '| 策略 | 有界 Run | 位置越界值 | 超速值 | 超力矩值 |',
        '|---|---:|---:|---:|---:|',
    ])
    for strategy in (*STRATEGIES, '全部'):
        selected = metrics if strategy == '全部' else by_strategy[strategy]
        bounded = sum(item['bounded'] for item in selected)
        lines.append(
            f'| {strategy} | {bounded}/{len(selected)} | '
            f'{sum(item["position_violations"] for item in selected)} | '
            f'{sum(item["speed_violations"] for item in selected)} | '
            f'{sum(item["torque_violations"] for item in selected)} |'
        )

    lines.extend([
        '',
        '### 2.2 Run 级指标分布',
        '',
        '| 策略 | 峰值速度 p50(rad/s) | p95 | max | 峰值力矩 p50(N·m) | p95 | max | 末1s速度RMS p50(rad/s) | p95 | max |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ])
    for strategy in (*STRATEGIES, '全部'):
        selected = metrics if strategy == '全部' else by_strategy[strategy]
        speed = distribution([item['peak_speed'] for item in selected])
        torque = distribution([item['peak_torque'] for item in selected])
        terminal = distribution([item['terminal_speed_rms'] for item in selected
                                 if item['terminal_speed_rms'] is not None])
        lines.append(
            f'| {strategy} | {fmt(speed[0])} | {fmt(speed[1])} | {fmt(speed[2])} | '
            f'{fmt(torque[0])} | {fmt(torque[1])} | {fmt(torque[2])} | '
            f'{fmt(terminal[0], 4)} | {fmt(terminal[1], 4)} | {fmt(terminal[2], 4)} |'
        )

    all_periods = [period for item in metrics for period in item['periods_ms']]
    total_frames = sum(item['frames'] for item in metrics)
    total_expected = sum(item['expected_frames'] for item in metrics)
    total_missing = sum(item['missing_frames'] for item in metrics)
    bounded = sum(item['bounded'] for item in metrics)
    lines.extend([
        '',
        '## 3. 结论与边界',
        '',
        f'- {len(metrics)} 条 Run 共 {total_frames}/{total_expected} 帧，轨迹缺帧 {total_missing}，'
        f'缺帧率 {total_missing / total_expected * 100:.4f}%。',
        f'- 仿真控制周期 p50={fmt(percentile(all_periods, 0.50))}ms、'
        f'p95={fmt(percentile(all_periods, 0.95))}ms、max={fmt(max(all_periods, default=None))}ms。',
        f'- {bounded}/{len(metrics)} 条 Run 全程满足位置、速度和力矩安全边界。',
        '- 当前契约与回放负载没有应用层 `seq`，本数据不能识别 MQTT 重复、重传或网络丢包；'
        '真实网络丢包率需另加序号或由 broker/订阅端抓包统计。',
        '- 当前周期来自离线 Python 仿真轨迹，不能替代 ROS 2/边端进程在真实调度负载下的墙钟时延测试。',
    ])
    return '\n'.join(lines) + '\n'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--summary', required=True)
    parser.add_argument('--out', help='可选：写入 Markdown 报告')
    parser.add_argument('--duration-s', type=float, default=8.0)
    args = parser.parse_args()

    summary_path = Path(args.summary)
    data = json.loads(summary_path.read_text(encoding='utf-8'))
    sample_rate_hz = int(data['meta']['sample_rate_hz'])
    limits = {
        'position': math.pi,
        'speed': float(data['meta']['max_scored_velocity_rad_s']),
        'torque': float(data['meta']['max_joint_torque_nm']),
    }
    metrics = [
        read_run_metrics(run, summary_path.parent / run['trace'],
                         sample_rate_hz, args.duration_s, limits)
        for run in data['runs']
    ]
    report = render_report(metrics, summary_path.as_posix(),
                           sample_rate_hz, args.duration_s, limits)
    print(report)
    if args.out:
        Path(args.out).write_text(report, encoding='utf-8')


if __name__ == '__main__':
    main()

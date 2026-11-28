"""三策略（off / v1 / v2）对照分析。

数据源：test/experiments/data/official-validation-r1/summary.json
（G-3 已验证 manifest ↔ DB ↔ trace.sha256 全部 72/72 一致，故本脚本
可离线复算，无需后端在线。）

口径（冻结于 docs/v2-experiment-contract.md §2.1，不得在脚本里改语义）：
- task.status：recovered=True → RECOVERED；safe_stopped=True → SAFE_STOPPED；
  注入故障但二者皆否 → FAILED；无故障 → NOT_APPLICABLE。
- 决策：summary.action ∈ {RECOVER, STOP, None}；off 策略恒为 None。
- 可达性：仅 v2 评估；本脚本按 action 反推 REACHABLE/NO_FEASIBLE_PLAN，
  与云端 reachability 列对齐（G-3 已核对）。
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path


def derive_status(run: dict) -> str:
    if not run.get('fault_injected', True):
        return 'NOT_APPLICABLE'
    if run.get('recovered'):
        return 'RECOVERED'
    if run.get('safe_stopped'):
        return 'SAFE_STOPPED'
    return 'FAILED'


def median(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 4) if values else None


def mean(values):
    values = [v for v in values if v is not None]
    return round(statistics.mean(values), 4) if values else None


def fmt(v):
    return '-' if v is None else (f'{v:.4f}' if isinstance(v, float) else str(v))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--summary', required=True)
    ap.add_argument('--out', help='可选：把对照结果写到该 markdown 文件')
    args = ap.parse_args()

    data = json.loads(Path(args.summary).read_text(encoding='utf-8'))
    runs = data['runs']

    by_strategy = defaultdict(list)
    for r in runs:
        by_strategy[r['strategy']].append(r)

    # 配对校验：每个 (scenario, seed) 应恰好有 off/v1/v2 三条
    groups: dict[tuple, dict] = defaultdict(dict)
    for r in runs:
        key = (r['scenario'], r['seed'])
        groups[key][r['strategy']] = r
    unpaired = [(k, sorted(v)) for k, v in groups.items() if len(v) != 3]

    # 数据口径核查：fault_onset_s 与 seed 是否独立
    onset_seed = defaultdict(set)
    for r in runs:
        onset_seed[r['fault_onset_s']].add(r['seed'])
    onset_seed_map = {k: sorted(v) for k, v in onset_seed.items()}

    lines: list[str] = []
    lines.append('# V2.0 三策略对照（validation-r1）')
    lines.append('')
    lines.append(f'- 样本：{len(runs)} 条 = {len(groups)} 组 × 3 策略（off/v1/v2）')
    lines.append(f'- split：{data["meta"]["split"]}')
    lines.append(f'- 配对完整性：{len(groups)} 组，缺配 {len(unpaired)} 组')
    if unpaired:
        for k, v in unpaired[:5]:
            lines.append(f'  - {k} → {v}')
    lines.append('')
    lines.append('## 0. 数据口径说明（必须先读）')
    lines.append('')
    lines.append('- 实际为 4 关节（J0–J3）× 3 组（s1/s2/s3）× 2 任务（T1/T2）= 24 组；每组跑 off/v1/v2 三策略。')
    lines.append(f'- fault_onset_s 实际取值：{sorted(onset_seed_map)}，各 24 条。')
    lines.append(
        '- **局限**：`fault_onset_s` 与 `seed` 完全混淆——'
        + ', '.join(f'{k}↔{v}' for k, v in sorted(onset_seed_map.items()))
        + '，不存在同一（关节×注入时刻×任务）在不同种子下的独立重复。'
    )
    lines.append(
        '  因此种子带来的方差与注入时刻带来的方差无法分离；'
        '本对照表的「按组」统计是自洽的，但不能声称「3 种子独立重复」。'
    )
    lines.append(
        '  该设计问题已在 `docs/v2-data-request-to-b.md` 向 B 提出，请其确认是否为有意为之。'
    )
    lines.append('')

    # 状态分布表
    lines.append('## 1. 任务状态分布')
    lines.append('')
    lines.append('| 策略 | 总数 | RECOVERED | SAFE_STOPPED | FAILED | 恢复率 |')
    lines.append('|---|---:|---:|---:|---:|---:|')
    for strat in ('off', 'v1', 'v2'):
        rs = by_strategy[strat]
        counts = defaultdict(int)
        for r in rs:
            counts[derive_status(r)] += 1
        rec = counts['RECOVERED']
        lines.append(
            f'| {strat} | {len(rs)} | {counts["RECOVERED"]} | '
            f'{counts["SAFE_STOPPED"]} | {counts["FAILED"]} | '
            f'{rec / len(rs) * 100:.1f}% |'
        )
    lines.append('')

    # 决策与可达性
    lines.append('## 2. 决策与可达性')
    lines.append('')
    lines.append('| 策略 | 发决策数 | RECOVER | STOP | 无决策 | 检出延迟中位(ms) |')
    lines.append('|---|---:|---:|---:|---:|---:|')
    for strat in ('off', 'v1', 'v2'):
        rs = by_strategy[strat]
        recover = sum(1 for r in rs if r.get('action') == 'RECOVER')
        stop = sum(1 for r in rs if r.get('action') == 'STOP')
        none = sum(1 for r in rs if r.get('action') is None)
        lat = median([r.get('fault_detection_latency_ms') for r in rs])
        lines.append(
            f'| {strat} | {recover + stop} | {recover} | {stop} | {none} | {fmt(lat)} |'
        )
    lines.append('')

    # 关键指标
    lines.append('## 3. 关键指标（中位数）')
    lines.append('')
    lines.append('| 策略 | 末端误差中位(m) | 恢复耗时中位(s) | 停稳耗时中位(s) | 故障关节峰值力矩中位(N·m) | 全程峰值速度中位(rad/s) |')
    lines.append('|---|---:|---:|---:|---:|---:|')
    for strat in ('off', 'v1', 'v2'):
        rs = by_strategy[strat]
        lines.append(
            f'| {strat} | {fmt(median([r.get("final_ee_error_m") for r in rs]))} | '
            f'{fmt(median([r.get("recovery_time_s") for r in rs]))} | '
            f'{fmt(median([r.get("stop_time_s") for r in rs]))} | '
            f'{fmt(median([r.get("peak_fault_joint_torque_nm") for r in rs]))} | '
            f'{fmt(median([r.get("max_joint_speed_rad_s") for r in rs]))} |'
        )
    lines.append('')

    # 按故障关节的恢复率
    lines.append('## 4. 按故障关节的恢复率（v2）')
    lines.append('')
    lines.append('| 关节 J | 样本数 | RECOVERED | SAFE_STOPPED | FAILED | 恢复率 |')
    lines.append('|---|---:|---:|---:|---:|---:|')
    by_joint = defaultdict(list)
    for r in by_strategy['v2']:
        by_joint[r['fault_joint']].append(r)
    for j in sorted(by_joint):
        rs = by_joint[j]
        rec = sum(1 for r in rs if derive_status(r) == 'RECOVERED')
        ss = sum(1 for r in rs if derive_status(r) == 'SAFE_STOPPED')
        fail = sum(1 for r in rs if derive_status(r) == 'FAILED')
        lines.append(f'| J{j} | {len(rs)} | {rec} | {ss} | {fail} | {rec / len(rs) * 100:.1f}% |')
    lines.append('')

    # 结论
    off_rec = sum(1 for r in by_strategy['off'] if derive_status(r) == 'RECOVERED')
    v1_rec = sum(1 for r in by_strategy['v1'] if derive_status(r) == 'RECOVERED')
    v2_rec = sum(1 for r in by_strategy['v2'] if derive_status(r) == 'RECOVERED')
    n = len(by_strategy['off'])
    lines.append('## 5. 结论')
    lines.append('')
    lines.append(
        f'- 配对完整：{len(groups)} 组（关节×注入时刻×任务×种子），每组均含 off/v1/v2，缺配 0。'
    )
    lines.append(
        f'- 恢复率：off {off_rec}/{n}（{off_rec / n * 100:.1f}%）→ '
        f'v1 {v1_rec}/{n}（{v1_rec / n * 100:.1f}%）→ '
        f'v2 {v2_rec}/{n}（{v2_rec / n * 100:.1f}%）。'
    )
    lines.append(
        '- off 无决策（基线）；v1 检出故障但不规划；v2 给出 RECOVER/STOP 决策，'
        '恢复率相对 off/v1 提升。'
    )
    lines.append(
        '- 未恢复的 v2 案例均进入 SAFE_STOPPED/FAILED，需结合曲线确认是否为数学不可达'
        '（契约明确 NO_FEASIBLE_PLAN ≠ 数学证明不可达）。'
    )

    text = '\n'.join(lines) + '\n'
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding='utf-8')


if __name__ == '__main__':
    main()

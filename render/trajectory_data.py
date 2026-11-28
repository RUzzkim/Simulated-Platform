"""Read the recorded positions without changing any source trajectories."""

from bisect import bisect_right
import csv
from dataclasses import dataclass
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DELIVERY = REPO / "member-a-delivery"
TRAJECTORIES = {
    "normal_cycle": DELIVERY / "runs/point-to-point-normal-95ef64c016994260b7ba18861c59da67/states.csv",
    "lock_event": DELIVERY / "runs/point-to-point-shoulder-lock-25d80a6e39bb485ba11daa0624be0b68/states.csv",
}
HANDLING = DELIVERY / "handling-no-fault.csv"
FPS = 30
FRAME_COUNT = 10 * FPS


@dataclass(frozen=True)
class Sample:
    tick: float
    time: float
    angles: tuple


def read_samples(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = [Sample(int(row["tick"]), float(row["sim_time_s"]),
                       tuple(float(row[f"joint_{n}_position_rad"]) for n in range(1, 7)))
                for row in csv.DictReader(source)]
    if len(rows) < 2 or any(a.time >= b.time for a, b in zip(rows, rows[1:])):
        raise ValueError(f"Need increasing simulation timestamps: {path}")
    return rows


def lock_event():
    with TRAJECTORIES["lock_event"].with_name("events.csv").open(encoding="utf-8-sig", newline="") as source:
        event, = [row for row in csv.DictReader(source)
                  if row["event"] == "joint_locked" and row["joint"] == "joint_2"]
    return float(event["sim_time_s"]), float(event["position_rad"])


def retime(rows, count=FRAME_COUNT):
    times = [row.time for row in rows]
    result = []
    for frame in range(count - 1):
        stamp = times[0] + (times[-1] - times[0]) * frame / (count - 1)
        index = bisect_right(times, stamp)
        a, b = rows[index - 1:index + 1]
        t = (stamp - a.time) / (b.time - a.time)
        result.append(Sample(a.tick + t * (b.tick - a.tick), stamp,
                             tuple(x + t * (y - x) for x, y in zip(a.angles, b.angles, strict=True))))
    return [*result, rows[-1]]

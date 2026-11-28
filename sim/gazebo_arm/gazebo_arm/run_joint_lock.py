"""Run a fixed-step joint-space scenario and record states and events."""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
from uuid import uuid4

import yaml

from .end_effector import JOINT_NAMES, POSE_FIELDS, EndEffector
from .plant import RealtimePlant
from .scenarios import HOME


DT = 0.01
URDF_PATH = Path("urdf/hydraulic_arm.urdf")


def package_path() -> Path:
    source = Path(__file__).resolve().parents[1]
    if (source / URDF_PATH).is_file():
        return source
    from ament_index_python.packages import get_package_share_directory

    return Path(get_package_share_directory("gazebo_arm"))


def scenario_files(package: Path) -> dict[str, Path]:
    return {path.stem: path for path in sorted((package / "scenarios").glob("*.yaml"))}


def time_to_ticks(value, field: str) -> int:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{field} must be a finite nonnegative time in seconds")
    steps = value / DT
    tick = round(steps)
    if not math.isclose(steps, tick, rel_tol=0, abs_tol=1e-8):
        raise ValueError(f"{field} must be a multiple of {DT} seconds")
    return tick


def load_scenario(path: Path, limits: list[tuple[float, float]]):
    """Validate the entire configuration before creating any output files."""
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or set(config) - {"output_dir", "waypoints", "fault"}:
        raise ValueError(f"{path.name}: expected output_dir, waypoints and optional fault")
    prefix = config.get("output_dir")
    if not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", prefix):
        raise ValueError(f"{path.name}: output_dir must be a single directory name")
    waypoints = config.get("waypoints")
    if not isinstance(waypoints, list) or not waypoints:
        raise ValueError(f"{path.name}: expected at least one waypoint")
    sequence = []
    for waypoint in waypoints:
        if not isinstance(waypoint, dict) or set(waypoint) != {"name", "position_rad", "duration_s"}:
            raise ValueError(f"{path.name}: each waypoint requires name, position_rad and duration_s")
        name, target = waypoint["name"], waypoint["position_rad"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{path.name}: waypoint name must be nonempty")
        if not isinstance(target, list) or len(target) != len(limits) or any(
            type(angle) not in (int, float) or not lower <= angle <= upper
            for angle, (lower, upper) in zip(target, limits)
        ):
            raise ValueError(f"{path.name}: waypoint {name} requires six angles within URDF limits")
        duration = time_to_ticks(waypoint["duration_s"], f"{name}.duration_s")
        if duration == 0:
            raise ValueError(f"{path.name}: waypoint {name} needs a positive duration")
        sequence.append((target, duration))
    fault = config.get("fault")
    if fault is None:
        return prefix, sequence, None, None
    if not isinstance(fault, dict) or set(fault) != {"joint", "at_s"} or fault["joint"] not in JOINT_NAMES:
        raise ValueError(f"{path.name}: fault requires joint_1 through joint_6 and at_s")
    lock_tick = time_to_ticks(fault["at_s"], "fault.at_s")
    if lock_tick >= sum(duration for _, duration in sequence):
        raise ValueError(f"{path.name}: fault must occur before the last simulation step ends")
    return prefix, sequence, JOINT_NAMES.index(fault["joint"]), lock_tick


def run(output: Path, lock: bool = False, *, scenario: str | None = None) -> Path:
    package = package_path()
    urdf = package / URDF_PATH
    end_effector = EndEffector(urdf)
    name = scenario or ("lock" if lock else "handling")
    prefix, sequence, lock_index, lock_tick = load_scenario(scenario_files(package)[name], end_effector.limits)
    run_id = f"{prefix}-{uuid4().hex}"
    run_dir = output / run_id
    run_dir.mkdir(parents=True)

    plant = RealtimePlant(HOME, v_max=0.6)
    fields = ["run_id", "tick", "sim_time_s"]
    for name in JOINT_NAMES:
        fields.extend(f"{name}_{field}" for field in ("target_rad", "position_rad", "velocity_rad_s", "effort_Nm"))
    fields.extend(POSE_FIELDS)

    with (run_dir / "states.csv").open("w", newline="", encoding="utf-8") as states_file, (
        run_dir / "events.csv"
    ).open("w", newline="", encoding="utf-8") as events_file:
        states = csv.writer(states_file)
        events = csv.writer(events_file)
        states.writerow(fields)
        events.writerow(["run_id", "event", "tick", "sim_time_s", "joint", "position_rad"])
        tick = 0
        for target, duration in sequence:
            plant.set_target(target)
            for _ in range(duration):
                if tick == lock_tick:
                    plant.lock_joint(lock_index)
                    events.writerow([run_id, "joint_locked", tick, f"{tick * DT:.2f}",
                                     JOINT_NAMES[lock_index], plant.q[lock_index]])
                plant.step(DT)
                tick += 1
                position, velocity, effort = plant.state()
                values = [value for joint in zip(target, position, velocity, effort) for value in joint]
                states.writerow([run_id, tick, f"{tick * DT:.2f}", *values, *end_effector.pose(position)])

    metadata = {
        "run_id": run_id,
        "scenario": prefix,
        "step_s": DT,
        "steps": tick,
        "initial_position_rad": HOME,
        "target_position_rad": sequence[-1][0],
        "reference_max_velocity_rad_s": plant.v_max,
        "lock_joint": JOINT_NAMES[lock_index] if lock_index is not None else None,
        "lock_tick": lock_tick,
        "end_effector_frame": "link_6",
        "pose_reference_frame": "base_link",
        "urdf_sha256": hashlib.sha256(urdf.read_bytes()).hexdigest(),
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    available = scenario_files(package_path())
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--scenario", choices=tuple(available))
    selection.add_argument("--lock", action="store_true", help="Legacy alias for --scenario lock.")
    parser.add_argument("--output", type=Path, help="Output root, default ./scenario-runs.")
    args = parser.parse_args()
    if args.scenario is None and not args.lock and args.output is None:
        print("Available scenarios: " + ", ".join(available))
        return
    try:
        print(run(args.output or Path("scenario-runs"), args.lock, scenario=args.scenario))
    except (ValueError, yaml.YAMLError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()

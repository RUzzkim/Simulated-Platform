"""Regression coverage for the YAML scenarios and the published 800-frame runs."""

import csv
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

import yaml

PACKAGE = Path(__file__).resolve().parents[1]
DELIVERY = PACKAGE.parents[1] / "member-a-delivery"
sys.path.insert(0, str(PACKAGE))

from gazebo_arm.end_effector import EndEffector, JOINT_NAMES, POSE_FIELDS
from gazebo_arm.run_joint_lock import load_scenario, run


VERIFIED_RUNS = {
    "handling": "point-to-point-normal-fa908ea857014556a1cff3f45e4ee94d",
    "lock": "point-to-point-shoulder-lock-38cec0f2888a4cc7ae20b82f33ce1a43",
}
ORIGINAL_RUNS = {
    "handling": "point-to-point-normal-95ef64c016994260b7ba18861c59da67",
    "lock": "point-to-point-shoulder-lock-25d80a6e39bb485ba11daa0624be0b68",
}


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


class ScenarioRunsTest(unittest.TestCase):
    def test_migrated_runs_keep_joint_states_events_and_current_fk(self):
        with tempfile.TemporaryDirectory() as directory:
            for scenario, run_id in VERIFIED_RUNS.items():
                with self.subTest(scenario=scenario):
                    result = run(Path(directory), scenario=scenario)
                    archived = DELIVERY / "runs" / ORIGINAL_RUNS[scenario]
                    verified = DELIVERY / "runs-dh-verified" / run_id
                    fields, states = read_csv(result / "states.csv")
                    self.assertEqual(len(states), 800)
                    self.assertEqual(states[0]["sim_time_s"], "0.01")
                    self.assertEqual(states[-1]["sim_time_s"], "8.00")
                    for reference in (archived, verified):
                        expected_fields, expected_states = read_csv(reference / "states.csv")
                        self.assertEqual(fields, expected_fields)
                        numeric = [field for field in fields if field != "run_id"]
                        if reference == archived:
                            numeric = [field for field in numeric if field not in POSE_FIELDS]
                        for actual, expected in zip(states, expected_states, strict=True):
                            self.assertEqual(actual["run_id"], result.name)
                            self.assertTrue(all(math.isclose(float(actual[field]), float(expected[field]),
                                                            rel_tol=0, abs_tol=1e-12) for field in numeric))
                        event_fields, events = read_csv(result / "events.csv")
                        expected_fields, expected_events = read_csv(reference / "events.csv")
                        self.assertEqual(event_fields, expected_fields)
                        for actual, expected in zip(events, expected_events, strict=True):
                            self.assertEqual(actual["run_id"], result.name)
                            for field in ("event", "tick", "sim_time_s", "joint"):
                                self.assertEqual(actual[field], expected[field])
                            self.assertAlmostEqual(float(actual["position_rad"]), float(expected["position_rad"]), 12)

    def test_elbow_grasp_reaches_depth_and_returns_toward_home(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run(Path(directory), scenario="elbow_grasp")
            _, states = read_csv(result / "states.csv")
            _, events = read_csv(result / "events.csv")
            metadata = json.loads((result / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(len(states), 1050)
        self.assertEqual(states[-1]["sim_time_s"], "10.50")
        self.assertEqual(events, [])
        elbow = [float(row["joint_3_position_rad"]) for row in states]
        self.assertLess(min(elbow[300:550]), -1.55)
        self.assertLess(abs(elbow[-1] + 0.72), 0.025)
        approach_z, grasp_z, retreat_z = (float(states[i]["ee_z_m"]) for i in (299, 549, 799))
        self.assertLess(grasp_z, min(approach_z, retreat_z))
        limits = EndEffector(PACKAGE / "urdf/hydraulic_arm.urdf").limits
        for joint, (lower, upper) in zip(JOINT_NAMES, limits, strict=True):
            self.assertTrue(all(lower <= float(row[f"{joint}_position_rad"]) <= upper for row in states))
        self.assertEqual(metadata["steps"], len(states))

    def test_rejects_invalid_waypoints_and_faults(self):
        limits = EndEffector(PACKAGE / "urdf/hydraulic_arm.urdf").limits
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.yaml"
            for patch, message in (
                ({"position_rad": [4.0] * 6}, "limits"),
                ({"duration_s": .015}, "multiple"),
                ({"fault": {"joint": "joint_7", "at_s": 0}}, "joint_1 through joint_6"),
                ({"fault": {"joint": "joint_2", "at_s": 1}}, "before the last simulation step"),
            ):
                with self.subTest(patch=patch):
                    waypoint = {"name": "home", "duration_s": 1, "position_rad": [0.0] * 6}
                    config = {"output_dir": "invalid", "waypoints": [waypoint]}
                    (config if "fault" in patch else waypoint).update(patch)
                    path.write_text(yaml.safe_dump(config), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, message):
                        load_scenario(path, limits)

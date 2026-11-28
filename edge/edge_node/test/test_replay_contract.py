"""离线回放产物与契约 schema 的一致性（不依赖原始轨迹数据）。"""
from __future__ import annotations

import csv
import gzip
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / 'test' / 'experiments'))

from jsonschema import Draft7Validator

import replay_trace_to_mqtt as replay

CONTRACT = BASE / 'docs' / 'contract'
RUN_ID = 'a1b2c3d4e5f60718293a4b5c6d7e8f90'
COLUMNS = ['t_s', 'event_type', 'event_joint', 'action', 'reason']
ROWS = [
    {'t_s': '0.50', 'event_type': '', 'event_joint': '', 'action': '', 'reason': ''},
    {'t_s': '1.20', 'event_type': 'JOINT_LOCKED', 'event_joint': '0', 'action': '', 'reason': ''},
    {'t_s': '1.45', 'event_type': '', 'event_joint': '', 'action': 'RECOVER', 'reason': 'TARGET_REACHED'},
]


class ReplayContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.trace = Path(cls.tmp.name) / f'{RUN_ID}.csv.gz'
        with gzip.open(cls.trace, 'wt', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(ROWS)
        cls.run_record = {
            'run_id': RUN_ID,
            'strategy': 'v2',
            'scenario': 'VALIDATION-LOCK-J0#s1T1',
            'seed': 300,
            'task_goal_rad': [0.0] * 6,
            'description': 'single joint lock recovery',
            'fault_joint': 0,
            'fault_onset_s': 1.2,
            'fault_detection_latency_ms': 20.0,
            'fault_injected': True,
            'recovered': True,
            'safe_stopped': False,
            'action': 'RECOVER',
            'decision_s': 1.45,
            'final_ee_error_m': 0.031,
            'recovery_time_s': 0.4,
            'stop_time_s': None,
            'peak_fault_joint_torque_nm': 12.5,
            'max_joint_speed_rad_s': 1.2,
            'max_joint_torque_nm': 12.5,
        }
        cls.summary = {'meta': {'source_sha256': {'algo.py': 'a' * 64}}}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @staticmethod
    def _validator(name):
        return Draft7Validator(json.loads((CONTRACT / name).read_text(encoding='utf-8')))

    def test_run_matches_contract(self):
        payload = replay.build_run(
            self.summary, self.run_record, str(self.trace), 1760000000000, 'SIM-001', 'ROBOT-001')
        self.assertEqual(payload['trace']['path'], f'{RUN_ID}.csv.gz')
        self.assertEqual(payload['task']['status'], 'RECOVERED')
        self.assertEqual([], list(self._validator('v2_run.schema.json').iter_errors(payload)))

    def test_events_match_contract(self):
        rows = replay.load_rows(str(self.trace))
        events = replay.build_events(rows, self.run_record, 1760000000000)
        self.assertEqual(['FAULT', 'DECISION'], [event['event_type'] for event in events])
        self.assertEqual(events[1]['action'], 'RECOVER')
        self.assertEqual(events[1]['reachability_status'], 'REACHABLE')
        validator = self._validator('v2_experiment_event.schema.json')
        for event in events:
            with self.subTest(event=event['event_type']):
                self.assertEqual([], list(validator.iter_errors(event)))


if __name__ == '__main__':
    unittest.main()

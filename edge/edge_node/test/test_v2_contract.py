"""V2.0 实验契约（2.0.0）schema 与夹具一致性测试。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator

EDGE_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_DIR = EDGE_ROOT / 'docs' / 'contract'
FIXTURE_DIR = Path(__file__).resolve().parent / 'fixtures' / 'v2_contract'

RUN_SCHEMA = CONTRACT_DIR / 'v2_run.schema.json'
FRAME_SCHEMA = CONTRACT_DIR / 'v2_trace_frame.schema.json'
EVENT_SCHEMA = CONTRACT_DIR / 'v2_experiment_event.schema.json'
VALID_RUN = FIXTURE_DIR / 'valid_run.json'
VALID_RUN_STOP = FIXTURE_DIR / 'valid_run_safe_stopped.json'
VALID_FRAME = FIXTURE_DIR / 'valid_trace_frame.json'
VALID_EVENTS = [FIXTURE_DIR / 'valid_fault_event.json', FIXTURE_DIR / 'valid_decision_event.json']


def _load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


class V2ContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_schema = _load(RUN_SCHEMA)
        cls.frame_schema = _load(FRAME_SCHEMA)
        cls.event_schema = _load(EVENT_SCHEMA)
        for schema in (cls.run_schema, cls.frame_schema, cls.event_schema):
            self_check = Draft7Validator(schema)
            self_check.check_schema(schema)

    def test_valid_fixtures_pass_schema(self):
        for path in (VALID_RUN, VALID_RUN_STOP):
            with self.subTest(fixture=path.name):
                run = _load(path)
                self.assertEqual([], list(Draft7Validator(self.run_schema).iter_errors(run)))
        frame = _load(VALID_FRAME)
        self.assertEqual([], list(Draft7Validator(self.frame_schema).iter_errors(frame)))
        for path in VALID_EVENTS:
            with self.subTest(fixture=path.name):
                event = _load(path)
                self.assertEqual([], list(Draft7Validator(self.event_schema).iter_errors(event)))

    def test_invalid_fixtures_are_rejected(self):
        cases = [
            ('invalid_run_missing_run_id.json', self.run_schema),
            ('invalid_run_bad_task_status.json', self.run_schema),
            ('invalid_run_bad_contract_version.json', self.run_schema),
            ('invalid_frame_seven_joints.json', self.frame_schema),
            ('invalid_frame_bad_joint_name.json', self.frame_schema),
            ('invalid_event_missing_run_id.json', self.event_schema),
            ('invalid_event_bad_type.json', self.event_schema),
        ]
        for name, schema in cases:
            with self.subTest(fixture=name):
                errors = list(Draft7Validator(schema).iter_errors(_load(FIXTURE_DIR / name)))
                self.assertTrue(errors, f'{name} 应被 schema 拒绝')

    def test_frozen_fields_are_required(self):
        run_required = {
            'contract_version', 'run_id', 'algorithm_version', 'started_at_ms',
            'simulation', 'scenario', 'fault', 'reachability', 'strategy',
            'decision', 'task', 'trace',
        }
        frame_required = {
            'contract_version', 'run_id', 'step', 'timestamp_ms', 'sim_time_s',
            'command_time_s', 'joints', 'end_effector', 'ee_error_m',
            'fault_active', 'fault_type', 'fault_joint', 'action', 'reason',
        }
        self.assertLessEqual(run_required, set(self.run_schema['required']))
        self.assertLessEqual(frame_required, set(self.frame_schema['required']))

    def test_fixtures_share_identity_and_time_base(self):
        run = _load(VALID_RUN)
        frame = _load(VALID_FRAME)
        self.assertEqual(run['run_id'], frame['run_id'])
        self.assertEqual(run['trace']['path'].removesuffix('.csv.gz'), run['run_id'])
        self.assertEqual(run['contract_version'], frame['contract_version'])
        expected_ms = run['started_at_ms'] + round(frame['sim_time_s'] * 1000)
        self.assertEqual(frame['timestamp_ms'], expected_ms)

    def test_fault_timing_and_joint_contract(self):
        run = _load(VALID_RUN)
        fault = run['fault']
        self.assertAlmostEqual(
            fault['detected_at_s'],
            fault['injected_at_s'] + fault['detection_latency_ms'] / 1000.0,
            places=9,
        )
        self.assertEqual(fault['confirmed'], fault['detection_latency_ms'] is not None)
        self.assertEqual(fault['joint_name'], f"J{fault['joint_index']}")

        frame = _load(VALID_FRAME)
        names = [joint['name'] for joint in frame['joints']]
        self.assertEqual(names, [f'J{i}' for i in range(6)])
        self.assertEqual(len(frame['end_effector']['position_m']), 3)
        self.assertEqual(len(frame['end_effector']['rpy_rad']), 3)

    def test_status_and_reachability_mapping(self):
        for path in (VALID_RUN, VALID_RUN_STOP):
            with self.subTest(fixture=path.name):
                run = _load(path)
                action = run['decision']['action']
                if action == 'RECOVER':
                    self.assertEqual(run['reachability']['status'], 'REACHABLE')
                    self.assertEqual(run['task']['status'], 'RECOVERED')
                    self.assertIsNotNone(run['task']['recovery_time_s'])
                    self.assertIsNone(run['task']['stop_time_s'])
                elif action == 'STOP':
                    self.assertEqual(run['reachability']['status'], 'NO_FEASIBLE_PLAN')
                    self.assertEqual(run['task']['status'], 'SAFE_STOPPED')
                    self.assertIsNone(run['task']['recovery_time_s'])
                    self.assertIsNotNone(run['task']['stop_time_s'])
                else:
                    self.assertEqual(run['reachability']['status'], 'NOT_ASSESSED')

    def test_validation_fixture_matches_frozen_seed(self):
        for path in (VALID_RUN, VALID_RUN_STOP):
            with self.subTest(fixture=path.name):
                run = _load(path)
                self.assertEqual(run['scenario']['split'], 'validation')
                self.assertIn(run['scenario']['seed'], {300, 301, 302})
                self.assertAlmostEqual(
                    run['simulation']['duration_s'] * run['simulation']['control_hz'],
                    run['trace']['frame_count'],
                )

    def test_schema_accepts_development_scenario_name(self):
        run = _load(VALID_RUN)
        run['scenario']['scenario_id'] = 'LOCK-J1#s1T1'
        run['scenario']['split'] = 'development'
        run['scenario']['seed'] = 100
        self.assertEqual([], list(Draft7Validator(self.run_schema).iter_errors(run)))

    def test_active_fault_frame_has_event_fields(self):
        frame = _load(VALID_FRAME)
        if frame['fault_active']:
            self.assertIsNotNone(frame['fault_type'])
            self.assertIsNotNone(frame['fault_joint'])

    def test_event_fixtures_link_to_run(self):
        run = _load(VALID_RUN)
        for path in VALID_EVENTS:
            with self.subTest(fixture=path.name):
                event = _load(path)
                self.assertEqual(event['run_id'], run['run_id'])
                self.assertEqual(event['contract_version'], run['contract_version'])
        decision = _load(FIXTURE_DIR / 'valid_decision_event.json')
        self.assertEqual(decision['action'], run['decision']['action'])
        self.assertEqual(decision['reachability_status'], run['reachability']['status'])


if __name__ == '__main__':
    unittest.main()

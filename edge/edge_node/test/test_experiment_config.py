"""边端实验运行配置与契约 2.0.0 的一致性。"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from edge_node.config.config_manager import ConfigManager

CONFIG_PATH = Path(__file__).resolve().parents[1] / 'config' / 'edge_config.yaml'
ENV_KEYS = (
    'EDGE_RUN_ID',
    'EDGE_SCENARIO_ID',
    'EDGE_RUN_SPLIT',
    'EDGE_RUN_SEED',
    'EDGE_EXPERIMENT_STRATEGY',
    'EDGE_ALGORITHM_VERSION',
)


class ExperimentConfigTest(unittest.TestCase):
    def setUp(self):
        self.saved = {key: os.environ.pop(key, None) for key in ENV_KEYS}

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_shipped_config_matches_contract_defaults(self):
        cfg = ConfigManager(str(CONFIG_PATH))
        self.assertEqual(cfg.experiment_run_id, '')
        self.assertEqual(cfg.experiment_scenario_id, 'ONLINE-LOCK')
        self.assertEqual(cfg.experiment_split, 'online')
        self.assertEqual(cfg.experiment_seed, 0)
        self.assertIn(cfg.experiment_strategy, {'off', 'v1', 'v2'})
        self.assertRegex(cfg.experiment_algorithm_version, r'^v\d+\.\d+\.\d+$')

    def test_env_overrides_run_context(self):
        os.environ['EDGE_RUN_ID'] = 'f' * 32
        os.environ['EDGE_SCENARIO_ID'] = 'VALIDATION-LOCK-J0#s1T1'
        os.environ['EDGE_RUN_SPLIT'] = 'validation'
        os.environ['EDGE_RUN_SEED'] = '301'
        os.environ['EDGE_EXPERIMENT_STRATEGY'] = 'v1'
        os.environ['EDGE_ALGORITHM_VERSION'] = 'v1.0.0'
        cfg = ConfigManager(str(CONFIG_PATH))
        self.assertEqual(cfg.experiment_run_id, 'f' * 32)
        self.assertEqual(cfg.experiment_scenario_id, 'VALIDATION-LOCK-J0#s1T1')
        self.assertEqual(cfg.experiment_split, 'validation')
        self.assertEqual(cfg.experiment_seed, 301)
        self.assertEqual(cfg.experiment_strategy, 'v1')
        self.assertEqual(cfg.experiment_algorithm_version, 'v1.0.0')

    def test_empty_env_falls_back_to_file(self):
        os.environ['EDGE_RUN_SEED'] = ''
        cfg = ConfigManager(str(CONFIG_PATH))
        self.assertEqual(cfg.experiment_seed, 0)


if __name__ == '__main__':
    unittest.main()

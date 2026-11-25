import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from edge_node.config.config_manager import ConfigManager


def test_task_recovery_is_disabled_by_default_and_can_be_enabled(tmp_path):
    config = tmp_path / "edge.yaml"
    config.write_text("fault_tolerance:\n  enabled: true\n  task_recovery: true\n", encoding="utf-8")

    manager = ConfigManager(str(config))

    assert manager.ft_task_recovery is True


def test_task_recovery_defaults_to_disabled():
    manager = ConfigManager()

    assert manager.ft_task_recovery is False

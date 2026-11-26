import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from edge_node.config.config_manager import ConfigManager


def test_ros2_topic_normalizes_device_id_without_changing_mqtt_topic(monkeypatch, tmp_path):
    config = tmp_path / 'edge.yaml'
    config.write_text('{}', encoding='utf-8')
    monkeypatch.setenv('EDGE_SIMULATION_ID', 'SIM-987')
    manager = ConfigManager(str(config))

    assert manager.render_ros2_topic('/simulation/{simulation_id}/joint_states') == (
        '/simulation/SIM_987/joint_states'
    )
    assert manager.render_topic('simulation/{simulation_id}/command') == (
        'simulation/SIM-987/command'
    )


def test_task_recovery_is_disabled_by_default_and_can_be_enabled(tmp_path):
    config = tmp_path / "edge.yaml"
    config.write_text("fault_tolerance:\n  enabled: true\n  task_recovery: true\n", encoding="utf-8")

    manager = ConfigManager(str(config))

    assert manager.ft_task_recovery is True


def test_task_recovery_defaults_to_disabled():
    manager = ConfigManager()

    assert manager.ft_task_recovery is False


def test_recovery_trajectory_limits_have_safe_defaults():
    manager = ConfigManager()

    assert manager.ft_recovery_max_velocity == 1.0
    assert manager.ft_recovery_max_acceleration == 2.0


def test_recovery_trajectory_limits_are_read_from_yaml(tmp_path):
    config = tmp_path / "edge.yaml"
    config.write_text(
        "fault_tolerance:\n"
        "  recovery_max_velocity: 0.6\n"
        "  recovery_max_acceleration: 1.4\n",
        encoding="utf-8",
    )

    manager = ConfigManager(str(config))

    assert manager.ft_recovery_max_velocity == 0.6
    assert manager.ft_recovery_max_acceleration == 1.4

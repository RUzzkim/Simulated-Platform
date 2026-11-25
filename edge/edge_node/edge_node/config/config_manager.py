"""配置管理模块：加载本地 YAML 配置 + 接收云端 MQTT config topic 下发的运行时配置

环境变量覆盖（Docker 部署友好）：
  加载 YAML 后，若存在对应环境变量则覆盖静态配置。
  映射关系见 _ENV_OVERRIDES。
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import yaml

from edge_node.model.messages import EdgeConfig

# 环境变量 → 配置路径的映射
# 仅覆盖部署时需要按节点差异化的字段，算法参数仍由 YAML 管理
_ENV_OVERRIDES = {
    'EDGE_SIMULATION_ID': ('edge', 'simulation_id'),
    'EDGE_ROBOT_ID': ('edge', 'robot_id'),
    'MQTT_BROKER_URL': ('mqtt', 'broker_url'),
    'MQTT_CLIENT_ID': ('mqtt', 'client_id'),
    'MQTT_USERNAME': ('mqtt', 'username'),
    'MQTT_PASSWORD': ('mqtt', 'password'),
    'MQTT_QOS': ('mqtt', 'qos'),
    'CONTROL_MODE': ('control', 'control_mode'),
    'FAULT_DETECTION_ENABLED': ('fault_detection', 'enabled'),
    'FAULT_TOLERANCE_ENABLED': ('fault_tolerance', 'enabled'),
    'ACTIVE_REPLANNING': ('fault_tolerance', 'active_replanning'),
    'TASK_RECOVERY_ENABLED': ('fault_tolerance', 'task_recovery'),
    'EDGE_HEARTBEAT_INTERVAL': ('runtime', 'heartbeat_interval_sec'),
    'EDGE_STATE_PUBLISH_HZ': ('runtime', 'state_publish_hz'),
    'EDGE_SAFE_COMMAND_ENABLED': ('control', 'safe_command_enabled'),
    'EDGE_SIGNAL_FILTER_ENABLED': ('signal_filter', 'enabled'),
    'EDGE_PUBLISH_FAULTS': ('runtime', 'publish_faults'),
}


class ConfigManager:
    """管理边端静态配置与云端动态配置"""

    def __init__(self, config_path: Optional[str] = None):
        self._static: Dict[str, Any] = {}
        self._runtime = EdgeConfig()
        if config_path:
            self.load_static(config_path)

    # ---- 静态配置（本地 YAML）----
    def load_static(self, config_path: str) -> None:
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        with open(config_path, 'r', encoding='utf-8') as f:
            self._static = yaml.safe_load(f) or {}
        self._apply_env_overrides()

    def _apply_env_overrides(self) -> None:
        """用环境变量覆盖静态配置（Docker 部署时按节点差异化配置）"""
        for env_var, path in _ENV_OVERRIDES.items():
            value = os.environ.get(env_var)
            if value is None or value == '':
                continue
            node = self._static
            for k in path[:-1]:
                if k not in node or not isinstance(node[k], dict):
                    node[k] = {}
                node = node[k]
            # 自动推断类型：bool / int / float / str
            if isinstance(node.get(path[-1]), bool) or value.lower() in ('true', 'false'):
                node[path[-1]] = value.lower() == 'true'
            else:
                try:
                    node[path[-1]] = int(value)
                except ValueError:
                    try:
                        node[path[-1]] = float(value)
                    except ValueError:
                        node[path[-1]] = value

    @property
    def static(self) -> Dict[str, Any]:
        return self._static

    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self._static
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    @property
    def simulation_id(self) -> str:
        return self.get('edge', 'simulation_id', default='SIM-001')

    @property
    def robot_id(self) -> str:
        return self.get('edge', 'robot_id', default='ROBOT-001')

    @property
    def joint_count(self) -> int:
        return self.get('ros2', 'joint_count', default=6)

    @property
    def state_publish_hz(self) -> float:
        return float(self.get('runtime', 'state_publish_hz', default=10.0))

    @property
    def heartbeat_interval_sec(self) -> float:
        return float(self.get('runtime', 'heartbeat_interval_sec', default=5.0))

    @property
    def default_status(self) -> str:
        return self.get('runtime', 'default_status', default='RUNNING')

    @property
    def max_torque(self) -> float:
        return float(self.get('runtime', 'max_torque', default=50.0))

    @property
    def publish_faults(self) -> bool:
        """上云 RobotState 是否携带可选 faults 故障明细数组（v1.1 加法扩展）"""
        return bool(self.get('runtime', 'publish_faults', default=True))

    # ---- 信号滤波/离群点剔除参数 ----
    @property
    def signal_filter_enabled(self) -> bool:
        return bool(self.get('signal_filter', 'enabled', default=True))

    @property
    def sf_window_size(self) -> int:
        return int(self.get('signal_filter', 'window_size', default=3))

    @property
    def sf_outlier_k(self) -> float:
        return float(self.get('signal_filter', 'outlier_k', default=3.5))

    @property
    def sf_alpha_position(self) -> float:
        return float(self.get('signal_filter', 'alpha_position', default=0.8))

    @property
    def sf_alpha_velocity(self) -> float:
        return float(self.get('signal_filter', 'alpha_velocity', default=0.5))

    @property
    def sf_alpha_effort(self) -> float:
        return float(self.get('signal_filter', 'alpha_effort', default=0.5))

    @property
    def sf_min_sigma_position(self) -> float:
        return float(self.get('signal_filter', 'min_sigma_position', default=0.002))

    @property
    def sf_min_sigma_velocity(self) -> float:
        return float(self.get('signal_filter', 'min_sigma_velocity', default=0.01))

    @property
    def sf_min_sigma_effort(self) -> float:
        return float(self.get('signal_filter', 'min_sigma_effort', default=0.1))

    # ---- 控制算法参数 ----
    @property
    def control_mode(self) -> str:
        return self.get('control', 'control_mode', default='pass_through')

    @property
    def control_rate_hz(self) -> float:
        return float(self.get('control', 'control_rate_hz', default=100.0))

    @property
    def control_dt(self) -> float:
        return 1.0 / max(self.control_rate_hz, 0.1)

    @property
    def safe_command_enabled(self) -> bool:
        """无 ROS 2 模式下是否将容错补偿目标经 MQTT 下发仿真端（执行器闭环）"""
        return bool(self.get('control', 'safe_command_enabled', default=True))

    @property
    def lambda_gain(self) -> float:
        return float(self.get('control', 'lambda_gain', default=10.0))

    @property
    def kd(self) -> float:
        return float(self.get('control', 'kd', default=50.0))

    @property
    def learning_rate(self) -> float:
        return float(self.get('control', 'learning_rate', default=0.1))

    @property
    def leakage(self) -> float:
        return float(self.get('control', 'leakage', default=0.001))

    @property
    def n_centers(self) -> int:
        return int(self.get('control', 'n_centers', default=64))

    @property
    def nominal_inertia(self) -> float:
        return float(self.get('control', 'nominal_inertia', default=1.0))

    @property
    def position_range(self) -> float:
        return float(self.get('control', 'position_range', default=3.14))

    @property
    def velocity_range(self) -> float:
        return float(self.get('control', 'velocity_range', default=2.0))

    # ---- 故障检测参数 ----
    @property
    def fault_detection_enabled(self) -> bool:
        return bool(self.get('fault_detection', 'enabled', default=True))

    @property
    def fault_window_size(self) -> int:
        return int(self.get('fault_detection', 'window_size', default=20))

    @property
    def fault_persistence(self) -> int:
        return int(self.get('fault_detection', 'persistence', default=5))

    @property
    def fault_max_velocity(self) -> float:
        return float(self.get('fault_detection', 'max_velocity', default=3.0))

    @property
    def fault_position_limit(self) -> float:
        return float(self.get('fault_detection', 'position_limit', default=6.28))

    @property
    def fault_torque_overload_threshold(self) -> float:
        return float(self.get('fault_detection', 'torque_overload_threshold', default=40.0))

    @property
    def fault_lock_position_threshold(self) -> float:
        return float(self.get('fault_detection', 'lock_position_threshold', default=0.001))

    @property
    def fault_lock_torque_threshold(self) -> float:
        return float(self.get('fault_detection', 'lock_torque_threshold', default=10.0))

    @property
    def fault_comm_timeout_ms(self) -> int:
        return int(self.get('fault_detection', 'comm_timeout_ms', default=500))

    # ---- 故障容错控制参数 ----
    @property
    def fault_tolerance_enabled(self) -> bool:
        return bool(self.get('fault_tolerance', 'enabled', default=True))

    @property
    def ft_torque_overload_scale(self) -> float:
        return float(self.get('fault_tolerance', 'torque_overload_scale', default=0.3))

    @property
    def ft_velocity_clamp(self) -> float:
        return float(self.get('fault_tolerance', 'velocity_clamp', default=0.05))

    @property
    def ft_recovery_frames(self) -> int:
        return int(self.get('fault_tolerance', 'recovery_frames', default=10))

    @property
    def ft_active_replanning(self) -> bool:
        return bool(self.get('fault_tolerance', 'active_replanning', default=True))

    @property
    def ft_task_recovery(self) -> bool:
        return bool(self.get('fault_tolerance', 'task_recovery', default=False))

    @property
    def ft_replanning_damping(self) -> float:
        return float(self.get('fault_tolerance', 'replanning_damping', default=0.05))

    @property
    def ft_replanning_step(self) -> float:
        return float(self.get('fault_tolerance', 'replanning_step', default=0.5))

    def render_topic(self, pattern: str) -> str:
        return pattern.replace('{simulation_id}', self.simulation_id)

    # ---- 动态配置（云端 config topic 下发）----
    def update_runtime(self, config: EdgeConfig) -> None:
        self._runtime = config

    @property
    def runtime(self) -> EdgeConfig:
        return self._runtime

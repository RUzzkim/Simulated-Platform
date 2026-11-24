"""
数据模型模块
严格对齐云端契约：docs/contract/openapi.yaml / schemas.json / AI_RULES.md
字段名、类型、长度、单位、枚举禁止修改。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

# ---- 契约常量（与云端一致，禁止修改）----
SIM_ID_PATTERN = re.compile(r'^SIM-\d{3}$')
ROBOT_ID_PATTERN = re.compile(r'^ROBOT-\d{3}$')
JOINT_COUNT = 6

ROBOT_STATUS_RUNNING = 'RUNNING'
ROBOT_STATUS_STOPPED = 'STOPPED'
ROBOT_STATUS_ERROR = 'ERROR'
ROBOT_STATUS_SET = {ROBOT_STATUS_RUNNING, ROBOT_STATUS_STOPPED, ROBOT_STATUS_ERROR}

HEARTBEAT_ONLINE = 'ONLINE'
HEARTBEAT_OFFLINE = 'OFFLINE'
HEARTBEAT_STATUS_SET = {HEARTBEAT_ONLINE, HEARTBEAT_OFFLINE}

CMD_START = 'START'
CMD_STOP = 'STOP'
CMD_MOVE_HOME = 'MOVE_HOME'
CMD_MOVE_JOINT = 'MOVE_JOINT'
CMD_TYPE_SET = {CMD_START, CMD_STOP, CMD_MOVE_HOME, CMD_MOVE_JOINT}

# ---- 故障检测常量 ----
FAULT_TORQUE_OVERLOAD = 'TORQUE_OVERLOAD'      # 持续力矩过载
FAULT_JOINT_LOCKED = 'JOINT_LOCKED'            # 关节卡死
FAULT_VELOCITY_ANOMALY = 'VELOCITY_ANOMALY'    # 速度异常（超速）
FAULT_SENSOR_INVALID = 'SENSOR_INVALID'        # 传感器数据无效
FAULT_COMM_TIMEOUT = 'COMMUNICATION_TIMEOUT'   # 通信超时
FAULT_TYPE_SET = {
    FAULT_TORQUE_OVERLOAD,
    FAULT_JOINT_LOCKED,
    FAULT_VELOCITY_ANOMALY,
    FAULT_SENSOR_INVALID,
    FAULT_COMM_TIMEOUT,
}

FAULT_SEVERITY_WARNING = 'WARNING'
FAULT_SEVERITY_ERROR = 'ERROR'
FAULT_SEVERITY_CRITICAL = 'CRITICAL'
FAULT_SEVERITY_SET = {FAULT_SEVERITY_WARNING, FAULT_SEVERITY_ERROR, FAULT_SEVERITY_CRITICAL}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _check_sim_id(simulation_id: str) -> None:
    if not simulation_id or not SIM_ID_PATTERN.match(simulation_id):
        raise ValueError(f"simulationId 格式错误，必须为 SIM-001 格式，实际: {simulation_id}")


def _check_robot_id(robot_id: str) -> None:
    if not robot_id or not ROBOT_ID_PATTERN.match(robot_id):
        raise ValueError(f"robotId 格式错误，必须为 ROBOT-001 格式，实际: {robot_id}")


def _check_joint_array(values: List[float], name: str) -> None:
    if values is None or len(values) != JOINT_COUNT:
        raise ValueError(f"{name} 长度必须为 {JOINT_COUNT}，实际长度: {None if values is None else len(values)}")
    for i, v in enumerate(values):
        if not isinstance(v, (int, float)):
            raise ValueError(f"{name}[{i}] 必须为数值类型，实际: {type(v).__name__}")


@dataclass
class RobotState:
    """机械臂状态 — 边端通过 MQTT state topic 上传到云端"""
    simulation_id: str
    robot_id: str
    timestamp: int
    joint_position: List[float]
    joint_velocity: List[float]
    joint_torque: List[float]
    status: str
    # 可选扩展（v1.1）：当前帧检测到的故障明细；无故障为空数组。
    # 加法字段，不改变既有字段/枚举；旧版云端忽略该字段，新版云端可直接消费。
    faults: Optional[List['FaultEvent']] = None

    def __post_init__(self) -> None:
        _check_sim_id(self.simulation_id)
        _check_robot_id(self.robot_id)
        if self.timestamp is None:
            self.timestamp = _now_ms()
        elif not (1000000000000 <= self.timestamp <= 9999999999999):
            raise ValueError(f"timestamp 必须为毫秒级 Unix 时间戳，实际: {self.timestamp}")
        _check_joint_array(self.joint_position, 'jointPosition')
        _check_joint_array(self.joint_velocity, 'jointVelocity')
        _check_joint_array(self.joint_torque, 'jointTorque')
        if self.status not in ROBOT_STATUS_SET:
            raise ValueError(f"status 必须为 RUNNING/STOPPED/ERROR，实际: {self.status}")
        if self.faults is None:
            self.faults = []
        else:
            for i, f in enumerate(self.faults):
                if not isinstance(f, FaultEvent):
                    raise ValueError(f"faults[{i}] 必须为 FaultEvent，实际: {type(f).__name__}")

    def to_dict(self) -> Dict[str, Any]:
        """序列化为云端约定的 JSON 字段名（camelCase）"""
        return {
            'simulationId': self.simulation_id,
            'robotId': self.robot_id,
            'timestamp': self.timestamp,
            'jointPosition': [float(x) for x in self.joint_position],
            'jointVelocity': [float(x) for x in self.joint_velocity],
            'jointTorque': [float(x) for x in self.joint_torque],
            'status': self.status,
            'faults': [f.to_dict() for f in self.faults],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'RobotState':
        return cls(
            simulation_id=d['simulationId'],
            robot_id=d['robotId'],
            timestamp=d['timestamp'],
            joint_position=list(d['jointPosition']),
            joint_velocity=list(d['jointVelocity']),
            joint_torque=list(d['jointTorque']),
            status=d['status'],
            faults=[FaultEvent.from_dict(x) for x in (d.get('faults') or [])],
        )


@dataclass
class Heartbeat:
    """边端心跳 — 边端通过 MQTT heartbeat topic 上传到云端"""
    simulation_id: str
    robot_id: str
    timestamp: int
    status: str

    def __post_init__(self) -> None:
        _check_sim_id(self.simulation_id)
        _check_robot_id(self.robot_id)
        if self.timestamp is None:
            self.timestamp = _now_ms()
        elif not (1000000000000 <= self.timestamp <= 9999999999999):
            raise ValueError(f"timestamp 必须为毫秒级 Unix 时间戳，实际: {self.timestamp}")
        if self.status not in HEARTBEAT_STATUS_SET:
            raise ValueError(f"status 必须为 ONLINE/OFFLINE，实际: {self.status}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            'simulationId': self.simulation_id,
            'robotId': self.robot_id,
            'timestamp': self.timestamp,
            'status': self.status,
        }


@dataclass
class RobotCommand:
    """云端下发的控制指令 — 通过 MQTT command topic 接收"""
    command_id: str
    simulation_id: str
    robot_id: str
    cmd_type: str
    timestamp: int
    joint_target: Optional[List[float]] = None
    speed: Optional[float] = None

    def __post_init__(self) -> None:
        _check_sim_id(self.simulation_id)
        _check_robot_id(self.robot_id)
        if self.cmd_type not in CMD_TYPE_SET:
            raise ValueError(f"cmdType 必须为 START/STOP/MOVE_HOME/MOVE_JOINT，实际: {self.cmd_type}")
        if self.timestamp is None:
            self.timestamp = _now_ms()
        if self.cmd_type == CMD_MOVE_JOINT:
            if self.joint_target is None or len(self.joint_target) != JOINT_COUNT:
                raise ValueError(f"MOVE_JOINT 指令必须提供长度为 {JOINT_COUNT} 的 jointTarget")
            _check_joint_array(self.joint_target, 'jointTarget')
        if self.speed is not None and not (0.0 <= self.speed <= 5.0):
            raise ValueError(f"speed 必须在 [0, 5] 范围内，实际: {self.speed}")

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'RobotCommand':
        return cls(
            command_id=d.get('commandId', ''),
            simulation_id=d.get('simulationId', ''),
            robot_id=d.get('robotId', ''),
            cmd_type=d.get('cmdType', ''),
            timestamp=d.get('timestamp'),
            joint_target=list(d['jointTarget']) if d.get('jointTarget') is not None else None,
            speed=d.get('speed'),
        )


@dataclass
class EdgeConfig:
    """云端通过 config topic 下发的边端配置（phase1 预留，字段待云端定义）"""
    control_mode: Optional[str] = None
    control_rate: Optional[float] = None
    algorithm_params: Dict[str, Any] = field(default_factory=dict)
    sim_params: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'EdgeConfig':
        return cls(
            control_mode=d.get('controlMode'),
            control_rate=d.get('controlRate'),
            algorithm_params=d.get('algorithmParams') or {},
            sim_params=d.get('simParams') or {},
            raw=dict(d),
        )


@dataclass
class FaultEvent:
    """故障事件 — 故障检测器输出

    :param fault_type: 故障类型（TORQUE_OVERLOAD / JOINT_LOCKED / ...）
    :param joint_index: 故障关节索引（0-based），通信超时类故障为 -1
    :param severity: 严重度（WARNING / ERROR / CRITICAL）
    :param timestamp: 毫秒级时间戳
    :param detail: 详细描述
    """
    fault_type: str
    joint_index: int
    severity: str
    timestamp: int
    detail: str = ''

    def __post_init__(self) -> None:
        if self.fault_type not in FAULT_TYPE_SET:
            raise ValueError(f"fault_type 非法: {self.fault_type}")
        if self.severity not in FAULT_SEVERITY_SET:
            raise ValueError(f"severity 非法: {self.severity}")
        if self.timestamp is None:
            self.timestamp = _now_ms()

    @property
    def is_critical(self) -> bool:
        return self.severity == FAULT_SEVERITY_CRITICAL

    def to_dict(self) -> Dict[str, Any]:
        return {
            'faultType': self.fault_type,
            'jointIndex': self.joint_index,
            'severity': self.severity,
            'timestamp': self.timestamp,
            'detail': self.detail,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'FaultEvent':
        return cls(
            fault_type=d['faultType'],
            joint_index=int(d['jointIndex']),
            severity=d['severity'],
            timestamp=d.get('timestamp'),
            detail=d.get('detail', ''),
        )

"""数据处理模块：将 ROS 2 JointState 转换为统一 RobotState，并做契约校验与状态推断

phase1 状态推断规则（对齐清单 2.4 推荐方案）：
  - 任一关节力矩 > max_torque → ERROR（最高优先级）
  - 收到 STOP 指令 → STOPPED
  - 收到 START / MOVE_JOINT / MOVE_HOME 指令 → RUNNING
  - 无指令时使用 default_status（默认 RUNNING）
"""
from __future__ import annotations

from typing import Optional

from edge_node.model.messages import RobotState


class StateProcessor:
    """把仿真端上报的关节状态转换为云端契约要求的 RobotState"""

    def __init__(
        self,
        simulation_id: str,
        robot_id: str,
        default_status: str = 'RUNNING',
        max_torque: float = 50.0,
    ):
        self._simulation_id = simulation_id
        self._robot_id = robot_id
        self._default_status = default_status
        self._max_torque = float(max_torque)
        # 由最近一条云端指令决定的运行状态（STOP→STOPPED，其余→RUNNING）
        self._command_status: Optional[str] = None

    def set_command_status(self, cmd_type: str) -> None:
        """根据云端指令更新运行状态推断"""
        if cmd_type == 'STOP':
            self._command_status = 'STOPPED'
        else:  # START / MOVE_JOINT / MOVE_HOME
            self._command_status = 'RUNNING'

    def _infer_status(self, effort) -> str:
        # 优先级 1：力矩超限 → ERROR
        for t in effort:
            if abs(float(t)) > self._max_torque:
                return 'ERROR'
        # 优先级 2：指令驱动的状态
        if self._command_status is not None:
            return self._command_status
        # 优先级 3：默认状态
        return self._default_status

    def from_joint_state(
        self,
        position,
        velocity,
        effort,
        stamp_nanosec: Optional[int] = None,
        status: Optional[str] = None,
    ) -> RobotState:
        """
        将 ROS 2 sensor_msgs/JointState 的字段转换为 RobotState。
        :param position: 关节位置数组 (rad)
        :param velocity: 关节速度数组 (rad/s)
        :param effort: 关节力矩数组 (N·m)
        :param stamp_nanosec: header.stamp 纳秒时间戳，None 则取当前毫秒
        :param status: 显式指定状态，None 则按规则推断
        """
        ts_ms = self._to_ms(stamp_nanosec)
        inferred = status if status is not None else self._infer_status(effort)
        return RobotState(
            simulation_id=self._simulation_id,
            robot_id=self._robot_id,
            timestamp=ts_ms,
            joint_position=list(position),
            joint_velocity=list(velocity),
            joint_torque=list(effort),
            status=inferred,
        )

    @staticmethod
    def _to_ms(stamp_nanosec: Optional[int]) -> int:
        if stamp_nanosec is None:
            import time
            return int(time.time() * 1000)
        # ROS 2 Time: seconds * 1e9 + nanoseconds
        return int(stamp_nanosec / 1_000_000)

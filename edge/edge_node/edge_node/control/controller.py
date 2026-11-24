"""控制算法模块（phase1 仅预留接口，不实现复杂算法）

后续替换控制算法（PID / 自适应神经网络 / 事件触发容错）时，
只需替换本模块实现，不影响 ROS 2 / MQTT 通信层。
"""
from __future__ import annotations

from typing import Optional, List

from edge_node.model.messages import RobotState, RobotCommand


class BaseController:
    """控制器基类：定义 step 接口"""

    def step(self, state: RobotState) -> Optional[RobotCommand]:
        """
        根据当前状态计算控制指令。
        phase1 默认返回 None（不主动产生指令，仅转发云端指令）。
        """
        return None


class PassThroughController(BaseController):
    """phase1 默认控制器：透传，不修改状态、不主动下发指令"""

    def step(self, state: RobotState) -> Optional[RobotCommand]:
        return None

    def command_to_target(self, command: RobotCommand) -> Optional[List[float]]:
        """把云端指令转换为目标关节位置（发布到 ROS 2 joint_command）"""
        if command.cmd_type == 'MOVE_JOINT' and command.joint_target is not None:
            return list(command.joint_target)
        if command.cmd_type == 'MOVE_HOME':
            return [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        # START / STOP 不直接对应目标位置，返回 None 由调用方处理
        return None

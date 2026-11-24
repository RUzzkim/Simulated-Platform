"""数据模型校验测试：验证与云端契约一致"""
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from edge_node.model.messages import (
    RobotState, Heartbeat, RobotCommand, EdgeConfig, FaultEvent,
    FAULT_TORQUE_OVERLOAD, FAULT_SEVERITY_ERROR,
    ROBOT_STATUS_SET, HEARTBEAT_STATUS_SET, CMD_TYPE_SET,
)


def _valid_state_dict():
    return {
        'simulationId': 'SIM-001',
        'robotId': 'ROBOT-001',
        'timestamp': 1760000000123,
        'jointPosition': [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        'jointVelocity': [0.01, 0.02, 0.03, 0.04, 0.05, 0.06],
        'jointTorque': [1, 2, 3, 4, 5, 6],
        'status': 'RUNNING',
    }


def test_robot_state_valid():
    s = RobotState.from_dict(_valid_state_dict())
    assert s.simulation_id == 'SIM-001'
    assert s.robot_id == 'ROBOT-001'
    assert s.timestamp == 1760000000123
    assert len(s.joint_position) == 6
    d = s.to_dict()
    # 字段名必须是 camelCase，与云端一致（v1.1 起恒含可选 faults）
    assert set(d.keys()) == {'simulationId', 'robotId', 'timestamp',
                             'jointPosition', 'jointVelocity', 'jointTorque',
                             'status', 'faults'}
    assert d['jointPosition'] == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    assert d['faults'] == []


def test_robot_state_timestamp_default():
    d = _valid_state_dict()
    d['timestamp'] = None
    s = RobotState.from_dict(d)
    assert s.timestamp is not None and s.timestamp > 0


def test_robot_state_invalid_sim_id():
    d = _valid_state_dict()
    d['simulationId'] = 'BAD'
    try:
        RobotState.from_dict(d)
        assert False, "应抛出 ValueError"
    except ValueError as e:
        assert 'simulationId' in str(e)


def test_robot_state_invalid_joint_length():
    d = _valid_state_dict()
    d['jointPosition'] = [0.1, 0.2, 0.3]
    try:
        RobotState.from_dict(d)
        assert False, "应抛出 ValueError"
    except ValueError as e:
        assert 'jointPosition' in str(e)


def test_robot_state_invalid_status():
    d = _valid_state_dict()
    d['status'] = 'UNKNOWN'
    try:
        RobotState.from_dict(d)
        assert False
    except ValueError as e:
        assert 'RUNNING/STOPPED/ERROR' in str(e)


def test_robot_state_faults_roundtrip():
    """v1.1：faults 故障明细随 state 序列化/反序列化"""
    d = _valid_state_dict()
    d['status'] = 'ERROR'
    d['faults'] = [{
        'faultType': 'TORQUE_OVERLOAD',
        'jointIndex': 0,
        'severity': 'ERROR',
        'timestamp': 1760000000123,
        'detail': 'joint 0 sustained avg torque 42.0 > 40.0',
    }]
    s = RobotState.from_dict(d)
    assert len(s.faults) == 1
    f = s.faults[0]
    assert isinstance(f, FaultEvent)
    assert f.fault_type == FAULT_TORQUE_OVERLOAD
    assert f.joint_index == 0
    assert f.severity == FAULT_SEVERITY_ERROR
    out = s.to_dict()
    assert out['faults'][0]['faultType'] == 'TORQUE_OVERLOAD'
    assert out['faults'][0]['jointIndex'] == 0
    # 再次往返保持一致
    assert RobotState.from_dict(out).to_dict() == out


def test_robot_state_faults_default_empty():
    """旧版载荷（无 faults 字段）必须兼容为空数组"""
    s = RobotState.from_dict(_valid_state_dict())
    assert s.faults == []
    s2 = RobotState(
        simulation_id='SIM-001', robot_id='ROBOT-001', timestamp=1760000000123,
        joint_position=[0.0] * 6, joint_velocity=[0.0] * 6,
        joint_torque=[0.0] * 6, status='RUNNING',
    )
    assert s2.faults == []


def test_robot_state_faults_invalid_element():
    try:
        RobotState(
            simulation_id='SIM-001', robot_id='ROBOT-001', timestamp=1760000000123,
            joint_position=[0.0] * 6, joint_velocity=[0.0] * 6,
            joint_torque=[0.0] * 6, status='RUNNING',
            faults=[{'faultType': 'TORQUE_OVERLOAD'}],  # 必须是 FaultEvent 实例
        )
        assert False
    except ValueError as e:
        assert 'faults[0]' in str(e)


def test_heartbeat_valid():
    hb = Heartbeat(simulation_id='SIM-001', robot_id='ROBOT-001',
                   timestamp=1760000000123, status='ONLINE')
    d = hb.to_dict()
    assert d['status'] == 'ONLINE'
    assert set(d.keys()) == {'simulationId', 'robotId', 'timestamp', 'status'}


def test_heartbeat_invalid_status():
    try:
        Heartbeat(simulation_id='SIM-001', robot_id='ROBOT-001',
                  timestamp=1760000000123, status='BAD')
        assert False
    except ValueError as e:
        assert 'ONLINE/OFFLINE' in str(e)


def test_command_move_joint_valid():
    cmd = RobotCommand.from_dict({
        'commandId': 'CMD-001',
        'simulationId': 'SIM-001',
        'robotId': 'ROBOT-001',
        'cmdType': 'MOVE_JOINT',
        'timestamp': 1760000000123,
        'jointTarget': [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        'speed': 1.0,
    })
    assert cmd.cmd_type == 'MOVE_JOINT'
    assert len(cmd.joint_target) == 6


def test_command_move_joint_missing_target():
    try:
        RobotCommand.from_dict({
            'commandId': 'CMD-001',
            'simulationId': 'SIM-001',
            'robotId': 'ROBOT-001',
            'cmdType': 'MOVE_JOINT',
            'timestamp': 1760000000123,
        })
        assert False
    except ValueError as e:
        assert 'jointTarget' in str(e)


def test_command_speed_out_of_range():
    try:
        RobotCommand.from_dict({
            'commandId': 'CMD-001',
            'simulationId': 'SIM-001',
            'robotId': 'ROBOT-001',
            'cmdType': 'START',
            'timestamp': 1760000000123,
            'speed': 99.0,
        })
        assert False
    except ValueError as e:
        assert 'speed' in str(e)


def test_enum_sets_match_contract():
    # 与云端 openapi.yaml 枚举对齐
    assert ROBOT_STATUS_SET == {'RUNNING', 'STOPPED', 'ERROR'}
    assert HEARTBEAT_STATUS_SET == {'ONLINE', 'OFFLINE'}
    assert CMD_TYPE_SET == {'START', 'STOP', 'MOVE_HOME', 'MOVE_JOINT'}


def test_config_from_dict():
    cfg = EdgeConfig.from_dict({
        'controlMode': 'POSITION',
        'controlRate': 100.0,
        'algorithmParams': {'k': 1},
        'simParams': {'gravity': 9.8},
    })
    assert cfg.control_mode == 'POSITION'
    assert cfg.control_rate == 100.0
    assert cfg.algorithm_params == {'k': 1}


if __name__ == '__main__':
    import traceback
    tests = [v for k, v in globals().items() if k.startswith('test_') and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} tests passed")
    sys.exit(0 if passed == len(tests) else 1)

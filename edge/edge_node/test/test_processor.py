"""数据处理模块测试（含状态推断：力矩超限→ERROR、STOP→STOPPED、START→RUNNING）"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from edge_node.processor.state_processor import StateProcessor


def test_default_status():
    p = StateProcessor('SIM-001', 'ROBOT-001', default_status='RUNNING', max_torque=50.0)
    state = p.from_joint_state(
        position=[0.0] * 6, velocity=[0.0] * 6, effort=[10.0] * 6,
    )
    assert state.status == 'RUNNING'


def test_stop_command_sets_stopped():
    p = StateProcessor('SIM-001', 'ROBOT-001', max_torque=50.0)
    p.set_command_status('STOP')
    state = p.from_joint_state(
        position=[0.0] * 6, velocity=[0.0] * 6, effort=[10.0] * 6,
    )
    assert state.status == 'STOPPED'


def test_start_command_sets_running_after_stop():
    p = StateProcessor('SIM-001', 'ROBOT-001', max_torque=50.0)
    p.set_command_status('STOP')
    assert p.from_joint_state([0]*6, [0]*6, [10]*6).status == 'STOPPED'
    p.set_command_status('START')
    assert p.from_joint_state([0]*6, [0]*6, [10]*6).status == 'RUNNING'


def test_move_joint_sets_running():
    p = StateProcessor('SIM-001', 'ROBOT-001', max_torque=50.0)
    p.set_command_status('STOP')
    p.set_command_status('MOVE_JOINT')
    assert p.from_joint_state([0]*6, [0]*6, [10]*6).status == 'RUNNING'


def test_torque_exceed_sets_error_overrides_stopped():
    """力矩超限优先级最高，即使已 STOP 也应为 ERROR"""
    p = StateProcessor('SIM-001', 'ROBOT-001', max_torque=50.0)
    p.set_command_status('STOP')
    state = p.from_joint_state(
        position=[0.0] * 6, velocity=[0.0] * 6, effort=[60.0, 10, 10, 10, 10, 10],
    )
    assert state.status == 'ERROR'


def test_torque_exceed_sets_error_overrides_running():
    p = StateProcessor('SIM-001', 'ROBOT-001', max_torque=50.0)
    p.set_command_status('START')
    state = p.from_joint_state(
        position=[0.0] * 6, velocity=[0.0] * 6, effort=[-55.0, 10, 10, 10, 10, 10],
    )
    assert state.status == 'ERROR'


def test_torque_within_limit_keeps_command_status():
    p = StateProcessor('SIM-001', 'ROBOT-001', max_torque=50.0)
    p.set_command_status('STOP')
    state = p.from_joint_state(
        position=[0.0] * 6, velocity=[0.0] * 6, effort=[50.0, 50, 50, 50, 50, 50],
    )
    # 等于上限不算超限
    assert state.status == 'STOPPED'


def test_explicit_status_overrides_inference():
    p = StateProcessor('SIM-001', 'ROBOT-001', max_torque=50.0)
    p.set_command_status('STOP')
    state = p.from_joint_state(
        position=[0.0] * 6, velocity=[0.0] * 6, effort=[10.0] * 6,
        status='RUNNING',
    )
    assert state.status == 'RUNNING'


def test_from_joint_state_basic_fields():
    p = StateProcessor('SIM-001', 'ROBOT-001', max_torque=50.0)
    state = p.from_joint_state(
        position=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        velocity=[0.01, 0.02, 0.03, 0.04, 0.05, 0.06],
        effort=[1, 2, 3, 4, 5, 6],
        stamp_nanosec=1760000000123 * 1_000_000,
    )
    assert state.simulation_id == 'SIM-001'
    assert state.robot_id == 'ROBOT-001'
    assert state.timestamp == 1760000000123
    assert state.joint_position == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]


def test_invalid_joint_length_raises():
    p = StateProcessor('SIM-001', 'ROBOT-001')
    try:
        p.from_joint_state(position=[0.1], velocity=[0.0] * 6, effort=[0.0] * 6)
        assert False
    except ValueError:
        pass


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

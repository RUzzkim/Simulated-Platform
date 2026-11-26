"""边端主节点：串联 ROS 2 <-> 数据处理 <-> MQTT 全链路

数据流：
  仿真端 --joint_states/sim_state--> StateSubscriber/MQTT --> RobotSignalFilter（离群剔除+中值+EMA）
       --> StateProcessor（状态推断） --> 故障检测/容错 --> (latest_state)
  定时器(state_publish_hz) --> MqttClient.publish_state
  定时器(heartbeat)        --> MqttClient.publish_heartbeat
  云端 --command(MQTT)--> MqttClient --> Controller --> CommandPublisher --joint_command--> 仿真端
  云端 --config(MQTT)-->  MqttClient --> ConfigManager.update_runtime
"""
from __future__ import annotations

import argparse
import threading
import time
from typing import Optional

from edge_node.config.config_manager import ConfigManager
from edge_node.control.adaptive_nn_controller import AdaptiveNNController
from edge_node.control.controller import PassThroughController
from edge_node.fault.detector import CompositeFaultDetector, NoOpFaultDetector
from edge_node.fault.tolerant import FaultTolerantController
from edge_node.model.messages import FAULT_SEVERITY_CRITICAL, Heartbeat, RobotCommand, RobotState
from edge_node.mqtt.mqtt_client import MqttClient
from edge_node.processor.signal_filter import RobotSignalFilter
from edge_node.processor.state_processor import StateProcessor
from edge_node.utils.logger import get_logger

logger = get_logger('edge_node.main')


def main(args=None):
    parser = argparse.ArgumentParser(description='工业机械臂仿真平台 - 边端节点')
    parser.add_argument('--config', type=str, required=True, help='edge_config.yaml 路径')
    parsed, _ = parser.parse_known_args(args)

    cfg = ConfigManager(parsed.config)
    sim_id = cfg.simulation_id
    robot_id = cfg.robot_id

    logger.info("启动边端节点 simulation_id=%s robot_id=%s", sim_id, robot_id)

    # ---- 业务层 ----
    processor = StateProcessor(
        sim_id, robot_id,
        default_status=cfg.default_status,
        max_torque=cfg.max_torque,
    )
    # 信号预处理：MAD 离群点剔除 + 中值 + EMA（位于所有处理/检测之前）
    if cfg.signal_filter_enabled:
        signal_filter = RobotSignalFilter(
            n_joints=cfg.joint_count,
            window_size=cfg.sf_window_size,
            outlier_k=cfg.sf_outlier_k,
            alpha_position=cfg.sf_alpha_position,
            alpha_velocity=cfg.sf_alpha_velocity,
            alpha_effort=cfg.sf_alpha_effort,
            min_sigma_position=cfg.sf_min_sigma_position,
            min_sigma_velocity=cfg.sf_min_sigma_velocity,
            min_sigma_effort=cfg.sf_min_sigma_effort,
        )
        logger.info("信号滤波已启用 (window=%d k=%.1f alpha=%.2f/%.2f/%.2f)",
                    cfg.sf_window_size, cfg.sf_outlier_k,
                    cfg.sf_alpha_position, cfg.sf_alpha_velocity, cfg.sf_alpha_effort)
    else:
        signal_filter = None
        logger.info("信号滤波未启用（原始信号直通）")

    # 故障检测器：根据配置启用复合检测器或占位检测器
    if cfg.fault_detection_enabled:
        fault_detector = CompositeFaultDetector(
            n_joints=cfg.joint_count,
            window_size=cfg.fault_window_size,
            persistence=cfg.fault_persistence,
            max_velocity=cfg.fault_max_velocity,
            position_limit=cfg.fault_position_limit,
            torque_overload_threshold=cfg.fault_torque_overload_threshold,
            lock_position_threshold=cfg.fault_lock_position_threshold,
            lock_torque_threshold=cfg.fault_lock_torque_threshold,
            comm_timeout_ms=cfg.fault_comm_timeout_ms,
        )
        logger.info("故障检测已启用 (window=%d persistence=%d)",
                    cfg.fault_window_size, cfg.fault_persistence)
    else:
        fault_detector = NoOpFaultDetector()
        logger.info("故障检测未启用")

    # 容错控制器：故障发生时对控制输出做安全补偿
    if cfg.fault_tolerance_enabled:
        ftc = FaultTolerantController(
            n_joints=cfg.joint_count,
            torque_overload_scale=cfg.ft_torque_overload_scale,
            velocity_clamp=cfg.ft_velocity_clamp,
            recovery_frames=cfg.ft_recovery_frames,
            active_replanning=cfg.ft_active_replanning,
            replanning_damping=cfg.ft_replanning_damping,
            replanning_step=cfg.ft_replanning_step,
        )
        logger.info("容错控制已启用 (torque_scale=%.2f vel_clamp=%.3f active_replan=%s)",
                    cfg.ft_torque_overload_scale, cfg.ft_velocity_clamp,
                    cfg.ft_active_replanning)
    else:
        ftc = None
        logger.info("容错控制未启用")

    # 控制器：根据配置选择透传或自适应 NN
    control_mode = cfg.control_mode
    pass_through = PassThroughController()
    nn_controller: Optional[AdaptiveNNController] = None
    if control_mode == 'adaptive_nn':
        nn_controller = AdaptiveNNController(
            n_joints=cfg.joint_count,
            lambda_gain=cfg.lambda_gain,
            kd=cfg.kd,
            learning_rate=cfg.learning_rate,
            leakage=cfg.leakage,
            n_centers=cfg.n_centers,
            nominal_inertia=cfg.nominal_inertia,
            position_range=cfg.position_range,
            velocity_range=cfg.velocity_range,
            dt=cfg.control_dt,
        )
        logger.info("控制模式: adaptive_nn (lambda=%.1f kd=%.1f lr=%.3f centers=%d)",
                    cfg.lambda_gain, cfg.kd, cfg.learning_rate, cfg.n_centers)
    else:
        logger.info("控制模式: pass_through")

    # 共享的最新状态（状态回调写，控制循环/MQTT 定时器读）
    latest_state: dict = {'value': None}
    latest_fault: dict = {'value': None}
    # 云端最近一次位置目标（无 ROS 2 容错闭环的参考目标）；None=无活动目标
    active_target: dict = {'value': None}
    state_lock = threading.Lock()

    # ---- 状态处理管线（ROS 2 joint_states 与 MQTT sim_state 共用）----
    def handle_joint_state(position, velocity, effort, stamp_ns=None):
        try:
            # 信号预处理：离群点剔除 + 中值 + EMA（ROS 2 与 MQTT sim_state 共用此入口）
            if signal_filter is not None:
                position, velocity, effort, outlier_mask = signal_filter.filter(
                    position, velocity, effort)
                if any(outlier_mask):
                    joints = [str(i) for i, flagged in enumerate(outlier_mask) if flagged]
                    logger.debug("[滤波] 离群帧已剔除并保持 joints=%s 累计剔除帧=%d",
                                 ','.join(joints), signal_filter.outlier_frames)
            state = processor.from_joint_state(
                position=position,
                velocity=velocity,
                effort=effort,
                stamp_nanosec=stamp_ns,
            )
            # 故障检测：严重度为 CRITICAL 的故障强制状态置 ERROR
            fault = fault_detector.detect_event(state)
            if ftc is not None:
                ftc.update_fault(fault)
            if fault is not None:
                logger.warning("[故障] %s joint=%d severity=%s: %s",
                               fault.fault_type, fault.joint_index,
                               fault.severity, fault.detail)
                if fault.severity == FAULT_SEVERITY_CRITICAL:
                    state.status = 'ERROR'
                # v1.1：故障明细随 state 上云（可选 faults 数组；无故障为空数组）
                if cfg.publish_faults:
                    state.faults = [fault]
            with state_lock:
                latest_state['value'] = state
                latest_fault['value'] = fault
        except Exception as e:
            logger.error("状态处理失败: %s", e)

    def handle_mqtt_state(data: dict) -> None:
        """无 ROS 2 模式：仿真端 MQTT 原始状态 → 同一处理管线"""
        handle_joint_state(
            position=data.get('jointPosition'),
            velocity=data.get('jointVelocity'),
            effort=data.get('jointTorque'),
            stamp_ns=data.get('stampNanosec'),
        )

    # ---- ROS 2 ----
    try:
        import rclpy
        from rclpy.node import Node
        from edge_node.ros2.state_subscriber import StateSubscriber
        from edge_node.ros2.command_publisher import CommandPublisher
        ros2_available = True
    except ImportError:
        ros2_available = False
        logger.warning("rclpy 不可用，将以无 ROS 2 模式运行（仅 MQTT 链路可测）")

    node = None
    command_publisher = None
    if ros2_available:
        rclpy.init(args=args)
        node = Node('edge_node')

        joint_states_topic = cfg.render_topic(cfg.get('ros2', 'joint_states_topic'))
        joint_command_topic = cfg.render_topic(cfg.get('ros2', 'joint_command_topic'))

        def on_joint_state(position, velocity, effort, stamp_ns=None):
            handle_joint_state(position, velocity, effort, stamp_ns)

        StateSubscriber(node, joint_states_topic, on_joint_state)
        command_publisher = CommandPublisher(node, joint_command_topic)
        logger.info("ROS 2 已订阅 %s，发布 %s", joint_states_topic, joint_command_topic)

    # ---- 云端指令回调 ----
    def on_command(cmd: RobotCommand):
        try:
            # 状态推断：根据指令类型更新运行状态（STOP→STOPPED，其余→RUNNING）
            processor.set_command_status(cmd.cmd_type)
            target = pass_through.command_to_target(cmd)
            # 记录活动目标（无 ROS 2 容错闭环参考）；STOP 后清空，避免对刹车中的臂下发补偿
            with state_lock:
                if cmd.cmd_type == 'STOP':
                    active_target['value'] = None
                elif target is not None:
                    active_target['value'] = list(target)
            detail = 'accepted'
            if nn_controller is not None:
                # 自适应 NN 模式：把云端目标设为 setpoint，由控制循环闭环跟踪
                if target is not None:
                    nn_controller.set_setpoint(target)
                    logger.info("NN setpoint 已更新 commandId=%s cmdType=%s target=%s",
                                cmd.command_id, cmd.cmd_type,
                                [round(t, 3) for t in target])
                else:
                    logger.info("收到指令 commandId=%s cmdType=%s（无位置目标）",
                                cmd.command_id, cmd.cmd_type)
            else:
                # 透传模式：直接转发到仿真端（故障时做容错补偿）
                if target is not None and command_publisher is not None:
                    if ftc is not None and ftc.has_any_fault:
                        with state_lock:
                            cur_state = latest_state['value']
                        if cur_state is not None:
                            target = ftc.compensate(cur_state, target)
                            logger.info("容错补偿后目标: %s",
                                        [round(t, 3) for t in target])
                    command_publisher.publish_position(target)
                    logger.info("已转发指令到仿真端 commandId=%s cmdType=%s", cmd.command_id, cmd.cmd_type)
                else:
                    logger.info("收到指令 commandId=%s cmdType=%s（无需发布位置或无 ROS 2）",
                                cmd.command_id, cmd.cmd_type)
            mqtt_client.publish_command_ack(robot_id, cmd.command_id, cmd.cmd_type,
                                            'SUCCESS', detail)
        except Exception as e:
            logger.error("处理云端指令失败 commandId=%s: %s", cmd.command_id, e)
            mqtt_client.publish_command_ack(robot_id, cmd.command_id, cmd.cmd_type,
                                            'FAILED', str(e))

    def on_config(runtime_cfg):
        cfg.update_runtime(runtime_cfg)
        logger.info("运行时配置已更新: controlMode=%s", runtime_cfg.control_mode)

    # ---- MQTT ----
    mqtt_client = MqttClient(
        broker_url=cfg.get('mqtt', 'broker_url'),
        client_id=cfg.get('mqtt', 'client_id'),
        simulation_id=sim_id,
        state_topic=cfg.render_topic(cfg.get('mqtt', 'state_topic')),
        heartbeat_topic=cfg.render_topic(cfg.get('mqtt', 'heartbeat_topic')),
        command_topic=cfg.render_topic(cfg.get('mqtt', 'command_topic')),
        config_topic=cfg.render_topic(cfg.get('mqtt', 'config_topic')),
        username=cfg.get('mqtt', 'username', default=''),
        password=cfg.get('mqtt', 'password', default=''),
        qos=int(cfg.get('mqtt', 'qos', default=1)),
        keepalive=int(cfg.get('mqtt', 'keepalive', default=60)),
        on_command=on_command,
        on_config=on_config,
        # 无 ROS 2 模式：订阅仿真端 MQTT 原始状态，走同一故障检测/容错管线
        on_state=None if ros2_available else handle_mqtt_state,
        upstream_state_topic=(
            None if ros2_available
            else cfg.render_topic(cfg.get(
                'mqtt', 'upstream_state_topic',
                default='simulation/{simulation_id}/sim_state'))
        ),
        # 双向 TLS（broker 仅开 8883，本机映射 8884）：路径相对 edge_config.yaml 解析
        ca_certs=cfg.mqtt_tls_ca_certs,
        certfile=cfg.mqtt_tls_certfile,
        keyfile=cfg.mqtt_tls_keyfile,
        tls_insecure=cfg.mqtt_tls_insecure,
    )
    mqtt_client.connect()

    # ---- 心跳线程（独立线程，不依赖 ROS 2 spin）----
    def heartbeat_loop():
        interval = cfg.heartbeat_interval_sec
        while True:
            try:
                hb = Heartbeat(
                    simulation_id=sim_id,
                    robot_id=robot_id,
                    timestamp=int(time.time() * 1000),
                    status='ONLINE',
                )
                mqtt_client.publish_heartbeat(hb)
            except Exception as e:
                logger.error("心跳发布失败: %s", e)
            time.sleep(interval)

    hb_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    hb_thread.start()

    # ---- 状态上传线程（按 state_publish_hz 节流）----
    def state_publish_loop():
        interval = 1.0 / max(cfg.state_publish_hz, 0.1)
        while True:
            try:
                # 通信超时检测
                timeout_fault = fault_detector.check_timeout() if hasattr(
                    fault_detector, 'check_timeout') else None
                if timeout_fault is not None:
                    if ftc is not None:
                        ftc.update_fault(timeout_fault)
                    logger.warning("[故障] %s: %s",
                                   timeout_fault.fault_type, timeout_fault.detail)
                with state_lock:
                    state: Optional[RobotState] = latest_state['value']
                if state is not None and mqtt_client.is_connected:
                    # 通信超时在发布线程检出（非状态回调），发布前挂到本帧 faults
                    if cfg.publish_faults and timeout_fault is not None:
                        state.faults = [timeout_fault]
                    mqtt_client.publish_state(state)
            except Exception as e:
                logger.error("状态发布失败: %s", e)
            time.sleep(interval)

    state_thread = threading.Thread(target=state_publish_loop, daemon=True)
    state_thread.start()

    # ---- 闭环控制循环（仅 adaptive_nn 模式）----
    def control_loop():
        if nn_controller is None:
            return
        interval = cfg.control_dt
        logger.info("自适应 NN 控制循环启动，频率=%.1fHz", cfg.control_rate_hz)
        while True:
            try:
                with state_lock:
                    state: Optional[RobotState] = latest_state['value']
                if state is not None and command_publisher is not None:
                    q = state.joint_position
                    q_dot = state.joint_velocity
                    q_target = nn_controller.compute_target_position(q, q_dot)
                    # 容错补偿：故障时对目标做安全修正
                    if ftc is not None:
                        q_target = ftc.compensate(state, q_target)
                    command_publisher.publish_position(q_target)
            except Exception as e:
                logger.error("控制循环失败: %s", e)
            time.sleep(interval)

    control_thread = threading.Thread(target=control_loop, daemon=True)
    control_thread.start()

    # ---- 无 ROS 2 容错执行器闭环（MQTT 安全指令线程）----
    # 故障时把 ftc 补偿目标以 MOVE_JOINT_SAFE 下发仿真端（直接伺服、不做轨迹规划）；
    # 恢复后下发 resume，仿真端重新梯形规划回云端原目标。
    if not ros2_available and cfg.safe_command_enabled and ftc is not None:
        def safe_command_loop():
            interval = 1.0 / max(cfg.state_publish_hz, 0.1)
            safe_active = False
            logger.info("容错 MQTT 闭环已启用（频率=%.1fHz）", cfg.state_publish_hz)
            while True:
                try:
                    with state_lock:
                        state: Optional[RobotState] = latest_state['value']
                        raw_target = active_target['value']
                        raw_target = list(raw_target) if raw_target is not None else None
                    if state is not None and raw_target is not None:
                        if nn_controller is not None:
                            q_target = nn_controller.compute_target_position(
                                state.joint_position, state.joint_velocity)
                        else:
                            q_target = raw_target
                        if ftc.has_any_fault:
                            safe_target = ftc.compensate(state, q_target)
                            mqtt_client.publish_safe_command(robot_id, target=safe_target)
                            if not safe_active:
                                logger.warning("容错激活：下发安全目标 %s",
                                               [round(t, 3) for t in safe_target])
                            safe_active = True
                        elif safe_active:
                            mqtt_client.publish_safe_command(robot_id, resume=True)
                            logger.info("容错解除：通知仿真端恢复原目标轨迹 %s",
                                        [round(t, 3) for t in raw_target])
                            safe_active = False
                except Exception as e:
                    logger.error("安全指令循环失败: %s", e)
                time.sleep(interval)

        safe_thread = threading.Thread(target=safe_command_loop, daemon=True)
        safe_thread.start()

    # ---- 主循环 ----
    try:
        if ros2_available and node is not None:
            rclpy.spin(node)
        else:
            # 无 ROS 2 模式：阻塞主线程，保持 MQTT 与心跳线程运行
            while True:
                time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在退出...")
    finally:
        mqtt_client.disconnect()
        if ros2_available and node is not None:
            node.destroy_node()
            rclpy.shutdown()
        logger.info("边端节点已退出")


if __name__ == '__main__':
    main()

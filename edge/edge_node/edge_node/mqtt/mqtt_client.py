"""MQTT 通信模块：边端 <-> 云端

严格对齐云端 MqttConfig / MqttMessageHandler：
- 发布: simulation/{simulationId}/state  (RobotState, 边端上报云端)
- 发布: simulation/{simulationId}/heartbeat (Heartbeat)
- 订阅: simulation/{simulationId}/command (RobotCommand, 云端下发)
- 订阅: simulation/{simulationId}/config  (EdgeConfig, 云端下发)
- 订阅: upstream_state_topic（可选，无 ROS 2 模式下接收仿真端原始状态，
        默认 simulation/{simulationId}/sim_state —— 与上报主题分离，避免自环）
"""
from __future__ import annotations

import json
import ssl
import threading
import time
from typing import Callable, Optional

import paho.mqtt.client as mqtt

from edge_node.model.messages import (
    Heartbeat,
    RobotCommand,
    RobotState,
    EdgeConfig,
)
from edge_node.utils.logger import get_logger

logger = get_logger('edge_node.mqtt')


class MqttClient:
    """封装 paho-mqtt，提供发布/订阅与回调"""

    def __init__(
        self,
        broker_url: str,
        client_id: str,
        simulation_id: str,
        state_topic: str,
        heartbeat_topic: str,
        command_topic: str,
        config_topic: str,
        username: str = '',
        password: str = '',
        qos: int = 1,
        keepalive: int = 60,
        on_command: Optional[Callable[[RobotCommand], None]] = None,
        on_config: Optional[Callable[[EdgeConfig], None]] = None,
        on_state: Optional[Callable[[dict], None]] = None,
        upstream_state_topic: Optional[str] = None,
        command_ack_topic: Optional[str] = None,
        ca_certs: Optional[str] = None,
        certfile: Optional[str] = None,
        keyfile: Optional[str] = None,
        tls_insecure: bool = False,
    ):
        self._broker_url = broker_url
        self._client_id = client_id
        self._simulation_id = simulation_id
        self._state_topic = state_topic
        self._heartbeat_topic = heartbeat_topic
        self._command_topic = command_topic
        self._config_topic = config_topic
        self._command_ack_topic = command_ack_topic or \
            f'simulation/{simulation_id}/command_ack'
        self._qos = qos
        self._keepalive = keepalive
        # 无 ROS 2 模式的上游状态源（仿真端原始状态主题），None 表示不订阅
        self._upstream_state_topic = upstream_state_topic
        self._on_command = on_command
        self._on_config = on_config
        self._on_state = on_state

        # 解析 host:port（ssl:// / mqtts:// / tls:// 走 TLS，默认 8883）
        host, port, secure = self._parse_broker(broker_url)

        self._client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
        if username:
            self._client.username_pw_set(username, password or None)
        if secure:
            self._configure_tls(ca_certs, certfile, keyfile, tls_insecure)

        # 遗嘱：异常断开时上报 OFFLINE，保证云端感知离线
        will_payload = json.dumps({
            'simulationId': simulation_id,
            'robotId': '',  # 心跳 robotId 在发布时由调用方提供；遗嘱仅保证 status=OFFLINE
            'timestamp': 0,
            'status': 'OFFLINE',
        })
        self._client.will_set(heartbeat_topic, payload=will_payload, qos=qos, retain=False)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

        self._host = host
        self._port = port
        self._connected = False
        self._lock = threading.Lock()

    @staticmethod
    def _parse_broker(url: str):
        """返回 (host, port, secure)；secure 表示该 scheme 需要 TLS"""
        url = url.strip()
        secure = False
        for scheme in ('tcp://', 'mqtt://'):
            if url.startswith(scheme):
                url = url[len(scheme):]
                break
        else:
            for scheme in ('ssl://', 'mqtts://', 'tls://'):
                if url.startswith(scheme):
                    url = url[len(scheme):]
                    secure = True
                    break
        if ':' in url:
            host, port_str = url.rsplit(':', 1)
            return host, int(port_str), secure
        return url, 8883 if secure else 1883, secure

    def _configure_tls(self, ca_certs: Optional[str], certfile: Optional[str],
                       keyfile: Optional[str], insecure: bool) -> None:
        """双向 TLS：校验 broker 证书（自签 CA），有客户端证书时一并出示"""
        ctx = ssl.create_default_context(cafile=ca_certs or None)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        if insecure:
            # 仅供联调：跳过服务端证书与主机名校验，生产禁用
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        if certfile:
            ctx.load_cert_chain(certfile=certfile, keyfile=keyfile or None)
        self._client.tls_set_context(ctx)
        logger.info("MQTT TLS 已启用 (ca=%s cert=%s insecure=%s)",
                    ca_certs or '<系统信任库>', certfile or '<无客户端证书>', insecure)

    # ---- 生命周期 ----
    def connect(self) -> None:
        logger.info("MQTT 连接 %s:%s (client_id=%s)", self._host, self._port, self._client_id)
        self._client.connect(self._host, self._port, keepalive=self._keepalive)
        self._client.loop_start()

    def disconnect(self) -> None:
        try:
            # 优雅下线：先发布 OFFLINE 心跳，再断开
            self.publish_heartbeat(Heartbeat(
                simulation_id=self._simulation_id,
                robot_id='',
                timestamp=0,
                status='OFFLINE',
            ))
        except Exception as e:
            logger.warning("发布 OFFLINE 心跳失败: %s", e)
        self._client.loop_stop()
        self._client.disconnect()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ---- 回调 ----
    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            if self._upstream_state_topic and self._on_state:
                logger.info("MQTT 已连接，订阅 command=%s config=%s sim_state=%s",
                            self._command_topic, self._config_topic,
                            self._upstream_state_topic)
            else:
                logger.info("MQTT 已连接，订阅 command=%s config=%s",
                            self._command_topic, self._config_topic)
            client.subscribe(self._command_topic, qos=self._qos)
            client.subscribe(self._config_topic, qos=self._qos)
            if self._upstream_state_topic and self._on_state:
                client.subscribe(self._upstream_state_topic, qos=self._qos)
        else:
            self._connected = False
            logger.error("MQTT 连接失败，rc=%s", rc)

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        if rc != 0:
            logger.warning("MQTT 异常断开 rc=%s，将自动重连", rc)
        else:
            logger.info("MQTT 已断开")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = msg.payload.decode('utf-8')
        except Exception:
            logger.error("MQTT payload 解码失败 topic=%s", topic)
            return

        if topic == self._command_topic:
            self._handle_command(payload)
        elif topic == self._config_topic:
            self._handle_config(payload)
        elif topic == self._upstream_state_topic:
            self._handle_state(payload)
        else:
            logger.debug("MQTT 收到未处理 topic=%s payload=%s", topic, payload)

    def _handle_state(self, payload: str) -> None:
        """仿真端原始状态（无 ROS 2 模式的 joint_states 等价通道）"""
        try:
            data = json.loads(payload)
            if self._on_state:
                self._on_state(data)
        except Exception as e:
            logger.error("解析 sim_state 失败: %s, payload=%s", e, payload[:120])

    def _handle_command(self, payload: str) -> None:
        try:
            data = json.loads(payload)
            # 自环过滤：边端容错时把 MOVE_JOINT_SAFE 发回同一 command 主题给仿真端，
            # 自己也会收到，不能当云端指令解析（否则每帧报解析错误）
            cmd_id = str(data.get('commandId', ''))
            if data.get('cmdType') == 'MOVE_JOINT_SAFE' or \
                    cmd_id.startswith(('EDGE-SAFE-', 'EDGE-RESUME-')):
                logger.debug("忽略边端自发的安全指令 commandId=%s", cmd_id)
                return
            cmd = RobotCommand.from_dict(data)
            logger.info("收到云端指令 commandId=%s cmdType=%s", cmd.command_id, cmd.cmd_type)
            if self._on_command:
                self._on_command(cmd)
        except Exception as e:
            logger.error("解析 command 失败: %s, payload=%s", e, payload)

    def _handle_config(self, payload: str) -> None:
        try:
            data = json.loads(payload)
            cfg = EdgeConfig.from_dict(data)
            logger.info("收到云端配置 controlMode=%s controlRate=%s",
                        cfg.control_mode, cfg.control_rate)
            if self._on_config:
                self._on_config(cfg)
        except Exception as e:
            logger.error("解析 config 失败: %s, payload=%s", e, payload)

    # ---- 发布 ----
    def publish_state(self, state: RobotState) -> None:
        payload = json.dumps(state.to_dict(), ensure_ascii=False)
        with self._lock:
            self._client.publish(self._state_topic, payload=payload, qos=self._qos)
        logger.debug("发布 state %s", payload)

    def publish_heartbeat(self, heartbeat: Heartbeat) -> None:
        payload = json.dumps(heartbeat.to_dict(), ensure_ascii=False)
        with self._lock:
            self._client.publish(self._heartbeat_topic, payload=payload, qos=self._qos)
        logger.debug("发布 heartbeat %s", payload)

    def publish_command_ack(self, robot_id: str, command_id: str, cmd_type: str,
                            result: str = 'SUCCESS', detail: Optional[str] = None) -> None:
        """指令回执：云端 command_log 靠它从 PENDING 置 SUCCESS/FAILED

        commandId 与云端 command_log.message_id 是同一个值（UUID）。
        """
        payload = {
            'commandId': command_id,
            'simulationId': self._simulation_id,
            'robotId': robot_id,
            'cmdType': cmd_type,
            'result': result,
            'detail': detail or '',
            'timestamp': int(time.time() * 1000),
        }
        body = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            self._client.publish(self._command_ack_topic, payload=body, qos=self._qos)
        logger.info("已回执指令 commandId=%s result=%s", command_id, result)

    def publish_safe_command(
        self, robot_id: str, target: Optional[list] = None, resume: bool = False
    ) -> None:
        """发布边端容错安全指令到仿真端（无 ROS 2 模式的执行器闭环通道）

        - target 非 None：MOVE_JOINT_SAFE，仿真端清除轨迹规划、直接伺服安全目标
        - resume=True：通知仿真端退出安全模式，重新规划回云端原目标
        走云端 command 主题（仿真端已订阅），以 cmdType 与 commandId 前缀区分。
        """
        if resume:
            payload = {
                'commandId': f'EDGE-RESUME-{int(time.time() * 1000)}',
                'simulationId': self._simulation_id,
                'robotId': robot_id,
                'cmdType': 'MOVE_JOINT_SAFE',
                'resume': True,
                'timestamp': int(time.time() * 1000),
            }
        else:
            payload = {
                'commandId': f'EDGE-SAFE-{int(time.time() * 1000)}',
                'simulationId': self._simulation_id,
                'robotId': robot_id,
                'cmdType': 'MOVE_JOINT_SAFE',
                'jointTarget': [float(x) for x in target],
                'timestamp': int(time.time() * 1000),
            }
        body = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            self._client.publish(self._command_topic, payload=body, qos=self._qos)
        logger.debug("发布安全指令 %s", body)

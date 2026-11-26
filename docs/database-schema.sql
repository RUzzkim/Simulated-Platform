-- 时间口径：所有 DATETIME 列存的都是**北京时间墙钟**（容器 TZ=Asia/Shanghai，Java 侧
-- LocalDateTime.now()、边端 epoch 经 Payloads.fromEpoch 都按这个时区换算），界面直接原样展示。
-- 2026-09-19 之前的历史数据是 UTC 墙钟，已由 migrate-v6-local-time.sql 整体 +8 小时对齐。
CREATE DATABASE IF NOT EXISTS robot_cloud
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE robot_cloud;

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS device (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  -- 大小写敏感：边端的 ROBOT-001 不能和演示设备 robot-001 判成同一台
  device_code VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL UNIQUE,
  -- 边端 simulation 契约里的仿真实例编号（SIM-001），由边端上报时自动绑定
  simulation_id VARCHAR(32) NULL,
  name VARCHAR(128) NOT NULL,
  robot_type VARCHAR(64) NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'OFFLINE',
  edge_node_code VARCHAR(64) NULL,
  remark VARCHAR(255) NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS device_heartbeat (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  device_id BIGINT NOT NULL,
  status VARCHAR(32) NOT NULL,
  cpu_usage DECIMAL(6,2) NULL,
  memory_usage DECIMAL(6,2) NULL,
  edge_version VARCHAR(64) NULL,
  reported_at DATETIME NOT NULL,
  INDEX idx_device_time (device_id, reported_at)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS telemetry_data (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  device_id BIGINT NOT NULL,
  reported_at DATETIME NOT NULL,
  state VARCHAR(32) NULL,
  control_mode VARCHAR(64) NULL,
  joint_payload JSON NOT NULL,
  end_effector_payload JSON NULL,
  INDEX idx_device_time (device_id, reported_at)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 遥测归档（阶段 4）：明细表保留最近 N 天，更早的按小时聚合成一行。
-- joint_metrics 形如 {"joint_1":{"position":..,"velocity":..,"torque":..},"_count":NN}，只存均值与帧数。
CREATE TABLE IF NOT EXISTS telemetry_hourly (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  device_id BIGINT NOT NULL,
  bucket_start DATETIME NOT NULL,
  frame_count INT NOT NULL,
  state VARCHAR(32) NULL,
  control_mode VARCHAR(64) NULL,
  joint_metrics JSON NOT NULL,
  archived_at DATETIME NOT NULL,
  UNIQUE KEY uk_device_bucket (device_id, bucket_start),
  INDEX idx_bucket (bucket_start)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS fault_event (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  device_id BIGINT NOT NULL,
  event_type VARCHAR(64) NOT NULL,
  level VARCHAR(32) NOT NULL,
  detail VARCHAR(255) NULL,
  context_payload JSON NULL,
  occurred_at DATETIME NOT NULL,
  INDEX idx_device_time (device_id, occurred_at)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS control_parameter (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  device_id BIGINT NOT NULL,
  version INT NOT NULL,
  param_payload JSON NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
  created_by BIGINT NULL,
  created_by_name VARCHAR(64) NULL,
  created_at DATETIME NOT NULL,
  UNIQUE KEY uk_device_version (device_id, version)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS control_strategy (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(128) NOT NULL,
  version INT NOT NULL,
  strategy_payload JSON NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
  created_by BIGINT NULL,
  created_by_name VARCHAR(64) NULL,
  created_at DATETIME NOT NULL,
  UNIQUE KEY uk_strategy_version (name, version)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS model_version (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  device_id BIGINT NOT NULL,
  model_name VARCHAR(128) NOT NULL,
  version INT NOT NULL,
  artifact_url VARCHAR(255) NULL,
  metadata_payload JSON NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
  created_by BIGINT NULL,
  created_by_name VARCHAR(64) NULL,
  created_at DATETIME NOT NULL,
  UNIQUE KEY uk_model_version (device_id, model_name, version)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS command_log (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  device_id BIGINT NOT NULL,
  -- 边端 simulation 契约：指令发往哪个 sim / 哪个 robotId（robot 契约设备为 NULL）
  simulation_id VARCHAR(32) NULL,
  target_robot_id VARCHAR(64) NULL,
  message_id VARCHAR(64) NOT NULL UNIQUE,
  cmd_type VARCHAR(32) NOT NULL,
  version INT NULL,
  payload JSON NOT NULL,
  issued_by BIGINT NULL,
  issued_by_name VARCHAR(64) NULL,
  issued_at DATETIME NOT NULL,
  result VARCHAR(32) NULL,
  result_detail VARCHAR(255) NULL,
  acknowledged_at DATETIME NULL
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS app_user (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  username VARCHAR(64) NOT NULL UNIQUE,
  display_name VARCHAR(128) NULL,
  password_hash VARCHAR(100) NOT NULL,
  role VARCHAR(32) NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 1,
  -- 审批状态：PENDING（自助注册待审）/ APPROVED（可登录）/ REJECTED（已驳回）
  status VARCHAR(16) NOT NULL DEFAULT 'APPROVED',
  last_login_at DATETIME NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_log (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  actor_type VARCHAR(16) NOT NULL,
  actor_id BIGINT NULL,
  actor_name VARCHAR(64) NULL,
  action VARCHAR(64) NOT NULL,
  target_type VARCHAR(32) NULL,
  target_id VARCHAR(64) NULL,
  detail VARCHAR(512) NULL,
  result VARCHAR(16) NOT NULL,
  error_message VARCHAR(255) NULL,
  client_ip VARCHAR(64) NULL,
  occurred_at DATETIME NOT NULL,
  INDEX idx_audit_time (occurred_at),
  INDEX idx_audit_actor (actor_type, actor_id),
  INDEX idx_audit_action (action)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS device_credential (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  device_id BIGINT NOT NULL UNIQUE,
  mqtt_username VARCHAR(64) NOT NULL UNIQUE,
  secret_cipher TEXT NOT NULL,
  token_cipher TEXT NOT NULL,
  token_version INT NOT NULL DEFAULT 1,
  status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
  issued_by BIGINT NULL,
  issued_at DATETIME NOT NULL,
  rotated_at DATETIME NULL,
  revoked_at DATETIME NULL,
  INDEX idx_credential_status (status)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- V2 实验 Run 与故障/决策事件（契约 2.0.0）
CREATE TABLE IF NOT EXISTS experiment_run (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  run_id CHAR(32) NOT NULL,
  device_id BIGINT NULL,
  simulation_id VARCHAR(16) NULL,
  robot_id VARCHAR(32) NULL,
  contract_version VARCHAR(16) NULL,
  algorithm_version VARCHAR(32) NULL,
  scenario_id VARCHAR(96) NULL,
  split_name VARCHAR(32) NULL,
  seed INT NULL,
  strategy VARCHAR(16) NULL,
  status VARCHAR(32) NULL,
  started_at DATETIME NULL,
  window_end_at DATETIME NULL,
  fault_type VARCHAR(32) NULL,
  fault_joint INT NULL,
  fault_injected_at_s DOUBLE NULL,
  fault_detected_at_s DOUBLE NULL,
  detection_latency_ms DOUBLE NULL,
  reachability_status VARCHAR(32) NULL,
  reachability_reason VARCHAR(64) NULL,
  decision_action VARCHAR(16) NULL,
  decision_reason VARCHAR(64) NULL,
  decision_at_s DOUBLE NULL,
  final_ee_error_m DOUBLE NULL,
  recovery_time_s DOUBLE NULL,
  stop_time_s DOUBLE NULL,
  peak_fault_joint_torque_nm DOUBLE NULL,
  max_joint_speed_rad_s DOUBLE NULL,
  max_joint_torque_nm DOUBLE NULL,
  trace_path VARCHAR(512) NULL,
  trace_sha256 CHAR(64) NULL,
  payload JSON NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uk_experiment_run_id (run_id),
  INDEX idx_experiment_device_started (device_id, started_at),
  INDEX idx_experiment_status (status)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS experiment_event (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  event_key VARCHAR(160) NOT NULL,
  run_id CHAR(32) NOT NULL,
  event_type VARCHAR(16) NOT NULL,
  event_time DATETIME NOT NULL,
  sim_time_s DOUBLE NULL,
  fault_type VARCHAR(32) NULL,
  joint_index INT NULL,
  action VARCHAR(16) NULL,
  reason VARCHAR(64) NULL,
  reachability_status VARCHAR(32) NULL,
  detail TEXT NULL,
  payload JSON NULL,
  created_at DATETIME NOT NULL,
  UNIQUE KEY uk_experiment_event_key (event_key),
  INDEX idx_experiment_event_run (run_id, event_time)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
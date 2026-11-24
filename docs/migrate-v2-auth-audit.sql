-- 阶段 3 增量迁移：账号/角色、审计日志、设备接入凭据
-- 现有库执行本脚本即可，无需重建数据卷；新库直接由 database-schema.sql 建好。
USE robot_cloud;

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS app_user (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  username VARCHAR(64) NOT NULL UNIQUE,
  display_name VARCHAR(128) NULL,
  password_hash VARCHAR(100) NOT NULL,
  role VARCHAR(32) NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 1,
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

-- 说明：command_log.issued_by 在最初的 database-schema.sql 中已存在；
-- 这里补一列“下发人用户名”，方便界面直接显示，历史数据保持 NULL（系统/匿名下发）。
ALTER TABLE command_log ADD COLUMN issued_by_name VARCHAR(64) NULL AFTER issued_by;
-- 阶段 4 增量迁移：参数/策略/模型版本化的创建人字段 + 遥测归档表
-- 现有库执行本脚本即可，无需重建数据卷；新库直接由 database-schema.sql 建好。
-- 用法：docker exec -i robot-mysql-local mysql --default-character-set=utf8mb4 -uroot -p<密码> robot_cloud < docs/migrate-v3-publish-archive.sql
USE robot_cloud;

SET NAMES utf8mb4;

-- 版本行补“创建人用户名”，界面直接显示（历史数据保持 NULL）。
ALTER TABLE control_parameter ADD COLUMN created_by_name VARCHAR(64) NULL AFTER created_by;
ALTER TABLE control_strategy  ADD COLUMN created_by_name VARCHAR(64) NULL AFTER created_by;
ALTER TABLE model_version     ADD COLUMN created_by BIGINT NULL AFTER status,
                              ADD COLUMN created_by_name VARCHAR(64) NULL AFTER created_by;

-- 遥测归档表：明细保留最近 N 天，更早的按小时聚合成一行（joint_metrics 存均值与帧数）。
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
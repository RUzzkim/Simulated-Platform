-- 阶段 6：全平台墙钟时间统一为北京时间（Asia/Shanghai）
--
-- 背景：以前所有时间列存的都是 UTC 墙钟——Java 侧 LocalDateTime.now() 跑在 UTC 容器里，
-- 边端上报的 epoch 毫秒也在 Payloads.fromEpoch 里按 ZoneOffset.UTC 换算。结果是库里和界面上
-- 显示的时间都比本地时间早 8 小时。现在容器 TZ=Asia/Shanghai、Payloads 按 PLATFORM_ZONE 换算，
-- 存量数据需要整体 +8 小时对齐。
--
-- @cutover 是切换时刻：这个点之前落库的是 UTC 墙钟（要平移），之后写入的已经是北京时间（不动）。
-- 不设这个边界的话，切换后到执行本脚本之间写进去的那几条会被多加 8 小时。
--
-- 幂等：靠 schema_migration 表登记，重复执行不会二次平移。
-- 新库直接由 database-schema.sql 建好、且写入即为北京时间，无需跑本脚本。
-- 用法：docker exec -i robot-mysql-local mysql --default-character-set=utf8mb4 -uroot -p<密码> robot_cloud < docs/migrate-v6-local-time.sql

USE robot_cloud;

SET NAMES utf8mb4;

SET @cutover := '2026-09-19 18:00:00';

CREATE TABLE IF NOT EXISTS schema_migration (
  name       VARCHAR(128) NOT NULL COMMENT '迁移标识',
  applied_at DATETIME     NOT NULL COMMENT '本次迁移的执行时刻（北京时间）',
  PRIMARY KEY (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='增量迁移登记表';

SET @pending := (SELECT COUNT(*) = 0 FROM schema_migration WHERE name = 'v6-local-time');
SET @shift := @pending AND 1;

-- device
UPDATE device SET created_at = created_at + INTERVAL 8 HOUR, updated_at = updated_at + INTERVAL 8 HOUR
  WHERE @shift AND created_at < @cutover;
-- telemetry_data
UPDATE telemetry_data SET reported_at = reported_at + INTERVAL 8 HOUR
  WHERE @shift AND reported_at < @cutover;
-- device_heartbeat
UPDATE device_heartbeat SET reported_at = reported_at + INTERVAL 8 HOUR
  WHERE @shift AND reported_at < @cutover;
-- telemetry_hourly
UPDATE telemetry_hourly SET bucket_start = bucket_start + INTERVAL 8 HOUR, archived_at = archived_at + INTERVAL 8 HOUR
  WHERE @shift AND bucket_start < @cutover;
-- fault_event
UPDATE fault_event SET occurred_at = occurred_at + INTERVAL 8 HOUR
  WHERE @shift AND occurred_at < @cutover;
-- command_log
UPDATE command_log SET issued_at = issued_at + INTERVAL 8 HOUR
  WHERE @shift AND issued_at < @cutover;
UPDATE command_log SET acknowledged_at = acknowledged_at + INTERVAL 8 HOUR
  WHERE @shift AND acknowledged_at IS NOT NULL AND acknowledged_at < @cutover;
-- audit_log
UPDATE audit_log SET occurred_at = occurred_at + INTERVAL 8 HOUR
  WHERE @shift AND occurred_at < @cutover;
-- control_parameter / control_strategy / model_version
UPDATE control_parameter SET created_at = created_at + INTERVAL 8 HOUR WHERE @shift AND created_at < @cutover;
UPDATE control_strategy  SET created_at = created_at + INTERVAL 8 HOUR WHERE @shift AND created_at < @cutover;
UPDATE model_version     SET created_at = created_at + INTERVAL 8 HOUR WHERE @shift AND created_at < @cutover;
-- device_credential
UPDATE device_credential SET issued_at = issued_at + INTERVAL 8 HOUR
  WHERE @shift AND issued_at < @cutover;
UPDATE device_credential SET rotated_at = rotated_at + INTERVAL 8 HOUR
  WHERE @shift AND rotated_at IS NOT NULL AND rotated_at < @cutover;
UPDATE device_credential SET revoked_at = revoked_at + INTERVAL 8 HOUR
  WHERE @shift AND revoked_at IS NOT NULL AND revoked_at < @cutover;
-- app_user
UPDATE app_user SET created_at = created_at + INTERVAL 8 HOUR, updated_at = updated_at + INTERVAL 8 HOUR
  WHERE @shift AND created_at < @cutover;
UPDATE app_user SET last_login_at = last_login_at + INTERVAL 8 HOUR
  WHERE @shift AND last_login_at IS NOT NULL AND last_login_at < @cutover;

INSERT INTO schema_migration (name, applied_at)
SELECT 'v6-local-time', NOW() FROM DUAL WHERE @shift;

SELECT @pending AS shifted, (SELECT COUNT(*) FROM schema_migration) AS migrations;
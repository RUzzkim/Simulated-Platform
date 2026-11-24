-- 阶段 5（边端对接）增量迁移：command_log 记录边端指令的目标
-- 幂等：可重复执行；新库直接由 database-schema.sql 建好，无需跑本脚本。
-- 用法：docker exec -i robot-mysql-local mysql --default-character-set=utf8mb4 -uroot -p<密码> robot_cloud < docs/migrate-v5-command-log.sql

USE robot_cloud;

SET NAMES utf8mb4;

-- simulation 契约：指令发往 simulation/{simulationId}/command，这里记下当时的 sim 与 robotId，
-- 便于设备改名/换绑之后仍能追溯这条指令到底发给了谁。
SET @sql := (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE command_log ADD COLUMN simulation_id VARCHAR(32) NULL COMMENT ''边端 sim 契约的 simulationId'' AFTER device_id',
    'DO 0')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'command_log' AND COLUMN_NAME = 'simulation_id');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE command_log ADD COLUMN target_robot_id VARCHAR(64) NULL COMMENT ''边端 sim 契约的 robotId'' AFTER simulation_id',
    'DO 0')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'command_log' AND COLUMN_NAME = 'target_robot_id');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
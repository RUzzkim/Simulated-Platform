-- 阶段 5（边端对接）增量迁移：设备归属的仿真实例 + device_code 大小写敏感
-- 幂等：可重复执行；新库直接由 database-schema.sql 建好，无需跑本脚本。
-- 用法：docker exec -i robot-mysql-local mysql --default-character-set=utf8mb4 -uroot -p<密码> robot_cloud < docs/migrate-v4-simulation.sql

USE robot_cloud;

SET NAMES utf8mb4;

-- 1) 边端 simulation 契约用 simulationId(SIM-001) + robotId(ROBOT-001) 标识数据来源；
--    其中 robotId 落到 device.device_code，simulationId 记在下面这列上（由边端上报时自动绑定）。
SET @has_col := (SELECT COUNT(*) FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'device' AND COLUMN_NAME = 'simulation_id');
SET @ddl := IF(@has_col = 0,
  'ALTER TABLE device ADD COLUMN simulation_id VARCHAR(32) NULL COMMENT ''边端 simulation 契约的仿真实例编号（SIM-001）'' AFTER device_code',
  'DO 0');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 2) device_code 必须大小写敏感：库默认 utf8mb4_0900_ai_ci 会把边端的 ROBOT-001
--    与演示设备的 robot-001 判成同一台，两个数据源静默混在一起（唯一索引也按 ci 比较）。
SET @cur_coll := (SELECT COLLATION_NAME FROM information_schema.COLUMNS
                  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'device' AND COLUMN_NAME = 'device_code');
SET @ddl := IF(@cur_coll IS NOT NULL AND @cur_coll <> 'utf8mb4_bin',
  'ALTER TABLE device MODIFY COLUMN device_code VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL',
  'DO 0');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
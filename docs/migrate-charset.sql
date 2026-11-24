-- 已有库的字符集补齐（docker-entrypoint-initdb.d 里的建表脚本只在空库执行一次）
-- 用法：docker exec -i robot-mysql-local mysql --default-character-set=utf8mb4 -uroot -p<密码> < docs/migrate-charset.sql
-- 注意：容器内 mysql 客户端默认字符集是 latin1，手工写中文必须带 --default-character-set=utf8mb4，否则又会写成乱码。

ALTER DATABASE robot_cloud CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

ALTER TABLE device            CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE device_heartbeat  CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE telemetry_data    CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE fault_event       CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE control_parameter CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE control_strategy  CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE model_version     CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE command_log       CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 校验：应该都是 utf8mb4 / utf8mb4_unicode_ci
-- SELECT TABLE_NAME, TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA = 'robot_cloud';

-- 如果历史数据是被 latin1 连接错误写入的，可以尝试原地还原（先备份、先在一条数据上验证）：
-- UPDATE device SET name = CONVERT(BINARY(CONVERT(name USING latin1)) USING utf8mb4)
--   WHERE name <> CONVERT(BINARY(CONVERT(name USING latin1)) USING utf8mb4);
-- 更稳妥的做法：在设备详情页用「重命名」重新写入正确名称。
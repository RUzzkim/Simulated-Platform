-- 阶段 5（账号治理）增量迁移：app_user 增加审批状态 status
-- 幂等：可重复执行；新库直接由 database-schema.sql 建好，无需跑本脚本。
-- 用法：docker exec -i robot-mysql-local mysql --default-character-set=utf8mb4 -uroot -p<密码> robot_cloud < docs/migrate-v7-user-approval.sql

USE robot_cloud;

SET NAMES utf8mb4;

-- 自助注册的账号先落 PENDING，ADMIN 审批后置 APPROVED 才能登录；驳回置 REJECTED。
-- 已有账号（迁移前建的）默认视为 APPROVED，保证升级后原账号能继续登录。
SET @sql := (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE app_user ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT ''APPROVED'' COMMENT ''审批状态 PENDING/APPROVED/REJECTED'' AFTER enabled',
    'DO 0')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'app_user' AND COLUMN_NAME = 'status');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 兜底：把历史行里可能为空的 status 补成 APPROVED（列是新加的一般不会有空值，防御性处理）。
UPDATE app_user SET status = 'APPROVED' WHERE status IS NULL OR status = '';

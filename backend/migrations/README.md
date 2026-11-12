# Schema 版本

## v1

本地启动使用SQLAlchemy metadata创建初始表。自然键：users.email、building_datasets.name、building_days(dataset_id,building_code,day)、model_runs.name、driver_findings(run_id,feature)、retrofit_hypotheses.title。数值测量与解释列使用DOUBLE。

## v2：研究取消、失败重试与尝试留痕

新增表 `run_attempts`，并给 `model_runs` 增加 `attempt_count`、`updated_at`：

```sql
CREATE TABLE run_attempts (
  id BIGINT NOT NULL AUTO_INCREMENT,
  run_id BIGINT NOT NULL,
  attempt_no INT NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'queued',
  stage VARCHAR(30) NOT NULL DEFAULT 'queued',
  progress INT NOT NULL DEFAULT 0,
  detail VARCHAR(600) NOT NULL DEFAULT '',
  error VARCHAR(600) NOT NULL DEFAULT '',
  active_key BIGINT NULL,
  started_at DATETIME NULL,
  finished_at DATETIME NULL,
  created_at DATETIME NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT fk_run_attempts_run FOREIGN KEY (run_id) REFERENCES model_runs (id),
  UNIQUE KEY uq_run_active_attempt (run_id, active_key)
);
ALTER TABLE model_runs ADD COLUMN attempt_count INT NOT NULL DEFAULT 0;
ALTER TABLE model_runs ADD COLUMN updated_at DATETIME NULL;

-- 回填v1遗留研究：终态研究补一条与现状一致的尝试，避免历史记录缺尝试
INSERT INTO run_attempts (run_id, attempt_no, status, stage, progress, detail, error, active_key, started_at, finished_at, created_at)
SELECT id, 1, status,
       CASE WHEN status='completed' THEN 'persist' ELSE 'queued' END,
       CASE WHEN status='completed' THEN 100 ELSE 0 END,
       '升级前历史尝试，按研究终态回填', COALESCE(error,''), NULL, created_at, created_at, created_at
FROM model_runs;
UPDATE model_runs SET attempt_count=1;
```

`active_key` 仅在尝试处于 queued/running 时等于 `run_id`，终态置 NULL。MySQL 唯一索引允许多个 NULL，因此同一研究可保留任意条历史尝试，却至多存在一条活动尝试，从数据库层保证并发重复重试只产生一次有效计算。回滚：`DROP TABLE run_attempts; ALTER TABLE model_runs DROP COLUMN attempt_count, DROP COLUMN updated_at;`

真实升级应编写版本化DDL与回滚步骤，不能仅依赖create_all修改现有列。

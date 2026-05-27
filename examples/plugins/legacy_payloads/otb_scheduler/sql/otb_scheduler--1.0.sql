-- ============================================================================
-- otb_scheduler - 调度与分区管理兼容层
-- pg_cron + pg_partman API兼容实现
-- ============================================================================

-- 创建schema
DROP SCHEMA IF EXISTS otb_scheduler CASCADE;
CREATE SCHEMA otb_scheduler;

-- ============================================================================
-- 1. 定时任务管理 (pg_cron兼容)
-- ============================================================================

-- 任务状态枚举
CREATE TYPE otb_scheduler.job_status AS ENUM (
    'active',
    'inactive',
    'running',
    'failed'
);

-- 定时任务表
CREATE TABLE otb_scheduler.jobs (
    jobid BIGSERIAL PRIMARY KEY,
    schedule TEXT NOT NULL,           -- cron表达式
    command TEXT NOT NULL,            -- SQL命令
    nodename TEXT DEFAULT 'localhost',
    nodeport INTEGER DEFAULT 30004,
    database TEXT DEFAULT current_database(),
    username TEXT DEFAULT current_user,
    active BOOLEAN DEFAULT true,
    jobname TEXT,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) DISTRIBUTE BY REPLICATION;

-- 任务执行日志
CREATE TABLE otb_scheduler.job_run_details (
    runid BIGSERIAL PRIMARY KEY,
    jobid BIGINT NOT NULL,
    job_pid INTEGER,
    database TEXT,
    username TEXT,
    command TEXT,
    status otb_scheduler.job_status,
    return_message TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP
) DISTRIBUTE BY REPLICATION;

CREATE INDEX idx_job_run_details_jobid ON otb_scheduler.job_run_details(jobid);
CREATE INDEX idx_job_run_details_start ON otb_scheduler.job_run_details(start_time);

-- ============================================================================
-- pg_cron兼容函数
-- ============================================================================

-- cron.schedule - 创建定时任务
CREATE OR REPLACE FUNCTION otb_scheduler.schedule(
    p_schedule TEXT,
    p_command TEXT
)
RETURNS BIGINT AS $$
DECLARE
    v_jobid BIGINT;
BEGIN
    INSERT INTO otb_scheduler.jobs (schedule, command)
    VALUES (p_schedule, p_command)
    RETURNING jobid INTO v_jobid;
    
    RAISE NOTICE 'Job % scheduled: % -> %', v_jobid, p_schedule, left(p_command, 50);
    RETURN v_jobid;
END;
$$ LANGUAGE plpgsql;

-- cron.schedule with job name
CREATE OR REPLACE FUNCTION otb_scheduler.schedule(
    p_job_name TEXT,
    p_schedule TEXT,
    p_command TEXT
)
RETURNS BIGINT AS $$
DECLARE
    v_jobid BIGINT;
    v_existing BIGINT;
BEGIN
    -- 检查是否存在同名任务
    SELECT jobid INTO v_existing 
    FROM otb_scheduler.jobs 
    WHERE jobname = p_job_name AND active = true;
    
    IF v_existing IS NOT NULL THEN
        RAISE WARNING 'Job "%" already exists (id: %). Creating new job with same name.', p_job_name, v_existing;
    END IF;
    
    INSERT INTO otb_scheduler.jobs (jobname, schedule, command)
    VALUES (p_job_name, p_schedule, p_command)
    RETURNING jobid INTO v_jobid;
    
    RAISE NOTICE 'Job "%" (id: %) scheduled', p_job_name, v_jobid;
    RETURN v_jobid;
END;
$$ LANGUAGE plpgsql;

-- cron.unschedule - 删除定时任务
CREATE OR REPLACE FUNCTION otb_scheduler.unschedule(
    p_jobid BIGINT
)
RETURNS BOOLEAN AS $$
DECLARE
    v_deleted BOOLEAN;
BEGIN
    DELETE FROM otb_scheduler.jobs WHERE jobid = p_jobid;
    v_deleted := FOUND;
    
    IF v_deleted THEN
        RAISE NOTICE 'Job % unscheduled', p_jobid;
    ELSE
        RAISE WARNING 'Job % not found', p_jobid;
    END IF;
    
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

-- cron.unschedule by name
CREATE OR REPLACE FUNCTION otb_scheduler.unschedule(
    p_job_name TEXT
)
RETURNS BOOLEAN AS $$
DECLARE
    v_deleted BOOLEAN;
BEGIN
    DELETE FROM otb_scheduler.jobs WHERE jobname = p_job_name;
    v_deleted := FOUND;
    
    IF v_deleted THEN
        RAISE NOTICE 'Job "%" unscheduled', p_job_name;
    ELSE
        RAISE WARNING 'Job "%" not found', p_job_name;
    END IF;
    
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

-- 启用/禁用任务
CREATE OR REPLACE FUNCTION otb_scheduler.alter_job(
    p_jobid BIGINT,
    p_active BOOLEAN DEFAULT NULL,
    p_schedule TEXT DEFAULT NULL,
    p_command TEXT DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    UPDATE otb_scheduler.jobs
    SET active = COALESCE(p_active, active),
        schedule = COALESCE(p_schedule, schedule),
        command = COALESCE(p_command, command),
        updated_at = CURRENT_TIMESTAMP
    WHERE jobid = p_jobid;
    
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Job % not found', p_jobid;
    END IF;
    
    RAISE NOTICE 'Job % updated', p_jobid;
END;
$$ LANGUAGE plpgsql;

-- 立即执行任务
CREATE OR REPLACE FUNCTION otb_scheduler.run_job(
    p_jobid BIGINT
)
RETURNS BIGINT AS $$
DECLARE
    v_job RECORD;
    v_runid BIGINT;
    v_start_time TIMESTAMP;
    v_end_time TIMESTAMP;
    v_status otb_scheduler.job_status;
    v_message TEXT;
BEGIN
    -- 获取任务信息
    SELECT * INTO v_job FROM otb_scheduler.jobs WHERE jobid = p_jobid;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Job % not found', p_jobid;
    END IF;
    
    v_start_time := clock_timestamp();
    
    BEGIN
        -- 执行命令
        EXECUTE v_job.command;
        v_status := 'active';
        v_message := 'Success';
    EXCEPTION WHEN OTHERS THEN
        v_status := 'failed';
        v_message := SQLERRM;
    END;
    
    v_end_time := clock_timestamp();
    
    -- 记录执行日志
    INSERT INTO otb_scheduler.job_run_details (
        jobid, database, username, command, status, return_message, start_time, end_time
    ) VALUES (
        p_jobid, v_job.database, v_job.username, v_job.command, v_status, v_message, v_start_time, v_end_time
    ) RETURNING runid INTO v_runid;
    
    RAISE NOTICE 'Job % executed: % (% ms)', p_jobid, v_status, 
                 EXTRACT(MILLISECONDS FROM (v_end_time - v_start_time));
    
    RETURN v_runid;
END;
$$ LANGUAGE plpgsql;

-- 查看任务列表（pg_cron兼容视图）
CREATE OR REPLACE VIEW otb_scheduler.job AS
SELECT 
    jobid,
    schedule,
    command,
    nodename,
    nodeport,
    database,
    username,
    active,
    jobname
FROM otb_scheduler.jobs;

-- 查看任务执行历史
CREATE OR REPLACE VIEW otb_scheduler.job_run_details_view AS
SELECT 
    r.runid,
    r.jobid,
    j.jobname,
    r.database,
    r.username,
    r.command,
    r.status,
    r.return_message,
    r.start_time,
    r.end_time,
    EXTRACT(EPOCH FROM (r.end_time - r.start_time)) AS duration_seconds
FROM otb_scheduler.job_run_details r
LEFT JOIN otb_scheduler.jobs j ON r.jobid = j.jobid
ORDER BY r.start_time DESC;

-- ============================================================================
-- 2. 分区管理 (pg_partman兼容)
-- ============================================================================

-- 分区配置表
CREATE TABLE otb_scheduler.part_config (
    parent_table TEXT PRIMARY KEY,
    control TEXT NOT NULL,                    -- 分区键列
    partition_type TEXT DEFAULT 'range',      -- range, list
    partition_interval TEXT NOT NULL,         -- 分区间隔
    premake INTEGER DEFAULT 4,                -- 预创建分区数
    retention TEXT,                           -- 保留策略
    retention_keep_table BOOLEAN DEFAULT true,
    datetime_string TEXT DEFAULT 'YYYYMMDD',
    automatic_maintenance TEXT DEFAULT 'on',
    template_table TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) DISTRIBUTE BY REPLICATION;

-- 分区日志
CREATE TABLE otb_scheduler.part_log (
    id BIGSERIAL PRIMARY KEY,
    parent_table TEXT NOT NULL,
    partition_name TEXT NOT NULL,
    action TEXT NOT NULL,  -- created, dropped, attached, detached
    performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) DISTRIBUTE BY REPLICATION;

-- ============================================================================
-- pg_partman兼容函数
-- ============================================================================

-- 创建分区父表配置
CREATE OR REPLACE FUNCTION otb_scheduler.create_parent(
    p_parent_table TEXT,
    p_control TEXT,
    p_type TEXT DEFAULT 'range',
    p_interval TEXT DEFAULT '1 day',
    p_premake INTEGER DEFAULT 4,
    p_start_partition TEXT DEFAULT NULL
)
RETURNS BOOLEAN AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
    v_start_time TIMESTAMP;
    v_partition_name TEXT;
    v_sql TEXT;
    i INTEGER;
BEGIN
    -- 解析schema.table
    IF p_parent_table LIKE '%.%' THEN
        v_schema := split_part(p_parent_table, '.', 1);
        v_table := split_part(p_parent_table, '.', 2);
    ELSE
        v_schema := 'public';
        v_table := p_parent_table;
    END IF;
    
    -- 保存配置
    INSERT INTO otb_scheduler.part_config (
        parent_table, control, partition_type, partition_interval, premake
    ) VALUES (
        p_parent_table, p_control, p_type, p_interval, p_premake
    ) ON CONFLICT (parent_table) DO UPDATE
    SET control = EXCLUDED.control,
        partition_type = EXCLUDED.partition_type,
        partition_interval = EXCLUDED.partition_interval,
        premake = EXCLUDED.premake,
        updated_at = CURRENT_TIMESTAMP;
    
    RAISE NOTICE 'Partition configuration created for %', p_parent_table;
    RAISE NOTICE '  Control column: %', p_control;
    RAISE NOTICE '  Partition type: %', p_type;
    RAISE NOTICE '  Interval: %', p_interval;
    RAISE NOTICE '  Premake: %', p_premake;
    
    RETURN true;
END;
$$ LANGUAGE plpgsql;

-- 运行分区维护
CREATE OR REPLACE FUNCTION otb_scheduler.run_maintenance(
    p_parent_table TEXT DEFAULT NULL,
    p_analyze BOOLEAN DEFAULT true
)
RETURNS INTEGER AS $$
DECLARE
    v_config RECORD;
    v_count INTEGER := 0;
BEGIN
    FOR v_config IN 
        SELECT * FROM otb_scheduler.part_config
        WHERE (p_parent_table IS NULL OR parent_table = p_parent_table)
          AND automatic_maintenance = 'on'
    LOOP
        RAISE NOTICE 'Running maintenance for %', v_config.parent_table;
        
        -- 检查并创建缺失分区
        PERFORM otb_scheduler.create_partitions(v_config.parent_table);
        
        -- 检查并删除过期分区
        IF v_config.retention IS NOT NULL THEN
            PERFORM otb_scheduler.drop_old_partitions(v_config.parent_table);
        END IF;
        
        v_count := v_count + 1;
    END LOOP;
    
    RAISE NOTICE 'Maintenance completed for % tables', v_count;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- 创建分区
CREATE OR REPLACE FUNCTION otb_scheduler.create_partitions(
    p_parent_table TEXT
)
RETURNS INTEGER AS $$
DECLARE
    v_config RECORD;
    v_schema TEXT;
    v_table TEXT;
    v_control TEXT;
    v_current_date DATE;
    v_partition_start DATE;
    v_partition_end DATE;
    v_partition_name TEXT;
    v_sql TEXT;
    v_count INTEGER := 0;
    i INTEGER;
BEGIN
    -- 获取配置
    SELECT * INTO v_config FROM otb_scheduler.part_config WHERE parent_table = p_parent_table;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No configuration found for %', p_parent_table;
    END IF;
    
    -- 解析表名
    IF p_parent_table LIKE '%.%' THEN
        v_schema := split_part(p_parent_table, '.', 1);
        v_table := split_part(p_parent_table, '.', 2);
    ELSE
        v_schema := 'public';
        v_table := p_parent_table;
    END IF;
    
    v_current_date := CURRENT_DATE;
    v_control := v_config.control;
    
    -- 创建预定义数量的分区
    FOR i IN 0..v_config.premake LOOP
        v_partition_start := v_current_date + (i || ' ' || v_config.partition_interval)::interval;
        v_partition_end := v_partition_start + ('1 ' || v_config.partition_interval)::interval;
        v_partition_name := v_table || '_p' || to_char(v_partition_start, 'YYYYMMDD');
        
        -- 检查分区是否已存在
        IF NOT EXISTS (
            SELECT 1 FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = v_schema AND c.relname = v_partition_name
        ) THEN
            -- 创建分区（这里生成DDL，实际执行需要用户手动或通过外部脚本）
            v_sql := format(
                'CREATE TABLE IF NOT EXISTS %I.%I PARTITION OF %I.%I FOR VALUES FROM (%L) TO (%L)',
                v_schema, v_partition_name, v_schema, v_table,
                v_partition_start, v_partition_end
            );
            
            BEGIN
                EXECUTE v_sql;
                v_count := v_count + 1;
                
                -- 记录日志
                INSERT INTO otb_scheduler.part_log (parent_table, partition_name, action)
                VALUES (p_parent_table, v_partition_name, 'created');
                
                RAISE NOTICE 'Created partition: %.%', v_schema, v_partition_name;
            EXCEPTION WHEN OTHERS THEN
                -- 分区可能已存在或父表不是分区表
                RAISE NOTICE 'Skipped: %.% (%)', v_schema, v_partition_name, SQLERRM;
            END;
        END IF;
    END LOOP;
    
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- 删除旧分区
CREATE OR REPLACE FUNCTION otb_scheduler.drop_old_partitions(
    p_parent_table TEXT
)
RETURNS INTEGER AS $$
DECLARE
    v_config RECORD;
    v_count INTEGER := 0;
    v_retention_date TIMESTAMP;
BEGIN
    SELECT * INTO v_config FROM otb_scheduler.part_config WHERE parent_table = p_parent_table;
    IF NOT FOUND OR v_config.retention IS NULL THEN
        RETURN 0;
    END IF;
    
    v_retention_date := CURRENT_TIMESTAMP - v_config.retention::interval;
    
    RAISE NOTICE 'Checking for partitions older than %', v_retention_date;
    
    -- 这里只是模拟，实际删除分区需要更复杂的逻辑
    -- 需要查询pg_inherits获取子分区，然后根据分区范围判断是否过期
    
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- 设置保留策略
CREATE OR REPLACE FUNCTION otb_scheduler.set_retention(
    p_parent_table TEXT,
    p_retention TEXT,
    p_keep_table BOOLEAN DEFAULT false
)
RETURNS VOID AS $$
BEGIN
    UPDATE otb_scheduler.part_config
    SET retention = p_retention,
        retention_keep_table = p_keep_table,
        updated_at = CURRENT_TIMESTAMP
    WHERE parent_table = p_parent_table;
    
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No configuration found for %', p_parent_table;
    END IF;
    
    RAISE NOTICE 'Retention set for %: % (keep_table: %)', p_parent_table, p_retention, p_keep_table;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 3. 辅助函数
-- ============================================================================

-- 解析cron表达式（简化版）
CREATE OR REPLACE FUNCTION otb_scheduler.parse_cron(
    p_cron TEXT
)
RETURNS TABLE(
    minute TEXT,
    hour TEXT,
    day_of_month TEXT,
    month TEXT,
    day_of_week TEXT
) AS $$
DECLARE
    v_parts TEXT[];
BEGIN
    v_parts := string_to_array(p_cron, ' ');
    
    IF array_length(v_parts, 1) < 5 THEN
        RAISE EXCEPTION 'Invalid cron expression: %', p_cron;
    END IF;
    
    minute := v_parts[1];
    hour := v_parts[2];
    day_of_month := v_parts[3];
    month := v_parts[4];
    day_of_week := v_parts[5];
    
    RETURN NEXT;
END;
$$ LANGUAGE plpgsql;

-- 检查cron表达式是否匹配当前时间
CREATE OR REPLACE FUNCTION otb_scheduler.cron_matches_now(
    p_cron TEXT
)
RETURNS BOOLEAN AS $$
DECLARE
    v_cron RECORD;
    v_now TIMESTAMP := CURRENT_TIMESTAMP;
BEGIN
    SELECT * INTO v_cron FROM otb_scheduler.parse_cron(p_cron);
    
    -- 简化检查（只检查分钟和小时）
    IF v_cron.minute != '*' AND v_cron.minute::INTEGER != EXTRACT(MINUTE FROM v_now) THEN
        RETURN false;
    END IF;
    
    IF v_cron.hour != '*' AND v_cron.hour::INTEGER != EXTRACT(HOUR FROM v_now) THEN
        RETURN false;
    END IF;
    
    IF v_cron.day_of_month != '*' AND v_cron.day_of_month::INTEGER != EXTRACT(DAY FROM v_now) THEN
        RETURN false;
    END IF;
    
    IF v_cron.month != '*' AND v_cron.month::INTEGER != EXTRACT(MONTH FROM v_now) THEN
        RETURN false;
    END IF;
    
    RETURN true;
END;
$$ LANGUAGE plpgsql;

-- 获取下次执行时间（简化版）
CREATE OR REPLACE FUNCTION otb_scheduler.get_next_run_time(
    p_cron TEXT,
    p_from TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
RETURNS TIMESTAMP AS $$
DECLARE
    v_cron RECORD;
    v_next TIMESTAMP;
    v_minute INTEGER;
    v_hour INTEGER;
BEGIN
    SELECT * INTO v_cron FROM otb_scheduler.parse_cron(p_cron);
    
    v_minute := CASE WHEN v_cron.minute = '*' THEN 0 ELSE v_cron.minute::INTEGER END;
    v_hour := CASE WHEN v_cron.hour = '*' THEN EXTRACT(HOUR FROM p_from)::INTEGER ELSE v_cron.hour::INTEGER END;
    
    v_next := date_trunc('day', p_from) + (v_hour || ' hours')::interval + (v_minute || ' minutes')::interval;
    
    IF v_next <= p_from THEN
        IF v_cron.hour = '*' THEN
            v_next := v_next + interval '1 hour';
        ELSE
            v_next := v_next + interval '1 day';
        END IF;
    END IF;
    
    RETURN v_next;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 4. 常用预设任务模板
-- ============================================================================

-- 创建定时VACUUM任务
CREATE OR REPLACE FUNCTION otb_scheduler.schedule_vacuum(
    p_table_name TEXT,
    p_schedule TEXT DEFAULT '0 3 * * *'  -- 默认每天凌晨3点
)
RETURNS BIGINT AS $$
DECLARE
    v_command TEXT;
BEGIN
    v_command := format('VACUUM ANALYZE %s', p_table_name);
    RETURN otb_scheduler.schedule(
        'vacuum_' || replace(p_table_name, '.', '_'),
        p_schedule,
        v_command
    );
END;
$$ LANGUAGE plpgsql;

-- 创建定时统计更新任务
CREATE OR REPLACE FUNCTION otb_scheduler.schedule_analyze(
    p_table_name TEXT,
    p_schedule TEXT DEFAULT '0 4 * * *'  -- 默认每天凌晨4点
)
RETURNS BIGINT AS $$
DECLARE
    v_command TEXT;
BEGIN
    v_command := format('ANALYZE %s', p_table_name);
    RETURN otb_scheduler.schedule(
        'analyze_' || replace(p_table_name, '.', '_'),
        p_schedule,
        v_command
    );
END;
$$ LANGUAGE plpgsql;

-- 创建定时清理日志任务
CREATE OR REPLACE FUNCTION otb_scheduler.schedule_cleanup_logs(
    p_days INTEGER DEFAULT 30,
    p_schedule TEXT DEFAULT '0 2 * * 0'  -- 默认每周日凌晨2点
)
RETURNS BIGINT AS $$
DECLARE
    v_command TEXT;
BEGIN
    v_command := format(
        'DELETE FROM otb_scheduler.job_run_details WHERE start_time < CURRENT_TIMESTAMP - interval ''%s days''',
        p_days
    );
    RETURN otb_scheduler.schedule(
        'cleanup_job_logs',
        p_schedule,
        v_command
    );
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 5. 统计与监控
-- ============================================================================

-- 任务统计视图
CREATE OR REPLACE VIEW otb_scheduler.job_stats AS
SELECT 
    j.jobid,
    j.jobname,
    j.schedule,
    j.active,
    COUNT(r.runid) as total_runs,
    COUNT(CASE WHEN r.status = 'active' THEN 1 END) as successful_runs,
    COUNT(CASE WHEN r.status = 'failed' THEN 1 END) as failed_runs,
    AVG(EXTRACT(EPOCH FROM (r.end_time - r.start_time))) as avg_duration_seconds,
    MAX(r.start_time) as last_run_time,
    MAX(r.end_time) as last_end_time
FROM otb_scheduler.jobs j
LEFT JOIN otb_scheduler.job_run_details r ON j.jobid = r.jobid
GROUP BY j.jobid, j.jobname, j.schedule, j.active;

-- 分区统计视图
CREATE OR REPLACE VIEW otb_scheduler.partition_stats AS
SELECT 
    pc.parent_table,
    pc.control,
    pc.partition_type,
    pc.partition_interval,
    pc.premake,
    pc.retention,
    COUNT(pl.id) as total_operations,
    MAX(pl.performed_at) as last_operation
FROM otb_scheduler.part_config pc
LEFT JOIN otb_scheduler.part_log pl ON pc.parent_table = pl.parent_table
GROUP BY pc.parent_table, pc.control, pc.partition_type, pc.partition_interval, pc.premake, pc.retention;

-- ============================================================================
-- 6. 任务依赖链管理 (增强功能)
-- ============================================================================

-- 任务依赖表
CREATE TABLE otb_scheduler.job_dependencies (
    id BIGSERIAL PRIMARY KEY,
    jobid BIGINT NOT NULL,              -- 当前任务
    depends_on_jobid BIGINT NOT NULL,   -- 依赖的任务
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_dependency UNIQUE (jobid, depends_on_jobid)
) DISTRIBUTE BY REPLICATION;

-- 添加任务依赖
CREATE OR REPLACE FUNCTION otb_scheduler.add_dependency(
    p_jobid BIGINT,
    p_depends_on BIGINT
)
RETURNS BOOLEAN AS $$
DECLARE
    v_cycle_check BIGINT[];
BEGIN
    -- 检查是否会形成循环依赖
    WITH RECURSIVE dep_chain AS (
        SELECT p_depends_on AS jobid, ARRAY[p_jobid, p_depends_on] AS path
        UNION ALL
        SELECT d.depends_on_jobid, dc.path || d.depends_on_jobid
        FROM otb_scheduler.job_dependencies d
        JOIN dep_chain dc ON d.jobid = dc.jobid
        WHERE NOT d.depends_on_jobid = ANY(dc.path)
    )
    SELECT path INTO v_cycle_check
    FROM dep_chain
    WHERE p_jobid = ANY(path) AND jobid != p_jobid
    LIMIT 1;
    
    IF v_cycle_check IS NOT NULL THEN
        RAISE EXCEPTION 'Circular dependency detected: would create cycle %', v_cycle_check;
    END IF;
    
    INSERT INTO otb_scheduler.job_dependencies (jobid, depends_on_jobid)
    VALUES (p_jobid, p_depends_on)
    ON CONFLICT (jobid, depends_on_jobid) DO NOTHING;
    
    RAISE NOTICE 'Job % now depends on job %', p_jobid, p_depends_on;
    RETURN true;
END;
$$ LANGUAGE plpgsql;

-- 移除任务依赖
CREATE OR REPLACE FUNCTION otb_scheduler.remove_dependency(
    p_jobid BIGINT,
    p_depends_on BIGINT
)
RETURNS BOOLEAN AS $$
BEGIN
    DELETE FROM otb_scheduler.job_dependencies
    WHERE jobid = p_jobid AND depends_on_jobid = p_depends_on;
    
    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- 获取任务依赖链
CREATE OR REPLACE FUNCTION otb_scheduler.get_dependencies(
    p_jobid BIGINT
)
RETURNS TABLE(
    level INTEGER,
    jobid BIGINT,
    jobname TEXT,
    schedule TEXT,
    active BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    WITH RECURSIVE dep_tree AS (
        SELECT 0 AS level, j.jobid, j.jobname, j.schedule, j.active
        FROM otb_scheduler.jobs j
        WHERE j.jobid = p_jobid
        
        UNION ALL
        
        SELECT dt.level + 1, j.jobid, j.jobname, j.schedule, j.active
        FROM otb_scheduler.job_dependencies d
        JOIN otb_scheduler.jobs j ON d.depends_on_jobid = j.jobid
        JOIN dep_tree dt ON d.jobid = dt.jobid
        WHERE dt.level < 10  -- 防止无限递归
    )
    SELECT DISTINCT ON (dt.jobid) dt.level, dt.jobid, dt.jobname, dt.schedule, dt.active
    FROM dep_tree dt
    ORDER BY dt.jobid, dt.level;
END;
$$ LANGUAGE plpgsql;

-- 检查依赖是否满足
CREATE OR REPLACE FUNCTION otb_scheduler.check_dependencies_met(
    p_jobid BIGINT
)
RETURNS BOOLEAN AS $$
DECLARE
    v_unmet_count INTEGER;
BEGIN
    -- 检查所有依赖任务是否在最近执行成功
    SELECT COUNT(*) INTO v_unmet_count
    FROM otb_scheduler.job_dependencies d
    WHERE d.jobid = p_jobid
    AND NOT EXISTS (
        SELECT 1 FROM otb_scheduler.job_run_details r
        WHERE r.jobid = d.depends_on_jobid
        AND r.status = 'active'
        AND r.start_time > CURRENT_TIMESTAMP - interval '24 hours'
    );
    
    RETURN v_unmet_count = 0;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 7. 任务重试机制 (增强功能)
-- ============================================================================

-- 添加重试配置列（如果不存在）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'otb_scheduler' 
        AND table_name = 'jobs' 
        AND column_name = 'max_retries'
    ) THEN
        ALTER TABLE otb_scheduler.jobs 
        ADD COLUMN max_retries INTEGER DEFAULT 0,
        ADD COLUMN retry_delay_seconds INTEGER DEFAULT 60,
        ADD COLUMN current_retries INTEGER DEFAULT 0;
    END IF;
END $$;

-- 设置任务重试配置
CREATE OR REPLACE FUNCTION otb_scheduler.set_retry_config(
    p_jobid BIGINT,
    p_max_retries INTEGER DEFAULT 3,
    p_retry_delay_seconds INTEGER DEFAULT 60
)
RETURNS BOOLEAN AS $$
BEGIN
    UPDATE otb_scheduler.jobs
    SET max_retries = p_max_retries,
        retry_delay_seconds = p_retry_delay_seconds,
        current_retries = 0,
        updated_at = CURRENT_TIMESTAMP
    WHERE jobid = p_jobid;
    
    RAISE NOTICE 'Job % retry config: max_retries=%, delay=%s', p_jobid, p_max_retries, p_retry_delay_seconds;
    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- 带重试的任务执行
CREATE OR REPLACE FUNCTION otb_scheduler.run_job_with_retry(
    p_jobid BIGINT
)
RETURNS TABLE(
    attempt INTEGER,
    success BOOLEAN,
    message TEXT
) AS $$
DECLARE
    v_job RECORD;
    v_runid BIGINT;
    v_attempt INTEGER := 1;
    v_success BOOLEAN := false;
    v_error_message TEXT;
BEGIN
    -- 获取任务信息
    SELECT * INTO v_job FROM otb_scheduler.jobs WHERE jobid = p_jobid;
    
    IF NOT FOUND THEN
        RETURN QUERY SELECT 0, false, 'Job not found'::TEXT;
        RETURN;
    END IF;
    
    -- 执行任务（最多重试max_retries次）
    WHILE v_attempt <= COALESCE(v_job.max_retries, 0) + 1 AND NOT v_success LOOP
        BEGIN
            -- 记录执行开始
            INSERT INTO otb_scheduler.job_run_details 
                (jobid, database, username, command, status, start_time)
            VALUES 
                (p_jobid, v_job.database, v_job.username, v_job.command, 'running', CURRENT_TIMESTAMP)
            RETURNING runid INTO v_runid;
            
            -- 执行命令
            EXECUTE v_job.command;
            
            -- 执行成功
            UPDATE otb_scheduler.job_run_details
            SET status = 'active', 
                end_time = CURRENT_TIMESTAMP,
                return_message = 'Success'
            WHERE runid = v_runid;
            
            v_success := true;
            
            RETURN QUERY SELECT v_attempt, true, 'Success'::TEXT;
            
        EXCEPTION WHEN OTHERS THEN
            v_error_message := SQLERRM;
            
            -- 记录失败
            UPDATE otb_scheduler.job_run_details
            SET status = 'failed',
                end_time = CURRENT_TIMESTAMP,
                return_message = v_error_message
            WHERE runid = v_runid;
            
            RETURN QUERY SELECT v_attempt, false, v_error_message;
            
            -- 如果还有重试机会，等待后重试
            IF v_attempt < COALESCE(v_job.max_retries, 0) + 1 THEN
                PERFORM pg_sleep(COALESCE(v_job.retry_delay_seconds, 60)::float / 1000);
            END IF;
            
            v_attempt := v_attempt + 1;
        END;
    END LOOP;
    
    -- 更新重试计数
    UPDATE otb_scheduler.jobs
    SET current_retries = v_attempt - 1,
        updated_at = CURRENT_TIMESTAMP
    WHERE jobid = p_jobid;
    
    RETURN;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 8. 任务组管理 (增强功能)
-- ============================================================================

-- 任务组表
CREATE TABLE otb_scheduler.job_groups (
    group_id BIGSERIAL PRIMARY KEY,
    group_name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) DISTRIBUTE BY REPLICATION;

-- 任务组成员关系
CREATE TABLE otb_scheduler.job_group_members (
    id BIGSERIAL PRIMARY KEY,
    group_id BIGINT NOT NULL,
    jobid BIGINT NOT NULL,
    execution_order INTEGER DEFAULT 0,
    CONSTRAINT unique_group_member UNIQUE (group_id, jobid)
) DISTRIBUTE BY REPLICATION;

-- 创建任务组
CREATE OR REPLACE FUNCTION otb_scheduler.create_job_group(
    p_group_name TEXT,
    p_description TEXT DEFAULT NULL
)
RETURNS BIGINT AS $$
DECLARE
    v_group_id BIGINT;
BEGIN
    INSERT INTO otb_scheduler.job_groups (group_name, description)
    VALUES (p_group_name, p_description)
    RETURNING group_id INTO v_group_id;
    
    RAISE NOTICE 'Job group "%" created with id %', p_group_name, v_group_id;
    RETURN v_group_id;
END;
$$ LANGUAGE plpgsql;

-- 添加任务到组
CREATE OR REPLACE FUNCTION otb_scheduler.add_job_to_group(
    p_group_name TEXT,
    p_jobid BIGINT,
    p_execution_order INTEGER DEFAULT 0
)
RETURNS BOOLEAN AS $$
DECLARE
    v_group_id BIGINT;
BEGIN
    SELECT group_id INTO v_group_id
    FROM otb_scheduler.job_groups
    WHERE group_name = p_group_name;
    
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Job group "%" not found', p_group_name;
    END IF;
    
    INSERT INTO otb_scheduler.job_group_members (group_id, jobid, execution_order)
    VALUES (v_group_id, p_jobid, p_execution_order)
    ON CONFLICT (group_id, jobid) 
    DO UPDATE SET execution_order = p_execution_order;
    
    RETURN true;
END;
$$ LANGUAGE plpgsql;

-- 运行任务组（按顺序执行）
CREATE OR REPLACE FUNCTION otb_scheduler.run_job_group(
    p_group_name TEXT
)
RETURNS TABLE(
    job_order INTEGER,
    jobid BIGINT,
    jobname TEXT,
    success BOOLEAN,
    message TEXT
) AS $$
DECLARE
    v_group_id BIGINT;
    v_job RECORD;
    v_result RECORD;
BEGIN
    SELECT group_id INTO v_group_id
    FROM otb_scheduler.job_groups
    WHERE group_name = p_group_name;
    
    IF NOT FOUND THEN
        RETURN QUERY SELECT 0, 0::BIGINT, 'Group not found'::TEXT, false, 'Group not found'::TEXT;
        RETURN;
    END IF;
    
    FOR v_job IN 
        SELECT m.execution_order, m.jobid, j.jobname
        FROM otb_scheduler.job_group_members m
        JOIN otb_scheduler.jobs j ON m.jobid = j.jobid
        WHERE m.group_id = v_group_id
        ORDER BY m.execution_order
    LOOP
        -- 运行每个任务
        SELECT * INTO v_result
        FROM otb_scheduler.run_job_with_retry(v_job.jobid)
        WHERE success = true
        LIMIT 1;
        
        IF v_result IS NULL THEN
            SELECT * INTO v_result
            FROM otb_scheduler.run_job_with_retry(v_job.jobid)
            ORDER BY attempt DESC
            LIMIT 1;
        END IF;
        
        RETURN QUERY SELECT 
            v_job.execution_order,
            v_job.jobid,
            v_job.jobname,
            COALESCE(v_result.success, false),
            COALESCE(v_result.message, 'Unknown error');
    END LOOP;
    
    RETURN;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 9. Cron表达式解析与验证 (增强功能)
-- ============================================================================

-- 解析cron表达式
CREATE OR REPLACE FUNCTION otb_scheduler.parse_cron(
    p_cron_expr TEXT
)
RETURNS TABLE(
    field TEXT,
    value TEXT,
    description TEXT
) AS $$
DECLARE
    v_parts TEXT[];
    v_field_names TEXT[] := ARRAY['minute', 'hour', 'day_of_month', 'month', 'day_of_week'];
    v_desc TEXT;
    i INTEGER;
BEGIN
    v_parts := string_to_array(trim(p_cron_expr), ' ');
    
    IF array_length(v_parts, 1) != 5 THEN
        RETURN QUERY SELECT 'error'::TEXT, p_cron_expr, 
            format('Invalid cron expression: expected 5 fields, got %s', array_length(v_parts, 1))::TEXT;
        RETURN;
    END IF;
    
    FOR i IN 1..5 LOOP
        -- 简单描述
        IF v_parts[i] = '*' THEN
            v_desc := 'every ' || v_field_names[i];
        ELSIF v_parts[i] ~ '^[0-9]+$' THEN
            v_desc := format('at %s %s', v_parts[i], v_field_names[i]);
        ELSIF v_parts[i] ~ '^[0-9]+-[0-9]+$' THEN
            v_desc := format('from %s', replace(v_parts[i], '-', ' to '));
        ELSIF v_parts[i] ~ '^[*]/[0-9]+$' THEN
            v_desc := format('every %s %ss', split_part(v_parts[i], '/', 2), v_field_names[i]);
        ELSE
            v_desc := v_parts[i];
        END IF;
        
        RETURN QUERY SELECT v_field_names[i], v_parts[i], v_desc;
    END LOOP;
    
    RETURN;
END;
$$ LANGUAGE plpgsql;

-- 验证cron表达式
CREATE OR REPLACE FUNCTION otb_scheduler.validate_cron(
    p_cron_expr TEXT
)
RETURNS BOOLEAN AS $$
DECLARE
    v_parts TEXT[];
    v_minute INTEGER;
    v_hour INTEGER;
    v_dom INTEGER;
    v_month INTEGER;
    v_dow INTEGER;
BEGIN
    v_parts := string_to_array(trim(p_cron_expr), ' ');
    
    IF array_length(v_parts, 1) != 5 THEN
        RETURN false;
    END IF;
    
    -- 验证每个字段（简化验证）
    -- minute: 0-59 or *
    IF v_parts[1] ~ '^([0-5]?[0-9]|[*]|[*/0-9,-]+)$' THEN
        -- OK
    ELSE
        RETURN false;
    END IF;
    
    -- hour: 0-23 or *
    IF v_parts[2] ~ '^([01]?[0-9]|2[0-3]|[*]|[*/0-9,-]+)$' THEN
        -- OK
    ELSE
        RETURN false;
    END IF;
    
    -- day of month: 1-31 or *
    IF v_parts[3] ~ '^([1-9]|[12][0-9]|3[01]|[*]|[*/0-9,-]+)$' THEN
        -- OK
    ELSE
        RETURN false;
    END IF;
    
    -- month: 1-12 or *
    IF v_parts[4] ~ '^([1-9]|1[0-2]|[*]|[*/0-9,-]+)$' THEN
        -- OK
    ELSE
        RETURN false;
    END IF;
    
    -- day of week: 0-7 or *
    IF v_parts[5] ~ '^([0-7]|[*]|[*/0-9,-]+)$' THEN
        -- OK
    ELSE
        RETURN false;
    END IF;
    
    RETURN true;
END;
$$ LANGUAGE plpgsql;

-- 获取下次执行时间（简化实现）
CREATE OR REPLACE FUNCTION otb_scheduler.get_next_run_time(
    p_cron_expr TEXT,
    p_from_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
RETURNS TIMESTAMP AS $$
DECLARE
    v_parts TEXT[];
    v_minute INTEGER;
    v_hour INTEGER;
    v_next TIMESTAMP;
BEGIN
    IF NOT otb_scheduler.validate_cron(p_cron_expr) THEN
        RETURN NULL;
    END IF;
    
    v_parts := string_to_array(trim(p_cron_expr), ' ');
    
    -- 简化实现：只处理简单的固定时间
    IF v_parts[1] ~ '^[0-9]+$' AND v_parts[2] ~ '^[0-9]+$' THEN
        v_minute := v_parts[1]::INTEGER;
        v_hour := v_parts[2]::INTEGER;
        
        v_next := date_trunc('day', p_from_time) + 
                  make_interval(hours => v_hour, mins => v_minute);
        
        IF v_next <= p_from_time THEN
            v_next := v_next + interval '1 day';
        END IF;
        
        RETURN v_next;
    END IF;
    
    -- 对于复杂表达式，返回下一分钟（简化）
    RETURN date_trunc('minute', p_from_time) + interval '1 minute';
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 安装完成提示
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '╔════════════════════════════════════════════════════════════════════╗';
    RAISE NOTICE '║  otb_scheduler 2.0 安装成功！                                      ║';
    RAISE NOTICE '║  pg_cron + pg_partman 兼容层 - 增强版                              ║';
    RAISE NOTICE '╠════════════════════════════════════════════════════════════════════╣';
    RAISE NOTICE '║                                                                    ║';
    RAISE NOTICE '║  pg_cron兼容函数:                                                  ║';
    RAISE NOTICE '║    • otb_scheduler.schedule(schedule, command)                     ║';
    RAISE NOTICE '║    • otb_scheduler.schedule(name, schedule, command)               ║';
    RAISE NOTICE '║    • otb_scheduler.unschedule(jobid) / alter_job() / run_job()     ║';
    RAISE NOTICE '║                                                                    ║';
    RAISE NOTICE '║  pg_partman兼容函数:                                               ║';
    RAISE NOTICE '║    • otb_scheduler.create_parent(table, control, type, interval)   ║';
    RAISE NOTICE '║    • otb_scheduler.run_maintenance(table) / set_retention()        ║';
    RAISE NOTICE '║                                                                    ║';
    RAISE NOTICE '║  任务依赖链 [新增]:                                                ║';
    RAISE NOTICE '║    • otb_scheduler.add_dependency(jobid, depends_on)               ║';
    RAISE NOTICE '║    • otb_scheduler.remove_dependency(jobid, depends_on)            ║';
    RAISE NOTICE '║    • otb_scheduler.get_dependencies(jobid)                         ║';
    RAISE NOTICE '║    • otb_scheduler.check_dependencies_met(jobid)                   ║';
    RAISE NOTICE '║                                                                    ║';
    RAISE NOTICE '║  重试机制 [新增]:                                                  ║';
    RAISE NOTICE '║    • otb_scheduler.set_retry_config(jobid, max_retries, delay)     ║';
    RAISE NOTICE '║    • otb_scheduler.run_job_with_retry(jobid)                       ║';
    RAISE NOTICE '║                                                                    ║';
    RAISE NOTICE '║  任务组 [新增]:                                                    ║';
    RAISE NOTICE '║    • otb_scheduler.create_job_group(name, description)             ║';
    RAISE NOTICE '║    • otb_scheduler.add_job_to_group(group, jobid, order)           ║';
    RAISE NOTICE '║    • otb_scheduler.run_job_group(group_name)                       ║';
    RAISE NOTICE '║                                                                    ║';
    RAISE NOTICE '║  Cron解析 [新增]:                                                  ║';
    RAISE NOTICE '║    • otb_scheduler.parse_cron(expr) / validate_cron(expr)          ║';
    RAISE NOTICE '║    • otb_scheduler.get_next_run_time(expr, from_time)              ║';
    RAISE NOTICE '║                                                                    ║';
    RAISE NOTICE '╚════════════════════════════════════════════════════════════════════╝';
    RAISE NOTICE '';
END $$;


-- ============================================================================
-- Version function
-- ============================================================================
CREATE OR REPLACE FUNCTION otb_scheduler.version()
RETURNS TEXT AS $$
BEGIN
    RETURN '1.0.0 - OpenTenBase Scheduler (pg_cron + pg_partman compatible)';
END;
$$ LANGUAGE plpgsql IMMUTABLE;

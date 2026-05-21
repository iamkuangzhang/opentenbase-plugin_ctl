-- 提示：请通过 CREATE EXTENSION 方式加载本文件（已允许直接执行用于测试）
-- \echo 使用 "CREATE EXTENSION otb_timeseries" 加载本文件。 \quit

-- 创建时序扩展的专用 schema
CREATE SCHEMA otb_ts;

-- =================================================================
-- 元数据表
-- =================================================================

-- Hypertable（时序表）注册表
CREATE TABLE otb_ts.hypertables (
    id SERIAL PRIMARY KEY,
    schema_name TEXT NOT NULL,
    table_name TEXT NOT NULL,
    time_column_name TEXT NOT NULL,
    chunk_time_interval INTERVAL NOT NULL,
    partition_column_name TEXT,  -- optional space partitioning column
    created_at TIMESTAMP DEFAULT now(),
    UNIQUE (schema_name, table_name)
) DISTRIBUTE BY REPLICATION;

-- Chunk（分区）注册表
-- 注意: REPLICATION 表不支持外键，改用应用层约束
CREATE TABLE otb_ts.chunks (
    id SERIAL PRIMARY KEY,
    hypertable_id INTEGER NOT NULL,  -- 引用 otb_ts.hypertables(id) 但不用外键
    chunk_schema TEXT NOT NULL,
    chunk_name TEXT NOT NULL,
    range_start TIMESTAMP NOT NULL,
    range_end TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT now(),
    status TEXT DEFAULT 'active',  -- active, compressed, archived
    UNIQUE (chunk_schema, chunk_name)
) DISTRIBUTE BY REPLICATION;

CREATE INDEX idx_chunks_hypertable ON otb_ts.chunks(hypertable_id);
CREATE INDEX idx_chunks_range ON otb_ts.chunks(range_start, range_end);

-- 策略表（Retention/Compression/Refresh）
-- 注意: hypertable_id 可以为 NULL（用于物化视图等非 hypertable 对象）
CREATE TABLE otb_ts.policies (
    id SERIAL PRIMARY KEY,
    hypertable_id INTEGER,  -- 改为可 NULL，物化视图等非 hypertable 对象用 NULL
    policy_type TEXT NOT NULL,  -- retention, compression, refresh
    config JSONB NOT NULL,
    enabled BOOLEAN DEFAULT true,
    last_run TIMESTAMP,
    next_run TIMESTAMP,
    created_at TIMESTAMP DEFAULT now(),
    UNIQUE (hypertable_id, policy_type)
    -- 注意：对于NULL hypertable_id的策略，需在应用层确保唯一性
    -- 或在PG15+使用 UNIQUE NULLS NOT DISTINCT
) DISTRIBUTE BY REPLICATION;

-- 为NULL hypertable_id的策略创建部分唯一索引（物化视图场景）
-- 确保同一view_name不能有重复的refresh策略
CREATE UNIQUE INDEX idx_policies_view_unique 
ON otb_ts.policies ((config->>'view_name'), policy_type) 
WHERE hypertable_id IS NULL;

-- 维护日志表
-- 注意: REPLICATION 表不支持外键
CREATE TABLE otb_ts.maintenance_log (
    id SERIAL PRIMARY KEY,
    operation TEXT NOT NULL,
    hypertable_id INTEGER,  -- 引用 otb_ts.hypertables(id) 但不用外键
    details TEXT,
    status TEXT,  -- success, failed
    started_at TIMESTAMP DEFAULT now(),
    completed_at TIMESTAMP
) DISTRIBUTE BY REPLICATION;

-- =================================================================
-- 核心函数
-- =================================================================

-- 函数: create_hypertable
-- 将普通表转换为时序 Hypertable，并初始化分区
CREATE OR REPLACE FUNCTION otb_ts.create_hypertable(
    relation REGCLASS,
    time_column TEXT,
    chunk_interval INTERVAL DEFAULT '1 day'::interval,
    partition_column NAME DEFAULT NULL,
    number_partitions INT DEFAULT 0
) RETURNS TABLE(
    hypertable_id INT,
    schema_name TEXT,
    table_name TEXT,
    created BOOLEAN
) AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
    v_hypertable_id INT;
    v_sql TEXT;
    v_first_chunk_start TIMESTAMP;
    v_first_chunk_end TIMESTAMP;
BEGIN
    -- 解析 schema 与表名
    SELECT n.nspname, c.relname 
    INTO v_schema, v_table
    FROM pg_class c 
    JOIN pg_namespace n ON c.relnamespace = n.oid 
    WHERE c.oid = relation;
    
    IF v_schema IS NULL THEN
        RAISE EXCEPTION 'Table % does not exist', relation;
    END IF;
    
    -- 参数验证: chunk_interval 必须为正数
    IF chunk_interval <= '0'::interval THEN
        RAISE EXCEPTION 'chunk_interval must be positive, got: %', chunk_interval;
    END IF;
    
    -- 参数验证: number_partitions 必须非负
    IF number_partitions < 0 THEN
        RAISE EXCEPTION 'number_partitions must be non-negative, got: %', number_partitions;
    END IF;
    
    -- 检查是否已是 hypertable
    IF EXISTS (
        SELECT 1
        FROM otb_ts.hypertables h
        WHERE h.schema_name = v_schema AND h.table_name = v_table
    ) THEN
        RAISE EXCEPTION 'Table %.% is already a hypertable', v_schema, v_table;
    END IF;
    
    -- 校验时间列是否存在
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns c
        WHERE c.table_schema = v_schema
          AND c.table_name = v_table
          AND c.column_name = time_column
    ) THEN
        RAISE EXCEPTION 'Column % does not exist in table %.%', 
                        time_column, v_schema, v_table;
    END IF;
    
    -- OpenTenBase多DN环境：确保父表使用REPLICATION分布策略
    BEGIN
        v_sql := format('ALTER TABLE %I.%I DISTRIBUTE BY REPLICATION', v_schema, v_table);
        EXECUTE v_sql;
    EXCEPTION WHEN OTHERS THEN
        -- 表可能已有分布策略，忽略错误
    END;
    
    -- 为时间列创建索引以优化查询（如果不存在）
    -- 使用表继承方式实现分区，无需显式转换表结构
    BEGIN
        -- 安全构造索引名：避免SQL注入和标识符问题
        v_sql := format('CREATE INDEX IF NOT EXISTS %I ON %I.%I (%I DESC)',
                      'idx_' || v_table || '_' || time_column,
                      v_schema, v_table, time_column);
        EXECUTE v_sql;
    EXCEPTION WHEN OTHERS THEN
        -- 索引可能已存在，忽略错误
    END;
    
    -- 注册 hypertable 元数据
    INSERT INTO otb_ts.hypertables (schema_name, table_name, time_column_name, 
                                    chunk_time_interval, partition_column_name)
    VALUES (v_schema, v_table, time_column, chunk_interval, partition_column)
    RETURNING id INTO v_hypertable_id;
    
    -- 创建首批分区（当前时间段 + 未来分区）
    v_first_chunk_start := date_trunc('day', now());
    v_first_chunk_end := v_first_chunk_start + chunk_interval;
    
    -- 预创建 7 个未来分区（按日分区即 1 周）
    FOR i IN 0..6 LOOP
        PERFORM otb_ts._create_chunk(
            v_hypertable_id,
            v_schema,
            v_table,
            time_column,
            v_first_chunk_start + (i * chunk_interval),
            v_first_chunk_end + (i * chunk_interval)
        );
    END LOOP;
    
    -- hypertable创建成功，返回结果
    RETURN QUERY SELECT v_hypertable_id, v_schema, v_table, true;
END;
$$ LANGUAGE plpgsql;

-- 内部函数: _create_chunk
-- 为指定 hypertable 创建一个分区 chunk
CREATE OR REPLACE FUNCTION otb_ts._create_chunk(
    p_hypertable_id INT,
    p_schema TEXT,
    p_table TEXT,
    p_time_column TEXT,
    p_range_start TIMESTAMP,
    p_range_end TIMESTAMP
) RETURNS BOOLEAN AS $$
DECLARE
    v_chunk_name TEXT;
    v_chunk_schema TEXT;
    v_sql TEXT;
    v_exists BOOLEAN;
    v_locator_type "char";
    v_dist_column TEXT;
    v_dist_clause TEXT;
BEGIN
    -- 基于时间范围生成 chunk 名称（包含秒以避免冲突）
    v_chunk_schema := p_schema;
    v_chunk_name := format('%s_chunk_%s', 
                          p_table,
                          to_char(p_range_start, 'YYYY_MM_DD_HH24_MI_SS'));
    
    -- 检查 chunk 是否已存在（避免重复创建）
    SELECT EXISTS(
        SELECT 1 FROM otb_ts.chunks 
        WHERE hypertable_id = p_hypertable_id 
        AND chunk_name = v_chunk_name
    ) INTO v_exists;
    
    IF v_exists THEN
        RETURN false;
    END IF;
    
    -- 继承子表必须和父表保持一致的分布策略，否则 OpenTenBase 会拒绝继承。
    SELECT pc.pclocatortype, a.attname
    INTO v_locator_type, v_dist_column
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pgxc_class pc ON pc.pcrelid = c.oid
    LEFT JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = pc.pcattnum
    WHERE n.nspname = p_schema
      AND c.relname = p_table;

    IF v_locator_type = 'R' OR v_locator_type IS NULL THEN
        v_dist_clause := 'DISTRIBUTE BY REPLICATION';
    ELSIF v_locator_type = 'S' AND v_dist_column IS NOT NULL THEN
        v_dist_clause := format('DISTRIBUTE BY SHARD(%I)', v_dist_column);
    ELSE
        RAISE EXCEPTION 'Unsupported distribution strategy for parent table %.%: locator_type=%',
                        p_schema, p_table, v_locator_type;
    END IF;

    -- OpenTenBase多DN环境：两步创建
    -- 步骤1：按父表实际分布策略创建 chunk
    v_sql := format(
        'CREATE TABLE IF NOT EXISTS %I.%I (LIKE %I.%I INCLUDING ALL) %s',
        v_chunk_schema, v_chunk_name,
        p_schema, p_table,
        v_dist_clause
    );
    
    BEGIN
        EXECUTE v_sql;
        
        -- 步骤2：建立继承关系
        v_sql := format(
            'ALTER TABLE %I.%I INHERIT %I.%I',
            v_chunk_schema, v_chunk_name,
            p_schema, p_table
        );
        EXECUTE v_sql;
        
        -- 步骤3：添加时间范围约束以实现分区剪枝
        v_sql := format(
            'ALTER TABLE %I.%I ADD CONSTRAINT %I_time_range 
             CHECK (%I >= %L::timestamp AND %I < %L::timestamp)',
            v_chunk_schema, v_chunk_name,
            v_chunk_name,
            p_time_column, p_range_start,
            p_time_column, p_range_end
        );
        EXECUTE v_sql;
        
        -- 为分区创建时间列索引（优化查询性能）
        -- 安全构造索引名
        v_sql := format('CREATE INDEX IF NOT EXISTS %I ON %I.%I (%I DESC)',
                       'idx_' || v_chunk_name || '_' || p_time_column,
                       v_chunk_schema, v_chunk_name, p_time_column);
        EXECUTE v_sql;
        
        -- 注册 chunk 元数据
        INSERT INTO otb_ts.chunks (hypertable_id, chunk_schema, chunk_name, 
                                   range_start, range_end, status)
        VALUES (p_hypertable_id, v_chunk_schema, v_chunk_name, 
                p_range_start, p_range_end, 'active');
        
        RETURN true;
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING '创建 chunk % 失败: %', v_chunk_name, SQLERRM;
        RETURN false;
    END;
END;
$$ LANGUAGE plpgsql;

-- 函数: show_chunks
-- 显示指定 hypertable 的所有分区 chunk
CREATE OR REPLACE FUNCTION otb_ts.show_chunks(
    relation REGCLASS
) RETURNS TABLE (
    chunk_schema TEXT,
    chunk_name TEXT,
    range_start TIMESTAMP,
    range_end TIMESTAMP,
    status TEXT,
    is_compressed BOOLEAN  -- 兼容TimescaleDB：是否已压缩
) AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
BEGIN
    SELECT n.nspname, c.relname 
    INTO v_schema, v_table
    FROM pg_class c 
    JOIN pg_namespace n ON c.relnamespace = n.oid 
    WHERE c.oid = relation;
    
    RETURN QUERY
    SELECT 
        ch.chunk_schema, 
        ch.chunk_name, 
        ch.range_start, 
        ch.range_end, 
        ch.status,
        (ch.status = 'compressed')::BOOLEAN AS is_compressed
    FROM otb_ts.chunks ch
    JOIN otb_ts.hypertables h ON ch.hypertable_id = h.id
    WHERE h.schema_name = v_schema AND h.table_name = v_table
    ORDER BY ch.range_start;
END;
$$ LANGUAGE plpgsql;

-- 函数: drop_chunks
-- 删除早于指定时间阈值的分区 chunk
CREATE OR REPLACE FUNCTION otb_ts.drop_chunks(
    relation REGCLASS,
    older_than INTERVAL
) RETURNS SETOF TEXT AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
    v_cutoff TIMESTAMP;
    v_chunk RECORD;
    v_sql TEXT;
BEGIN
    SELECT n.nspname, c.relname 
    INTO v_schema, v_table
    FROM pg_class c 
    JOIN pg_namespace n ON c.relnamespace = n.oid 
    WHERE c.oid = relation;
    
    v_cutoff := now() - older_than;
    
    FOR v_chunk IN 
        SELECT ch.chunk_schema, ch.chunk_name, ch.range_end
        FROM otb_ts.chunks ch
        JOIN otb_ts.hypertables h ON ch.hypertable_id = h.id
        WHERE h.schema_name = v_schema 
        AND h.table_name = v_table
        AND ch.range_end < v_cutoff
        AND ch.status = 'active'
    LOOP
        v_sql := format('DROP TABLE IF EXISTS %I.%I', 
                       v_chunk.chunk_schema, v_chunk.chunk_name);
        EXECUTE v_sql;
        
        DELETE FROM otb_ts.chunks 
        WHERE chunk_schema = v_chunk.chunk_schema 
        AND chunk_name = v_chunk.chunk_name;
        
        RETURN NEXT v_chunk.chunk_name;
    END LOOP;
    
    RETURN;
END;
$$ LANGUAGE plpgsql;

-- 函数: add_dimension
-- 为Hypertable添加额外的分区维度（空间分区）
CREATE OR REPLACE FUNCTION otb_ts.add_dimension(
    hypertable REGCLASS,
    column_name NAME,
    number_partitions INTEGER DEFAULT NULL,
    chunk_time_interval INTERVAL DEFAULT NULL,
    partitioning_func REGPROC DEFAULT NULL,
    if_not_exists BOOLEAN DEFAULT false
) RETURNS TABLE(
    dimension_id INT,
    schema_name TEXT,
    table_name TEXT,
    col_name TEXT,
    created BOOLEAN
) AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
    v_hypertable_id INT;
    v_dimension_exists BOOLEAN;
    v_col_name TEXT;
BEGIN
    v_col_name := column_name::TEXT;
    -- 解析表名
    SELECT n.nspname, c.relname 
    INTO v_schema, v_table
    FROM pg_class c 
    JOIN pg_namespace n ON c.relnamespace = n.oid 
    WHERE c.oid = hypertable;
    
    -- 检查是否为hypertable
    SELECT id INTO v_hypertable_id
    FROM otb_ts.hypertables
    WHERE schema_name = v_schema AND table_name = v_table;
    
    IF v_hypertable_id IS NULL THEN
        RAISE EXCEPTION 'Table %.% is not a hypertable', v_schema, v_table;
    END IF;
    
    -- 检查列是否存在
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = v_schema 
        AND table_name = v_table
        AND information_schema.columns.column_name = v_col_name
    ) THEN
        RAISE EXCEPTION 'Column % does not exist in table %.%', 
                        v_col_name, v_schema, v_table;
    END IF;
    
    -- 检查维度是否已存在
    SELECT partition_column_name IS NOT NULL INTO v_dimension_exists
    FROM otb_ts.hypertables
    WHERE id = v_hypertable_id;
    
    IF v_dimension_exists THEN
        IF if_not_exists THEN
            RAISE NOTICE 'Dimension already exists for hypertable %.%, skipping', v_schema, v_table;
            RETURN QUERY SELECT 0, v_schema, v_table, v_col_name, false;
            RETURN;
        ELSE
            RAISE EXCEPTION 'Hypertable %.% already has a space dimension', v_schema, v_table;
        END IF;
    END IF;
    
    -- 更新hypertable元数据，添加空间分区列
    UPDATE otb_ts.hypertables
    SET partition_column_name = v_col_name
    WHERE id = v_hypertable_id;
    
    RAISE NOTICE 'Added dimension % to hypertable %.%', v_col_name, v_schema, v_table;
    
    RETURN QUERY SELECT v_hypertable_id, v_schema, v_table, v_col_name, true;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION otb_ts.add_dimension IS 
'Add a space partitioning dimension to a hypertable';

-- 函数: set_chunk_time_interval
-- 动态修改Hypertable的chunk时间间隔
CREATE OR REPLACE FUNCTION otb_ts.set_chunk_time_interval(
    hypertable REGCLASS,
    chunk_time_interval INTERVAL,
    dimension_name NAME DEFAULT NULL
) RETURNS VOID AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
    v_hypertable_id INT;
    v_old_interval INTERVAL;
BEGIN
    -- 解析表名
    SELECT n.nspname, c.relname 
    INTO v_schema, v_table
    FROM pg_class c 
    JOIN pg_namespace n ON c.relnamespace = n.oid 
    WHERE c.oid = hypertable;
    
    -- 检查是否为hypertable
    SELECT id, chunk_time_interval INTO v_hypertable_id, v_old_interval
    FROM otb_ts.hypertables
    WHERE schema_name = v_schema AND table_name = v_table;
    
    IF v_hypertable_id IS NULL THEN
        RAISE EXCEPTION 'Table %.% is not a hypertable', v_schema, v_table;
    END IF;
    
    -- 验证新的interval
    IF chunk_time_interval <= '0'::interval THEN
        RAISE EXCEPTION 'chunk_time_interval must be positive, got: %', chunk_time_interval;
    END IF;
    
    -- 更新chunk间隔
    UPDATE otb_ts.hypertables
    SET chunk_time_interval = set_chunk_time_interval.chunk_time_interval
    WHERE id = v_hypertable_id;
    
    RAISE NOTICE 'Changed chunk_time_interval for %.% from % to %', 
                 v_schema, v_table, v_old_interval, chunk_time_interval;
    
    -- 注意：已存在的chunk不受影响，只影响新创建的chunk
    RAISE NOTICE 'Note: Existing chunks are not affected. New chunks will use the new interval.';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION otb_ts.set_chunk_time_interval IS 
'Change the chunk_time_interval for a hypertable (affects future chunks only)';

-- 函数: alter_job
-- 修改后台任务（policy）的配置
CREATE OR REPLACE FUNCTION otb_ts.alter_job(
    job_id INTEGER,
    schedule_interval INTERVAL DEFAULT NULL,
    max_runtime INTERVAL DEFAULT NULL,
    max_retries INTEGER DEFAULT NULL,
    retry_period INTERVAL DEFAULT NULL,
    scheduled BOOLEAN DEFAULT NULL,
    config JSONB DEFAULT NULL,
    next_start TIMESTAMPTZ DEFAULT NULL,
    if_exists BOOLEAN DEFAULT false
) RETURNS TABLE(
    out_job_id INTEGER,
    out_schedule_interval INTERVAL,
    out_max_retries INTEGER,
    out_scheduled BOOLEAN
) AS $$
DECLARE
    v_policy_exists BOOLEAN;
    v_config JSONB;
BEGIN
    -- 检查policy是否存在
    SELECT EXISTS(SELECT 1 FROM otb_ts.policies WHERE id = alter_job.job_id) 
    INTO v_policy_exists;
    
    IF NOT v_policy_exists THEN
        IF if_exists THEN
            RAISE NOTICE 'Job % does not exist, skipping', alter_job.job_id;
            RETURN;
        ELSE
            RAISE EXCEPTION 'Job % does not exist', alter_job.job_id;
        END IF;
    END IF;
    
    -- 获取当前配置
    SELECT policies.config INTO v_config
    FROM otb_ts.policies
    WHERE id = alter_job.job_id;
    
    -- 更新配置（合并新配置）
    IF alter_job.config IS NOT NULL THEN
        v_config := v_config || alter_job.config;
    END IF;
    
    -- 如果提供了schedule_interval，更新config中的相关字段
    IF schedule_interval IS NOT NULL THEN
        v_config := jsonb_set(v_config, '{schedule_interval}', to_jsonb(schedule_interval::TEXT));
    END IF;
    
    -- 更新policy
    UPDATE otb_ts.policies
    SET 
        config = v_config,
        enabled = COALESCE(alter_job.scheduled, enabled),
        next_run = COALESCE(alter_job.next_start, next_run)
    WHERE id = alter_job.job_id;
    
    RAISE NOTICE 'Updated job %', alter_job.job_id;
    
    -- 返回更新后的job信息
    RETURN QUERY 
    SELECT 
        p.id,
        (p.config->>'schedule_interval')::INTERVAL,
        0::INTEGER AS max_retries,
        p.enabled
    FROM otb_ts.policies p
    WHERE p.id = alter_job.job_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION otb_ts.alter_job IS 
'Alter configuration of a background job (compression/retention/refresh policy)';

-- 函数: remove_continuous_aggregate_policy
-- 移除连续聚合的刷新策略
CREATE OR REPLACE FUNCTION otb_ts.remove_continuous_aggregate_policy(
    continuous_aggregate REGCLASS,
    if_exists BOOLEAN DEFAULT false
) RETURNS VOID AS $$
DECLARE
    v_schema TEXT;
    v_view TEXT;
    v_policy_id INT;
BEGIN
    -- 解析视图名
    SELECT n.nspname, c.relname 
    INTO v_schema, v_view
    FROM pg_class c 
    JOIN pg_namespace n ON c.relnamespace = n.oid 
    WHERE c.oid = continuous_aggregate;
    
    -- 查找对应的refresh policy
    SELECT id INTO v_policy_id
    FROM otb_ts.policies
    WHERE policy_type = 'refresh'
    AND config->>'view_name' = v_schema || '.' || v_view;
    
    IF v_policy_id IS NULL THEN
        IF if_exists THEN
            RAISE NOTICE 'No refresh policy found for %.%, skipping', v_schema, v_view;
            RETURN;
        ELSE
            RAISE EXCEPTION 'No refresh policy found for %.%', v_schema, v_view;
        END IF;
    END IF;
    
    -- 删除policy
    DELETE FROM otb_ts.policies WHERE id = v_policy_id;
    
    RAISE NOTICE 'Removed refresh policy for continuous aggregate %.%', v_schema, v_view;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION otb_ts.remove_continuous_aggregate_policy IS 
'Remove the refresh policy from a continuous aggregate';

-- 函数: add_retention_policy
-- 添加自动数据保留策略
CREATE OR REPLACE FUNCTION otb_ts.add_retention_policy(
    relation REGCLASS,
    older_than INTERVAL
) RETURNS INTEGER AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
    v_hypertable_id INT;
    v_policy_id INT;
BEGIN
    SELECT n.nspname, c.relname 
    INTO v_schema, v_table
    FROM pg_class c 
    JOIN pg_namespace n ON c.relnamespace = n.oid 
    WHERE c.oid = relation;
    
    SELECT id INTO v_hypertable_id
    FROM otb_ts.hypertables
    WHERE schema_name = v_schema AND table_name = v_table;
    
    IF v_hypertable_id IS NULL THEN
        RAISE EXCEPTION 'Table %.% is not a hypertable', v_schema, v_table;
    END IF;
    
    INSERT INTO otb_ts.policies (hypertable_id, policy_type, config, enabled)
    VALUES (v_hypertable_id, 'retention', 
            jsonb_build_object('older_than', older_than::text), 
            true)
    ON CONFLICT (hypertable_id, policy_type) 
    DO UPDATE SET config = EXCLUDED.config, enabled = true
    RETURNING id INTO v_policy_id;
    
    RAISE NOTICE 'Retention policy added: drop data older than %', older_than;
    
    RETURN v_policy_id;
END;
$$ LANGUAGE plpgsql;

-- 函数: remove_retention_policy
-- 移除数据保留策略
CREATE OR REPLACE FUNCTION otb_ts.remove_retention_policy(
    relation REGCLASS
) RETURNS BOOLEAN AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
    v_hypertable_id INT;
    v_row_count INT;
BEGIN
    SELECT n.nspname, c.relname 
    INTO v_schema, v_table
    FROM pg_class c 
    JOIN pg_namespace n ON c.relnamespace = n.oid 
    WHERE c.oid = relation;
    
    SELECT id INTO v_hypertable_id
    FROM otb_ts.hypertables
    WHERE schema_name = v_schema AND table_name = v_table;
    
    IF v_hypertable_id IS NULL THEN
        RAISE WARNING 'Table %.% is not a hypertable', v_schema, v_table;
        RETURN false;
    END IF;
    
    DELETE FROM otb_ts.policies
    WHERE hypertable_id = v_hypertable_id AND policy_type = 'retention';
    
    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    
    IF v_row_count = 0 THEN
        RAISE NOTICE 'No retention policy found for %.%', v_schema, v_table;
        RETURN false;
    END IF;
    
    RAISE NOTICE 'Retention policy removed for %.%', v_schema, v_table;
    RETURN true;
END;
$$ LANGUAGE plpgsql;

-- 函数: compress_chunk
-- 将 chunk 标记为已压缩（占位实现，未来可替换为真实压缩）
CREATE OR REPLACE FUNCTION otb_ts.compress_chunk(
    chunk_name REGCLASS
) RETURNS BOOLEAN AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
    v_row_count INT;
BEGIN
    SELECT n.nspname, c.relname 
    INTO v_schema, v_table
    FROM pg_class c 
    JOIN pg_namespace n ON c.relnamespace = n.oid 
    WHERE c.oid = chunk_name;
    
    UPDATE otb_ts.chunks
    SET status = 'compressed'
    WHERE chunk_schema = v_schema AND chunk_name = v_table;
    
    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    
    IF v_row_count = 0 THEN
        RAISE WARNING 'Chunk %.% not found in metadata', v_schema, v_table;
        RETURN false;
    END IF;
    
    RAISE NOTICE 'Chunk %.% marked as compressed (actual compression not yet implemented)', 
                 v_schema, v_table;
    
    RETURN true;
END;
$$ LANGUAGE plpgsql;

-- 函数: decompress_chunk
-- 将 chunk 恢复为 active 状态
CREATE OR REPLACE FUNCTION otb_ts.decompress_chunk(
    chunk_name REGCLASS
) RETURNS BOOLEAN AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
    v_row_count INT;
BEGIN
    SELECT n.nspname, c.relname 
    INTO v_schema, v_table
    FROM pg_class c 
    JOIN pg_namespace n ON c.relnamespace = n.oid 
    WHERE c.oid = chunk_name;
    
    UPDATE otb_ts.chunks
    SET status = 'active'
    WHERE chunk_schema = v_schema AND chunk_name = v_table;
    
    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    
    IF v_row_count = 0 THEN
        RAISE WARNING 'Chunk %.% not found in metadata', v_schema, v_table;
        RETURN false;
    END IF;
    
    RETURN true;
END;
$$ LANGUAGE plpgsql;

-- Function: ensure_chunks
-- 为指定时间范围预创建 chunk，避免运行时分区错误
CREATE OR REPLACE FUNCTION otb_ts.ensure_chunks(
    relation REGCLASS,
    start_time TIMESTAMP,
    end_time TIMESTAMP
) RETURNS INTEGER AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
    v_hypertable_id INT;
    v_time_column TEXT;
    v_chunk_interval INTERVAL;
    v_current_time TIMESTAMP;
    v_chunk_count INT := 0;
BEGIN
    -- 获取 hypertable 信息
    SELECT n.nspname, c.relname 
    INTO v_schema, v_table
    FROM pg_class c 
    JOIN pg_namespace n ON c.relnamespace = n.oid 
    WHERE c.oid = relation;
    
    SELECT id, time_column_name, chunk_time_interval
    INTO v_hypertable_id, v_time_column, v_chunk_interval
    FROM otb_ts.hypertables
    WHERE schema_name = v_schema AND table_name = v_table;
    
    IF v_hypertable_id IS NULL THEN
        RAISE EXCEPTION '表 %.% 不是 hypertable', v_schema, v_table;
    END IF;
    
    -- 死循环防护：验证chunk_interval有效性
    IF v_chunk_interval <= '0'::interval THEN
        RAISE EXCEPTION 'Invalid chunk_interval (must be positive): %', v_chunk_interval;
    END IF;
    
    -- 参数验证：时间范围必须合理
    IF end_time <= start_time THEN
        RAISE EXCEPTION 'end_time must be greater than start_time';
    END IF;
    
    -- 为时间范围创建 chunk（添加最大迭代次数防护）
    v_current_time := date_trunc('day', start_time);
    FOR i IN 1..10000 LOOP  -- 最多10000次迭代，防止死循环
        EXIT WHEN v_current_time >= end_time;
        
        IF otb_ts._create_chunk(
            v_hypertable_id,
            v_schema,
            v_table,
            v_time_column,
            v_current_time,
            v_current_time + v_chunk_interval
        ) THEN
            v_chunk_count := v_chunk_count + 1;
        END IF;
        
        v_current_time := v_current_time + v_chunk_interval;
        
        -- 安全检查：确保时间在前进
        IF v_current_time <= v_current_time - v_chunk_interval THEN
            RAISE EXCEPTION 'Infinite loop detected: chunk_interval is not advancing time';
        END IF;
    END LOOP;
    
    -- 如果达到最大迭代次数，发出警告
    IF v_current_time < end_time THEN
        RAISE WARNING 'Reached maximum iteration limit (10000), some chunks may not be created';
    END IF;
    
    RAISE NOTICE '为时间范围 % 到 % 创建了 % 个 chunks', start_time, end_time, v_chunk_count;
    
    RETURN v_chunk_count;
END;
$$ LANGUAGE plpgsql;

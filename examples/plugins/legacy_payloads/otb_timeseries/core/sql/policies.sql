-- =================================================================
-- 数据保留策略管理 (Retention Policies)
-- =================================================================
--
-- 注意：以下功能已独立为 otb_health 插件：
--   - recommend_partition_strategy()
--   - health_check()
--   - auto_tune_advisor()
--
-- 此文件保留核心的保留策略功能。
-- =================================================================

-- 保留策略表（由 hypertable.sql 创建的 otb_ts.policies 表管理）
-- 此处保留基础的策略管理功能

-- 函数: 添加数据保留策略
CREATE OR REPLACE FUNCTION otb_ts.add_retention_policy(
    hypertable REGCLASS,
    drop_after INTERVAL,
    schedule_interval INTERVAL DEFAULT NULL
) RETURNS INTEGER AS $$
DECLARE
    v_policy_id INTEGER;
    v_hypertable_id INTEGER;
    v_schema TEXT;
    v_table TEXT;
BEGIN
    -- 获取hypertable信息
    SELECT n.nspname, c.relname INTO v_schema, v_table
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE c.oid = hypertable;
    
    -- 获取hypertable ID
    SELECT id INTO v_hypertable_id
    FROM otb_ts.hypertables
    WHERE schema_name = v_schema AND table_name = v_table;
    
    IF v_hypertable_id IS NULL THEN
        RAISE EXCEPTION 'Table % is not a hypertable', hypertable;
    END IF;
    
    -- 删除旧的保留策略（如果存在）
    DELETE FROM otb_ts.policies
    WHERE hypertable_id = v_hypertable_id AND policy_type = 'retention';
    
    -- 插入新策略
    INSERT INTO otb_ts.policies (hypertable_id, policy_type, config, schedule_interval)
    VALUES (
        v_hypertable_id,
        'retention',
        jsonb_build_object('drop_after', drop_after::TEXT),
        COALESCE(schedule_interval, '1 day'::INTERVAL)
    )
    RETURNING policy_id INTO v_policy_id;
    
    RAISE NOTICE 'Retention policy created for %: drop data older than %', hypertable, drop_after;
    
    RETURN v_policy_id;
END;
$$ LANGUAGE plpgsql;

-- 函数: 移除数据保留策略
CREATE OR REPLACE FUNCTION otb_ts.remove_retention_policy(
    hypertable REGCLASS
) RETURNS BOOLEAN AS $$
DECLARE
    v_hypertable_id INTEGER;
    v_schema TEXT;
    v_table TEXT;
BEGIN
    SELECT n.nspname, c.relname INTO v_schema, v_table
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE c.oid = hypertable;
    
    SELECT id INTO v_hypertable_id
    FROM otb_ts.hypertables
    WHERE schema_name = v_schema AND table_name = v_table;
    
    IF v_hypertable_id IS NULL THEN
        RAISE EXCEPTION 'Table % is not a hypertable', hypertable;
    END IF;
    
    DELETE FROM otb_ts.policies
    WHERE hypertable_id = v_hypertable_id AND policy_type = 'retention';
    
    RAISE NOTICE 'Retention policy removed for %', hypertable;
    
    RETURN true;
END;
$$ LANGUAGE plpgsql;

-- 函数: 添加压缩策略
CREATE OR REPLACE FUNCTION otb_ts.add_compression_policy(
    hypertable REGCLASS,
    compress_after INTERVAL,
    schedule_interval INTERVAL DEFAULT NULL
) RETURNS INTEGER AS $$
DECLARE
    v_policy_id INTEGER;
    v_hypertable_id INTEGER;
    v_schema TEXT;
    v_table TEXT;
BEGIN
    SELECT n.nspname, c.relname INTO v_schema, v_table
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE c.oid = hypertable;
    
    SELECT id INTO v_hypertable_id
    FROM otb_ts.hypertables
    WHERE schema_name = v_schema AND table_name = v_table;
    
    IF v_hypertable_id IS NULL THEN
        RAISE EXCEPTION 'Table % is not a hypertable', hypertable;
    END IF;
    
    DELETE FROM otb_ts.policies
    WHERE hypertable_id = v_hypertable_id AND policy_type = 'compression';
    
    INSERT INTO otb_ts.policies (hypertable_id, policy_type, config, schedule_interval)
    VALUES (
        v_hypertable_id,
        'compression',
        jsonb_build_object('compress_after', compress_after::TEXT),
        COALESCE(schedule_interval, '1 day'::INTERVAL)
    )
    RETURNING policy_id INTO v_policy_id;
    
    RAISE NOTICE 'Compression policy created for %: compress data older than %', hypertable, compress_after;
    
    RETURN v_policy_id;
END;
$$ LANGUAGE plpgsql;

-- 函数: 移除压缩策略
CREATE OR REPLACE FUNCTION otb_ts.remove_compression_policy(
    hypertable REGCLASS
) RETURNS BOOLEAN AS $$
DECLARE
    v_hypertable_id INTEGER;
    v_schema TEXT;
    v_table TEXT;
BEGIN
    SELECT n.nspname, c.relname INTO v_schema, v_table
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE c.oid = hypertable;
    
    SELECT id INTO v_hypertable_id
    FROM otb_ts.hypertables
    WHERE schema_name = v_schema AND table_name = v_table;
    
    IF v_hypertable_id IS NULL THEN
        RAISE EXCEPTION 'Table % is not a hypertable', hypertable;
    END IF;
    
    DELETE FROM otb_ts.policies
    WHERE hypertable_id = v_hypertable_id AND policy_type = 'compression';
    
    RAISE NOTICE 'Compression policy removed for %', hypertable;
    
    RETURN true;
END;
$$ LANGUAGE plpgsql;

-- 函数: 执行保留策略（删除过期数据）
CREATE OR REPLACE FUNCTION otb_ts.apply_retention_policies()
RETURNS INTEGER AS $$
DECLARE
    v_policy RECORD;
    v_count INTEGER := 0;
    v_drop_after INTERVAL;
    v_cutoff TIMESTAMPTZ;
BEGIN
    FOR v_policy IN
        SELECT p.*, ht.schema_name, ht.table_name, ht.time_column_name
        FROM otb_ts.policies p
        JOIN otb_ts.hypertables ht ON p.hypertable_id = ht.id
        WHERE p.policy_type = 'retention'
    LOOP
        v_drop_after := (v_policy.config->>'drop_after')::INTERVAL;
        v_cutoff := now() - v_drop_after;
        
        -- 删除过期的chunk
        PERFORM otb_ts.drop_chunks(
            format('%I.%I', v_policy.schema_name, v_policy.table_name)::REGCLASS,
            v_cutoff
        );
        
        v_count := v_count + 1;
    END LOOP;
    
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- 函数: 查看所有策略
CREATE OR REPLACE FUNCTION otb_ts.show_policies(
    hypertable REGCLASS DEFAULT NULL
) RETURNS TABLE(
    policy_id INTEGER,
    hypertable_name TEXT,
    policy_type TEXT,
    config JSONB,
    schedule_interval INTERVAL,
    created_at TIMESTAMPTZ,
    last_run TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        p.policy_id,
        format('%I.%I', ht.schema_name, ht.table_name),
        p.policy_type,
        p.config,
        p.schedule_interval,
        p.created_at,
        p.last_run
    FROM otb_ts.policies p
    JOIN otb_ts.hypertables ht ON p.hypertable_id = ht.id
    WHERE hypertable IS NULL 
       OR (ht.schema_name || '.' || ht.table_name = hypertable::TEXT);
END;
$$ LANGUAGE plpgsql;

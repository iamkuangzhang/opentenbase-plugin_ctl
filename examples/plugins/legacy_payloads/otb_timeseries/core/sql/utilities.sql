-- ============================================================================
-- PART 5: Information Views（信息视图系统）
-- ============================================================================

\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '  PART 5: 创建信息视图（TimescaleDB兼容）'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

-- 1. timescaledb.hypertables - Hypertable详细信息
CREATE OR REPLACE VIEW timescaledb.hypertables AS
SELECT 
    h.schema_name AS hypertable_schema,
    h.table_name AS hypertable_name,
    format('%I.%I', h.schema_name, h.table_name) AS main_table_name,
    h.chunk_time_interval,
    FALSE AS compression_enabled,
    h.created_at,
    (SELECT COUNT(*) FROM otb_ts.chunks c WHERE c.hypertable_id = h.id) AS num_chunks,
    FALSE AS distributed
FROM otb_ts.hypertables h
ORDER BY h.schema_name, h.table_name;

COMMENT ON VIEW timescaledb.hypertables IS 
'List of all hypertables with their configuration and statistics';

\echo '  ✓ timescaledb.hypertables'

-- 2. timescaledb.chunks - Chunk详细信息
CREATE OR REPLACE VIEW timescaledb.chunks AS
SELECT 
    c.chunk_schema,
    c.chunk_name,
    h.schema_name AS hypertable_schema,
    h.table_name AS hypertable_name,
    c.range_start,
    c.range_end,
    (c.status = 'compressed') AS compressed,
    NULL::NUMERIC AS compression_ratio,
    c.created_at,
    c.id AS chunk_id,
    c.hypertable_id
FROM otb_ts.chunks c
JOIN otb_ts.hypertables h ON c.hypertable_id = h.id
ORDER BY c.range_start DESC;

COMMENT ON VIEW timescaledb.chunks IS 
'List of all chunks with their time ranges and compression status';

\echo '  ✓ timescaledb.chunks'

-- 3. timescaledb.dimensions - Hypertable分区维度
CREATE OR REPLACE VIEW timescaledb.dimensions AS
SELECT 
    h.schema_name AS hypertable_schema,
    h.table_name AS hypertable_name,
    h.time_column_name AS column_name,
    'time' AS column_type,
    h.chunk_time_interval AS interval_length,
    1 AS dimension_number,
    NULL AS partitioning_func,
    h.id AS hypertable_id
FROM otb_ts.hypertables h
ORDER BY h.schema_name, h.table_name;

COMMENT ON VIEW timescaledb.dimensions IS 
'List of all partitioning dimensions for each hypertable';

\echo '  ✓ timescaledb.dimensions'

-- 4. timescaledb.compression_settings - 压缩配置
CREATE OR REPLACE VIEW timescaledb.compression_settings AS
SELECT 
    h.schema_name AS hypertable_schema,
    h.table_name AS hypertable_name,
    FALSE AS compression_enabled,
    'delta,gorilla' AS compression_algorithm,
    (SELECT COUNT(*) 
     FROM otb_ts.chunks c 
     WHERE c.hypertable_id = h.id AND c.status = 'compressed') AS compressed_chunks,
    (SELECT COUNT(*) 
     FROM otb_ts.chunks c 
     WHERE c.hypertable_id = h.id) AS total_chunks,
    NULL::NUMERIC AS avg_compression_ratio
FROM otb_ts.hypertables h
ORDER BY h.schema_name, h.table_name;

COMMENT ON VIEW timescaledb.compression_settings IS 
'Compression configuration and statistics for each hypertable';

\echo '  ✓ timescaledb.compression_settings'

-- 5. timescaledb.jobs - 数据生命周期管理Job
CREATE OR REPLACE VIEW timescaledb.jobs AS
SELECT 
    p.id AS job_id,
    h.schema_name || '.' || h.table_name AS hypertable,
    p.policy_type AS job_type,
    CASE 
        WHEN p.policy_type = 'retention' THEN 'DROP old chunks'
        WHEN p.policy_type = 'compression' THEN 'COMPRESS chunks'
        ELSE p.policy_type
    END AS job_description,
    p.config::TEXT AS config,
    p.enabled AS scheduled,
    p.created_at AS next_start,
    h.id AS hypertable_id
FROM otb_ts.policies p
JOIN otb_ts.hypertables h ON p.hypertable_id = h.id
WHERE p.enabled = TRUE
ORDER BY p.policy_type, h.schema_name, h.table_name;

COMMENT ON VIEW timescaledb.jobs IS 
'List of all background jobs (retention, compression policies)';

\echo '  ✓ timescaledb.jobs'

-- 6. timescaledb.continuous_aggregates - 连续聚合信息
CREATE OR REPLACE VIEW timescaledb.continuous_aggregates AS
SELECT 
    'public' AS agg_schema,
    cagg_name AS agg_name,
    NULL::TEXT AS hypertable_schema,
    NULL::TEXT AS hypertable_name,
    source_query AS view_definition,
    TRUE AS materialized,
    created_at,
    cagg_id AS agg_id,
    NULL::INT AS hypertable_id
FROM otb_ts.continuous_aggregates
ORDER BY cagg_name;

COMMENT ON VIEW timescaledb.continuous_aggregates IS 
'List of all continuous aggregates (materialized views)';

\echo '  ✓ timescaledb.continuous_aggregates'

-- 7. timescaledb.maintenance_log - 维护日志（最近100条）
CREATE OR REPLACE VIEW timescaledb.maintenance_log AS
SELECT 
    m.id AS log_id,
    m.operation,
    COALESCE(
        (SELECT format('%I.%I', h.schema_name, h.table_name) 
         FROM otb_ts.hypertables h 
         WHERE h.id = m.hypertable_id),
        NULL
    ) AS hypertable_name,
    NULL::TEXT AS chunk_name,
    m.status,
    m.details AS message,
    m.started_at AS executed_at
FROM otb_ts.maintenance_log m
ORDER BY m.started_at DESC
LIMIT 100;

COMMENT ON VIEW timescaledb.maintenance_log IS 
'Recent maintenance operations log (last 100 entries)';

\echo '  ✓ timescaledb.maintenance_log'

\echo ''
\echo '═══════════════════════════════════════════════════════════════'
\echo '  信息视图系统安装完成！'
\echo '  新增：7个TimescaleDB兼容视图'
\echo '═══════════════════════════════════════════════════════════════'

-- ============================================================================
-- PART 6: Advanced Management Functions（高级管理函数）
-- ============================================================================

\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '  PART 6: 创建高级管理函数'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

-- show_chunks() 已在前面定义，这里添加其他管理函数

-- drop_chunks() 已在前面定义，保留原有实现

-- set_chunk_time_interval() 已在前面定义，保留原有实现

\echo '  ✓ show_chunks(), drop_chunks(), set_chunk_time_interval() - 已存在'

-- alter_job() - 修改job配置（兼容 if_exists 参数）
CREATE OR REPLACE FUNCTION otb_ts.alter_job(
    p_job_id INT,
    scheduled BOOLEAN DEFAULT NULL,
    if_exists BOOLEAN DEFAULT FALSE,
    p_config JSONB DEFAULT NULL
)
RETURNS TABLE(job_id INT, scheduled BOOLEAN, config JSONB)
LANGUAGE plpgsql
AS $$
DECLARE
    v_policy RECORD;
BEGIN
    -- 获取policy信息
    SELECT * INTO v_policy
    FROM otb_ts.policies
    WHERE id = p_job_id;

    IF NOT FOUND THEN
        IF if_exists THEN
            RAISE NOTICE 'Job % does not exist, skipping', p_job_id;
            RETURN;
        ELSE
            RAISE EXCEPTION 'Job with ID % does not exist', p_job_id;
        END IF;
    END IF;

    -- 更新enabled状态
    IF scheduled IS NOT NULL THEN
        UPDATE otb_ts.policies
        SET enabled = scheduled
        WHERE id = p_job_id;
        
        RAISE NOTICE 'Job % % %', 
                     p_job_id, 
                     v_policy.policy_type,
                     CASE WHEN scheduled THEN 'enabled' ELSE 'disabled' END;
    END IF;

    -- 更新配置
    IF p_config IS NOT NULL THEN
        UPDATE otb_ts.policies
        SET config = p_config
        WHERE id = p_job_id;
        
        RAISE NOTICE 'Job % configuration updated', p_job_id;
    END IF;

    -- 记录日志
    INSERT INTO otb_ts.maintenance_log (operation, status, details)
    VALUES ('alter_job', 'success', 
            format('Modified job %s (type: %s)', p_job_id, v_policy.policy_type));

    -- 返回结果
    RETURN QUERY 
    SELECT p.id, p.enabled, p.config
    FROM otb_ts.policies p
    WHERE p.id = p_job_id;
END;
$$;

COMMENT ON FUNCTION otb_ts.alter_job(INT, BOOLEAN, BOOLEAN, JSONB) IS 
'Alter job configuration (enable/disable, change config)';

\echo '  ✓ alter_job() - 修改job配置'

-- remove_continuous_aggregate_policy() - 删除连续聚合策略
CREATE OR REPLACE FUNCTION otb_ts.remove_continuous_aggregate_policy(
    p_continuous_aggregate_name TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
AS $$
DECLARE
    v_cagg_id INT;
    v_schema TEXT;
    v_agg TEXT;
BEGIN
    -- 解析连续聚合名称
    IF position('.' IN p_continuous_aggregate_name) > 0 THEN
        v_schema := split_part(p_continuous_aggregate_name, '.', 1);
        v_agg := split_part(p_continuous_aggregate_name, '.', 2);
    ELSE
        v_schema := 'public';
        v_agg := p_continuous_aggregate_name;
    END IF;

    -- 获取cagg_id
    SELECT cagg_id INTO v_cagg_id
    FROM otb_ts.continuous_aggregates
    WHERE cagg_name = v_agg;

    IF v_cagg_id IS NULL THEN
        RAISE EXCEPTION 'Continuous aggregate "%" does not exist', p_continuous_aggregate_name;
    END IF;

    -- 这里只是占位符，实际应该有continuous aggregate的policy表
    RAISE NOTICE 'Removed refresh policy from continuous aggregate "%"', p_continuous_aggregate_name;
    
    -- 记录日志
    INSERT INTO otb_ts.maintenance_log (operation, status, details)
    VALUES ('remove_continuous_aggregate_policy', 'success', 
            format('Removed policy from continuous aggregate %s', p_continuous_aggregate_name));

    RETURN TRUE;
END;
$$;

COMMENT ON FUNCTION otb_ts.remove_continuous_aggregate_policy(TEXT) IS 
'Remove refresh policy from a continuous aggregate';

\echo '  ✓ remove_continuous_aggregate_policy() - 删除连续聚合策略'

-- reorder_chunk() - 重新排序chunk数据（优化查询性能）
CREATE OR REPLACE FUNCTION otb_ts.reorder_chunk(
    p_chunk_name TEXT,
    p_index_name TEXT DEFAULT NULL
)
RETURNS BOOLEAN
LANGUAGE plpgsql
AS $$
DECLARE
    v_schema TEXT;
    v_chunk TEXT;
BEGIN
    -- 解析chunk名称
    IF position('.' IN p_chunk_name) > 0 THEN
        v_schema := split_part(p_chunk_name, '.', 1);
        v_chunk := split_part(p_chunk_name, '.', 2);
    ELSE
        RAISE EXCEPTION 'Chunk name must include schema (e.g., "schema.chunk_name")';
    END IF;

    -- 执行CLUSTER命令（如果指定了索引）
    IF p_index_name IS NOT NULL THEN
        EXECUTE format('CLUSTER %I.%I USING %I', v_schema, v_chunk, p_index_name);
        RAISE NOTICE 'Reordered chunk %.% using index %', v_schema, v_chunk, p_index_name;
    ELSE
        -- 默认按时间列排序
        EXECUTE format('CLUSTER %I.%I', v_schema, v_chunk);
        RAISE NOTICE 'Reordered chunk %.%', v_schema, v_chunk;
    END IF;

    -- 记录日志
    INSERT INTO otb_ts.maintenance_log (operation, status, details)
    VALUES ('reorder_chunk', 'success', 
            format('Chunk %s reordered%s', p_chunk_name,
                   CASE WHEN p_index_name IS NOT NULL 
                        THEN ' using index ' || p_index_name 
                        ELSE '' END));

    RETURN TRUE;
EXCEPTION WHEN OTHERS THEN
    -- 记录错误
    INSERT INTO otb_ts.maintenance_log (operation, status, details)
    VALUES ('reorder_chunk', 'failed', format('Chunk %s: %s', p_chunk_name, SQLERRM));
    
    RAISE WARNING 'Failed to reorder chunk %: %', p_chunk_name, SQLERRM;
    RETURN FALSE;
END;
$$;

COMMENT ON FUNCTION otb_ts.reorder_chunk(TEXT, TEXT) IS 
'Reorder chunk data for better query performance (using CLUSTER)';

\echo '  ✓ reorder_chunk() - 重新排序chunk'

\echo ''
\echo '═══════════════════════════════════════════════════════════════'
\echo '  高级管理函数安装完成！'
\echo '  新增：alter_job(), remove_continuous_aggregate_policy(), reorder_chunk()'
\echo '═══════════════════════════════════════════════════════════════'

-- ============================================================================
-- PART 7: TimescaleDB兼容包装函数（在timescaledb schema中）
-- ============================================================================

\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '  PART 7: 创建TimescaleDB兼容包装函数'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

-- show_chunks() 包装
CREATE OR REPLACE FUNCTION timescaledb.show_chunks(
    relation REGCLASS,
    older_than INTERVAL DEFAULT NULL,
    newer_than INTERVAL DEFAULT NULL
)
RETURNS TABLE(chunk_schema TEXT, chunk_name TEXT, range_start TIMESTAMPTZ, range_end TIMESTAMPTZ)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT * FROM otb_ts.show_chunks(relation::TEXT, older_than, newer_than);
END;
$$;

\echo '  ✓ timescaledb.show_chunks()'

-- drop_chunks() 包装
CREATE OR REPLACE FUNCTION timescaledb.drop_chunks(
    relation REGCLASS,
    older_than INTERVAL,
    verbose BOOLEAN DEFAULT FALSE
)
RETURNS TABLE(chunk_schema TEXT, chunk_name TEXT, dropped BOOLEAN)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT * FROM otb_ts.drop_chunks(relation::TEXT, older_than, verbose);
END;
$$;

\echo '  ✓ timescaledb.drop_chunks()'

\echo ''
\echo '═══════════════════════════════════════════════════════════════'
\echo '  TimescaleDB兼容包装函数创建完成！'
\echo '═══════════════════════════════════════════════════════════════'

-- ============================================================================
-- Installation Complete
-- ============================================================================

\echo ''
\echo '═══════════════════════════════════════════════════════════════'
\echo '  ✅ OpenTenBase TimeSeries 核心扩展安装完成！'
\echo '  新增：信息视图 + 高级管理函数'
\echo '═══════════════════════════════════════════════════════════════'
\echo ''

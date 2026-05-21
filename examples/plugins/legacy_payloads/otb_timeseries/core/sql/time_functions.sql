-- =================================================================
-- 第三部分：系统信息与版本管理 (System Information & Versioning)
-- =================================================================

-- 元数据配置表
CREATE TABLE IF NOT EXISTS otb_ts.metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT
) DISTRIBUTE BY REPLICATION;

INSERT INTO otb_ts.metadata VALUES 
    ('version', '1.0.0', 'OpenTenBase TimeSeries Adapter version'),
    ('compatible_with_timescaledb', '2.x', 'Compatible TimescaleDB version'),
    ('adapter_type', 'API-compatible layer', 'Implementation approach'),
    ('based_on', 'PostgreSQL 11 + OpenTenBase', 'Technology stack');

-- 函数: 版本信息
CREATE OR REPLACE FUNCTION otb_ts.version() 
RETURNS TEXT AS $$
    SELECT value FROM otb_ts.metadata WHERE key = 'version';
$$ LANGUAGE SQL STABLE;

-- 函数: 详细版本信息
CREATE OR REPLACE FUNCTION otb_ts.version_info()
RETURNS TABLE(
    component TEXT,
    version TEXT,
    description TEXT
) AS $$
    SELECT key AS component, value AS version, description
    FROM otb_ts.metadata
    ORDER BY key;
$$ LANGUAGE SQL STABLE;

-- =================================================================
-- 第四部分：系统视图 (System Views - timescaledb_information schema)
-- =================================================================

-- 创建 timescaledb_information schema（标准 TimescaleDB 系统视图命名空间）
CREATE SCHEMA IF NOT EXISTS timescaledb_information;

-- 视图: hypertables（用户友好的 Hypertable 信息视图）
CREATE OR REPLACE VIEW timescaledb_information.hypertables AS
SELECT 
    ht.id AS hypertable_id,
    ht.schema_name AS hypertable_schema,
    ht.table_name AS hypertable_name,
    format('%I.%I', ht.schema_name, ht.table_name) AS hypertable_full_name,
    ht.time_column_name,
    ht.chunk_time_interval AS chunk_sizing_interval,
    ht.partition_column_name AS space_column,
    COUNT(c.id) AS num_chunks,
    pg_size_pretty(
        COALESCE(pg_total_relation_size((ht.schema_name || '.' || ht.table_name)::regclass), 0)
    ) AS total_size,
    ht.created_at
FROM otb_ts.hypertables ht
LEFT JOIN otb_ts.chunks c ON c.hypertable_id = ht.id
GROUP BY ht.id, ht.schema_name, ht.table_name, ht.time_column_name, 
         ht.chunk_time_interval, ht.partition_column_name, ht.created_at;

-- 视图: chunks（分区详细信息）
CREATE OR REPLACE VIEW timescaledb_information.chunks AS
SELECT 
    c.id AS chunk_id,
    format('%I.%I', ht.schema_name, ht.table_name) AS hypertable_name,
    ht.schema_name AS hypertable_schema,
    ht.table_name AS hypertable_table,
    c.chunk_schema,
    c.chunk_name,
    format('%I.%I', c.chunk_schema, c.chunk_name) AS chunk_full_name,
    c.range_start,
    c.range_end,
    c.range_end - c.range_start AS range_interval,
    c.status AS compression_status,
    pg_size_pretty(
        COALESCE(pg_total_relation_size((c.chunk_schema || '.' || c.chunk_name)::regclass), 0)
    ) AS chunk_size,
    c.created_at
FROM otb_ts.chunks c
JOIN otb_ts.hypertables ht ON c.hypertable_id = ht.id
ORDER BY ht.schema_name, ht.table_name, c.range_start DESC;

-- 视图: dimensions（分区维度信息）
CREATE OR REPLACE VIEW timescaledb_information.dimensions AS
SELECT 
    ht.id AS hypertable_id,
    format('%I.%I', ht.schema_name, ht.table_name) AS hypertable_name,
    1 AS dimension_number,
    ht.time_column_name AS column_name,
    'Time' AS column_type,
    ht.chunk_time_interval AS time_interval,
    NULL::INTEGER AS num_partitions
FROM otb_ts.hypertables ht
UNION ALL
SELECT 
    ht.id AS hypertable_id,
    format('%I.%I', ht.schema_name, ht.table_name) AS hypertable_name,
    2 AS dimension_number,
    ht.partition_column_name AS column_name,
    'Space' AS column_type,
    NULL::INTERVAL AS time_interval,
    0 AS num_partitions
FROM otb_ts.hypertables ht
WHERE ht.partition_column_name IS NOT NULL;

-- 视图: jobs（策略/作业信息）
CREATE OR REPLACE VIEW timescaledb_information.jobs AS
SELECT 
    p.id AS job_id,
    'user-defined' AS application_name,
    p.policy_type AS schedule_interval,
    '0 seconds'::INTERVAL AS max_runtime,
    0 AS max_retries,
    0 AS retry_period,
    format('%I.%I', ht.schema_name, ht.table_name) AS hypertable_name,
    p.config,
    p.enabled AS scheduled,
    p.last_run AS last_run_started_at,
    NULL::TIMESTAMP AS last_run_finished_at,
    CASE WHEN p.enabled THEN p.next_run ELSE NULL END AS next_scheduled_run,
    p.created_at
FROM otb_ts.policies p
LEFT JOIN otb_ts.hypertables ht ON p.hypertable_id = ht.id;

-- 视图: compression_settings（压缩设置）
CREATE OR REPLACE VIEW timescaledb_information.compression_settings AS
SELECT 
    format('%I.%I', ht.schema_name, ht.table_name) AS hypertable_name,
    ht.time_column_name AS attname,
    'Compression' AS compression_algorithm,
    1 AS orderby_column_index
FROM otb_ts.hypertables ht
WHERE EXISTS (
    SELECT 1 FROM otb_ts.policies p 
    WHERE p.hypertable_id = ht.id AND p.policy_type = 'compression'
);

-- 视图: hypertable_stats（统计摘要）
CREATE OR REPLACE VIEW timescaledb_information.hypertable_stats AS
SELECT 
    format('%I.%I', ht.schema_name, ht.table_name) AS hypertable_name,
    COUNT(c.id) AS num_chunks,
    SUM(CASE WHEN c.status = 'compressed' THEN 1 ELSE 0 END) AS num_compressed_chunks,
    COALESCE(pg_total_relation_size((ht.schema_name || '.' || ht.table_name)::regclass), 0) AS total_size,
    (SELECT COUNT(*) FROM otb_ts.policies p WHERE p.hypertable_id = ht.id) AS num_policies
FROM otb_ts.hypertables ht
LEFT JOIN otb_ts.chunks c ON c.hypertable_id = ht.id
GROUP BY ht.id, ht.schema_name, ht.table_name;

-- 视图: continuous_aggregates（连续聚合信息）
CREATE OR REPLACE VIEW timescaledb_information.continuous_aggregates AS
SELECT 
    mat.schemaname AS view_schema,
    mat.matviewname AS view_name,
    mat.matviewowner AS view_owner,
    format('%I.%I', mat.schemaname, mat.matviewname) AS view_definition,
    NULL::TEXT AS materialization_hypertable_schema,
    NULL::TEXT AS materialization_hypertable_name,
    NULL::TEXT AS direct_view_schema,
    NULL::TEXT AS direct_view_name,
    p.config->>'refresh_interval' AS refresh_interval,
    p.enabled AS materialized_only,
    p.last_run AS last_run_started_at,
    p.next_run AS next_scheduled_run
FROM pg_matviews mat
LEFT JOIN otb_ts.policies p ON p.policy_type = 'refresh' 
    AND p.config->>'view_name' = mat.schemaname || '.' || mat.matviewname
WHERE mat.schemaname NOT IN ('pg_catalog', 'information_schema');

COMMENT ON VIEW timescaledb_information.continuous_aggregates IS 
'Information about continuous aggregates (materialized views with refresh policies)';

-- =================================================================
-- 第五部分：帮助与诊断函数 (Help & Diagnostic Functions)
-- =================================================================

-- 函数: 获取所有可用函数列表
CREATE OR REPLACE FUNCTION otb_ts.get_available_functions()
RETURNS TABLE(
    category TEXT,
    function_name TEXT,
    description TEXT,
    example TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT * FROM (
        -- DDL 管理函数
        SELECT 'DDL Management'::TEXT AS category, 'create_hypertable'::TEXT AS function_name, 
               'Convert a regular table to a hypertable'::TEXT AS description,
               'SELECT create_hypertable(''metrics'', ''ts'', ''1 day'');'::TEXT AS example
        UNION ALL
        SELECT 'DDL Management', 'ensure_chunks', 
               'Pre-create chunks for a time range',
               'SELECT ensure_chunks(''metrics'', now(), now() + interval ''7 days'');'
        UNION ALL
        SELECT 'DDL Management', 'show_chunks', 
               'Show all chunks of a hypertable',
               'SELECT * FROM show_chunks(''metrics'');'
        UNION ALL
        SELECT 'DDL Management', 'drop_chunks', 
               'Drop old chunks based on time',
               'SELECT drop_chunks(''metrics'', interval ''30 days'');'
        UNION ALL
        
        -- 时序查询函数
        SELECT 'Time-Series Queries', 'time_bucket', 
               'Time bucket aggregation',
               'SELECT time_bucket(''1 hour'', ts), AVG(value) FROM metrics GROUP BY 1;'
        UNION ALL
        SELECT 'Time-Series Queries', 'time_bucket_gapfill', 
               'Fill missing time buckets',
               'SELECT time_bucket_gapfill(''5 minutes'', ts), AVG(value) FROM metrics GROUP BY 1;'
        UNION ALL
        SELECT 'Time-Series Queries', 'interpolate', 
               'Linear interpolation for missing values',
               'SELECT interpolate(prev_val, next_val, prev_ts, next_ts, current_ts);'
        UNION ALL
        SELECT 'Time-Series Queries', 'locf', 
               'Last observation carried forward',
               'SELECT locf(value) FROM metrics;'
        UNION ALL
        
        -- 数据管理
        SELECT 'Data Management', 'add_retention_policy', 
               'Add automatic data retention policy',
               'SELECT add_retention_policy(''metrics'', interval ''90 days'');'
        UNION ALL
        SELECT 'Data Management', 'remove_retention_policy', 
               'Remove retention policy',
               'SELECT remove_retention_policy(''metrics'');'
        UNION ALL
        SELECT 'Data Management', 'maintain', 
               'Execute maintenance tasks (retention, compression, etc.)',
               'SELECT maintain();'
        UNION ALL
        
        -- 性能诊断
        SELECT 'Performance & Diagnostics', 'explain_pruning', 
               'Explain partition pruning for a query',
               'SELECT * FROM explain_pruning(''SELECT * FROM metrics WHERE ts > now() - interval ''''1 day'''''' '');'
        UNION ALL
        SELECT 'Performance & Diagnostics', 'verify_indexes', 
               'Verify if necessary indexes exist',
               'SELECT * FROM verify_indexes(''metrics'');'
        UNION ALL
        SELECT 'Performance & Diagnostics', 'approximate_row_count', 
               'Fast approximate row count',
               'SELECT approximate_row_count(''metrics'');'
    ) AS funcs
    ORDER BY category, function_name;
END;
$$ LANGUAGE plpgsql;

-- 函数: show_functions (别名，为了兼容性)
CREATE OR REPLACE FUNCTION otb_ts.show_functions()
RETURNS TABLE(
    category TEXT,
    function_name TEXT,
    description TEXT,
    example TEXT
) AS $$
    SELECT * FROM otb_ts.get_available_functions();
$$ LANGUAGE SQL;

-- 函数: 获取 Hypertable 大小（标准 TimescaleDB 函数）
CREATE OR REPLACE FUNCTION otb_ts.hypertable_size(relation REGCLASS)
RETURNS BIGINT AS $$
    SELECT pg_total_relation_size(relation);
$$ LANGUAGE SQL STABLE;

-- 函数: 获取 Hypertable 详细大小
CREATE OR REPLACE FUNCTION otb_ts.hypertable_detailed_size(relation REGCLASS)
RETURNS TABLE(
    table_bytes BIGINT,
    index_bytes BIGINT,
    toast_bytes BIGINT,
    total_bytes BIGINT
) AS $$
    SELECT 
        pg_relation_size(relation) AS table_bytes,
        pg_indexes_size(relation) AS index_bytes,
        pg_total_relation_size(relation) - pg_relation_size(relation) - pg_indexes_size(relation) AS toast_bytes,
        pg_total_relation_size(relation) AS total_bytes;
$$ LANGUAGE SQL STABLE;

-- 函数: 获取所有 chunks 的详细大小
CREATE OR REPLACE FUNCTION otb_ts.chunks_detailed_size(relation REGCLASS)
RETURNS TABLE(
    chunk_schema TEXT,
    chunk_name TEXT,
    table_bytes BIGINT,
    index_bytes BIGINT,
    toast_bytes BIGINT,
    total_bytes BIGINT,
    table_size TEXT,      -- 别名：兼容测试
    index_size TEXT,      -- 别名：兼容测试
    total_size TEXT
) AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
BEGIN
    SELECT n.nspname, c.relname INTO v_schema, v_table
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE c.oid = relation;
    
    RETURN QUERY
    SELECT 
        ch.chunk_schema,
        ch.chunk_name,
        pg_relation_size((ch.chunk_schema || '.' || ch.chunk_name)::regclass) AS table_bytes,
        pg_indexes_size((ch.chunk_schema || '.' || ch.chunk_name)::regclass) AS index_bytes,
        pg_total_relation_size((ch.chunk_schema || '.' || ch.chunk_name)::regclass) - 
            pg_relation_size((ch.chunk_schema || '.' || ch.chunk_name)::regclass) - 
            pg_indexes_size((ch.chunk_schema || '.' || ch.chunk_name)::regclass) AS toast_bytes,
        pg_total_relation_size((ch.chunk_schema || '.' || ch.chunk_name)::regclass) AS total_bytes,
        pg_size_pretty(pg_relation_size((ch.chunk_schema || '.' || ch.chunk_name)::regclass)) AS table_size,
        pg_size_pretty(pg_indexes_size((ch.chunk_schema || '.' || ch.chunk_name)::regclass)) AS index_size,
        pg_size_pretty(pg_total_relation_size((ch.chunk_schema || '.' || ch.chunk_name)::regclass)) AS total_size
    FROM otb_ts.chunks ch
    JOIN otb_ts.hypertables ht ON ch.hypertable_id = ht.id
    WHERE ht.schema_name = v_schema AND ht.table_name = v_table
      AND EXISTS(SELECT 1 FROM pg_class pc 
                 JOIN pg_namespace pn ON pc.relnamespace = pn.oid 
                 WHERE pn.nspname = ch.chunk_schema AND pc.relname = ch.chunk_name)
    ORDER BY ch.range_start DESC;
END;
$$ LANGUAGE plpgsql;

-- =================================================================
-- 第六部分：高级统计分析功能 (Advanced Analytics)
-- =================================================================

-- 注意：数据质量检查功能已独立为 otb_health 插件：
--   - check_time_gaps() → otb_health.check_time_gaps()
--   - check_duplicates() → otb_health.check_duplicates()
--   - check_nulls() → otb_health.check_nulls()
--   - health_check() → otb_health.health_check()

-- 函数: 降采样 (Downsampling) - 核心时序功能，保留
CREATE OR REPLACE FUNCTION otb_ts.downsample(
    source_table REGCLASS,
    target_table TEXT,
    bucket_width INTERVAL,
    agg_columns TEXT DEFAULT 'AVG(temperature) as avg_temp, MAX(humidity) as max_humidity',
    group_columns TEXT DEFAULT 'device_id'
) RETURNS BIGINT AS $$
DECLARE
    v_sql TEXT;
    v_row_count BIGINT;
    v_group_by TEXT;
    v_target_schema TEXT;
    v_target_name TEXT;
BEGIN
    -- 解析目标表的schema和表名
    IF target_table LIKE '%.%' THEN
        v_target_schema := split_part(target_table, '.', 1);
        v_target_name := split_part(target_table, '.', 2);
    ELSE
        v_target_schema := 'public';
        v_target_name := target_table;
    END IF;
    
    -- 构建GROUP BY子句
    v_group_by := 'time';
    IF group_columns IS NOT NULL AND length(group_columns) > 0 THEN
        v_group_by := v_group_by || ', ' || group_columns;
    END IF;
    
    -- 检查目标表是否存在，如果存在则删除
    EXECUTE format(
        'DROP TABLE IF EXISTS %I.%I CASCADE',
        v_target_schema, v_target_name
    );
    
    -- 使用CREATE TABLE AS SELECT创建降采样表
    v_sql := format(
        'CREATE TABLE %I.%I 
         DISTRIBUTE BY REPLICATION
         AS SELECT 
             time_bucket(%L, time) AS time,
             %s%s
         FROM %s
         GROUP BY %s',
        v_target_schema, v_target_name,
        bucket_width,
        CASE WHEN group_columns IS NOT NULL AND length(group_columns) > 0 
             THEN group_columns || ', ' 
             ELSE '' 
        END,
        agg_columns,
        source_table,
        v_group_by
    );
    
    EXECUTE v_sql;
    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    
    RETURN v_row_count;
END;
$$ LANGUAGE plpgsql;

-- 函数: JSON 导出 (TIMESTAMP 版本)
CREATE OR REPLACE FUNCTION otb_ts.export_to_json(
    table_name REGCLASS,
    time_column TEXT DEFAULT 'ts',
    start_time TIMESTAMP DEFAULT NULL,
    end_time TIMESTAMP DEFAULT NULL,
    row_limit INT DEFAULT 1000
) RETURNS JSON AS $$
DECLARE
    v_sql TEXT;
    v_result JSON;
BEGIN
    v_sql := format(
        'SELECT json_agg(row_to_json(t)) FROM (
            SELECT * FROM %s 
            WHERE 1=1 %s %s
            ORDER BY %I DESC
            LIMIT %s
        ) t',
        table_name,
        CASE WHEN start_time IS NOT NULL THEN format('AND %I >= %L', time_column, start_time) ELSE '' END,
        CASE WHEN end_time IS NOT NULL THEN format('AND %I <= %L', time_column, end_time) ELSE '' END,
        time_column,
        row_limit
    );
    
    EXECUTE v_sql INTO v_result;
    RETURN v_result;
END;
$$ LANGUAGE plpgsql;

-- 函数: JSON 导出 (TIMESTAMPTZ 版本 - 重载)
CREATE OR REPLACE FUNCTION otb_ts.export_to_json(
    table_name REGCLASS,
    time_column TEXT,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    row_limit INT DEFAULT 1000
) RETURNS JSON AS $$
BEGIN
    -- 转换为 TIMESTAMP 后调用原函数
    RETURN otb_ts.export_to_json(
        table_name,
        time_column,
        start_time::TIMESTAMP,
        end_time::TIMESTAMP,
        row_limit
    );
END;
$$ LANGUAGE plpgsql;

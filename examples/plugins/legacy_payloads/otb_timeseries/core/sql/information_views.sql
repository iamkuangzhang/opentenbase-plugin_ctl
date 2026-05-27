-- ============================================================================
-- OpenTenBase TimeSeries - Information Views（信息视图）
-- TimescaleDB兼容的系统信息视图
-- ============================================================================

\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '  创建 TimescaleDB 兼容信息视图'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo ''

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
\echo ''

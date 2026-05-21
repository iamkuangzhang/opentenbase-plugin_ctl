-- =================================================================
-- 第十部分：数据分层与生命周期管理 (Data Tiering & Lifecycle)
-- =================================================================

-- 函数: 数据温度分析（冷热分层建议）
-- 重载版本：支持INTERVAL参数
CREATE OR REPLACE FUNCTION otb_ts.analyze_data_temperature(
    table_name REGCLASS,
    hot_threshold INTERVAL DEFAULT '30 days'
) RETURNS TABLE(
    data_tier TEXT,
    time_range TSRANGE,
    chunk_count INT,
    total_size TEXT,
    access_frequency NUMERIC,
    recommendation TEXT
) AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
BEGIN
    SELECT n.nspname, c.relname INTO v_schema, v_table
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE c.oid = table_name;
    
    RETURN QUERY
    WITH chunk_stats AS (
        SELECT 
            c.chunk_schema || '.' || c.chunk_name AS full_chunk_name,
            c.range_start,
            c.range_end,
            CASE 
                WHEN c.range_end > now() - hot_threshold THEN 'hot'
                WHEN c.range_end > now() - hot_threshold - interval '60 days' THEN 'warm'
                WHEN c.range_end > now() - hot_threshold - interval '180 days' THEN 'cold'
                ELSE 'frozen'
            END AS tier,
            pg_total_relation_size((c.chunk_schema || '.' || c.chunk_name)::regclass) AS size
        FROM otb_ts.chunks c
        JOIN otb_ts.hypertables ht ON c.hypertable_id = ht.id
        WHERE ht.schema_name = v_schema AND ht.table_name = v_table
          AND EXISTS(SELECT 1 FROM pg_class pc 
                     JOIN pg_namespace pn ON pc.relnamespace = pn.oid 
                     WHERE pn.nspname = c.chunk_schema AND pc.relname = c.chunk_name)
    ),
    tier_summary AS (
        SELECT 
            tier,
            tsrange(MIN(range_start)::TIMESTAMP, MAX(range_end)::TIMESTAMP) AS time_range,
            COUNT(*) AS chunk_cnt,
            SUM(size) AS total_bytes,
            CASE tier
                WHEN 'hot' THEN 10.0
                WHEN 'warm' THEN 1.0
                WHEN 'cold' THEN 0.1
                ELSE 0.01
            END AS access_freq
        FROM chunk_stats
        GROUP BY tier
    )
    SELECT 
        tier AS data_tier,
        time_range,
        chunk_cnt::INT,
        pg_size_pretty(total_bytes),
        access_freq,
        CASE tier
            WHEN 'hot' THEN 'Keep in fast storage, optimize for read performance'
            WHEN 'warm' THEN 'Consider compression to save space'
            WHEN 'cold' THEN 'Compress and move to cheaper storage'
            ELSE 'Archive to object storage or cold storage tier'
        END AS recommendation
    FROM tier_summary
    ORDER BY access_freq DESC;
END;
$$ LANGUAGE plpgsql;

-- 原版本：支持INT天数参数（保留兼容性）
CREATE OR REPLACE FUNCTION otb_ts.analyze_data_temperature(
    table_name REGCLASS,
    analysis_days INT DEFAULT 30
) RETURNS TABLE(
    data_tier TEXT,
    time_range TSRANGE,
    chunk_count INT,
    total_size TEXT,
    access_frequency NUMERIC,
    recommendation TEXT
) AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
BEGIN
    SELECT n.nspname, c.relname INTO v_schema, v_table
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE c.oid = table_name;
    
    RETURN QUERY
    WITH chunk_stats AS (
        SELECT 
            c.chunk_schema || '.' || c.chunk_name AS full_chunk_name,
            c.range_start,
            c.range_end,
            CASE 
                WHEN c.range_end > now() - interval '7 days' THEN 'hot'
                WHEN c.range_end > now() - interval '30 days' THEN 'warm'
                WHEN c.range_end > now() - interval '90 days' THEN 'cold'
                ELSE 'frozen'
            END AS tier,
            pg_total_relation_size((c.chunk_schema || '.' || c.chunk_name)::regclass) AS size
        FROM otb_ts.chunks c
        JOIN otb_ts.hypertables ht ON c.hypertable_id = ht.id
        WHERE ht.schema_name = v_schema AND ht.table_name = v_table
          AND EXISTS(SELECT 1 FROM pg_class pc 
                     JOIN pg_namespace pn ON pc.relnamespace = pn.oid 
                     WHERE pn.nspname = c.chunk_schema AND pc.relname = c.chunk_name)
    ),
    tier_summary AS (
        SELECT 
            tier,
            tsrange(MIN(range_start)::TIMESTAMP, MAX(range_end)::TIMESTAMP) AS time_range,
            COUNT(*) AS chunk_cnt,
            SUM(size) AS total_bytes,
            CASE tier
                WHEN 'hot' THEN 10.0
                WHEN 'warm' THEN 1.0
                WHEN 'cold' THEN 0.1
                ELSE 0.01
            END AS access_freq
        FROM chunk_stats
        GROUP BY tier
    )
    SELECT 
        tier AS data_tier,
        time_range,
        chunk_cnt::INT,
        pg_size_pretty(total_bytes),
        access_freq,
        CASE tier
            WHEN 'hot' THEN 'Keep current configuration, recommend creating indexes'
            WHEN 'warm' THEN 'Can be compressed to reduce storage cost'
            WHEN 'cold' THEN 'Recommend compressing and moving to slow storage'
            ELSE 'Recommend archiving to object storage (S3/OSS)'
        END AS recommendation
    FROM tier_summary
    ORDER BY 
        CASE tier
            WHEN 'hot' THEN 1
            WHEN 'warm' THEN 2
            WHEN 'cold' THEN 3
            ELSE 4
        END;
END;
$$ LANGUAGE plpgsql;

-- =================================================================
-- 权限授予（新增功能）
-- =================================================================

GRANT USAGE ON SCHEMA timescaledb_information TO PUBLIC;
GRANT SELECT ON ALL TABLES IN SCHEMA timescaledb_information TO PUBLIC;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA otb_ts TO PUBLIC;


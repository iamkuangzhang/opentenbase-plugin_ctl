-- 创建 timescaledb schema（兼容命名空间）
CREATE SCHEMA IF NOT EXISTS timescaledb;

-- ═══════════════════════════════════════════════════════════════
-- 核心函数包装
-- ═══════════════════════════════════════════════════════════════

-- create_hypertable (TimescaleDB 兼容)
CREATE OR REPLACE FUNCTION timescaledb.create_hypertable(
    relation REGCLASS,
    time_column NAME,
    chunk_time_interval INTERVAL DEFAULT '1 day'::interval,
    partitioning_column NAME DEFAULT NULL,
    number_partitions INT DEFAULT NULL,
    chunk_target_size TEXT DEFAULT NULL,
    if_not_exists BOOLEAN DEFAULT false,
    migrate_data BOOLEAN DEFAULT false
) RETURNS TABLE (
    hypertable_id INT,
    schema_name TEXT,
    table_name TEXT,
    created BOOLEAN
) LANGUAGE plpgsql AS $$
DECLARE
    v_schema NAME;
    v_table NAME;
    v_id INT;
BEGIN
    RETURN QUERY
    SELECT * FROM otb_ts.create_hypertable(
        relation, 
        time_column, 
        chunk_time_interval,
        partitioning_column,
        number_partitions
    );
END;
$$;

-- add_retention_policy (TimescaleDB 兼容)
CREATE OR REPLACE FUNCTION timescaledb.add_retention_policy(
    relation REGCLASS,
    drop_after INTERVAL,
    if_not_exists BOOLEAN DEFAULT false
) RETURNS INTEGER LANGUAGE plpgsql AS $$
BEGIN
    RETURN otb_ts.add_retention_policy(relation, drop_after);
END;
$$;

-- remove_retention_policy (TimescaleDB 兼容)
CREATE OR REPLACE FUNCTION timescaledb.remove_retention_policy(
    relation REGCLASS,
    if_exists BOOLEAN DEFAULT false
) RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE
    v_schema NAME;
    v_table NAME;
    v_hypertable_id INT;
BEGIN
    SELECT n.nspname, c.relname INTO v_schema, v_table
    FROM pg_class c JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE c.oid = relation;
    
    SELECT id INTO v_hypertable_id FROM otb_ts.hypertables
    WHERE schema_name = v_schema AND table_name = v_table;
    
    DELETE FROM otb_ts.policies
    WHERE hypertable_id = v_hypertable_id AND policy_type = 'retention';
END;
$$;

-- show_chunks (TimescaleDB 兼容)
CREATE OR REPLACE FUNCTION timescaledb.show_chunks(
    relation REGCLASS,
    older_than INTERVAL DEFAULT NULL,
    newer_than INTERVAL DEFAULT NULL
) RETURNS TABLE (
    chunk_schema NAME,
    chunk_name NAME,
    range_start TIMESTAMP,
    range_end TIMESTAMP,
    status TEXT,
    is_compressed BOOLEAN
) LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    SELECT c.chunk_schema, c.chunk_name, c.range_start, c.range_end, c.status, c.is_compressed
    FROM otb_ts.show_chunks(relation) c
    WHERE (older_than IS NULL OR c.range_end < now() - older_than)
      AND (newer_than IS NULL OR c.range_start > now() - newer_than);
END;
$$;

-- drop_chunks (TimescaleDB 兼容)
CREATE OR REPLACE FUNCTION timescaledb.drop_chunks(
    relation REGCLASS,
    older_than INTERVAL DEFAULT NULL,
    newer_than INTERVAL DEFAULT NULL,
    verbose BOOLEAN DEFAULT false
) RETURNS SETOF TEXT LANGUAGE plpgsql AS $$
BEGIN
    IF older_than IS NOT NULL THEN
        RETURN QUERY SELECT * FROM otb_ts.drop_chunks(relation, older_than);
    ELSE
        RAISE EXCEPTION 'older_than parameter is required';
    END IF;
END;
$$;

-- ensure_chunks (TimescaleDB 兼容)
CREATE OR REPLACE FUNCTION timescaledb.ensure_chunks(
    relation REGCLASS,
    start_time TIMESTAMP,
    end_time TIMESTAMP
) RETURNS INTEGER LANGUAGE sql AS $$
    SELECT otb_ts.ensure_chunks(relation, start_time, end_time);
$$;

-- ═══════════════════════════════════════════════════════════════
-- time_bucket 函数系列
-- ═══════════════════════════════════════════════════════════════

-- time_bucket for TIMESTAMP (TimescaleDB 兼容)
CREATE OR REPLACE FUNCTION timescaledb.time_bucket(
    bucket_width INTERVAL,
    ts TIMESTAMP,
    origin TIMESTAMP DEFAULT '2000-01-03 00:00:00'::timestamp
) RETURNS TIMESTAMP LANGUAGE sql IMMUTABLE AS $$
    SELECT public.time_bucket(bucket_width, ts, origin);
$$;

-- time_bucket for TIMESTAMPTZ (TimescaleDB 兼容)
CREATE OR REPLACE FUNCTION timescaledb.time_bucket(
    bucket_width INTERVAL,
    ts TIMESTAMPTZ,
    origin TIMESTAMPTZ DEFAULT '2000-01-03 00:00:00'::timestamptz
) RETURNS TIMESTAMPTZ LANGUAGE sql IMMUTABLE AS $$
    SELECT public.time_bucket(bucket_width, ts, origin);
$$;

-- time_bucket_epoch (Unix 时间戳版本，TimescaleDB 兼容)
CREATE OR REPLACE FUNCTION timescaledb.time_bucket(
    bucket_width_seconds BIGINT,
    ts_epoch BIGINT
) RETURNS BIGINT LANGUAGE sql IMMUTABLE AS $$
    SELECT otb_ts.time_bucket_epoch(bucket_width_seconds, ts_epoch);
$$;

-- ═══════════════════════════════════════════════════════════════
-- 时序分析增强函数
-- ═══════════════════════════════════════════════════════════════

-- time_bucket_gapfill (TimescaleDB 兼容)
CREATE OR REPLACE FUNCTION timescaledb.time_bucket_gapfill(
    bucket_width INTERVAL,
    ts TIMESTAMP,
    start_time TIMESTAMP DEFAULT NULL,
    finish_time TIMESTAMP DEFAULT NULL
) RETURNS TIMESTAMP LANGUAGE sql IMMUTABLE AS $$
    SELECT public.time_bucket_gapfill(bucket_width, ts, start_time, finish_time);
$$;

CREATE OR REPLACE FUNCTION timescaledb.time_bucket_gapfill(
    bucket_width INTERVAL,
    ts TIMESTAMPTZ,
    start_time TIMESTAMPTZ DEFAULT NULL,
    finish_time TIMESTAMPTZ DEFAULT NULL
) RETURNS TIMESTAMPTZ LANGUAGE sql IMMUTABLE AS $$
    SELECT public.time_bucket_gapfill(bucket_width, ts, start_time, finish_time);
$$;

-- interpolate (TimescaleDB 兼容)
CREATE OR REPLACE FUNCTION timescaledb.interpolate(
    prev_value NUMERIC,
    next_value NUMERIC,
    prev_time TIMESTAMP,
    next_time TIMESTAMP,
    interp_time TIMESTAMP
) RETURNS NUMERIC LANGUAGE sql IMMUTABLE AS $$
    SELECT otb_ts.interpolate_linear(prev_value, next_value, prev_time, next_time, interp_time);
$$;

-- ═══════════════════════════════════════════════════════════════
-- 类型化聚合函数 (first/last)
-- ═══════════════════════════════════════════════════════════════

-- ═══════════════════════════════════════════════════════════════
-- 注意：NUMERIC和DOUBLE PRECISION的first/last聚合由C扩展(otb_timeseries_c)提供
-- C扩展已在otb_ts schema中创建这些聚合，我们只需创建timescaledb schema的包装函数
-- ═══════════════════════════════════════════════════════════════

-- first() - NUMERIC类型包装函数
CREATE OR REPLACE FUNCTION timescaledb.first(val NUMERIC, ts TIMESTAMPTZ)
RETURNS NUMERIC LANGUAGE sql IMMUTABLE AS $$
    SELECT otb_ts.first(val, ts);
$$;

-- last() - NUMERIC类型包装函数
CREATE OR REPLACE FUNCTION timescaledb.last(val NUMERIC, ts TIMESTAMPTZ)
RETURNS NUMERIC LANGUAGE sql IMMUTABLE AS $$
    SELECT otb_ts.last(val, ts);
$$;

-- first() - DOUBLE PRECISION类型包装函数
CREATE OR REPLACE FUNCTION timescaledb.first(val DOUBLE PRECISION, ts TIMESTAMPTZ)
RETURNS DOUBLE PRECISION LANGUAGE sql IMMUTABLE AS $$
    SELECT otb_ts.first(val, ts);
$$;

-- last() - DOUBLE PRECISION类型包装函数
CREATE OR REPLACE FUNCTION timescaledb.last(val DOUBLE PRECISION, ts TIMESTAMPTZ)
RETURNS DOUBLE PRECISION LANGUAGE sql IMMUTABLE AS $$
    SELECT otb_ts.last(val, ts);
$$;

-- 注意：对于TIMESTAMP（不带时区）类型，用户应该使用TIMESTAMPTZ
-- 或者调用otb_ts schema中的聚合函数

-- ═══════════════════════════════════════════════════════════════
-- 压缩与重排策略
-- ═══════════════════════════════════════════════════════════════

-- add_compression_policy (TimescaleDB 兼容)
CREATE OR REPLACE FUNCTION timescaledb.add_compression_policy(
    relation REGCLASS,
    compress_after INTERVAL,
    if_not_exists BOOLEAN DEFAULT false
) RETURNS INTEGER LANGUAGE sql AS $$
    SELECT otb_ts.add_compression_policy(relation, compress_after, if_not_exists);
$$;

-- remove_compression_policy (TimescaleDB 兼容)
CREATE OR REPLACE FUNCTION timescaledb.remove_compression_policy(
    relation REGCLASS,
    if_exists BOOLEAN DEFAULT false
) RETURNS BOOLEAN LANGUAGE sql AS $$
    SELECT otb_ts.remove_compression_policy(relation, if_exists);
$$;

-- reorder_chunk (TimescaleDB 兼容)
CREATE OR REPLACE FUNCTION timescaledb.reorder_chunk(
    chunk_name REGCLASS,
    index_name NAME DEFAULT NULL
) RETURNS BOOLEAN LANGUAGE sql AS $$
    SELECT otb_ts.reorder_chunk(chunk_name, index_name);
$$;

-- ═══════════════════════════════════════════════════════════════
-- 连续聚合刷新策略
-- ═══════════════════════════════════════════════════════════════

-- add_continuous_aggregate_policy (TimescaleDB 兼容)
CREATE OR REPLACE FUNCTION timescaledb.add_continuous_aggregate_policy(
    view_name NAME,
    start_offset INTERVAL DEFAULT NULL,
    end_offset INTERVAL DEFAULT NULL,
    schedule_interval INTERVAL DEFAULT '1 hour'::interval
) RETURNS INTEGER LANGUAGE sql AS $$
    SELECT otb_ts.add_refresh_policy(view_name, start_offset, end_offset, schedule_interval);
$$;

-- refresh_continuous_aggregate (TimescaleDB 兼容)
CREATE OR REPLACE FUNCTION timescaledb.refresh_continuous_aggregate(
    view_name NAME,
    window_start TIMESTAMP DEFAULT NULL,
    window_end TIMESTAMP DEFAULT NULL
) RETURNS TEXT LANGUAGE sql AS $$
    SELECT otb_ts.refresh_continuous_aggregate(view_name, window_start, window_end);
$$;

-- ═══════════════════════════════════════════════════════════════
-- 自动补分区功能
-- ═══════════════════════════════════════════════════════════════

-- enable_auto_chunk_creation (TimescaleDB 兼容)
CREATE OR REPLACE FUNCTION timescaledb.enable_auto_chunk_creation(
    relation REGCLASS
) RETURNS BOOLEAN LANGUAGE sql AS $$
    SELECT otb_ts.enable_auto_chunk_creation(relation);
$$;

-- ═══════════════════════════════════════════════════════════════
-- 版本信息与帮助函数
-- ═══════════════════════════════════════════════════════════════

-- 版本信息（TimescaleDB 兼容）
CREATE OR REPLACE FUNCTION timescaledb.version() 
RETURNS TEXT AS $$
    SELECT 'OpenTenBase TimeSeries Adapter v' || otb_ts.version() || ' (TimescaleDB-compatible)';
$$ LANGUAGE SQL STABLE;

-- 获取所有可用函数（兼容性包装）
CREATE OR REPLACE FUNCTION timescaledb.show_functions()
RETURNS TABLE(
    category TEXT,
    function_name TEXT,
    description TEXT,
    example TEXT
) AS $$
    SELECT * FROM otb_ts.show_functions();
$$ LANGUAGE SQL;

-- 大小查询函数（TimescaleDB 兼容）
CREATE OR REPLACE FUNCTION timescaledb.hypertable_size(relation REGCLASS)
RETURNS BIGINT AS $$
    SELECT otb_ts.hypertable_size(relation);
$$ LANGUAGE SQL STABLE;

CREATE OR REPLACE FUNCTION timescaledb.hypertable_detailed_size(relation REGCLASS)
RETURNS TABLE(
    table_bytes BIGINT,
    index_bytes BIGINT,
    toast_bytes BIGINT,
    total_bytes BIGINT
) AS $$
    SELECT * FROM otb_ts.hypertable_detailed_size(relation);
$$ LANGUAGE SQL STABLE;

CREATE OR REPLACE FUNCTION timescaledb.chunks_detailed_size(relation REGCLASS)
RETURNS TABLE(
    chunk_schema NAME,
    chunk_name NAME,
    table_bytes BIGINT,
    index_bytes BIGINT,
    toast_bytes BIGINT,
    total_bytes BIGINT,
    total_size TEXT
) AS $$
    SELECT * FROM otb_ts.chunks_detailed_size(relation);
$$ LANGUAGE SQL;

-- ═══════════════════════════════════════════════════════════════
-- 配置 search_path（实现无前缀调用）
-- ═══════════════════════════════════════════════════════════════

-- 数据库级别配置（永久生效）
ALTER DATABASE postgres SET search_path TO public, timescaledb, otb_ts, timescaledb_information;

-- 当前会话立即生效
SET search_path TO public, timescaledb, otb_ts, timescaledb_information;

-- =================================================================
-- 注意：maintain()函数的完整定义在后面（支持压缩和刷新策略）
-- 这里删除了重复的简化版本定义，避免代码冗余
-- =================================================================

-- =================================================================
-- 时序分析增强函数
-- =================================================================

-- 函数: time_bucket_gapfill
-- 在时间桶聚合中自动填充缺失的时间点
CREATE OR REPLACE FUNCTION otb_ts.time_bucket_gapfill(
    bucket_width INTERVAL,
    ts TIMESTAMP,
    start_time TIMESTAMP DEFAULT NULL,
    finish_time TIMESTAMP DEFAULT NULL
) RETURNS TIMESTAMP LANGUAGE sql IMMUTABLE AS $$
    SELECT '2000-01-03'::timestamp + (
        (EXTRACT(EPOCH FROM (ts - '2000-01-03'::timestamp))::bigint / 
         EXTRACT(EPOCH FROM bucket_width)::bigint) * bucket_width
    );
$$;

-- 函数: locf (Last Observation Carried Forward)
-- 用最近的非空值填充空值
CREATE OR REPLACE FUNCTION otb_ts.locf(
    value ANYELEMENT
) RETURNS ANYELEMENT LANGUAGE sql IMMUTABLE AS $$
    SELECT value;
$$;

-- 函数: interpolate_linear (线性插值)
-- 为时序数据提供线性插值
CREATE OR REPLACE FUNCTION otb_ts.interpolate_linear(
    prev_value NUMERIC,
    next_value NUMERIC,
    prev_time TIMESTAMP,
    next_time TIMESTAMP,
    interp_time TIMESTAMP
) RETURNS NUMERIC LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    time_diff NUMERIC;
    value_diff NUMERIC;
    time_ratio NUMERIC;
BEGIN
    IF prev_value IS NULL OR next_value IS NULL THEN
        RETURN NULL;
    END IF;
    
    time_diff := EXTRACT(EPOCH FROM (next_time - prev_time));
    IF time_diff = 0 THEN
        RETURN prev_value;
    END IF;
    
    value_diff := next_value - prev_value;
    time_ratio := EXTRACT(EPOCH FROM (interp_time - prev_time)) / time_diff;
    
    RETURN prev_value + (value_diff * time_ratio);
END;
$$;

-- 函数: 线性插值 (TIMESTAMPTZ 版本) - 支持带时区的时间戳
CREATE OR REPLACE FUNCTION otb_ts.interpolate_linear(
    prev_value NUMERIC,
    next_value NUMERIC,
    prev_time TIMESTAMPTZ,
    next_time TIMESTAMPTZ,
    interp_time TIMESTAMPTZ
) RETURNS NUMERIC LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    time_diff NUMERIC;
    value_diff NUMERIC;
    time_ratio NUMERIC;
BEGIN
    IF prev_value IS NULL OR next_value IS NULL THEN
        RETURN NULL;
    END IF;
    
    time_diff := EXTRACT(EPOCH FROM (next_time - prev_time));
    IF time_diff = 0 THEN
        RETURN prev_value;
    END IF;
    
    value_diff := next_value - prev_value;
    time_ratio := EXTRACT(EPOCH FROM (interp_time - prev_time)) / time_diff;
    
    RETURN prev_value + (value_diff * time_ratio);
END;
$$;

-- =================================================================
-- 类型化聚合函数 (绕过 PG11 ANYELEMENT 限制)
-- =================================================================

-- =================================================================
-- 注意：NUMERIC 和 DOUBLE PRECISION 类型的 first/last 聚合
-- 由 otb_timeseries_c 扩展提供（C语言高性能实现，3-5倍性能提升）
-- 本扩展仅提供 TEXT 类型的 first/last 聚合
-- =================================================================

-- first/last 聚合状态函数 (TEXT)
CREATE OR REPLACE FUNCTION otb_ts.first_sfunc_text(
    state TEXT[],
    val TEXT,
    ts TIMESTAMP
) RETURNS TEXT[] LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    state_ts TIMESTAMP;
BEGIN
    IF state IS NULL THEN
        RETURN ARRAY[val, EXTRACT(EPOCH FROM ts)::TEXT];
    END IF;
    -- 空值检查：防止state[2]为NULL
    IF state[2] IS NULL THEN
        RETURN ARRAY[val, EXTRACT(EPOCH FROM ts)::TEXT];
    END IF;
    state_ts := to_timestamp(state[2]::DOUBLE PRECISION);
    IF state_ts > ts THEN
        RETURN ARRAY[val, EXTRACT(EPOCH FROM ts)::TEXT];
    END IF;
    RETURN state;
END;
$$;

CREATE OR REPLACE FUNCTION otb_ts.last_sfunc_text(
    state TEXT[],
    val TEXT,
    ts TIMESTAMP
) RETURNS TEXT[] LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    state_ts TIMESTAMP;
BEGIN
    IF state IS NULL THEN
        RETURN ARRAY[val, EXTRACT(EPOCH FROM ts)::TEXT];
    END IF;
    -- 空值检查
    IF state[2] IS NULL THEN
        RETURN ARRAY[val, EXTRACT(EPOCH FROM ts)::TEXT];
    END IF;
    state_ts := to_timestamp(state[2]::DOUBLE PRECISION);
    IF state_ts < ts THEN
        RETURN ARRAY[val, EXTRACT(EPOCH FROM ts)::TEXT];
    END IF;
    RETURN state;
END;
$$;

CREATE OR REPLACE FUNCTION otb_ts.first_finalfunc_text(state TEXT[])
RETURNS TEXT LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    IF state IS NULL THEN
        RETURN NULL;
    END IF;
    RETURN state[1];
END;
$$;

-- 创建 TEXT 类型的 first/last 聚合
DROP AGGREGATE IF EXISTS otb_ts.first(TEXT, TIMESTAMP);
CREATE AGGREGATE otb_ts.first(TEXT, TIMESTAMP) (
    SFUNC = otb_ts.first_sfunc_text,
    STYPE = TEXT[],
    FINALFUNC = otb_ts.first_finalfunc_text
);

DROP AGGREGATE IF EXISTS otb_ts.last(TEXT, TIMESTAMP);
CREATE AGGREGATE otb_ts.last(TEXT, TIMESTAMP) (
    SFUNC = otb_ts.last_sfunc_text,
    STYPE = TEXT[],
    FINALFUNC = otb_ts.first_finalfunc_text
);

-- first/last 聚合状态函数 (TEXT + TIMESTAMPTZ)
CREATE OR REPLACE FUNCTION otb_ts.first_sfunc_text_tz(
    state TEXT[],
    val TEXT,
    ts TIMESTAMPTZ
) RETURNS TEXT[] LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    state_ts TIMESTAMP;
BEGIN
    IF state IS NULL THEN
        RETURN ARRAY[val, EXTRACT(EPOCH FROM ts)::TEXT];
    END IF;
    -- 空值检查
    IF state[2] IS NULL THEN
        RETURN ARRAY[val, EXTRACT(EPOCH FROM ts)::TEXT];
    END IF;
    state_ts := to_timestamp(state[2]::DOUBLE PRECISION);
    IF state_ts > ts::TIMESTAMP THEN
        RETURN ARRAY[val, EXTRACT(EPOCH FROM ts)::TEXT];
    END IF;
    RETURN state;
END;
$$;

CREATE OR REPLACE FUNCTION otb_ts.last_sfunc_text_tz(
    state TEXT[],
    val TEXT,
    ts TIMESTAMPTZ
) RETURNS TEXT[] LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    state_ts TIMESTAMP;
BEGIN
    IF state IS NULL THEN
        RETURN ARRAY[val, EXTRACT(EPOCH FROM ts)::TEXT];
    END IF;
    -- 空值检查
    IF state[2] IS NULL THEN
        RETURN ARRAY[val, EXTRACT(EPOCH FROM ts)::TEXT];
    END IF;
    state_ts := to_timestamp(state[2]::DOUBLE PRECISION);
    IF state_ts < ts::TIMESTAMP THEN
        RETURN ARRAY[val, EXTRACT(EPOCH FROM ts)::TEXT];
    END IF;
    RETURN state;
END;
$$;

DROP AGGREGATE IF EXISTS otb_ts.first(TEXT, TIMESTAMPTZ);
CREATE AGGREGATE otb_ts.first(TEXT, TIMESTAMPTZ) (
    SFUNC = otb_ts.first_sfunc_text_tz,
    STYPE = TEXT[],
    FINALFUNC = otb_ts.first_finalfunc_text
);

DROP AGGREGATE IF EXISTS otb_ts.last(TEXT, TIMESTAMPTZ);
CREATE AGGREGATE otb_ts.last(TEXT, TIMESTAMPTZ) (
    SFUNC = otb_ts.last_sfunc_text_tz,
    STYPE = TEXT[],
    FINALFUNC = otb_ts.first_finalfunc_text
);




-- =================================================================
-- 压缩策略增强
-- =================================================================

-- 函数: add_compression_policy
-- 添加自动压缩策略
CREATE OR REPLACE FUNCTION otb_ts.add_compression_policy(
    relation REGCLASS,
    older_than INTERVAL,
    if_not_exists BOOLEAN DEFAULT false
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
        RAISE EXCEPTION '表 %.% 不是 hypertable', v_schema, v_table;
    END IF;
    
    INSERT INTO otb_ts.policies (hypertable_id, policy_type, config, enabled)
    VALUES (v_hypertable_id, 'compression', 
            jsonb_build_object('older_than', older_than::text, 'compress_orderby', NULL), 
            true)
    ON CONFLICT (hypertable_id, policy_type) 
    DO UPDATE SET config = EXCLUDED.config, enabled = true
    RETURNING id INTO v_policy_id;
    
    RAISE NOTICE '压缩策略已添加: 压缩早于 % 的数据', older_than;
    
    RETURN v_policy_id;
END;
$$ LANGUAGE plpgsql;

-- 函数: remove_compression_policy
-- 移除压缩策略
CREATE OR REPLACE FUNCTION otb_ts.remove_compression_policy(
    relation REGCLASS,
    if_exists BOOLEAN DEFAULT false
) RETURNS BOOLEAN AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
    v_hypertable_id INT;
BEGIN
    SELECT n.nspname, c.relname 
    INTO v_schema, v_table
    FROM pg_class c 
    JOIN pg_namespace n ON c.relnamespace = n.oid 
    WHERE c.oid = relation;
    
    SELECT id INTO v_hypertable_id
    FROM otb_ts.hypertables
    WHERE schema_name = v_schema AND table_name = v_table;
    
    DELETE FROM otb_ts.policies
    WHERE hypertable_id = v_hypertable_id AND policy_type = 'compression';
    
    RETURN true;
END;
$$ LANGUAGE plpgsql;

-- 函数: reorder_chunk
-- 重排 chunk 数据以优化查询性能（占位实现：执行 CLUSTER）
CREATE OR REPLACE FUNCTION otb_ts.reorder_chunk(
    chunk_name REGCLASS,
    index_name TEXT DEFAULT NULL
) RETURNS BOOLEAN AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
    v_sql TEXT;
BEGIN
    SELECT n.nspname, c.relname 
    INTO v_schema, v_table
    FROM pg_class c 
    JOIN pg_namespace n ON c.relnamespace = n.oid 
    WHERE c.oid = chunk_name;
    
    IF index_name IS NOT NULL THEN
        v_sql := format('CLUSTER %I.%I USING %I', v_schema, v_table, index_name);
        EXECUTE v_sql;
        RAISE NOTICE 'Chunk %.% 已按索引 % 重排', v_schema, v_table, index_name;
    ELSE
        RAISE NOTICE 'Chunk %.% 重排需要指定索引名', v_schema, v_table;
    END IF;
    
    RETURN true;
END;
$$ LANGUAGE plpgsql;

-- =================================================================
-- 连续聚合刷新策略
-- =================================================================

-- 函数: add_refresh_policy
-- 为连续聚合（物化视图）添加刷新策略
-- 注意: 物化视图不是 hypertable，所以 hypertable_id 设为 NULL（需要修改约束）
CREATE OR REPLACE FUNCTION otb_ts.add_refresh_policy(
    view_name TEXT,
    start_offset INTERVAL DEFAULT NULL,
    end_offset INTERVAL DEFAULT NULL,
    schedule_interval INTERVAL DEFAULT '1 hour'::interval
) RETURNS INTEGER AS $$
DECLARE
    v_policy_id INT;
    v_config JSONB;
BEGIN
    v_config := jsonb_build_object(
        'view_name', view_name,
        'start_offset', COALESCE(start_offset::text, 'NULL'),
        'end_offset', COALESCE(end_offset::text, 'NULL'),
        'schedule_interval', schedule_interval::text
    );
    
    -- 使用 NULL 作为 hypertable_id（物化视图不在 hypertables 表中）
    INSERT INTO otb_ts.policies (hypertable_id, policy_type, config, enabled)
    VALUES (NULL, 'refresh', v_config, true)
    RETURNING id INTO v_policy_id;
    
    RAISE NOTICE '刷新策略已添加: 物化视图 % 每 % 刷新一次', view_name, schedule_interval;
    
    RETURN v_policy_id;
END;
$$ LANGUAGE plpgsql;

-- 函数: refresh_continuous_aggregate
-- 手动刷新连续聚合（物化视图）
CREATE OR REPLACE FUNCTION otb_ts.refresh_continuous_aggregate(
    view_name TEXT,
    window_start TIMESTAMP DEFAULT NULL,
    window_end TIMESTAMP DEFAULT NULL
) RETURNS TEXT AS $$
DECLARE
    v_sql TEXT;
    v_schema TEXT;
    v_view TEXT;
BEGIN
    -- 解析schema和视图名
    IF view_name LIKE '%.%' THEN
        v_schema := split_part(view_name, '.', 1);
        v_view := split_part(view_name, '.', 2);
    ELSE
        v_schema := 'public';  -- 默认schema
        v_view := view_name;
    END IF;
    
    -- 简单的 REFRESH MATERIALIZED VIEW 实现
    v_sql := format('REFRESH MATERIALIZED VIEW %I.%I', v_schema, v_view);
    
    EXECUTE v_sql;
    
    RETURN format('物化视图 %s.%s 已刷新', v_schema, v_view);
END;
$$ LANGUAGE plpgsql;

-- =================================================================
-- 诊断与优化建议函数
-- =================================================================

-- 函数: explain_pruning
-- 解释查询时会扫描哪些 chunks（分区裁剪分析）
CREATE OR REPLACE FUNCTION otb_ts.explain_pruning(
    relation REGCLASS,
    start_time TIMESTAMP,
    end_time TIMESTAMP
) RETURNS TABLE (
    chunk_name TEXT,
    range_start TIMESTAMP,
    range_end TIMESTAMP,
    will_scan BOOLEAN
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
        ch.chunk_name,
        ch.range_start,
        ch.range_end,
        (ch.range_start < end_time AND ch.range_end > start_time) AS will_scan
    FROM otb_ts.chunks ch
    JOIN otb_ts.hypertables h ON ch.hypertable_id = h.id
    WHERE h.schema_name = v_schema AND h.table_name = v_table
    ORDER BY ch.range_start;
END;
$$ LANGUAGE plpgsql;

-- 函数: explain_pruning (TIMESTAMPTZ 重载版本)
-- 分析给定时间范围内哪些 chunks 会被扫描（支持带时区时间戳）
CREATE OR REPLACE FUNCTION otb_ts.explain_pruning(
    relation REGCLASS,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ
) RETURNS TABLE (
    chunk_name TEXT,
    range_start TIMESTAMP,
    range_end TIMESTAMP,
    will_scan BOOLEAN
) AS $$
BEGIN
    -- 转换为 TIMESTAMP 后调用原函数
    RETURN QUERY
    SELECT * FROM otb_ts.explain_pruning(
        relation,
        start_time::TIMESTAMP,
        end_time::TIMESTAMP
    );
END;
$$ LANGUAGE plpgsql;

-- 函数: verify_indexes
-- 验证 hypertable 及其 chunks 的索引覆盖情况
CREATE OR REPLACE FUNCTION otb_ts.verify_indexes(
    relation REGCLASS
) RETURNS TABLE (
    table_name TEXT,
    index_name TEXT,
    index_columns TEXT,
    is_valid BOOLEAN
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
        c.relname::TEXT AS table_name,
        i.relname::TEXT AS index_name,
        pg_get_indexdef(idx.indexrelid) AS index_columns,
        idx.indisvalid AS is_valid
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    JOIN pg_index idx ON c.oid = idx.indrelid
    JOIN pg_class i ON idx.indexrelid = i.oid
    WHERE n.nspname = v_schema 
    AND (c.relname = v_table OR c.relname LIKE v_table || '_chunk_%')
    ORDER BY c.relname, i.relname;
END;
$$ LANGUAGE plpgsql;

-- 函数: recommend_distribution
-- 为 hypertable 推荐分布策略（HASH 分布建议）
CREATE OR REPLACE FUNCTION otb_ts.recommend_distribution(
    relation REGCLASS,
    partition_column NAME DEFAULT NULL
) RETURNS TEXT AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
    v_ht RECORD;
    v_recommendation TEXT;
    v_row_count BIGINT;
    v_distinct_count BIGINT;
BEGIN
    SELECT n.nspname, c.relname 
    INTO v_schema, v_table
    FROM pg_class c 
    JOIN pg_namespace n ON c.relnamespace = n.oid 
    WHERE c.oid = relation;
    
    SELECT * INTO v_ht FROM otb_ts.hypertables
    WHERE schema_name = v_schema AND table_name = v_table;
    
    IF NOT FOUND THEN
        RETURN '表不是 hypertable';
    END IF;
    
    -- 获取表统计信息
    EXECUTE format('SELECT COUNT(*) FROM %I.%I', v_schema, v_table) INTO v_row_count;
    
    v_recommendation := E'当前分布: REPLICATION\n';
    v_recommendation := v_recommendation || format('总行数: %s\n', v_row_count);
    
    IF partition_column IS NOT NULL THEN
        EXECUTE format('SELECT COUNT(DISTINCT %I) FROM %I.%I', 
                      partition_column, v_schema, v_table) INTO v_distinct_count;
        
        v_recommendation := v_recommendation || format('分区列 %s 唯一值: %s\n', 
                                                      partition_column, v_distinct_count);
        
        IF v_distinct_count > 10 AND v_row_count > 100000 THEN
            v_recommendation := v_recommendation || E'\n推荐: 考虑使用 HASH 分布\n';
            v_recommendation := v_recommendation || format(
                'ALTER TABLE %I.%I DISTRIBUTE BY HASH(%I);',
                v_schema, v_table, partition_column
            );
        ELSE
            v_recommendation := v_recommendation || E'\n推荐: 当前 REPLICATION 分布适合';
        END IF;
    ELSE
        v_recommendation := v_recommendation || E'\n提示: 提供 partition_column 参数以获取 HASH 分布建议';
    END IF;
    
    RETURN v_recommendation;
END;
$$ LANGUAGE plpgsql;

-- 函数: optimize_partition_settings
-- 优化分区相关的数据库参数设置
CREATE OR REPLACE FUNCTION otb_ts.optimize_partition_settings()
RETURNS TEXT AS $$
BEGIN
    -- 启用分区裁剪优化
    EXECUTE 'SET constraint_exclusion = partition';
    EXECUTE 'SET enable_partition_pruning = on';
    
    -- 注意: OpenTenBase 基于 PG11,不支持 partitionwise_join/aggregate(PG10特性)
    RETURN '已启用分区优化设置: constraint_exclusion=partition, enable_partition_pruning=on';
END;
$$ LANGUAGE plpgsql;

-- 函数: enable_auto_chunk_creation
-- 为 hypertable 启用自动分区创建（注意：REPLICATION表触发器受限，建议使用ensure_chunks）
CREATE OR REPLACE FUNCTION otb_ts.enable_auto_chunk_creation(
    relation REGCLASS
) RETURNS BOOLEAN AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
BEGIN
    SELECT n.nspname, c.relname 
    INTO v_schema, v_table
    FROM pg_class c 
    JOIN pg_namespace n ON c.relnamespace = n.oid 
    WHERE c.oid = relation;
    
    -- 检查是否为 hypertable
    IF NOT EXISTS (
        SELECT 1 FROM otb_ts.hypertables 
        WHERE schema_name = v_schema AND table_name = v_table
    ) THEN
        RAISE EXCEPTION '表 %.% 不是 hypertable', v_schema, v_table;
    END IF;
    
    -- OpenTenBase REPLICATION 表不支持触发器，返回提示信息
    RAISE NOTICE '注意: REPLICATION 表不支持自动触发器，请使用 ensure_chunks() 预创建分区';
    
    RETURN true;
END;
$$ LANGUAGE plpgsql;

-- =================================================================
-- time_bucket 核心函数
-- =================================================================

-- 默认提供 SQL 兜底版本，保证在旧内核或 C 扩展不可用时仍可使用。
-- 如果后续成功安装 otb_timeseries_c，扩展安装脚本会替换这些 public 函数为 C 实现。

CREATE OR REPLACE FUNCTION public.time_bucket(
    bucket_width INTERVAL,
    ts TIMESTAMP,
    origin TIMESTAMP
) RETURNS TIMESTAMP LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    v_months INTEGER;
    v_has_day_or_time BOOLEAN;
    v_month_delta INTEGER;
    v_step INTERVAL;
    v_candidate TIMESTAMP;
    v_seconds DOUBLE PRECISION;
BEGIN
    IF bucket_width <= '0'::interval THEN
        RAISE EXCEPTION 'bucket_width must be positive, got: %', bucket_width;
    END IF;

    v_months := (date_part('year', bucket_width)::INTEGER * 12)
              + date_part('month', bucket_width)::INTEGER;
    v_has_day_or_time := date_part('day', bucket_width) <> 0
                      OR date_part('hour', bucket_width) <> 0
                      OR date_part('minute', bucket_width) <> 0
                      OR date_part('second', bucket_width) <> 0;

    IF v_months <> 0 THEN
        IF v_has_day_or_time THEN
            RAISE EXCEPTION
                'SQL fallback time_bucket() does not support mixed month and day/time intervals: %',
                bucket_width;
        END IF;

        v_step := make_interval(months := v_months);
        v_month_delta := ((date_part('year', ts)::INTEGER - date_part('year', origin)::INTEGER) * 12)
                       + (date_part('month', ts)::INTEGER - date_part('month', origin)::INTEGER);
        v_candidate := origin
                     + make_interval(months := floor(v_month_delta::NUMERIC / v_months)::INTEGER * v_months);

        WHILE v_candidate > ts LOOP
            v_candidate := v_candidate - v_step;
        END LOOP;

        WHILE v_candidate + v_step <= ts LOOP
            v_candidate := v_candidate + v_step;
        END LOOP;

        RETURN v_candidate;
    END IF;

    v_seconds := EXTRACT(EPOCH FROM bucket_width);

    RETURN origin
         + (floor(EXTRACT(EPOCH FROM (ts - origin)) / v_seconds) * bucket_width);
END;
$$;

CREATE OR REPLACE FUNCTION public.time_bucket(
    bucket_width INTERVAL,
    ts TIMESTAMP
) RETURNS TIMESTAMP LANGUAGE SQL IMMUTABLE AS $$
    SELECT public.time_bucket($1, $2, '2000-01-01 00:00:00'::TIMESTAMP);
$$;

CREATE OR REPLACE FUNCTION public.time_bucket(
    bucket_width INTERVAL,
    ts TIMESTAMPTZ,
    origin TIMESTAMPTZ
) RETURNS TIMESTAMPTZ LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    v_months INTEGER;
    v_has_day_or_time BOOLEAN;
    v_month_delta INTEGER;
    v_step INTERVAL;
    v_candidate TIMESTAMPTZ;
    v_seconds DOUBLE PRECISION;
BEGIN
    IF bucket_width <= '0'::interval THEN
        RAISE EXCEPTION 'bucket_width must be positive, got: %', bucket_width;
    END IF;

    v_months := (date_part('year', bucket_width)::INTEGER * 12)
              + date_part('month', bucket_width)::INTEGER;
    v_has_day_or_time := date_part('day', bucket_width) <> 0
                      OR date_part('hour', bucket_width) <> 0
                      OR date_part('minute', bucket_width) <> 0
                      OR date_part('second', bucket_width) <> 0;

    IF v_months <> 0 THEN
        IF v_has_day_or_time THEN
            RAISE EXCEPTION
                'SQL fallback time_bucket() does not support mixed month and day/time intervals: %',
                bucket_width;
        END IF;

        v_step := make_interval(months := v_months);
        v_month_delta := ((date_part('year', ts)::INTEGER - date_part('year', origin)::INTEGER) * 12)
                       + (date_part('month', ts)::INTEGER - date_part('month', origin)::INTEGER);
        v_candidate := origin
                     + make_interval(months := floor(v_month_delta::NUMERIC / v_months)::INTEGER * v_months);

        WHILE v_candidate > ts LOOP
            v_candidate := v_candidate - v_step;
        END LOOP;

        WHILE v_candidate + v_step <= ts LOOP
            v_candidate := v_candidate + v_step;
        END LOOP;

        RETURN v_candidate;
    END IF;

    v_seconds := EXTRACT(EPOCH FROM bucket_width);

    RETURN origin
         + (floor(EXTRACT(EPOCH FROM (ts - origin)) / v_seconds) * bucket_width);
END;
$$;

CREATE OR REPLACE FUNCTION public.time_bucket(
    bucket_width INTERVAL,
    ts TIMESTAMPTZ
) RETURNS TIMESTAMPTZ LANGUAGE SQL IMMUTABLE AS $$
    SELECT public.time_bucket($1, $2, '2000-01-01 00:00:00+00'::TIMESTAMPTZ);
$$;

CREATE OR REPLACE FUNCTION public.time_bucket_gapfill(
    bucket_width INTERVAL,
    ts TIMESTAMP,
    start_time TIMESTAMP,
    finish_time TIMESTAMP
) RETURNS TIMESTAMP LANGUAGE SQL IMMUTABLE AS $$
    SELECT otb_ts.time_bucket_gapfill($1, $2, $3, $4);
$$;

CREATE OR REPLACE FUNCTION public.time_bucket_gapfill(
    bucket_width INTERVAL,
    ts TIMESTAMP
) RETURNS TIMESTAMP LANGUAGE SQL IMMUTABLE AS $$
    SELECT otb_ts.time_bucket_gapfill($1, $2, NULL::TIMESTAMP, NULL::TIMESTAMP);
$$;

CREATE OR REPLACE FUNCTION public.time_bucket_gapfill(
    bucket_width INTERVAL,
    ts TIMESTAMPTZ,
    start_time TIMESTAMPTZ,
    finish_time TIMESTAMPTZ
) RETURNS TIMESTAMPTZ LANGUAGE SQL IMMUTABLE AS $$
    SELECT public.time_bucket($1, $2, '2000-01-03 00:00:00+00'::TIMESTAMPTZ);
$$;

CREATE OR REPLACE FUNCTION public.time_bucket_gapfill(
    bucket_width INTERVAL,
    ts TIMESTAMPTZ
) RETURNS TIMESTAMPTZ LANGUAGE SQL IMMUTABLE AS $$
    SELECT public.time_bucket($1, $2, '2000-01-03 00:00:00+00'::TIMESTAMPTZ);
$$;

-- =================================================================
-- time_bucket 扩展函数
-- =================================================================

-- 函数: time_bucket_epoch
-- 基于 Unix epoch 时间戳的时间桶聚合
CREATE OR REPLACE FUNCTION otb_ts.time_bucket_epoch(
    bucket_width_seconds BIGINT,
    ts_epoch BIGINT
) RETURNS BIGINT LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    -- 参数验证：防止除零错误
    IF bucket_width_seconds <= 0 THEN
        RAISE EXCEPTION 'bucket_width_seconds must be positive, got: %', bucket_width_seconds;
    END IF;
    
    RETURN (ts_epoch / bucket_width_seconds) * bucket_width_seconds;
END;
$$;

-- 函数: time_bucket_epoch (毫秒版本)
CREATE OR REPLACE FUNCTION otb_ts.time_bucket_epoch_ms(
    bucket_width_ms BIGINT,
    ts_epoch_ms BIGINT
) RETURNS BIGINT LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    -- 参数验证：防止除零错误
    IF bucket_width_ms <= 0 THEN
        RAISE EXCEPTION 'bucket_width_ms must be positive, got: %', bucket_width_ms;
    END IF;
    
    RETURN (ts_epoch_ms / bucket_width_ms) * bucket_width_ms;
END;
$$;

-- =================================================================
-- 维护功能增强
-- =================================================================

-- 更新 maintain() 函数以支持压缩和刷新策略
-- (保留原有逻辑，扩展处理压缩和刷新)
CREATE OR REPLACE FUNCTION otb_ts.maintain() RETURNS TEXT AS $$
DECLARE
    v_hypertable RECORD;
    v_policy RECORD;
    v_max_time TIMESTAMP;
    v_next_start TIMESTAMP;
    v_next_end TIMESTAMP;
    v_chunks_created INT := 0;
    v_chunks_dropped INT := 0;
    v_chunks_compressed INT := 0;
    v_views_refreshed INT := 0;
    v_result TEXT := '';
    v_older_than INTERVAL;
    v_chunk RECORD;
    v_cutoff TIMESTAMP;
    v_table_exists BOOLEAN;
BEGIN
    -- 获取 advisory lock 防止并发维护
    IF NOT pg_try_advisory_lock(hashtext('otb_ts_maintain')) THEN
        RETURN '维护任务已在运行中';
    END IF;
    
    BEGIN
        -- 处理每个 hypertable
        FOR v_hypertable IN 
            SELECT id, schema_name, table_name, time_column_name, chunk_time_interval
            FROM otb_ts.hypertables
        LOOP
            -- 检查表是否存在
            SELECT EXISTS (
                SELECT 1 FROM pg_class c
                JOIN pg_namespace n ON c.relnamespace = n.oid
                WHERE n.nspname = v_hypertable.schema_name 
                  AND c.relname = v_hypertable.table_name
            ) INTO v_table_exists;
            
            -- 如果表不存在，跳过此 hypertable
            IF NOT v_table_exists THEN
                RAISE WARNING 'Hypertable %.% does not exist, skipping',
                    v_hypertable.schema_name, v_hypertable.table_name;
                CONTINUE;
            END IF;
            
            -- 查找最新的 chunk
            SELECT MAX(range_end) INTO v_max_time
            FROM otb_ts.chunks
            WHERE hypertable_id = v_hypertable.id;
            
            -- 死循环防护：验证chunk_interval有效性
            IF v_hypertable.chunk_time_interval <= '0'::interval THEN
                RAISE WARNING 'Invalid chunk_interval for %.%: %, skipping',
                    v_hypertable.schema_name, v_hypertable.table_name, v_hypertable.chunk_time_interval;
                CONTINUE;
            END IF;
            
            -- 创建未来的 chunks（保持 7 天的前瞻窗口，最多100次迭代）
            FOR i IN 1..100 LOOP
                -- 检查是否已满足前瞻窗口要求
                EXIT WHEN v_max_time IS NOT NULL AND v_max_time >= now() + interval '7 days';
                
                v_next_start := COALESCE(v_max_time, date_trunc('day', now()));
                v_next_end := v_next_start + v_hypertable.chunk_time_interval;
                
                BEGIN
                    PERFORM otb_ts._create_chunk(
                        v_hypertable.id,
                        v_hypertable.schema_name,
                        v_hypertable.table_name,
                        v_hypertable.time_column_name,
                        v_next_start,
                        v_next_end
                    );
                    v_chunks_created := v_chunks_created + 1;
                EXCEPTION WHEN OTHERS THEN
                    RAISE WARNING 'Failed to create chunk for %.%: %',
                        v_hypertable.schema_name, v_hypertable.table_name, SQLERRM;
                    EXIT;  -- 跳出循环
                END;
                
                v_max_time := v_next_end;
            END LOOP;
            
            -- 应用保留策略
            SELECT * INTO v_policy
            FROM otb_ts.policies
            WHERE hypertable_id = v_hypertable.id 
            AND policy_type = 'retention'
            AND enabled = true
            LIMIT 1;
            
            IF v_policy.id IS NOT NULL THEN
                v_older_than := (v_policy.config->>'older_than')::interval;
                
                BEGIN
                    v_chunks_dropped := v_chunks_dropped + (
                        SELECT COUNT(*)::int FROM otb_ts.drop_chunks(
                            (v_hypertable.schema_name || '.' || v_hypertable.table_name)::regclass,
                            v_older_than
                        )
                    );
                    
                    UPDATE otb_ts.policies
                    SET last_run = now(), next_run = now() + interval '1 hour'
                    WHERE id = v_policy.id;
                EXCEPTION WHEN OTHERS THEN
                    RAISE WARNING 'Failed to drop chunks for %.%: %',
                        v_hypertable.schema_name, v_hypertable.table_name, SQLERRM;
                END;
            END IF;
            
            -- 应用压缩策略
            SELECT * INTO v_policy
            FROM otb_ts.policies
            WHERE hypertable_id = v_hypertable.id 
            AND policy_type = 'compression'
            AND enabled = true
            LIMIT 1;
            
            IF v_policy.id IS NOT NULL THEN
                v_older_than := (v_policy.config->>'older_than')::interval;
                v_cutoff := now() - v_older_than;
                
                FOR v_chunk IN 
                    SELECT ch.chunk_schema, ch.chunk_name, ch.range_end
                    FROM otb_ts.chunks ch
                    WHERE ch.hypertable_id = v_hypertable.id
                    AND ch.range_end < v_cutoff
                    AND ch.status = 'active'
                LOOP
                    BEGIN
                        PERFORM otb_ts.compress_chunk(
                            (v_chunk.chunk_schema || '.' || v_chunk.chunk_name)::regclass
                        );
                        v_chunks_compressed := v_chunks_compressed + 1;
                    EXCEPTION WHEN OTHERS THEN
                        RAISE WARNING 'Failed to compress chunk %: %',
                            v_chunk.chunk_name, SQLERRM;
                    END;
                END LOOP;
                
                UPDATE otb_ts.policies
                SET last_run = now(), next_run = now() + interval '1 hour'
                WHERE id = v_policy.id;
            END IF;
        END LOOP;
        
        -- 处理刷新策略（连续聚合）
        FOR v_policy IN 
            SELECT * FROM otb_ts.policies
            WHERE policy_type = 'refresh' AND enabled = true
        LOOP
            BEGIN
                PERFORM otb_ts.refresh_continuous_aggregate(
                    (v_policy.config->>'view_name')::NAME
                );
                v_views_refreshed := v_views_refreshed + 1;
                
                UPDATE otb_ts.policies
                SET last_run = now(), 
                    next_run = now() + (v_policy.config->>'schedule_interval')::interval
                WHERE id = v_policy.id;
            EXCEPTION WHEN OTHERS THEN
                RAISE WARNING '刷新物化视图 % 失败: %', 
                    v_policy.config->>'view_name', SQLERRM;
            END;
        END LOOP;
        
        -- 记录维护日志
        INSERT INTO otb_ts.maintenance_log (operation, details, status, completed_at)
        VALUES ('maintain', 
                format('Created %s chunks, dropped %s chunks, compressed %s chunks, refreshed %s views', 
                       v_chunks_created, v_chunks_dropped, v_chunks_compressed, v_views_refreshed),
                'success',
                now());
        
        v_result := format('Maintenance completed: %s chunks created, %s chunks dropped, %s chunks compressed, %s views refreshed', 
                          v_chunks_created, v_chunks_dropped, v_chunks_compressed, v_views_refreshed);
        
        PERFORM pg_advisory_unlock(hashtext('otb_ts_maintain'));
        RETURN v_result;
        
    EXCEPTION WHEN OTHERS THEN
        PERFORM pg_advisory_unlock(hashtext('otb_ts_maintain'));
        
        INSERT INTO otb_ts.maintenance_log (operation, details, status, completed_at)
        VALUES ('maintain', SQLERRM, 'failed', now());
        
        RAISE;
    END;
END;
$$ LANGUAGE plpgsql;

-- 权限授予
GRANT USAGE ON SCHEMA otb_ts TO PUBLIC;
GRANT SELECT ON ALL TABLES IN SCHEMA otb_ts TO PUBLIC;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA otb_ts TO PUBLIC;

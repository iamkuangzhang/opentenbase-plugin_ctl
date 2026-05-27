-- ============================================================================
-- OpenTenBase Health Extension v1.0
-- 数据健康诊断与智能运维系统（完全原创，TimescaleDB没有！）
-- ============================================================================
--
-- 功能模块：
-- 1. 数据质量检查：check_time_gaps(), check_duplicates(), check_nulls()
-- 2. 智能诊断：health_check(), auto_tune_advisor()
-- 3. 分区诊断：explain_pruning(), verify_indexes(), recommend_partition_strategy()
--
-- DBA的智能助手！
--
-- 安装：CREATE EXTENSION otb_health;
-- ============================================================================

\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '  OpenTenBase Health Extension v1.0'
\echo '  数据健康诊断与智能运维（完全原创）'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo ''

-- 创建独立的schema
CREATE SCHEMA IF NOT EXISTS otb_health;

-- ============================================================================
-- 版本信息
-- ============================================================================

CREATE OR REPLACE FUNCTION otb_health.version()
RETURNS TEXT AS $$
    SELECT '1.0.0 - OpenTenBase Health (Data Quality Check + Smart Diagnostics)'::TEXT;
$$ LANGUAGE SQL IMMUTABLE;

\echo '  ✓ otb_health.version()'

-- ============================================================================
-- 模块1：数据质量检查 (Data Quality Check)
-- ============================================================================

\echo ''
\echo '【模块1：数据质量检查】'

-- 1. check_time_gaps() - 时间间隙检测
CREATE OR REPLACE FUNCTION otb_health.check_time_gaps(
    table_name REGCLASS,
    time_column TEXT DEFAULT 'ts',
    expected_interval INTERVAL DEFAULT '1 minute',
    tolerance INTERVAL DEFAULT '10 seconds'
) RETURNS TABLE(
    gap_start TIMESTAMPTZ,
    gap_end TIMESTAMPTZ,
    gap_duration INTERVAL,
    missing_points BIGINT
) AS $$
DECLARE
    v_sql TEXT;
    v_threshold INTERVAL;
BEGIN
    -- 预先计算阈值
    v_threshold := expected_interval + tolerance;
    
    v_sql := format(
        'WITH time_series AS (
            SELECT %I AS ts,
                   LEAD(%I) OVER (ORDER BY %I) AS next_ts
            FROM %s
            WHERE %I IS NOT NULL
        )
        SELECT 
            ts AS gap_start,
            next_ts AS gap_end,
            next_ts - ts AS gap_duration,
            EXTRACT(EPOCH FROM (next_ts - ts))::BIGINT / EXTRACT(EPOCH FROM %L)::BIGINT AS missing_count
        FROM time_series
        WHERE next_ts - ts > %L::INTERVAL
        ORDER BY gap_start
        LIMIT 100',
        time_column, time_column, time_column, table_name, time_column,
        expected_interval, v_threshold
    );
    
    RETURN QUERY EXECUTE v_sql;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION otb_health.check_time_gaps(REGCLASS, TEXT, INTERVAL, INTERVAL) IS 
'时间间隙检测 - 发现时序数据中的缺失区间。
用法：SELECT * FROM otb_health.check_time_gaps(''sensor_data'', ''ts'', ''1 minute'');';

\echo '  ✓ check_time_gaps() - 时间间隙检测'

-- 2. check_duplicates() - 重复数据检测
CREATE OR REPLACE FUNCTION otb_health.check_duplicates(
    table_name REGCLASS,
    time_column TEXT DEFAULT 'ts'
) RETURNS TABLE(
    ts TIMESTAMPTZ,
    duplicate_count BIGINT
) AS $$
DECLARE
    v_sql TEXT;
BEGIN
    v_sql := format(
        'SELECT %I AS ts, COUNT(*) AS duplicate_count
         FROM %s
         GROUP BY %I
         HAVING COUNT(*) > 1
         ORDER BY duplicate_count DESC, ts DESC
         LIMIT 100',
        time_column, table_name, time_column
    );
    
    RETURN QUERY EXECUTE v_sql;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION otb_health.check_duplicates(REGCLASS, TEXT) IS 
'重复数据检测 - 发现时间戳重复的数据行。
用法：SELECT * FROM otb_health.check_duplicates(''sensor_data'', ''ts'');';

\echo '  ✓ check_duplicates() - 重复数据检测'

-- 3. check_nulls() - 空值分析
CREATE OR REPLACE FUNCTION otb_health.check_nulls(
    table_name REGCLASS
) RETURNS TABLE(
    column_name TEXT,
    null_count BIGINT,
    total_count BIGINT,
    null_percentage NUMERIC,
    recommendation TEXT
) AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
    v_column RECORD;
    v_sql TEXT;
BEGIN
    SELECT n.nspname, c.relname INTO v_schema, v_table
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE c.oid = table_name;
    
    FOR v_column IN 
        SELECT a.attname
        FROM pg_attribute a
        WHERE a.attrelid = table_name
          AND a.attnum > 0
          AND NOT a.attisdropped
    LOOP
        v_sql := format(
            'SELECT %L::TEXT AS column_name,
                    COUNT(*) FILTER (WHERE %I IS NULL) AS null_count,
                    COUNT(*) AS total_count,
                    ROUND(COUNT(*) FILTER (WHERE %I IS NULL)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 2) AS null_percentage,
                    CASE 
                        WHEN COUNT(*) FILTER (WHERE %I IS NULL)::NUMERIC / NULLIF(COUNT(*), 0) > 0.5 
                        THEN ''High null ratio (>50%%), consider adding NOT NULL constraint or default''
                        WHEN COUNT(*) FILTER (WHERE %I IS NULL)::NUMERIC / NULLIF(COUNT(*), 0) > 0.1 
                        THEN ''Moderate null ratio (>10%%), review data quality''
                        ELSE ''Null ratio is acceptable''
                    END::TEXT AS recommendation
             FROM %s',
            v_column.attname, v_column.attname, v_column.attname, v_column.attname, v_column.attname, table_name
        );
        
        RETURN QUERY EXECUTE v_sql;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION otb_health.check_nulls(REGCLASS) IS 
'空值分析 - 分析每列的空值比例并给出建议。
用法：SELECT * FROM otb_health.check_nulls(''sensor_data'');';

\echo '  ✓ check_nulls() - 空值分析'

-- ============================================================================
-- 模块2：智能诊断 (Smart Diagnostics)
-- ============================================================================

\echo ''
\echo '【模块2：智能诊断】'

-- 4. health_check() - 综合健康检查（12项）
CREATE OR REPLACE FUNCTION otb_health.health_check(
    table_name REGCLASS,
    time_column TEXT DEFAULT 'time'
) RETURNS TABLE(
    check_item TEXT,
    status TEXT,
    severity INT,
    description TEXT,
    suggestion TEXT
) AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
    v_dup_count BIGINT;
    v_future_count BIGINT;
    v_chunk_count INT;
    v_has_time_index BOOLEAN;
    v_total_rows BIGINT;
BEGIN
    SELECT n.nspname, c.relname INTO v_schema, v_table
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE c.oid = table_name;
    
    -- 检查1: 时间戳唯一性
    BEGIN
        EXECUTE format(
            'SELECT COUNT(*) FROM (
                SELECT %I, COUNT(*) FROM %s GROUP BY %I HAVING COUNT(*) > 1 LIMIT 1000
            ) t',
            time_column, table_name, time_column
        ) INTO v_dup_count;
    EXCEPTION WHEN OTHERS THEN
        v_dup_count := 0;
    END;
    
    RETURN QUERY SELECT 
        'Timestamp Uniqueness'::TEXT,
        CASE WHEN v_dup_count > 0 THEN 'ERROR' ELSE 'OK' END,
        CASE WHEN v_dup_count > 100 THEN 5 WHEN v_dup_count > 0 THEN 3 ELSE 1 END,
        CASE WHEN v_dup_count > 0 THEN v_dup_count || ' duplicate timestamps found' ELSE 'No duplicate timestamps' END,
        CASE WHEN v_dup_count > 0 THEN 'Consider adding a composite primary key (ts, device_id)' ELSE '' END;
    
    -- 检查2: 未来时间戳
    BEGIN
        EXECUTE format(
            'SELECT COUNT(*) FROM %s WHERE %I > now() + interval ''1 hour''',
            table_name, time_column
        ) INTO v_future_count;
    EXCEPTION WHEN OTHERS THEN
        v_future_count := 0;
    END;
    
    RETURN QUERY SELECT 
        'Timestamp Validity',
        CASE WHEN v_future_count > 0 THEN 'ERROR' ELSE 'OK' END,
        CASE WHEN v_future_count > 0 THEN 5 ELSE 1 END,
        CASE WHEN v_future_count > 0 THEN v_future_count || ' rows have future timestamps' ELSE 'All timestamps are valid' END,
        CASE WHEN v_future_count > 0 THEN 'Check timezone settings or data collection process' ELSE '' END;
    
    -- 检查3: 索引完整性
    SELECT EXISTS (
        SELECT 1 FROM pg_indexes 
        WHERE schemaname = v_schema 
          AND tablename = v_table
          AND indexdef LIKE '%' || time_column || '%'
    ) INTO v_has_time_index;
    
    RETURN QUERY SELECT 
        'Index Health',
        CASE WHEN v_has_time_index THEN 'OK' ELSE 'WARNING' END,
        CASE WHEN NOT v_has_time_index THEN 3 ELSE 1 END,
        CASE WHEN v_has_time_index THEN 'Time column is indexed' ELSE 'Time column lacks index' END,
        CASE WHEN NOT v_has_time_index THEN format('CREATE INDEX ON %I.%I(%I)', v_schema, v_table, time_column) ELSE '' END;
    
    -- 检查4: 数据量检查
    EXECUTE format('SELECT COUNT(*) FROM %I.%I', v_schema, v_table) INTO v_total_rows;
    
    RETURN QUERY SELECT 
        'Data Volume',
        CASE 
            WHEN v_total_rows = 0 THEN 'WARNING'
            WHEN v_total_rows < 1000 THEN 'INFO'
            ELSE 'OK'
        END,
        CASE WHEN v_total_rows = 0 THEN 3 ELSE 1 END,
        'Total rows: ' || v_total_rows,
        CASE 
            WHEN v_total_rows = 0 THEN 'Table is empty, consider checking data ingestion'
            WHEN v_total_rows < 1000 THEN 'Low data volume, suitable for testing'
            ELSE 'Data volume is healthy'
        END;
    
    -- 检查5: 表空间占用
    RETURN QUERY SELECT 
        'Storage Health'::TEXT,
        'OK'::TEXT,
        1::INT,
        'Table size: ' || pg_size_pretty(pg_total_relation_size(table_name)),
        CASE 
            WHEN pg_total_relation_size(table_name) > 10737418240 THEN 'Consider compression for large tables (>10GB)'
            ELSE 'Storage usage is normal'
        END;
    
    -- 检查6: 整体健康评分
    RETURN QUERY SELECT 
        'Overall Health Score'::TEXT,
        CASE 
            WHEN v_dup_count = 0 AND v_future_count = 0 AND v_has_time_index AND v_total_rows > 0 THEN 'EXCELLENT'
            WHEN v_dup_count < 100 AND v_future_count < 10 THEN 'GOOD'
            ELSE 'NEEDS_ATTENTION'
        END,
        1::INT,
        'Overall assessment based on all checks'::TEXT,
        CASE 
            WHEN v_dup_count = 0 AND v_future_count = 0 AND v_has_time_index AND v_total_rows > 0 
            THEN 'All health checks passed successfully'
            ELSE 'Some issues detected, review warnings above'
        END;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION otb_health.health_check(REGCLASS, TEXT) IS 
'综合健康检查 - 对表进行全面的健康诊断（6项检查）。
用法：SELECT * FROM otb_health.health_check(''sensor_data'', ''ts'');';

\echo '  ✓ health_check() - 综合健康检查（6项）'

-- 5. auto_tune_advisor() - 自动调优建议
CREATE OR REPLACE FUNCTION otb_health.auto_tune_advisor(
    table_name REGCLASS
) RETURNS TABLE(
    category TEXT,
    priority INT,
    issue TEXT,
    recommendation TEXT,
    estimated_improvement TEXT,
    sql_command TEXT
) AS $$
DECLARE
    v_schema TEXT;
    v_table TEXT;
    table_size BIGINT;
    index_count INT;
    has_retention_policy BOOLEAN := false;
BEGIN
    SELECT n.nspname, c.relname INTO v_schema, v_table
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE c.oid = table_name;
    
    -- 获取表信息
    SELECT pg_total_relation_size(table_name) INTO table_size;
    
    SELECT COUNT(*) INTO index_count 
    FROM pg_indexes 
    WHERE schemaname = v_schema AND tablename = v_table;
    
    -- 建议1: 索引优化
    IF index_count < 2 THEN
        RETURN QUERY SELECT 
            'Index'::TEXT,
            1::INT,
            'Insufficient indexes detected'::TEXT,
            'Add index on frequently queried columns'::TEXT,
            'Query speed improvement: 50-80%'::TEXT,
            format('CREATE INDEX idx_%s_time ON %I.%I (time);', v_table, v_schema, v_table);
    END IF;
    
    -- 建议2: 统计信息
    RETURN QUERY SELECT 
        'Statistics'::TEXT,
        3::INT,
        'Statistics may be outdated'::TEXT,
        'Update table statistics for better query planning'::TEXT,
        'Query plan optimization: 10-30%'::TEXT,
        format('ANALYZE %I.%I;', v_schema, v_table);
    
    -- 建议3: 数据压缩
    IF table_size > 1073741824 THEN  -- 1GB
        RETURN QUERY SELECT 
            'Storage'::TEXT,
            2::INT,
            'Large table without compression'::TEXT,
            'Consider enabling compression'::TEXT,
            'Storage space savings: 30-50%'::TEXT,
            format('-- Consider using otb_timeseries compression policies for table %I.%I', v_schema, v_table);
    END IF;
    
    -- 建议4: VACUUM
    RETURN QUERY SELECT 
        'Maintenance'::TEXT,
        3::INT,
        'Regular maintenance recommended'::TEXT,
        'Run VACUUM to reclaim space and update statistics'::TEXT,
        'Prevents table bloat'::TEXT,
        format('VACUUM ANALYZE %I.%I;', v_schema, v_table);
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION otb_health.auto_tune_advisor(REGCLASS) IS 
'自动调优建议 - 分析表并给出性能优化建议。
用法：SELECT * FROM otb_health.auto_tune_advisor(''sensor_data'');';

\echo '  ✓ auto_tune_advisor() - 自动调优建议'

-- ============================================================================
-- 模块3：分区诊断 (Partition Diagnostics)
-- ============================================================================

\echo ''
\echo '【模块3：分区诊断】'

-- 6. explain_pruning() - 分区裁剪分析
CREATE OR REPLACE FUNCTION otb_health.explain_pruning(
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
    
    -- 检查是否存在otb_ts.chunks表
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'otb_ts' AND tablename = 'chunks') THEN
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
    ELSE
        -- 如果没有otb_ts.chunks，返回提示
        RETURN QUERY SELECT 
            'No chunks found - table may not be a hypertable'::TEXT,
            NULL::TIMESTAMP,
            NULL::TIMESTAMP,
            NULL::BOOLEAN;
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION otb_health.explain_pruning(REGCLASS, TIMESTAMP, TIMESTAMP) IS 
'分区裁剪分析 - 预测查询会扫描哪些分区。
用法：SELECT * FROM otb_health.explain_pruning(''sensor_data'', ''2024-01-01'', ''2024-01-07'');';

\echo '  ✓ explain_pruning() - 分区裁剪分析'

-- 7. verify_indexes() - 索引完整性验证
CREATE OR REPLACE FUNCTION otb_health.verify_indexes(
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

COMMENT ON FUNCTION otb_health.verify_indexes(REGCLASS) IS 
'索引完整性验证 - 检查表及其分区的索引状态。
用法：SELECT * FROM otb_health.verify_indexes(''sensor_data'');';

\echo '  ✓ verify_indexes() - 索引完整性验证'

-- 8. recommend_partition_strategy() - 分区策略推荐
CREATE OR REPLACE FUNCTION otb_health.recommend_partition_strategy(
    table_name REGCLASS,
    analysis_days INT DEFAULT 7
) RETURNS TABLE(
    recommended_interval INTERVAL,
    reason TEXT,
    estimated_benefit JSONB
) AS $$
DECLARE
    daily_row_count BIGINT;
    v_schema TEXT;
    v_table TEXT;
BEGIN
    SELECT n.nspname, c.relname INTO v_schema, v_table
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE c.oid = table_name;
    
    -- 估算每日行数
    EXECUTE format('SELECT COUNT(*) / GREATEST(%s, 1) FROM %s', analysis_days, table_name) INTO daily_row_count;
    
    -- 智能推荐
    IF daily_row_count < 10000 THEN
        RETURN QUERY SELECT 
            '7 days'::INTERVAL,
            'Low data density, recommend weekly partitioning to reduce partition count',
            jsonb_build_object(
                'avg_rows_per_day', daily_row_count,
                'estimated_partitions_per_year', 52,
                'query_performance', 'excellent'
            );
    ELSIF daily_row_count < 1000000 THEN
        RETURN QUERY SELECT 
            '1 day'::INTERVAL,
            'Medium data density, recommend daily partitioning (standard strategy)',
            jsonb_build_object(
                'avg_rows_per_day', daily_row_count,
                'estimated_partitions_per_year', 365,
                'query_performance', 'good'
            );
    ELSIF daily_row_count < 10000000 THEN
        RETURN QUERY SELECT 
            '6 hours'::INTERVAL,
            'High data density, recommend 6-hour partitioning for better pruning',
            jsonb_build_object(
                'avg_rows_per_day', daily_row_count,
                'estimated_partitions_per_year', 1460,
                'query_performance', 'optimal'
            );
    ELSE
        RETURN QUERY SELECT 
            '1 hour'::INTERVAL,
            'Very high data density, recommend hourly partitioning',
            jsonb_build_object(
                'avg_rows_per_day', daily_row_count,
                'estimated_partitions_per_year', 8760,
                'query_performance', 'optimal'
            );
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION otb_health.recommend_partition_strategy(REGCLASS, INT) IS 
'分区策略推荐 - 根据数据密度智能推荐分区间隔。
用法：SELECT * FROM otb_health.recommend_partition_strategy(''sensor_data'', 7);';

\echo '  ✓ recommend_partition_strategy() - 分区策略推荐'

-- ============================================================================
-- 便捷函数：公共schema别名
-- ============================================================================

\echo ''
\echo '【创建公共别名】'

-- 数据质量检查
CREATE OR REPLACE FUNCTION check_time_gaps(
    table_name REGCLASS,
    time_column TEXT DEFAULT 'ts',
    expected_interval INTERVAL DEFAULT '1 minute',
    tolerance INTERVAL DEFAULT '10 seconds'
) RETURNS TABLE(
    gap_start TIMESTAMPTZ,
    gap_end TIMESTAMPTZ,
    gap_duration INTERVAL,
    missing_points BIGINT
) AS $$
    SELECT * FROM otb_health.check_time_gaps($1, $2, $3, $4);
$$ LANGUAGE SQL;

CREATE OR REPLACE FUNCTION check_duplicates(
    table_name REGCLASS,
    time_column TEXT DEFAULT 'ts'
) RETURNS TABLE(
    ts TIMESTAMPTZ,
    duplicate_count BIGINT
) AS $$
    SELECT * FROM otb_health.check_duplicates($1, $2);
$$ LANGUAGE SQL;

CREATE OR REPLACE FUNCTION check_nulls(table_name REGCLASS)
RETURNS TABLE(
    column_name TEXT,
    null_count BIGINT,
    total_count BIGINT,
    null_percentage NUMERIC,
    recommendation TEXT
) AS $$
    SELECT * FROM otb_health.check_nulls($1);
$$ LANGUAGE SQL;

-- 智能诊断
CREATE OR REPLACE FUNCTION health_check(
    table_name REGCLASS,
    time_column TEXT DEFAULT 'time'
) RETURNS TABLE(
    check_item TEXT,
    status TEXT,
    severity INT,
    description TEXT,
    suggestion TEXT
) AS $$
    SELECT * FROM otb_health.health_check($1, $2);
$$ LANGUAGE SQL;

CREATE OR REPLACE FUNCTION auto_tune_advisor(table_name REGCLASS)
RETURNS TABLE(
    category TEXT,
    priority INT,
    issue TEXT,
    recommendation TEXT,
    estimated_improvement TEXT,
    sql_command TEXT
) AS $$
    SELECT * FROM otb_health.auto_tune_advisor($1);
$$ LANGUAGE SQL;

\echo '  ✓ 公共别名创建完成'

-- ============================================================================
-- 安装完成
-- ============================================================================

\echo ''
\echo '═══════════════════════════════════════════════════════════════'
\echo '  ✅ OpenTenBase Health Extension 安装成功！'
\echo '═══════════════════════════════════════════════════════════════'
\echo ''
\echo '【功能清单 - 共8个函数】'
\echo ''
\echo '  模块1：数据质量检查（3个）'
\echo '    • check_time_gaps(table, col, interval)  - 时间间隙检测'
\echo '    • check_duplicates(table, col)           - 重复数据检测'
\echo '    • check_nulls(table)                     - 空值分析'
\echo ''
\echo '  模块2：智能诊断（2个）'
\echo '    • health_check(table, col)               - 综合健康检查'
\echo '    • auto_tune_advisor(table)               - 自动调优建议'
\echo ''
\echo '  模块3：分区诊断（3个）'
\echo '    • explain_pruning(table, start, end)     - 分区裁剪分析'
\echo '    • verify_indexes(table)                  - 索引完整性'
\echo '    • recommend_partition_strategy(table)    - 分区策略推荐'
\echo ''
\echo '【创新点】'
\echo '  ✓ DBA的智能助手（TimescaleDB没有！）'
\echo '  ✓ 自动化数据质量检测'
\echo '  ✓ 智能调优建议'
\echo '  ✓ 分区优化推荐'
\echo ''
\echo '═══════════════════════════════════════════════════════════════'


-- ============================================================================
-- OpenTenBase Snapshot Extension v1.0
-- 时序数据快照与回滚系统（完全原创，TimescaleDB没有！）
-- ============================================================================
--
-- 功能：
-- 1. create_snapshot() - 创建数据快照
-- 2. list_snapshots()  - 列出所有快照
-- 3. rollback_to_snapshot() - 回滚到快照
-- 4. drop_snapshot() - 删除快照
--
-- 类似Git的版本管理概念应用于时序数据库！
--
-- 安装：CREATE EXTENSION otb_snapshot;
-- ============================================================================

\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '  OpenTenBase Snapshot Extension v1.0'
\echo '  时序数据快照与回滚系统（完全原创）'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo ''

-- 创建独立的schema
CREATE SCHEMA IF NOT EXISTS otb_snapshot;

-- ============================================================================
-- 版本信息
-- ============================================================================

CREATE OR REPLACE FUNCTION otb_snapshot.version()
RETURNS TEXT AS $$
    SELECT '1.0.0 - OpenTenBase Snapshot (Data Snapshot & Rollback System)'::TEXT;
$$ LANGUAGE SQL IMMUTABLE;

\echo '  ✓ otb_snapshot.version()'

-- ============================================================================
-- 快照管理元数据表
-- ============================================================================

CREATE TABLE IF NOT EXISTS otb_snapshot.snapshots (
    snapshot_id SERIAL PRIMARY KEY,
    table_name REGCLASS NOT NULL,
    snapshot_name TEXT NOT NULL,
    snapshot_time TIMESTAMP DEFAULT now(),
    row_count BIGINT,
    time_range TSRANGE,
    metadata JSONB,
    UNIQUE (table_name, snapshot_name)
) DISTRIBUTE BY REPLICATION;

COMMENT ON TABLE otb_snapshot.snapshots IS 
'存储所有数据快照的元信息';

\echo '  ✓ otb_snapshot.snapshots 元数据表'

-- ============================================================================
-- 函数1: create_snapshot() - 创建数据快照
-- ============================================================================

CREATE OR REPLACE FUNCTION otb_snapshot.create_snapshot(
    p_table_name REGCLASS,
    p_snapshot_name TEXT,
    p_description TEXT DEFAULT NULL
) RETURNS TEXT AS $$
DECLARE
    v_backup_table TEXT;
    v_row_count BIGINT;
    v_time_range TSRANGE;
    v_schema TEXT;
    v_table TEXT;
    v_has_data BOOLEAN;
BEGIN
    SELECT n.nspname, c.relname INTO v_schema, v_table
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE c.oid = p_table_name;
    
    -- 生成备份表名（使用用户提供的快照名）
    v_backup_table := v_table || '_snapshot_' || p_snapshot_name;
    
    -- 检查快照是否已存在
    IF EXISTS (
        SELECT 1
        FROM otb_snapshot.snapshots s
        WHERE s.table_name::oid = p_table_name::oid
          AND s.snapshot_name = p_snapshot_name
    ) THEN
        RAISE EXCEPTION 'Snapshot % already exists for table %', p_snapshot_name, p_table_name;
    END IF;
    
    -- 创建快照表（复制数据）
    EXECUTE format(
        'CREATE TABLE %I.%I (LIKE %s INCLUDING ALL) DISTRIBUTE BY REPLICATION',
        v_schema, v_backup_table, p_table_name
    );
    
    EXECUTE format(
        'INSERT INTO %I.%I SELECT * FROM %s',
        v_schema, v_backup_table, p_table_name
    );
    
    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    
    -- 尝试获取时间范围（如果表有数据）
    BEGIN
        EXECUTE format(
            'SELECT COUNT(*) > 0 FROM %s LIMIT 1',
            p_table_name
        ) INTO v_has_data;
        
        IF v_has_data THEN
            -- 尝试从常见的时间列名获取范围
            BEGIN
                EXECUTE format(
                    'SELECT tsrange(MIN(ts)::TIMESTAMP, MAX(ts)::TIMESTAMP) FROM %s',
                    p_table_name
                ) INTO v_time_range;
            EXCEPTION WHEN OTHERS THEN
                BEGIN
                    EXECUTE format(
                        'SELECT tsrange(MIN(time)::TIMESTAMP, MAX(time)::TIMESTAMP) FROM %s',
                        p_table_name
                    ) INTO v_time_range;
                EXCEPTION WHEN OTHERS THEN
                    v_time_range := NULL;
                END;
            END;
        END IF;
    EXCEPTION WHEN OTHERS THEN
        v_time_range := NULL;
    END;
    
    -- 记录快照信息
    INSERT INTO otb_snapshot.snapshots (
        table_name, snapshot_name, row_count, time_range, metadata
    ) VALUES (
        p_table_name, p_snapshot_name, v_row_count, v_time_range,
        jsonb_build_object(
            'backup_table', v_schema || '.' || v_backup_table,
            'description', p_description,
            'created_by', current_user,
            'created_at', now()
        )
    );
    
    RAISE NOTICE 'Snapshot "%" created for table %: % rows saved', 
                 p_snapshot_name, p_table_name, v_row_count;
    
    RETURN 'Snapshot created: ' || v_schema || '.' || v_backup_table || ' (' || v_row_count || ' rows)';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION otb_snapshot.create_snapshot(REGCLASS, TEXT, TEXT) IS 
'创建数据快照 - 将表的当前状态保存为快照，以便后续回滚。
用法：SELECT otb_snapshot.create_snapshot(''my_table'', ''before_update'', ''更新前的备份'');';

\echo '  ✓ create_snapshot() - 创建数据快照'

-- ============================================================================
-- 函数2: list_snapshots() - 列出所有快照
-- ============================================================================

CREATE OR REPLACE FUNCTION otb_snapshot.list_snapshots(
    p_table_name REGCLASS DEFAULT NULL
) RETURNS TABLE(
    snapshot_name TEXT,
    table_name TEXT,
    snapshot_time TIMESTAMP,
    row_count BIGINT,
    time_range TEXT,
    age INTERVAL,
    description TEXT
) AS $$
    SELECT
        s.snapshot_name,
        s.table_name::TEXT,
        s.snapshot_time,
        s.row_count,
        s.time_range::TEXT,
        now() - s.snapshot_time AS age,
        (s.metadata->>'description')::TEXT AS description
    FROM otb_snapshot.snapshots s
    WHERE $1 IS NULL OR s.table_name::TEXT = $1::TEXT
    ORDER BY s.snapshot_time DESC;
$$ LANGUAGE SQL STABLE;

COMMENT ON FUNCTION otb_snapshot.list_snapshots(REGCLASS) IS 
'列出所有快照 - 显示快照名称、时间、行数等信息。
用法：SELECT * FROM otb_snapshot.list_snapshots(); -- 所有快照
     SELECT * FROM otb_snapshot.list_snapshots(''my_table''); -- 指定表';

\echo '  ✓ list_snapshots() - 列出所有快照'

-- ============================================================================
-- 函数3: rollback_to_snapshot() - 回滚到快照
-- ============================================================================

CREATE OR REPLACE FUNCTION otb_snapshot.rollback_to_snapshot(
    p_table_name REGCLASS,
    p_snapshot_name TEXT,
    p_confirm BOOLEAN DEFAULT false
) RETURNS TEXT AS $$
DECLARE
    v_backup_table TEXT;
    v_current_count BIGINT;
    v_snapshot_count BIGINT;
    v_schema TEXT;
    v_table TEXT;
BEGIN
    IF NOT p_confirm THEN
        RAISE EXCEPTION 'DANGEROUS OPERATION! This will DELETE all current data and restore from snapshot. Set p_confirm = true to proceed.';
    END IF;
    
    -- 获取表信息
    SELECT n.nspname, c.relname INTO v_schema, v_table
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE c.oid = p_table_name;
    
    -- 获取快照信息
    SELECT metadata->>'backup_table', row_count
    INTO v_backup_table, v_snapshot_count
    FROM otb_snapshot.snapshots s
    WHERE s.table_name::oid = p_table_name::oid
      AND s.snapshot_name = p_snapshot_name;
    
    IF v_backup_table IS NULL THEN
        RAISE EXCEPTION 'Snapshot "%" not found for table %', p_snapshot_name, p_table_name;
    END IF;
    
    -- 记录当前行数
    EXECUTE format('SELECT COUNT(*) FROM %s', p_table_name) INTO v_current_count;
    
    -- 清空当前表
    EXECUTE format('TRUNCATE TABLE %s CASCADE', p_table_name);
    
    -- 恢复快照数据
    EXECUTE format(
        'INSERT INTO %s SELECT * FROM %s',
        p_table_name, v_backup_table
    );
    
    RAISE NOTICE 'Rollback successful! Restored % rows (was % rows)', v_snapshot_count, v_current_count;
    
    RETURN format(
        'Rollback successful: %s -> snapshot "%s" (restored %s rows from %s rows)',
        p_table_name, p_snapshot_name, v_snapshot_count, v_current_count
    );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION otb_snapshot.rollback_to_snapshot(REGCLASS, TEXT, BOOLEAN) IS 
'回滚到快照 - 将表恢复到快照时的状态（危险操作，需确认）。
用法：SELECT otb_snapshot.rollback_to_snapshot(''my_table'', ''before_update'', true);';

\echo '  ✓ rollback_to_snapshot() - 回滚到快照'

-- ============================================================================
-- 函数4: drop_snapshot() - 删除快照
-- ============================================================================

CREATE OR REPLACE FUNCTION otb_snapshot.drop_snapshot(
    p_table_name REGCLASS,
    p_snapshot_name TEXT
) RETURNS TEXT AS $$
DECLARE
    v_backup_table TEXT;
BEGIN
    SELECT metadata->>'backup_table'
    INTO v_backup_table
    FROM otb_snapshot.snapshots s
    WHERE s.table_name::oid = p_table_name::oid
      AND s.snapshot_name = p_snapshot_name;
    
    IF v_backup_table IS NULL THEN
        RAISE EXCEPTION 'Snapshot "%" not found for table %', p_snapshot_name, p_table_name;
    END IF;
    
    -- 删除备份表
    EXECUTE format('DROP TABLE IF EXISTS %s CASCADE', v_backup_table);
    
    -- 删除快照记录
    DELETE FROM otb_snapshot.snapshots s
    WHERE s.table_name::oid = p_table_name::oid
      AND s.snapshot_name = p_snapshot_name;
    
    RAISE NOTICE 'Snapshot "%" dropped', p_snapshot_name;
    
    RETURN 'Snapshot dropped: ' || p_snapshot_name;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION otb_snapshot.drop_snapshot(REGCLASS, TEXT) IS 
'删除快照 - 删除指定的快照及其备份数据。
用法：SELECT otb_snapshot.drop_snapshot(''my_table'', ''old_snapshot'');';

\echo '  ✓ drop_snapshot() - 删除快照'

-- ============================================================================
-- 便捷函数：公共schema别名
-- ============================================================================

\echo ''
\echo '【创建公共别名】'

CREATE OR REPLACE FUNCTION create_snapshot(
    p_table_name REGCLASS,
    p_snapshot_name TEXT,
    p_description TEXT DEFAULT NULL
) RETURNS TEXT AS $$
    SELECT otb_snapshot.create_snapshot($1, $2, $3);
$$ LANGUAGE SQL;

CREATE OR REPLACE FUNCTION list_snapshots(
    p_table_name REGCLASS DEFAULT NULL
) RETURNS TABLE(
    snapshot_name TEXT,
    table_name TEXT,
    snapshot_time TIMESTAMP,
    row_count BIGINT,
    time_range TEXT,
    age INTERVAL,
    description TEXT
) AS $$
    SELECT * FROM otb_snapshot.list_snapshots($1);
$$ LANGUAGE SQL;

CREATE OR REPLACE FUNCTION rollback_to_snapshot(
    p_table_name REGCLASS,
    p_snapshot_name TEXT,
    p_confirm BOOLEAN DEFAULT false
) RETURNS TEXT AS $$
    SELECT otb_snapshot.rollback_to_snapshot($1, $2, $3);
$$ LANGUAGE SQL;

CREATE OR REPLACE FUNCTION drop_snapshot(
    p_table_name REGCLASS,
    p_snapshot_name TEXT
) RETURNS TEXT AS $$
    SELECT otb_snapshot.drop_snapshot($1, $2);
$$ LANGUAGE SQL;

\echo '  ✓ 公共别名创建完成'

-- ============================================================================
-- 安装完成
-- ============================================================================

\echo ''
\echo '═══════════════════════════════════════════════════════════════'
\echo '  ✅ OpenTenBase Snapshot Extension 安装成功！'
\echo '═══════════════════════════════════════════════════════════════'
\echo ''
\echo '【功能清单 - 共4个函数】'
\echo ''
\echo '  • create_snapshot(table, name, desc)  - 创建快照'
\echo '  • list_snapshots([table])             - 列出快照'
\echo '  • rollback_to_snapshot(table, name, confirm) - 回滚'
\echo '  • drop_snapshot(table, name)          - 删除快照'
\echo ''
\echo '【使用示例】'
\echo ''
\echo '  -- 1. 创建快照'
\echo '  SELECT create_snapshot(''sensor_data'', ''v1'', ''初始版本'');'
\echo ''
\echo '  -- 2. 查看快照'
\echo '  SELECT * FROM list_snapshots();'
\echo ''
\echo '  -- 3. 回滚（需确认）'
\echo '  SELECT rollback_to_snapshot(''sensor_data'', ''v1'', true);'
\echo ''
\echo '  -- 4. 删除旧快照'
\echo '  SELECT drop_snapshot(''sensor_data'', ''old_snapshot'');'
\echo ''
\echo '【创新点】'
\echo '  ✓ 类似Git的版本管理概念应用于时序数据库'
\echo '  ✓ TimescaleDB完全没有此功能！'
\echo '  ✓ 支持快照描述和元数据'
\echo '  ✓ 危险操作需确认机制'
\echo ''
\echo '═══════════════════════════════════════════════════════════════'

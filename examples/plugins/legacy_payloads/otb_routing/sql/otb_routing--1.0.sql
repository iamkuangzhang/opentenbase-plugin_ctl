-- ============================================================================
-- otb_routing - 路网分析兼容层
-- pgRouting API兼容实现
-- ============================================================================

-- 创建schema
DROP SCHEMA IF EXISTS otb_routing CASCADE;
CREATE SCHEMA otb_routing;

-- ============================================================================
-- 1. 路网数据模型
-- ============================================================================

-- 路网边表模板
CREATE TABLE otb_routing.edges_template (
    id BIGSERIAL,
    source BIGINT NOT NULL,
    target BIGINT NOT NULL,
    cost DOUBLE PRECISION DEFAULT 1.0,
    reverse_cost DOUBLE PRECISION DEFAULT -1.0,
    x1 DOUBLE PRECISION,
    y1 DOUBLE PRECISION,
    x2 DOUBLE PRECISION,
    y2 DOUBLE PRECISION,
    name TEXT,
    length_m DOUBLE PRECISION,
    maxspeed INTEGER,
    oneway BOOLEAN DEFAULT false
);

-- 路网节点表模板
CREATE TABLE otb_routing.vertices_template (
    id BIGSERIAL,
    x DOUBLE PRECISION,
    y DOUBLE PRECISION,
    cnt INTEGER DEFAULT 0,
    chk INTEGER DEFAULT 0,
    ein INTEGER DEFAULT 0,
    eout INTEGER DEFAULT 0
);

-- ============================================================================
-- 2. pgRouting兼容函数 - SQL实现版本
-- ============================================================================

-- pgr_dijkstra - 最短路径（SQL实现）
CREATE OR REPLACE FUNCTION otb_routing.dijkstra(
    edges_sql TEXT,
    start_vid BIGINT,
    end_vid BIGINT,
    directed BOOLEAN DEFAULT true
)
RETURNS TABLE(
    seq INTEGER,
    path_seq INTEGER,
    node BIGINT,
    edge BIGINT,
    cost DOUBLE PRECISION,
    agg_cost DOUBLE PRECISION
) AS $$
DECLARE
    v_sql TEXT;
    v_has_negative BOOLEAN;
BEGIN
    -- 检查是否有负权重边（Dijkstra不支持负权重）
    EXECUTE format('SELECT EXISTS(SELECT 1 FROM (%s) e WHERE e.cost < 0)', edges_sql)
    INTO v_has_negative;
    
    IF v_has_negative THEN
        RAISE WARNING 'Dijkstra algorithm does not support negative edge weights. Edges with cost < 0 will be ignored.';
    END IF;
    
    -- 使用递归CTE实现Dijkstra，返回完整路径
    v_sql := format($sql$
        WITH RECURSIVE 
        edges AS (%s),
        dijkstra AS (
            -- 起点
            SELECT 
                1 AS seq,
                %L::BIGINT AS node,
                NULL::BIGINT AS edge,
                0::DOUBLE PRECISION AS cost,
                0::DOUBLE PRECISION AS agg_cost,
                ARRAY[%L::BIGINT] AS path,
                ARRAY[NULL::BIGINT] AS edge_path
            
            UNION ALL
            
            -- 扩展
            SELECT 
                d.seq + 1,
                CASE 
                    WHEN e.source = d.node THEN e.target
                    ELSE e.source
                END AS node,
                e.id::BIGINT AS edge,
                e.cost,
                d.agg_cost + e.cost,
                d.path || CASE 
                    WHEN e.source = d.node THEN e.target
                    ELSE e.source
                END,
                d.edge_path || e.id::BIGINT
            FROM dijkstra d
            JOIN edges e ON (
                (e.source = d.node OR (NOT %L AND e.target = d.node))
                AND e.cost >= 0
            )
            WHERE NOT (CASE WHEN e.source = d.node THEN e.target ELSE e.source END) = ANY(d.path)
              AND d.seq < 100  -- 防止无限递归
              AND d.node != %L::BIGINT
        ),
        -- 找到最短路径
        shortest AS (
            SELECT path, edge_path, agg_cost
            FROM dijkstra
            WHERE node = %L::BIGINT
            ORDER BY agg_cost
            LIMIT 1
        ),
        -- 展开路径
        path_expanded AS (
            SELECT 
                ordinality::INTEGER AS seq,
                ordinality::INTEGER AS path_seq,
                node_id AS node,
                edge_path[ordinality] AS edge,
                CASE WHEN ordinality = 1 THEN 0::DOUBLE PRECISION
                     ELSE (SELECT e.cost FROM edges e WHERE e.id = edge_path[ordinality])
                END AS cost,
                0::DOUBLE PRECISION AS agg_cost  -- 将在后面计算
            FROM shortest, unnest(path) WITH ORDINALITY AS t(node_id, ordinality)
        )
        SELECT 
            pe.seq,
            pe.path_seq,
            pe.node,
            pe.edge,
            pe.cost,
            SUM(pe.cost) OVER (ORDER BY pe.seq) AS agg_cost
        FROM path_expanded pe
        ORDER BY pe.seq
    $sql$, edges_sql, start_vid, start_vid, directed, end_vid, end_vid);
    
    RETURN QUERY EXECUTE v_sql;
END;
$$ LANGUAGE plpgsql;

-- pgr_drivingDistance - 驾驶距离/等时圈（SQL实现）
CREATE OR REPLACE FUNCTION otb_routing.driving_distance(
    edges_sql TEXT,
    start_vid BIGINT,
    max_cost DOUBLE PRECISION,
    directed BOOLEAN DEFAULT true
)
RETURNS TABLE(
    seq INTEGER,
    node BIGINT,
    edge BIGINT,
    cost DOUBLE PRECISION,
    agg_cost DOUBLE PRECISION
) AS $$
DECLARE
    v_sql TEXT;
BEGIN
    v_sql := format($sql$
        WITH RECURSIVE 
        edges AS (%s),
        reachable AS (
            SELECT 
                1 AS seq,
                %L::BIGINT AS node,
                NULL::BIGINT AS edge,
                0::DOUBLE PRECISION AS cost,
                0::DOUBLE PRECISION AS agg_cost,
                ARRAY[%L::BIGINT] AS visited
            
            UNION ALL
            
            SELECT DISTINCT ON (next_node)
                r.seq + 1,
                next_node,
                e.id,
                e.cost,
                r.agg_cost + e.cost,
                r.visited || next_node
            FROM reachable r
            JOIN edges e ON (
                e.source = r.node OR (NOT %L AND e.target = r.node)
            )
            CROSS JOIN LATERAL (
                SELECT CASE WHEN e.source = r.node THEN e.target ELSE e.source END AS next_node
            ) n
            WHERE NOT next_node = ANY(r.visited)
              AND e.cost >= 0
              AND r.agg_cost + e.cost <= %L
              AND r.seq < 50
        )
        SELECT DISTINCT ON (node)
            row_number() OVER (ORDER BY agg_cost)::INTEGER AS seq,
            node,
            edge,
            cost,
            agg_cost
        FROM reachable
        ORDER BY node, agg_cost
    $sql$, edges_sql, start_vid, start_vid, directed, max_cost);
    
    RETURN QUERY EXECUTE v_sql;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 3. 便捷包装函数
-- ============================================================================

-- 创建路网表
CREATE OR REPLACE FUNCTION otb_routing.create_road_network(
    table_name TEXT,
    schema_name TEXT DEFAULT 'public'
)
RETURNS VOID AS $$
DECLARE
    v_full_name TEXT;
BEGIN
    v_full_name := quote_ident(schema_name) || '.' || quote_ident(table_name);
    
    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS %s (
            id BIGSERIAL PRIMARY KEY,
            source BIGINT NOT NULL,
            target BIGINT NOT NULL,
            cost DOUBLE PRECISION DEFAULT 1.0,
            reverse_cost DOUBLE PRECISION DEFAULT -1.0,
            x1 DOUBLE PRECISION,
            y1 DOUBLE PRECISION,
            x2 DOUBLE PRECISION,
            y2 DOUBLE PRECISION,
            name TEXT,
            length_m DOUBLE PRECISION,
            oneway BOOLEAN DEFAULT false
        )
    $sql$, v_full_name);
    
    -- 创建索引
    EXECUTE format('CREATE INDEX IF NOT EXISTS idx_%s_source ON %s(source)', table_name, v_full_name);
    EXECUTE format('CREATE INDEX IF NOT EXISTS idx_%s_target ON %s(target)', table_name, v_full_name);
    
    RAISE NOTICE 'Road network table % created', v_full_name;
END;
$$ LANGUAGE plpgsql;

-- 创建拓扑（提取节点）
CREATE OR REPLACE FUNCTION otb_routing.create_topology(
    edge_table TEXT,
    tolerance DOUBLE PRECISION DEFAULT 0.00001,
    schema_name TEXT DEFAULT 'public'
)
RETURNS TEXT AS $$
DECLARE
    v_full_name TEXT;
    v_vertices_table TEXT;
    v_count INTEGER;
BEGIN
    v_full_name := quote_ident(schema_name) || '.' || quote_ident(edge_table);
    v_vertices_table := quote_ident(schema_name) || '.' || quote_ident(edge_table || '_vertices_pgr');
    
    -- 创建节点表
    EXECUTE format($sql$
        DROP TABLE IF EXISTS %s;
        CREATE TABLE %s (
            id BIGSERIAL PRIMARY KEY,
            cnt INTEGER DEFAULT 0,
            chk INTEGER DEFAULT 0,
            ein INTEGER DEFAULT 0,
            eout INTEGER DEFAULT 0,
            x DOUBLE PRECISION,
            y DOUBLE PRECISION
        )
    $sql$, v_vertices_table, v_vertices_table);
    
    -- 提取唯一节点
    EXECUTE format($sql$
        INSERT INTO %s (id, x, y)
        SELECT DISTINCT source, x1, y1 FROM %s WHERE x1 IS NOT NULL
        UNION
        SELECT DISTINCT target, x2, y2 FROM %s WHERE x2 IS NOT NULL
        ON CONFLICT DO NOTHING
    $sql$, v_vertices_table, v_full_name, v_full_name);
    
    -- 更新统计
    EXECUTE format($sql$
        UPDATE %s v SET
            eout = (SELECT COUNT(*) FROM %s e WHERE e.source = v.id),
            ein = (SELECT COUNT(*) FROM %s e WHERE e.target = v.id)
    $sql$, v_vertices_table, v_full_name, v_full_name);
    
    EXECUTE format('UPDATE %s SET cnt = ein + eout', v_vertices_table);
    
    EXECUTE format('SELECT COUNT(*) FROM %s', v_vertices_table) INTO v_count;
    
    RETURN format('OK: %s vertices created in %s', v_count, v_vertices_table);
END;
$$ LANGUAGE plpgsql;

-- 分析路网
CREATE OR REPLACE FUNCTION otb_routing.analyze_graph(
    edge_table TEXT,
    schema_name TEXT DEFAULT 'public'
)
RETURNS TABLE(
    metric TEXT,
    value BIGINT
) AS $$
DECLARE
    v_full_name TEXT;
BEGIN
    v_full_name := quote_ident(schema_name) || '.' || quote_ident(edge_table);
    
    RETURN QUERY EXECUTE format($sql$
        SELECT 'total_edges'::TEXT, COUNT(*)::BIGINT FROM %s
        UNION ALL
        SELECT 'unique_sources', COUNT(DISTINCT source) FROM %s
        UNION ALL
        SELECT 'unique_targets', COUNT(DISTINCT target) FROM %s
        UNION ALL
        SELECT 'bidirectional_edges', COUNT(*) FROM %s WHERE reverse_cost >= 0
        UNION ALL
        SELECT 'oneway_edges', COUNT(*) FROM %s WHERE reverse_cost < 0
    $sql$, v_full_name, v_full_name, v_full_name, v_full_name, v_full_name);
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 4. 路网分析函数
-- ============================================================================

-- 找到最近的节点
CREATE OR REPLACE FUNCTION otb_routing.find_nearest_node(
    edge_table TEXT,
    x DOUBLE PRECISION,
    y DOUBLE PRECISION,
    schema_name TEXT DEFAULT 'public'
)
RETURNS BIGINT AS $$
DECLARE
    v_full_name TEXT;
    v_node_id BIGINT;
BEGIN
    v_full_name := quote_ident(schema_name) || '.' || quote_ident(edge_table);
    
    EXECUTE format($sql$
        SELECT source 
        FROM %s
        WHERE x1 IS NOT NULL AND y1 IS NOT NULL
        ORDER BY sqrt(power(x1 - $1, 2) + power(y1 - $2, 2))
        LIMIT 1
    $sql$, v_full_name)
    INTO v_node_id
    USING x, y;
    
    RETURN v_node_id;
END;
$$ LANGUAGE plpgsql;

-- 计算两点间距离（欧几里得）
CREATE OR REPLACE FUNCTION otb_routing.distance(
    x1 DOUBLE PRECISION,
    y1 DOUBLE PRECISION,
    x2 DOUBLE PRECISION,
    y2 DOUBLE PRECISION
)
RETURNS DOUBLE PRECISION AS $$
BEGIN
    RETURN sqrt(power(x2 - x1, 2) + power(y2 - y1, 2));
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 计算路径总长度
CREATE OR REPLACE FUNCTION otb_routing.path_length(
    edge_table TEXT,
    path_nodes BIGINT[]
)
RETURNS DOUBLE PRECISION AS $$
DECLARE
    v_total DOUBLE PRECISION := 0;
    v_cost DOUBLE PRECISION;
    i INTEGER;
BEGIN
    IF array_length(path_nodes, 1) < 2 THEN
        RETURN 0;
    END IF;
    
    -- 遍历连续节点对，查找边的cost
    FOR i IN 1 .. array_length(path_nodes, 1) - 1
    LOOP
        EXECUTE format($sql$
            SELECT COALESCE(cost, 0) 
            FROM %I 
            WHERE (source = $1 AND target = $2) 
               OR (source = $2 AND target = $1)
            LIMIT 1
        $sql$, edge_table)
        INTO v_cost
        USING path_nodes[i], path_nodes[i+1];
        
        v_total := v_total + COALESCE(v_cost, 0);
    END LOOP;
    
    RETURN v_total;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 5. 路网统计视图
-- ============================================================================

-- 创建路网统计函数
CREATE OR REPLACE FUNCTION otb_routing.network_stats(
    edge_table TEXT,
    schema_name TEXT DEFAULT 'public'
)
RETURNS TABLE(
    total_edges BIGINT,
    total_vertices BIGINT,
    avg_degree DOUBLE PRECISION,
    total_length DOUBLE PRECISION,
    avg_edge_length DOUBLE PRECISION
) AS $$
DECLARE
    v_full_name TEXT;
BEGIN
    v_full_name := quote_ident(schema_name) || '.' || quote_ident(edge_table);
    
    RETURN QUERY EXECUTE format($sql$
        SELECT 
            COUNT(*)::BIGINT AS total_edges,
            (SELECT COUNT(DISTINCT v) FROM (
                SELECT source AS v FROM %s UNION SELECT target FROM %s
            ) t)::BIGINT AS total_vertices,
            (COUNT(*) * 2.0 / NULLIF((SELECT COUNT(DISTINCT v) FROM (
                SELECT source AS v FROM %s UNION SELECT target FROM %s
            ) t), 0)) AS avg_degree,
            COALESCE(SUM(length_m), 0) AS total_length,
            COALESCE(AVG(length_m), 0) AS avg_edge_length
        FROM %s
    $sql$, v_full_name, v_full_name, v_full_name, v_full_name, v_full_name);
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 安装完成提示
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '╔═══════════════════════════════════════════════════════════════════╗';
    RAISE NOTICE '║  otb_routing 1.0 安装成功！                                        ║';
    RAISE NOTICE '║  pgRouting 兼容层                                                 ║';
    RAISE NOTICE '╠═══════════════════════════════════════════════════════════════════╣';
    RAISE NOTICE '║                                                                   ║';
    RAISE NOTICE '║  路径计算函数:                                                    ║';
    RAISE NOTICE '║    • otb_routing.dijkstra(sql, start, end, directed)              ║';
    RAISE NOTICE '║    • otb_routing.driving_distance(sql, start, max_cost, directed) ║';
    RAISE NOTICE '║                                                                   ║';
    RAISE NOTICE '║  路网管理函数:                                                    ║';
    RAISE NOTICE '║    • otb_routing.create_road_network(table, schema)               ║';
    RAISE NOTICE '║    • otb_routing.create_topology(table, tolerance, schema)        ║';
    RAISE NOTICE '║    • otb_routing.analyze_graph(table, schema)                     ║';
    RAISE NOTICE '║                                                                   ║';
    RAISE NOTICE '║  辅助函数:                                                        ║';
    RAISE NOTICE '║    • otb_routing.find_nearest_node(table, x, y, schema)           ║';
    RAISE NOTICE '║    • otb_routing.distance(x1, y1, x2, y2)                         ║';
    RAISE NOTICE '║    • otb_routing.network_stats(table, schema)                     ║';
    RAISE NOTICE '╚═══════════════════════════════════════════════════════════════════╝';
    RAISE NOTICE '';
END $$;



-- 为缺少version函数的模块添加函数定义
-- otb_routing.version()
CREATE OR REPLACE FUNCTION otb_routing.version()
RETURNS TEXT AS $$
BEGIN
    RETURN '1.0.0 - OpenTenBase Routing (pgRouting compatible)';
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- otb_scheduler.version()
CREATE OR REPLACE FUNCTION otb_scheduler.version()
RETURNS TEXT AS $$
BEGIN
    RETURN '1.0.0 - OpenTenBase Scheduler (pg_cron + pg_partman compatible)';
END;
$$ LANGUAGE plpgsql IMMUTABLE;


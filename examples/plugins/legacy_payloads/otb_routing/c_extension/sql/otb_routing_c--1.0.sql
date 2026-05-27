-- ============================================================================
-- otb_routing_c - 高性能路网算法C扩展
-- pgRouting兼容实现
-- ============================================================================

-- Dijkstra最短路径（C实现）
CREATE OR REPLACE FUNCTION dijkstra_c(
    edges_sql TEXT,
    start_vid BIGINT,
    end_vid BIGINT,
    directed BOOLEAN DEFAULT true
)
RETURNS TABLE(
    seq INTEGER,
    node BIGINT,
    edge BIGINT,
    cost DOUBLE PRECISION,
    agg_cost DOUBLE PRECISION
) AS 'otb_routing_c', 'dijkstra_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION dijkstra_c IS 'Dijkstra shortest path algorithm (C implementation, pgRouting compatible)';

-- 驾驶距离/等时圈（C实现）
CREATE OR REPLACE FUNCTION driving_distance_c(
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
) AS 'otb_routing_c', 'driving_distance_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION driving_distance_c IS 'Driving distance (isochrone) calculation (C implementation)';

-- ============================================================================
-- A* 启发式最短路径（C实现）
-- ============================================================================

CREATE OR REPLACE FUNCTION astar_c(
    edges_sql TEXT,
    start_vid BIGINT,
    end_vid BIGINT,
    directed BOOLEAN DEFAULT true,
    heuristic DOUBLE PRECISION DEFAULT 1.0
)
RETURNS TABLE(
    seq INTEGER,
    node BIGINT,
    edge BIGINT,
    cost DOUBLE PRECISION,
    agg_cost DOUBLE PRECISION
) AS 'otb_routing_c', 'astar_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION astar_c IS 'A* heuristic shortest path (C implementation). edges_sql needs x1,y1,x2,y2 columns for coordinates.';

-- ============================================================================
-- Bellman-Ford 最短路径（支持负权重）
-- ============================================================================

CREATE OR REPLACE FUNCTION bellman_ford_c(
    edges_sql TEXT,
    start_vid BIGINT,
    end_vid BIGINT,
    directed BOOLEAN DEFAULT true
)
RETURNS TABLE(
    seq INTEGER,
    node BIGINT,
    edge BIGINT,
    cost DOUBLE PRECISION,
    agg_cost DOUBLE PRECISION
) AS 'otb_routing_c', 'bellman_ford_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION bellman_ford_c IS 'Bellman-Ford shortest path (C implementation). Supports negative edge weights and detects negative cycles.';

-- ============================================================================
-- 距离计算函数（C实现）
-- ============================================================================

CREATE OR REPLACE FUNCTION euclidean_distance_c(
    x1 DOUBLE PRECISION,
    y1 DOUBLE PRECISION,
    x2 DOUBLE PRECISION,
    y2 DOUBLE PRECISION
)
RETURNS DOUBLE PRECISION AS 'otb_routing_c', 'euclidean_distance_c'
LANGUAGE C STRICT IMMUTABLE;

COMMENT ON FUNCTION euclidean_distance_c IS 'Euclidean distance calculation (C implementation)';

CREATE OR REPLACE FUNCTION manhattan_distance_c(
    x1 DOUBLE PRECISION,
    y1 DOUBLE PRECISION,
    x2 DOUBLE PRECISION,
    y2 DOUBLE PRECISION
)
RETURNS DOUBLE PRECISION AS 'otb_routing_c', 'manhattan_distance_c'
LANGUAGE C STRICT IMMUTABLE;

COMMENT ON FUNCTION manhattan_distance_c IS 'Manhattan distance calculation (C implementation)';

-- ============================================================================
-- 路径成本计算（C实现）
-- ============================================================================

CREATE OR REPLACE FUNCTION path_cost_c(
    table_name TEXT,
    path_nodes BIGINT[]
)
RETURNS DOUBLE PRECISION AS 'otb_routing_c', 'path_cost_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION path_cost_c IS 'Calculate total cost of a path through given nodes (C implementation)';

-- ============================================================================
-- 空间搜索函数（C实现）
-- ============================================================================

-- 查找最近节点（C实现）
CREATE OR REPLACE FUNCTION find_nearest_node_c(
    edges_sql TEXT,
    target_x DOUBLE PRECISION,
    target_y DOUBLE PRECISION,
    k INTEGER DEFAULT 1
)
RETURNS TABLE(
    node_id BIGINT,
    distance DOUBLE PRECISION,
    x DOUBLE PRECISION,
    y DOUBLE PRECISION
) AS 'otb_routing_c', 'find_nearest_node_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION find_nearest_node_c IS 'Find K nearest nodes to a point (C implementation). edges_sql needs x1,y1,x2,y2 columns.';

-- K最近邻搜索（C实现）
CREATE OR REPLACE FUNCTION knn_search_c(
    points_x DOUBLE PRECISION[],
    points_y DOUBLE PRECISION[],
    point_ids BIGINT[],
    query_x DOUBLE PRECISION,
    query_y DOUBLE PRECISION,
    k INTEGER DEFAULT 1
)
RETURNS TABLE(
    node_id BIGINT,
    distance DOUBLE PRECISION,
    x DOUBLE PRECISION,
    y DOUBLE PRECISION
) AS 'otb_routing_c', 'knn_search_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION knn_search_c IS 'K-Nearest Neighbors search (C implementation)';

-- ============================================================================
-- 安装完成提示
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '╔════════════════════════════════════════════════════════════════════╗';
    RAISE NOTICE '║  otb_routing_c 3.0 安装成功！                                       ║';
    RAISE NOTICE '║  pgRouting兼容高性能路网算法 - 完整版                               ║';
    RAISE NOTICE '╠════════════════════════════════════════════════════════════════════╣';
    RAISE NOTICE '║                                                                    ║';
    RAISE NOTICE '║  路径算法 (C实现):                                                 ║';
    RAISE NOTICE '║    • dijkstra_c(sql, start, end, directed)                         ║';
    RAISE NOTICE '║    • astar_c(sql, start, end, directed, heuristic)                 ║';
    RAISE NOTICE '║    • bellman_ford_c(sql, start, end, directed)                     ║';
    RAISE NOTICE '║    • driving_distance_c(sql, start, max_cost, directed)            ║';
    RAISE NOTICE '║                                                                    ║';
    RAISE NOTICE '║  距离函数 (C实现):                                                 ║';
    RAISE NOTICE '║    • euclidean_distance_c(x1, y1, x2, y2)                          ║';
    RAISE NOTICE '║    • manhattan_distance_c(x1, y1, x2, y2)                          ║';
    RAISE NOTICE '║    • path_cost_c(table_name, path_nodes[])                         ║';
    RAISE NOTICE '║                                                                    ║';
    RAISE NOTICE '║  空间搜索 (C实现) [新增]:                                          ║';
    RAISE NOTICE '║    • find_nearest_node_c(sql, x, y, k)      查找最近K个节点        ║';
    RAISE NOTICE '║    • knn_search_c(x[], y[], ids[], qx, qy, k) K近邻搜索            ║';
    RAISE NOTICE '║                                                                    ║';
    RAISE NOTICE '╚════════════════════════════════════════════════════════════════════╝';
    RAISE NOTICE '';
END $$;


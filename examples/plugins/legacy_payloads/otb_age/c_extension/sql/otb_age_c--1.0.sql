-- ============================================================================
-- otb_age_c - 高性能图算法C扩展
-- ============================================================================

-- BFS广度优先遍历（C实现，性能提升10-50倍）
CREATE OR REPLACE FUNCTION bfs_c(
    start_vertex_id BIGINT,
    graph_id INTEGER,
    max_depth INTEGER DEFAULT 3
)
RETURNS TABLE(
    vertex_id BIGINT,
    depth INTEGER,
    path BIGINT[]
) AS 'otb_age_c', 'bfs_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION bfs_c IS 'BFS breadth-first traversal (C implementation, 10-50x faster)';

-- 最短路径（C实现Dijkstra算法）
CREATE OR REPLACE FUNCTION shortest_path_c(
    start_id BIGINT,
    end_id BIGINT,
    graph_id INTEGER,
    max_depth INTEGER DEFAULT 10
)
RETURNS TABLE(
    path BIGINT[],
    path_length INTEGER,
    found BOOLEAN
) AS 'otb_age_c', 'shortest_path_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION shortest_path_c IS 'Shortest path using BFS (C implementation)';

-- 顶点度数（C实现）
CREATE OR REPLACE FUNCTION vertex_degree_c(
    vertex_id BIGINT,
    graph_id INTEGER
)
RETURNS INTEGER AS 'otb_age_c', 'vertex_degree_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION vertex_degree_c IS 'Get vertex degree (C implementation)';

-- 路径存在性检查（C实现，用于快速判断连通性）
CREATE OR REPLACE FUNCTION path_exists_c(
    start_id BIGINT,
    end_id BIGINT,
    graph_id INTEGER,
    max_depth INTEGER DEFAULT 10
)
RETURNS BOOLEAN AS 'otb_age_c', 'path_exists_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION path_exists_c IS 'Check if path exists between two vertices (C implementation)';

-- ============================================================================
-- 便捷包装函数（自动获取graph_id）
-- ============================================================================

-- BFS包装函数（通过图名获取graph_id）
CREATE OR REPLACE FUNCTION otb_age.bfs_fast(
    graph_name TEXT,
    start_vertex_id BIGINT,
    max_depth INTEGER DEFAULT 3
)
RETURNS TABLE(
    vertex_id BIGINT,
    depth INTEGER,
    path BIGINT[]
) AS $$
DECLARE
    v_graph_id INTEGER;
BEGIN
    SELECT id INTO v_graph_id FROM otb_age.graphs WHERE name = graph_name;
    IF v_graph_id IS NULL THEN
        RAISE EXCEPTION 'Graph "%" does not exist', graph_name;
    END IF;
    
    RETURN QUERY SELECT * FROM bfs_c(start_vertex_id, v_graph_id, max_depth);
END;
$$ LANGUAGE plpgsql;

-- 最短路径包装函数
CREATE OR REPLACE FUNCTION otb_age.shortest_path_fast(
    graph_name TEXT,
    start_vertex_id BIGINT,
    end_vertex_id BIGINT,
    max_depth INTEGER DEFAULT 10
)
RETURNS TABLE(
    path BIGINT[],
    path_length INTEGER,
    found BOOLEAN
) AS $$
DECLARE
    v_graph_id INTEGER;
BEGIN
    SELECT id INTO v_graph_id FROM otb_age.graphs WHERE name = graph_name;
    IF v_graph_id IS NULL THEN
        RAISE EXCEPTION 'Graph "%" does not exist', graph_name;
    END IF;
    
    RETURN QUERY SELECT * FROM shortest_path_c(start_vertex_id, end_vertex_id, v_graph_id, max_depth);
END;
$$ LANGUAGE plpgsql;

-- 路径存在性检查包装函数
CREATE OR REPLACE FUNCTION otb_age.path_exists_fast(
    graph_name TEXT,
    start_vertex_id BIGINT,
    end_vertex_id BIGINT,
    max_depth INTEGER DEFAULT 10
)
RETURNS BOOLEAN AS $$
DECLARE
    v_graph_id INTEGER;
BEGIN
    SELECT id INTO v_graph_id FROM otb_age.graphs WHERE name = graph_name;
    IF v_graph_id IS NULL THEN
        RAISE EXCEPTION 'Graph "%" does not exist', graph_name;
    END IF;
    
    RETURN path_exists_c(start_vertex_id, end_vertex_id, v_graph_id, max_depth);
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 新增高级图算法 (C实现)
-- ============================================================================

-- PageRank算法（C实现）
CREATE OR REPLACE FUNCTION pagerank_c(
    graph_name TEXT,
    damping DOUBLE PRECISION DEFAULT 0.85,
    max_iterations INTEGER DEFAULT 20,
    tolerance DOUBLE PRECISION DEFAULT 0.0001
)
RETURNS TABLE(
    vertex_id BIGINT,
    rank DOUBLE PRECISION
) AS 'otb_age_c', 'pagerank_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION pagerank_c IS 'PageRank algorithm (C implementation). Returns vertex importance scores.';

-- 度中心性（C实现）
CREATE OR REPLACE FUNCTION degree_centrality_c(
    graph_name TEXT,
    mode TEXT DEFAULT 'both'  -- 'in', 'out', 'both'
)
RETURNS TABLE(
    vertex_id BIGINT,
    centrality DOUBLE PRECISION
) AS 'otb_age_c', 'degree_centrality_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION degree_centrality_c IS 'Degree centrality (C implementation). Mode: in/out/both';

-- Jaccard相似度（C实现）
CREATE OR REPLACE FUNCTION jaccard_similarity_c(
    graph_name TEXT,
    node1 BIGINT,
    node2 BIGINT
)
RETURNS DOUBLE PRECISION AS 'otb_age_c', 'jaccard_similarity_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION jaccard_similarity_c IS 'Jaccard similarity between two nodes (C implementation)';

-- 共同邻居数（C实现）
CREATE OR REPLACE FUNCTION common_neighbors_c(
    graph_name TEXT,
    node1 BIGINT,
    node2 BIGINT
)
RETURNS INTEGER AS 'otb_age_c', 'common_neighbors_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION common_neighbors_c IS 'Count common neighbors (C implementation, for link prediction)';

-- 三角形计数（C实现）
CREATE OR REPLACE FUNCTION triangle_count_c(
    graph_name TEXT
)
RETURNS BIGINT AS 'otb_age_c', 'triangle_count_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION triangle_count_c IS 'Count triangles in graph (C implementation)';

-- 连通分量计算（C实现，Union-Find算法）
CREATE OR REPLACE FUNCTION connected_components_c(
    graph_name TEXT
)
RETURNS TABLE(
    vertex_id BIGINT,
    component_id INTEGER
) AS 'otb_age_c', 'connected_components_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION connected_components_c IS 'Find connected components using Union-Find (C implementation, 10-50x faster than SQL)';

-- 度分布统计（C实现）
CREATE OR REPLACE FUNCTION degree_distribution_c(
    graph_name TEXT
)
RETURNS TABLE(
    degree INTEGER,
    node_count BIGINT
) AS 'otb_age_c', 'degree_distribution_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION degree_distribution_c IS 'Calculate degree distribution (C implementation)';

-- ============================================================================
-- 安装完成提示
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '╔════════════════════════════════════════════════════════════════════╗';
    RAISE NOTICE '║  otb_age_c 2.0 安装成功！                                          ║';
    RAISE NOTICE '║  高性能图算法C扩展 - 增强版                                        ║';
    RAISE NOTICE '╠════════════════════════════════════════════════════════════════════╣';
    RAISE NOTICE '║  基础图算法（C实现）：                                             ║';
    RAISE NOTICE '║    • bfs_c(vertex, graph_id, depth)                                ║';
    RAISE NOTICE '║    • shortest_path_c(start, end, graph_id, depth)                  ║';
    RAISE NOTICE '║    • vertex_degree_c(vertex, graph_id)                             ║';
    RAISE NOTICE '║    • path_exists_c(start, end, graph_id, depth)                    ║';
    RAISE NOTICE '║                                                                    ║';
    RAISE NOTICE '║  高级图算法（C实现）：                                               ║';
    RAISE NOTICE '║    • pagerank_c(graph, damping, iterations, tolerance)             ║';
    RAISE NOTICE '║    • degree_centrality_c(graph, mode)                              ║';
    RAISE NOTICE '║    • jaccard_similarity_c(graph, node1, node2)                     ║';
    RAISE NOTICE '║    • common_neighbors_c(graph, node1, node2)                       ║';
    RAISE NOTICE '║    • triangle_count_c(graph)                                       ║';
    RAISE NOTICE '║    • connected_components_c(graph)          [新增-Union-Find]      ║';
    RAISE NOTICE '║    • degree_distribution_c(graph)           [新增]                 ║';
    RAISE NOTICE '║                                                                    ║';
    RAISE NOTICE '║  便捷函数（通过图名调用）：                                        ║';
    RAISE NOTICE '║    • otb_age.bfs_fast(graph_name, vertex, depth)                   ║';
    RAISE NOTICE '║    • otb_age.shortest_path_fast(graph, start, end, depth)          ║';
    RAISE NOTICE '║    • otb_age.path_exists_fast(graph, start, end, depth)            ║';
    RAISE NOTICE '╚════════════════════════════════════════════════════════════════════╝';
    RAISE NOTICE '';
END $$;


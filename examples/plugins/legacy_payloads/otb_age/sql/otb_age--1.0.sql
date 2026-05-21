-- ============================================================================
-- OpenTenBase AGE Adapter (otb_age) - Apache AGE 兼容层
-- 版本: 1.0.0
-- 描述: 为OpenTenBase提供图数据库能力，兼容Apache AGE核心API
-- ============================================================================

-- 清理旧对象
DROP SCHEMA IF EXISTS otb_age CASCADE;
DROP SCHEMA IF EXISTS ag_catalog CASCADE;

-- 创建schema
CREATE SCHEMA otb_age;
CREATE SCHEMA ag_catalog;  -- AGE兼容schema

-- ============================================================================
-- 第1部分：元数据表（OpenTenBase分布式兼容 - 不使用外键）
-- ============================================================================

-- 图定义表
CREATE TABLE otb_age.graphs (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    namespace TEXT DEFAULT 'public',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    description TEXT
) DISTRIBUTE BY REPLICATION;

-- 顶点标签定义（不使用外键，改用应用层校验）
CREATE TABLE otb_age.vertex_labels (
    id SERIAL PRIMARY KEY,
    graph_id INTEGER NOT NULL,  -- 逻辑外键，引用graphs.id
    name TEXT NOT NULL,
    properties JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(graph_id, name)
) DISTRIBUTE BY REPLICATION;

-- 边标签定义
CREATE TABLE otb_age.edge_labels (
    id SERIAL PRIMARY KEY,
    graph_id INTEGER NOT NULL,  -- 逻辑外键，引用graphs.id
    name TEXT NOT NULL,
    properties JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(graph_id, name)
) DISTRIBUTE BY REPLICATION;

-- 顶点数据表
CREATE TABLE otb_age.vertices (
    id BIGSERIAL PRIMARY KEY,
    graph_id INTEGER NOT NULL,   -- 逻辑外键，引用graphs.id
    label_id INTEGER NOT NULL,   -- 逻辑外键，引用vertex_labels.id
    properties JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
) DISTRIBUTE BY REPLICATION;

-- 边数据表
CREATE TABLE otb_age.edges (
    id BIGSERIAL PRIMARY KEY,
    graph_id INTEGER NOT NULL,   -- 逻辑外键，引用graphs.id
    label_id INTEGER NOT NULL,   -- 逻辑外键，引用edge_labels.id
    start_id BIGINT NOT NULL,    -- 逻辑外键，引用vertices.id
    end_id BIGINT NOT NULL,      -- 逻辑外键，引用vertices.id
    properties JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
) DISTRIBUTE BY REPLICATION;

-- 创建索引
CREATE INDEX idx_vertex_labels_graph ON otb_age.vertex_labels(graph_id);
CREATE INDEX idx_edge_labels_graph ON otb_age.edge_labels(graph_id);
CREATE INDEX idx_vertices_graph ON otb_age.vertices(graph_id);
CREATE INDEX idx_vertices_label ON otb_age.vertices(label_id);
CREATE INDEX idx_vertices_properties ON otb_age.vertices USING GIN(properties);
CREATE INDEX idx_edges_graph ON otb_age.edges(graph_id);
CREATE INDEX idx_edges_label ON otb_age.edges(label_id);
CREATE INDEX idx_edges_start ON otb_age.edges(start_id);
CREATE INDEX idx_edges_end ON otb_age.edges(end_id);
CREATE INDEX idx_edges_properties ON otb_age.edges USING GIN(properties);

-- ============================================================================
-- 第2部分：图管理函数
-- ============================================================================

-- 创建图
CREATE OR REPLACE FUNCTION otb_age.create_graph(graph_name TEXT, description TEXT DEFAULT NULL)
RETURNS TABLE(graph_id INTEGER, name TEXT, created BOOLEAN) AS $$
DECLARE
    v_graph_id INTEGER;
    v_exists BOOLEAN;
BEGIN
    SELECT EXISTS(SELECT 1 FROM otb_age.graphs WHERE graphs.name = graph_name) INTO v_exists;
    
    IF v_exists THEN
        SELECT g.id INTO v_graph_id FROM otb_age.graphs g WHERE g.name = graph_name;
        RETURN QUERY SELECT v_graph_id, graph_name, FALSE;
    ELSE
        INSERT INTO otb_age.graphs (name, description) 
        VALUES (graph_name, description)
        RETURNING id INTO v_graph_id;
        
        RAISE NOTICE 'Graph "%" created successfully', graph_name;
        RETURN QUERY SELECT v_graph_id, graph_name, TRUE;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- 删除图（级联删除所有相关数据）
CREATE OR REPLACE FUNCTION otb_age.drop_graph(graph_name TEXT, cascade_flag BOOLEAN DEFAULT FALSE)
RETURNS BOOLEAN AS $$
DECLARE
    v_graph_id INTEGER;
    v_vertex_count INTEGER;
    v_edge_count INTEGER;
BEGIN
    SELECT id INTO v_graph_id FROM otb_age.graphs WHERE name = graph_name;
    
    IF v_graph_id IS NULL THEN
        RAISE EXCEPTION 'Graph "%" does not exist', graph_name;
    END IF;
    
    SELECT COUNT(*) INTO v_vertex_count FROM otb_age.vertices WHERE graph_id = v_graph_id;
    SELECT COUNT(*) INTO v_edge_count FROM otb_age.edges WHERE graph_id = v_graph_id;
    
    IF (v_vertex_count > 0 OR v_edge_count > 0) AND NOT cascade_flag THEN
        RAISE EXCEPTION 'Graph "%" is not empty (% vertices, % edges). Use cascade=true to force drop', 
            graph_name, v_vertex_count, v_edge_count;
    END IF;
    
    -- 手动级联删除（因为没有外键）
    DELETE FROM otb_age.edges WHERE graph_id = v_graph_id;
    DELETE FROM otb_age.vertices WHERE graph_id = v_graph_id;
    DELETE FROM otb_age.edge_labels WHERE graph_id = v_graph_id;
    DELETE FROM otb_age.vertex_labels WHERE graph_id = v_graph_id;
    DELETE FROM otb_age.graphs WHERE id = v_graph_id;
    
    RAISE NOTICE 'Graph "%" dropped (% vertices, % edges removed)', graph_name, v_vertex_count, v_edge_count;
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- 列出所有图
CREATE OR REPLACE FUNCTION otb_age.list_graphs()
RETURNS TABLE(
    graph_id INTEGER, 
    name TEXT, 
    vertex_count BIGINT, 
    edge_count BIGINT, 
    created_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        g.id,
        g.name,
        COALESCE((SELECT COUNT(*) FROM otb_age.vertices v WHERE v.graph_id = g.id), 0),
        COALESCE((SELECT COUNT(*) FROM otb_age.edges e WHERE e.graph_id = g.id), 0),
        g.created_at
    FROM otb_age.graphs g
    ORDER BY g.name;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 第3部分：标签管理函数
-- ============================================================================

-- 创建顶点标签
CREATE OR REPLACE FUNCTION otb_age.create_vlabel(graph_name TEXT, label_name TEXT)
RETURNS INTEGER AS $$
DECLARE
    v_graph_id INTEGER;
    v_label_id INTEGER;
BEGIN
    SELECT id INTO v_graph_id FROM otb_age.graphs WHERE name = graph_name;
    IF v_graph_id IS NULL THEN
        RAISE EXCEPTION 'Graph "%" does not exist', graph_name;
    END IF;
    
    INSERT INTO otb_age.vertex_labels (graph_id, name)
    VALUES (v_graph_id, label_name)
    ON CONFLICT (graph_id, name) DO UPDATE SET name = EXCLUDED.name
    RETURNING id INTO v_label_id;
    
    RETURN v_label_id;
END;
$$ LANGUAGE plpgsql;

-- 创建边标签
CREATE OR REPLACE FUNCTION otb_age.create_elabel(graph_name TEXT, label_name TEXT)
RETURNS INTEGER AS $$
DECLARE
    v_graph_id INTEGER;
    v_label_id INTEGER;
BEGIN
    SELECT id INTO v_graph_id FROM otb_age.graphs WHERE name = graph_name;
    IF v_graph_id IS NULL THEN
        RAISE EXCEPTION 'Graph "%" does not exist', graph_name;
    END IF;
    
    INSERT INTO otb_age.edge_labels (graph_id, name)
    VALUES (v_graph_id, label_name)
    ON CONFLICT (graph_id, name) DO UPDATE SET name = EXCLUDED.name
    RETURNING id INTO v_label_id;
    
    RETURN v_label_id;
END;
$$ LANGUAGE plpgsql;

-- 列出顶点标签
CREATE OR REPLACE FUNCTION otb_age.list_vlabels(graph_name TEXT)
RETURNS TABLE(label_id INTEGER, label_name TEXT, vertex_count BIGINT) AS $$
DECLARE
    v_graph_id INTEGER;
BEGIN
    SELECT id INTO v_graph_id FROM otb_age.graphs WHERE name = graph_name;
    IF v_graph_id IS NULL THEN
        RAISE EXCEPTION 'Graph "%" does not exist', graph_name;
    END IF;
    
    RETURN QUERY
    SELECT 
        vl.id,
        vl.name,
        COALESCE((SELECT COUNT(*) FROM otb_age.vertices v WHERE v.label_id = vl.id), 0)
    FROM otb_age.vertex_labels vl
    WHERE vl.graph_id = v_graph_id
    ORDER BY vl.name;
END;
$$ LANGUAGE plpgsql;

-- 列出边标签
CREATE OR REPLACE FUNCTION otb_age.list_elabels(graph_name TEXT)
RETURNS TABLE(label_id INTEGER, label_name TEXT, edge_count BIGINT) AS $$
DECLARE
    v_graph_id INTEGER;
BEGIN
    SELECT id INTO v_graph_id FROM otb_age.graphs WHERE name = graph_name;
    IF v_graph_id IS NULL THEN
        RAISE EXCEPTION 'Graph "%" does not exist', graph_name;
    END IF;
    
    RETURN QUERY
    SELECT 
        el.id,
        el.name,
        COALESCE((SELECT COUNT(*) FROM otb_age.edges e WHERE e.label_id = el.id), 0)
    FROM otb_age.edge_labels el
    WHERE el.graph_id = v_graph_id
    ORDER BY el.name;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 第4部分：顶点和边操作函数
-- ============================================================================

-- 添加顶点
CREATE OR REPLACE FUNCTION otb_age.add_vertex(
    graph_name TEXT, 
    label_name TEXT, 
    properties JSONB DEFAULT '{}'
)
RETURNS BIGINT AS $$
DECLARE
    v_graph_id INTEGER;
    v_label_id INTEGER;
    v_vertex_id BIGINT;
BEGIN
    SELECT id INTO v_graph_id FROM otb_age.graphs WHERE name = graph_name;
    IF v_graph_id IS NULL THEN
        RAISE EXCEPTION 'Graph "%" does not exist', graph_name;
    END IF;
    
    SELECT id INTO v_label_id FROM otb_age.vertex_labels 
    WHERE graph_id = v_graph_id AND name = label_name;
    
    IF v_label_id IS NULL THEN
        -- 自动创建标签
        INSERT INTO otb_age.vertex_labels (graph_id, name) VALUES (v_graph_id, label_name)
        RETURNING id INTO v_label_id;
    END IF;
    
    INSERT INTO otb_age.vertices (graph_id, label_id, properties)
    VALUES (v_graph_id, v_label_id, properties)
    RETURNING id INTO v_vertex_id;
    
    RETURN v_vertex_id;
END;
$$ LANGUAGE plpgsql;

-- 批量添加顶点
CREATE OR REPLACE FUNCTION otb_age.add_vertices(
    graph_name TEXT,
    label_name TEXT,
    properties_array JSONB[]
)
RETURNS INTEGER AS $$
DECLARE
    v_graph_id INTEGER;
    v_label_id INTEGER;
    v_count INTEGER := 0;
    v_props JSONB;
BEGIN
    SELECT id INTO v_graph_id FROM otb_age.graphs WHERE name = graph_name;
    IF v_graph_id IS NULL THEN
        RAISE EXCEPTION 'Graph "%" does not exist', graph_name;
    END IF;
    
    SELECT id INTO v_label_id FROM otb_age.vertex_labels 
    WHERE graph_id = v_graph_id AND name = label_name;
    
    IF v_label_id IS NULL THEN
        INSERT INTO otb_age.vertex_labels (graph_id, name) VALUES (v_graph_id, label_name)
        RETURNING id INTO v_label_id;
    END IF;
    
    FOREACH v_props IN ARRAY properties_array LOOP
        INSERT INTO otb_age.vertices (graph_id, label_id, properties)
        VALUES (v_graph_id, v_label_id, v_props);
        v_count := v_count + 1;
    END LOOP;
    
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- 添加边
CREATE OR REPLACE FUNCTION otb_age.add_edge(
    graph_name TEXT,
    start_vertex_id BIGINT,
    end_vertex_id BIGINT,
    label_name TEXT,
    properties JSONB DEFAULT '{}'
)
RETURNS BIGINT AS $$
DECLARE
    v_graph_id INTEGER;
    v_label_id INTEGER;
    v_edge_id BIGINT;
BEGIN
    SELECT id INTO v_graph_id FROM otb_age.graphs WHERE name = graph_name;
    IF v_graph_id IS NULL THEN
        RAISE EXCEPTION 'Graph "%" does not exist', graph_name;
    END IF;
    
    -- 验证顶点存在
    IF NOT EXISTS(SELECT 1 FROM otb_age.vertices WHERE id = start_vertex_id AND graph_id = v_graph_id) THEN
        RAISE EXCEPTION 'Start vertex % does not exist in graph "%"', start_vertex_id, graph_name;
    END IF;
    
    IF NOT EXISTS(SELECT 1 FROM otb_age.vertices WHERE id = end_vertex_id AND graph_id = v_graph_id) THEN
        RAISE EXCEPTION 'End vertex % does not exist in graph "%"', end_vertex_id, graph_name;
    END IF;
    
    SELECT id INTO v_label_id FROM otb_age.edge_labels 
    WHERE graph_id = v_graph_id AND name = label_name;
    
    IF v_label_id IS NULL THEN
        INSERT INTO otb_age.edge_labels (graph_id, name) VALUES (v_graph_id, label_name)
        RETURNING id INTO v_label_id;
    END IF;
    
    INSERT INTO otb_age.edges (graph_id, label_id, start_id, end_id, properties)
    VALUES (v_graph_id, v_label_id, start_vertex_id, end_vertex_id, properties)
    RETURNING id INTO v_edge_id;
    
    RETURN v_edge_id;
END;
$$ LANGUAGE plpgsql;

-- 删除顶点
CREATE OR REPLACE FUNCTION otb_age.delete_vertex(vertex_id BIGINT, cascade_edges BOOLEAN DEFAULT TRUE)
RETURNS BOOLEAN AS $$
BEGIN
    IF cascade_edges THEN
        DELETE FROM otb_age.edges WHERE start_id = vertex_id OR end_id = vertex_id;
    ELSE
        IF EXISTS(SELECT 1 FROM otb_age.edges WHERE start_id = vertex_id OR end_id = vertex_id) THEN
            RAISE EXCEPTION 'Vertex % has connected edges. Use cascade_edges=true to delete', vertex_id;
        END IF;
    END IF;
    
    DELETE FROM otb_age.vertices WHERE id = vertex_id;
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- 删除边
CREATE OR REPLACE FUNCTION otb_age.delete_edge(edge_id BIGINT)
RETURNS BOOLEAN AS $$
BEGIN
    DELETE FROM otb_age.edges WHERE id = edge_id;
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- 更新顶点属性
CREATE OR REPLACE FUNCTION otb_age.set_vertex_property(
    vertex_id BIGINT,
    key TEXT,
    value JSONB
)
RETURNS BOOLEAN AS $$
BEGIN
    UPDATE otb_age.vertices 
    SET properties = properties || jsonb_build_object(key, value)
    WHERE id = vertex_id;
    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- 更新边属性
CREATE OR REPLACE FUNCTION otb_age.set_edge_property(
    edge_id BIGINT,
    key TEXT,
    value JSONB
)
RETURNS BOOLEAN AS $$
BEGIN
    UPDATE otb_age.edges 
    SET properties = properties || jsonb_build_object(key, value)
    WHERE id = edge_id;
    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 第5部分：图查询函数
-- ============================================================================

-- 获取顶点
CREATE OR REPLACE FUNCTION otb_age.get_vertex(vertex_id BIGINT)
RETURNS TABLE(
    id BIGINT,
    label TEXT,
    properties JSONB,
    created_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT v.id, vl.name, v.properties, v.created_at
    FROM otb_age.vertices v
    JOIN otb_age.vertex_labels vl ON v.label_id = vl.id
    WHERE v.id = vertex_id;
END;
$$ LANGUAGE plpgsql;

-- 查询顶点（按标签）
CREATE OR REPLACE FUNCTION otb_age.match_vertices(
    graph_name TEXT,
    label_name TEXT DEFAULT NULL,
    filter_properties JSONB DEFAULT NULL
)
RETURNS TABLE(
    vertex_id BIGINT,
    label TEXT,
    properties JSONB
) AS $$
DECLARE
    v_graph_id INTEGER;
BEGIN
    SELECT id INTO v_graph_id FROM otb_age.graphs WHERE name = graph_name;
    IF v_graph_id IS NULL THEN
        RAISE EXCEPTION 'Graph "%" does not exist', graph_name;
    END IF;
    
    RETURN QUERY
    SELECT v.id, vl.name, v.properties
    FROM otb_age.vertices v
    JOIN otb_age.vertex_labels vl ON v.label_id = vl.id
    WHERE v.graph_id = v_graph_id
      AND (label_name IS NULL OR vl.name = label_name)
      AND (filter_properties IS NULL OR v.properties @> filter_properties);
END;
$$ LANGUAGE plpgsql;

-- 查询边（按标签）
CREATE OR REPLACE FUNCTION otb_age.match_edges(
    graph_name TEXT,
    label_name TEXT DEFAULT NULL,
    filter_properties JSONB DEFAULT NULL
)
RETURNS TABLE(
    edge_id BIGINT,
    label TEXT,
    start_vertex BIGINT,
    end_vertex BIGINT,
    properties JSONB
) AS $$
DECLARE
    v_graph_id INTEGER;
BEGIN
    SELECT id INTO v_graph_id FROM otb_age.graphs WHERE name = graph_name;
    IF v_graph_id IS NULL THEN
        RAISE EXCEPTION 'Graph "%" does not exist', graph_name;
    END IF;
    
    RETURN QUERY
    SELECT e.id, el.name, e.start_id, e.end_id, e.properties
    FROM otb_age.edges e
    JOIN otb_age.edge_labels el ON e.label_id = el.id
    WHERE e.graph_id = v_graph_id
      AND (label_name IS NULL OR el.name = label_name)
      AND (filter_properties IS NULL OR e.properties @> filter_properties);
END;
$$ LANGUAGE plpgsql;

-- 获取顶点的邻居（修复参数名冲突）
CREATE OR REPLACE FUNCTION otb_age.get_neighbors(
    vertex_id BIGINT,
    direction TEXT DEFAULT 'both',  -- 'out', 'in', 'both'
    filter_edge_label TEXT DEFAULT NULL
)
RETURNS TABLE(
    neighbor_id BIGINT,
    neighbor_label TEXT,
    neighbor_properties JSONB,
    edge_id BIGINT,
    rel_label TEXT,
    edge_properties JSONB,
    rel_direction TEXT
) AS $$
BEGIN
    IF direction IN ('out', 'both') THEN
        RETURN QUERY
        SELECT 
            v.id, vl.name, v.properties,
            e.id, el.name, e.properties,
            'out'::TEXT
        FROM otb_age.edges e
        JOIN otb_age.vertices v ON e.end_id = v.id
        JOIN otb_age.vertex_labels vl ON v.label_id = vl.id
        JOIN otb_age.edge_labels el ON e.label_id = el.id
        WHERE e.start_id = vertex_id
          AND (filter_edge_label IS NULL OR el.name = filter_edge_label);
    END IF;
    
    IF direction IN ('in', 'both') THEN
        RETURN QUERY
        SELECT 
            v.id, vl.name, v.properties,
            e.id, el.name, e.properties,
            'in'::TEXT
        FROM otb_age.edges e
        JOIN otb_age.vertices v ON e.start_id = v.id
        JOIN otb_age.vertex_labels vl ON v.label_id = vl.id
        JOIN otb_age.edge_labels el ON e.label_id = el.id
        WHERE e.end_id = vertex_id
          AND (filter_edge_label IS NULL OR el.name = filter_edge_label);
    END IF;
END;
$$ LANGUAGE plpgsql;

-- 获取顶点的出度
CREATE OR REPLACE FUNCTION otb_age.out_degree(vertex_id BIGINT, filter_label TEXT DEFAULT NULL)
RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_count
    FROM otb_age.edges e
    LEFT JOIN otb_age.edge_labels el ON e.label_id = el.id
    WHERE e.start_id = vertex_id
      AND (filter_label IS NULL OR el.name = filter_label);
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- 获取顶点的入度
CREATE OR REPLACE FUNCTION otb_age.in_degree(vertex_id BIGINT, filter_label TEXT DEFAULT NULL)
RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_count
    FROM otb_age.edges e
    LEFT JOIN otb_age.edge_labels el ON e.label_id = el.id
    WHERE e.end_id = vertex_id
      AND (filter_label IS NULL OR el.name = filter_label);
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 第6部分：图算法
-- ============================================================================

-- BFS广度优先遍历
CREATE OR REPLACE FUNCTION otb_age.bfs(
    graph_name TEXT,
    start_vertex_id BIGINT,
    max_depth INTEGER DEFAULT 3,
    filter_edge_label TEXT DEFAULT NULL
)
RETURNS TABLE(
    vertex_id BIGINT,
    vertex_label TEXT,
    depth INTEGER,
    path BIGINT[]
) AS $$
DECLARE
    v_graph_id INTEGER;
BEGIN
    -- 获取图ID
    SELECT id INTO v_graph_id FROM otb_age.graphs WHERE name = graph_name;
    IF v_graph_id IS NULL THEN
        RAISE EXCEPTION 'Graph "%" does not exist', graph_name;
    END IF;

    RETURN QUERY
    WITH RECURSIVE bfs_traversal AS (
        -- 起始顶点
        SELECT 
            v.id AS vid,
            vl.name AS vlabel,
            0 AS d,
            ARRAY[v.id] AS p
        FROM otb_age.vertices v
        JOIN otb_age.vertex_labels vl ON v.label_id = vl.id
        WHERE v.id = start_vertex_id
          AND v.graph_id = v_graph_id
        
        UNION ALL
        
        -- 递归遍历
        SELECT 
            v.id,
            vl.name,
            bt.d + 1,
            bt.p || v.id
        FROM bfs_traversal bt
        JOIN otb_age.edges e ON e.start_id = bt.vid AND e.graph_id = v_graph_id
        JOIN otb_age.vertices v ON e.end_id = v.id AND v.graph_id = v_graph_id
        JOIN otb_age.vertex_labels vl ON v.label_id = vl.id
        LEFT JOIN otb_age.edge_labels el ON e.label_id = el.id
        WHERE bt.d < max_depth
          AND NOT v.id = ANY(bt.p)  -- 避免循环
          AND (filter_edge_label IS NULL OR el.name = filter_edge_label)
    )
    SELECT DISTINCT ON (vid) vid, vlabel, bfs_traversal.d, bfs_traversal.p
    FROM bfs_traversal
    ORDER BY vid, d;
END;
$$ LANGUAGE plpgsql;

-- 最短路径（Dijkstra算法，无权重）
CREATE OR REPLACE FUNCTION otb_age.shortest_path(
    graph_name TEXT,
    start_vertex_id BIGINT,
    end_vertex_id BIGINT,
    max_depth INTEGER DEFAULT 10,
    filter_edge_label TEXT DEFAULT NULL
)
RETURNS TABLE(
    path BIGINT[],
    path_length INTEGER,
    found BOOLEAN
) AS $$
DECLARE
    v_graph_id INTEGER;
    v_path BIGINT[];
    v_found BOOLEAN := FALSE;
BEGIN
    -- 获取图ID
    SELECT id INTO v_graph_id FROM otb_age.graphs WHERE name = graph_name;
    IF v_graph_id IS NULL THEN
        RAISE EXCEPTION 'Graph "%" does not exist', graph_name;
    END IF;

    WITH RECURSIVE path_search AS (
        SELECT 
            ARRAY[start_vertex_id] AS p,
            start_vertex_id AS current,
            0 AS d
        
        UNION ALL
        
        SELECT 
            ps.p || e.end_id,
            e.end_id,
            ps.d + 1
        FROM path_search ps
        JOIN otb_age.edges e ON e.start_id = ps.current AND e.graph_id = v_graph_id
        LEFT JOIN otb_age.edge_labels el ON e.label_id = el.id
        WHERE ps.d < max_depth
          AND NOT e.end_id = ANY(ps.p)
          AND (filter_edge_label IS NULL OR el.name = filter_edge_label)
    )
    SELECT ps.p INTO v_path
    FROM path_search ps
    WHERE ps.current = end_vertex_id
    ORDER BY array_length(ps.p, 1)
    LIMIT 1;
    
    IF v_path IS NOT NULL THEN
        v_found := TRUE;
        RETURN QUERY SELECT v_path, array_length(v_path, 1) - 1, v_found;
    ELSE
        RETURN QUERY SELECT NULL::BIGINT[], NULL::INTEGER, FALSE;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- 所有路径（限制数量）
CREATE OR REPLACE FUNCTION otb_age.all_paths(
    graph_name TEXT,
    start_vertex_id BIGINT,
    end_vertex_id BIGINT,
    max_depth INTEGER DEFAULT 5,
    max_paths INTEGER DEFAULT 10
)
RETURNS TABLE(
    path BIGINT[],
    path_length INTEGER
) AS $$
DECLARE
    v_graph_id INTEGER;
BEGIN
    -- 获取图ID
    SELECT id INTO v_graph_id FROM otb_age.graphs WHERE name = graph_name;
    IF v_graph_id IS NULL THEN
        RAISE EXCEPTION 'Graph "%" does not exist', graph_name;
    END IF;

    RETURN QUERY
    WITH RECURSIVE path_search AS (
        SELECT 
            ARRAY[start_vertex_id] AS p,
            start_vertex_id AS current,
            0 AS d
        
        UNION ALL
        
        SELECT 
            ps.p || e.end_id,
            e.end_id,
            ps.d + 1
        FROM path_search ps
        JOIN otb_age.edges e ON e.start_id = ps.current AND e.graph_id = v_graph_id
        WHERE ps.d < max_depth
          AND NOT e.end_id = ANY(ps.p)
    )
    SELECT ps.p, array_length(ps.p, 1) - 1
    FROM path_search ps
    WHERE ps.current = end_vertex_id
    ORDER BY array_length(ps.p, 1)
    LIMIT max_paths;
END;
$$ LANGUAGE plpgsql;

-- 连通分量（简化版）
CREATE OR REPLACE FUNCTION otb_age.connected_components(graph_name TEXT)
RETURNS TABLE(
    component_id INTEGER,
    vertex_count BIGINT
) AS $$
DECLARE
    v_graph_id INTEGER;
BEGIN
    SELECT id INTO v_graph_id FROM otb_age.graphs WHERE name = graph_name;
    IF v_graph_id IS NULL THEN
        RAISE EXCEPTION 'Graph "%" does not exist', graph_name;
    END IF;
    
    -- 简化实现：返回连通分量统计
    RETURN QUERY
    WITH RECURSIVE connected AS (
        SELECT 
            v.id AS vid,
            v.id AS root_id
        FROM otb_age.vertices v
        WHERE v.graph_id = v_graph_id
        
        UNION
        
        SELECT 
            CASE WHEN e.start_id = c.vid THEN e.end_id ELSE e.start_id END,
            LEAST(c.root_id, CASE WHEN e.start_id = c.vid THEN e.end_id ELSE e.start_id END)
        FROM connected c
        JOIN otb_age.edges e ON (e.start_id = c.vid OR e.end_id = c.vid)
        WHERE e.graph_id = v_graph_id
    ),
    final_roots AS (
        SELECT vid, MIN(root_id) AS final_root
        FROM connected
        GROUP BY vid
    )
    SELECT 
        ROW_NUMBER() OVER (ORDER BY final_root)::INTEGER AS comp_id,
        COUNT(*)::BIGINT AS v_count
    FROM final_roots
    GROUP BY final_root
    ORDER BY comp_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 第7部分：图统计函数
-- ============================================================================

-- 图统计信息
CREATE OR REPLACE FUNCTION otb_age.graph_stats(graph_name TEXT)
RETURNS TABLE(
    metric TEXT,
    value BIGINT
) AS $$
DECLARE
    v_graph_id INTEGER;
BEGIN
    SELECT id INTO v_graph_id FROM otb_age.graphs WHERE name = graph_name;
    IF v_graph_id IS NULL THEN
        RAISE EXCEPTION 'Graph "%" does not exist', graph_name;
    END IF;
    
    RETURN QUERY
    SELECT 'vertex_count'::TEXT, COUNT(*)::BIGINT FROM otb_age.vertices WHERE graph_id = v_graph_id
    UNION ALL
    SELECT 'edge_count'::TEXT, COUNT(*)::BIGINT FROM otb_age.edges WHERE graph_id = v_graph_id
    UNION ALL
    SELECT 'vertex_label_count'::TEXT, COUNT(*)::BIGINT FROM otb_age.vertex_labels WHERE graph_id = v_graph_id
    UNION ALL
    SELECT 'edge_label_count'::TEXT, COUNT(*)::BIGINT FROM otb_age.edge_labels WHERE graph_id = v_graph_id;
END;
$$ LANGUAGE plpgsql;

-- 度分布统计
CREATE OR REPLACE FUNCTION otb_age.degree_distribution(graph_name TEXT)
RETURNS TABLE(
    degree INTEGER,
    vertex_count BIGINT
) AS $$
DECLARE
    v_graph_id INTEGER;
BEGIN
    SELECT id INTO v_graph_id FROM otb_age.graphs WHERE name = graph_name;
    IF v_graph_id IS NULL THEN
        RAISE EXCEPTION 'Graph "%" does not exist', graph_name;
    END IF;
    
    RETURN QUERY
    WITH vertex_degrees AS (
        SELECT 
            v.id,
            COALESCE((SELECT COUNT(*) FROM otb_age.edges e WHERE e.start_id = v.id OR e.end_id = v.id), 0) AS deg
        FROM otb_age.vertices v
        WHERE v.graph_id = v_graph_id
    )
    SELECT deg::INTEGER, COUNT(*)
    FROM vertex_degrees
    GROUP BY deg
    ORDER BY deg;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 第8部分：Cypher兼容层（简化版）
-- ============================================================================

-- Cypher查询执行器（简化版，支持基本模式匹配）
CREATE OR REPLACE FUNCTION otb_age.cypher(
    graph_name TEXT,
    query TEXT
)
RETURNS SETOF JSONB AS $$
DECLARE
    v_graph_id INTEGER;
    v_label TEXT;
    v_where_clause TEXT;
    v_prop_name TEXT;
    v_prop_op TEXT;
    v_prop_val TEXT;
    v_count BIGINT;
BEGIN
    SELECT id INTO v_graph_id FROM otb_age.graphs WHERE name = graph_name;
    IF v_graph_id IS NULL THEN
        RAISE EXCEPTION 'Graph "%" does not exist', graph_name;
    END IF;
    
    -- 支持 RETURN count(n)
    IF query ~* 'RETURN\s+count\s*\(' THEN
        SELECT COUNT(*) INTO v_count
        FROM otb_age.vertices v
        WHERE v.graph_id = v_graph_id;
        
        RETURN QUERY SELECT jsonb_build_object('count', v_count);
        RETURN;
    END IF;
    
    -- 支持 MATCH (n:Label) WHERE n.prop > val RETURN n
    IF query ~* 'MATCH\s*\(\s*\w+\s*:\s*(\w+)\s*\)\s*WHERE\s+\w+\.(\w+)\s*(>|<|=|>=|<=)\s*(\d+)\s*RETURN' THEN
        v_label := substring(query from 'MATCH\s*\(\s*\w+\s*:\s*(\w+)\s*\)');
        v_prop_name := substring(query from 'WHERE\s+\w+\.(\w+)\s*[><=]');
        v_prop_op := substring(query from 'WHERE\s+\w+\.\w+\s*([><=]+)');
        v_prop_val := substring(query from 'WHERE\s+\w+\.\w+\s*[><=]+\s*(\d+)');
        
        RETURN QUERY
        SELECT jsonb_build_object(
            'id', v.id,
            'label', vl.name,
            'properties', v.properties
        )
        FROM otb_age.vertices v
        JOIN otb_age.vertex_labels vl ON v.label_id = vl.id
        WHERE v.graph_id = v_graph_id
          AND vl.name = v_label
          AND CASE 
                WHEN v_prop_op = '>' THEN (v.properties->>v_prop_name)::numeric > v_prop_val::numeric
                WHEN v_prop_op = '<' THEN (v.properties->>v_prop_name)::numeric < v_prop_val::numeric
                WHEN v_prop_op = '=' THEN (v.properties->>v_prop_name)::numeric = v_prop_val::numeric
                WHEN v_prop_op = '>=' THEN (v.properties->>v_prop_name)::numeric >= v_prop_val::numeric
                WHEN v_prop_op = '<=' THEN (v.properties->>v_prop_name)::numeric <= v_prop_val::numeric
                ELSE true
              END;
        RETURN;
    END IF;
    
    -- 简化的Cypher解析：支持 MATCH (n:Label) RETURN n
    IF query ~* 'MATCH\s*\(\s*\w+\s*:\s*(\w+)\s*\)\s*RETURN' THEN
        v_label := substring(query from 'MATCH\s*\(\s*\w+\s*:\s*(\w+)\s*\)');
        
        RETURN QUERY
        SELECT jsonb_build_object(
            'id', v.id,
            'label', vl.name,
            'properties', v.properties
        )
        FROM otb_age.vertices v
        JOIN otb_age.vertex_labels vl ON v.label_id = vl.id
        WHERE v.graph_id = v_graph_id
          AND vl.name = v_label;
    
    -- 支持 MATCH (n) RETURN n（返回所有顶点）
    ELSIF query ~* 'MATCH\s*\(\s*\w+\s*\)\s*RETURN' THEN
        RETURN QUERY
        SELECT jsonb_build_object(
            'id', v.id,
            'label', vl.name,
            'properties', v.properties
        )
        FROM otb_age.vertices v
        JOIN otb_age.vertex_labels vl ON v.label_id = vl.id
        WHERE v.graph_id = v_graph_id;
    
    -- 支持 MATCH (a)-[r]->(b) RETURN a,r,b（返回边关系）
    ELSIF query ~* 'MATCH\s*\(\s*\w+\s*\)\s*-\s*\[\s*\w*\s*\]\s*->\s*\(\s*\w+\s*\)\s*RETURN' THEN
        RETURN QUERY
        SELECT jsonb_build_object(
            'start', jsonb_build_object('id', sv.id, 'label', svl.name, 'properties', sv.properties),
            'edge', jsonb_build_object('id', e.id, 'label', el.name, 'properties', e.properties),
            'end', jsonb_build_object('id', ev.id, 'label', evl.name, 'properties', ev.properties)
        )
        FROM otb_age.edges e
        JOIN otb_age.vertices sv ON e.start_id = sv.id
        JOIN otb_age.vertices ev ON e.end_id = ev.id
        JOIN otb_age.vertex_labels svl ON sv.label_id = svl.id
        JOIN otb_age.vertex_labels evl ON ev.label_id = evl.id
        JOIN otb_age.edge_labels el ON e.label_id = el.id
        WHERE e.graph_id = v_graph_id;
    
    ELSE
        RAISE NOTICE 'Cypher query pattern not fully supported. Supported patterns:';
        RAISE NOTICE '  MATCH (n:Label) RETURN n';
        RAISE NOTICE '  MATCH (n:Label) WHERE n.prop > val RETURN n';
        RAISE NOTICE '  MATCH (n) RETURN n';
        RAISE NOTICE '  MATCH (n) RETURN count(n)';
        RAISE NOTICE '  MATCH (a)-[r]->(b) RETURN a,r,b';
        RETURN;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 第9部分：AGE兼容视图和别名
-- ============================================================================

-- 创建ag_catalog兼容视图
CREATE OR REPLACE VIEW ag_catalog.ag_graph AS
SELECT id AS graphid, name, namespace AS nsp
FROM otb_age.graphs;

CREATE OR REPLACE VIEW ag_catalog.ag_label AS
SELECT 
    vl.id AS labid,
    vl.name,
    vl.graph_id AS graph,
    'v'::char AS kind
FROM otb_age.vertex_labels vl
UNION ALL
SELECT 
    el.id AS labid,
    el.name,
    el.graph_id AS graph,
    'e'::char AS kind
FROM otb_age.edge_labels el;

-- 版本信息
CREATE OR REPLACE FUNCTION otb_age.version()
RETURNS TEXT AS $$
BEGIN
    RETURN 'otb_age 1.0.0 (Apache AGE compatible)';
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 第10部分：公共API别名（兼容AGE语法）
-- ============================================================================

-- 创建公共schema下的别名函数
CREATE OR REPLACE FUNCTION public.create_graph(graph_name TEXT)
RETURNS TABLE(graph_id INTEGER, name TEXT, created BOOLEAN) AS $$
    SELECT * FROM otb_age.create_graph(graph_name);
$$ LANGUAGE SQL;

CREATE OR REPLACE FUNCTION public.drop_graph(graph_name TEXT, cascade_flag BOOLEAN DEFAULT FALSE)
RETURNS BOOLEAN AS $$
    SELECT otb_age.drop_graph(graph_name, cascade_flag);
$$ LANGUAGE SQL;

-- ============================================================================
-- 安装完成提示
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '╔═══════════════════════════════════════════════════════════════╗';
    RAISE NOTICE '║  otb_age 1.0.0 安装成功！                                     ║';
    RAISE NOTICE '║  Apache AGE 兼容层 for OpenTenBase                            ║';
    RAISE NOTICE '╠═══════════════════════════════════════════════════════════════╣';
    RAISE NOTICE '║  核心功能：                                                   ║';
    RAISE NOTICE '║    • 图管理：create_graph, drop_graph, list_graphs            ║';
    RAISE NOTICE '║    • 标签管理：create_vlabel, create_elabel                   ║';
    RAISE NOTICE '║    • 顶点/边操作：add_vertex, add_edge, delete_*              ║';
    RAISE NOTICE '║    • 图查询：match_vertices, match_edges, get_neighbors       ║';
    RAISE NOTICE '║    • 图算法：bfs, shortest_path, all_paths                    ║';
    RAISE NOTICE '║    • Cypher兼容：cypher() 函数                                ║';
    RAISE NOTICE '╚═══════════════════════════════════════════════════════════════╝';
    RAISE NOTICE '';
END $$;

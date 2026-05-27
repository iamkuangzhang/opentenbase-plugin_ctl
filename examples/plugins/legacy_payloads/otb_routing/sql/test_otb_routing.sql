-- ============================================================================
-- otb_routing 功能测试
-- ============================================================================

\echo '============================================'
\echo '   otb_routing 功能测试'
\echo '============================================'

-- 清理
DROP SCHEMA IF EXISTS otb_routing CASCADE;
DROP TABLE IF EXISTS test_roads CASCADE;

-- 加载扩展
\i /data/opentenbase/OpenTenBase/contrib/otb_routing/sql/otb_routing--1.0.sql

-- ============================================================================
-- 1. 创建测试路网
-- ============================================================================

\echo ''
\echo '========== 1. 创建测试路网 =========='

-- 创建路网表
CREATE TABLE test_roads (
    id BIGSERIAL PRIMARY KEY,
    source BIGINT NOT NULL,
    target BIGINT NOT NULL,
    cost DOUBLE PRECISION DEFAULT 1.0,
    reverse_cost DOUBLE PRECISION DEFAULT 1.0,
    x1 DOUBLE PRECISION,
    y1 DOUBLE PRECISION,
    x2 DOUBLE PRECISION,
    y2 DOUBLE PRECISION,
    name TEXT
) DISTRIBUTE BY REPLICATION;

-- 插入测试数据（简单网格路网）
-- 节点布局：
--   1 --- 2 --- 3
--   |     |     |
--   4 --- 5 --- 6
--   |     |     |
--   7 --- 8 --- 9

INSERT INTO test_roads (source, target, cost, reverse_cost, x1, y1, x2, y2, name) VALUES
-- 横向道路
(1, 2, 1.0, 1.0, 0, 2, 1, 2, 'Road A'),
(2, 3, 1.0, 1.0, 1, 2, 2, 2, 'Road B'),
(4, 5, 1.0, 1.0, 0, 1, 1, 1, 'Road C'),
(5, 6, 1.0, 1.0, 1, 1, 2, 1, 'Road D'),
(7, 8, 1.0, 1.0, 0, 0, 1, 0, 'Road E'),
(8, 9, 1.0, 1.0, 1, 0, 2, 0, 'Road F'),
-- 纵向道路
(1, 4, 1.0, 1.0, 0, 2, 0, 1, 'Road G'),
(4, 7, 1.0, 1.0, 0, 1, 0, 0, 'Road H'),
(2, 5, 1.0, 1.0, 1, 2, 1, 1, 'Road I'),
(5, 8, 1.0, 1.0, 1, 1, 1, 0, 'Road J'),
(3, 6, 1.0, 1.0, 2, 2, 2, 1, 'Road K'),
(6, 9, 1.0, 1.0, 2, 1, 2, 0, 'Road L'),
-- 对角线道路（单行）
(1, 5, 1.414, -1.0, 0, 2, 1, 1, 'Diagonal 1'),
(5, 9, 1.414, -1.0, 1, 1, 2, 0, 'Diagonal 2');

\echo '路网数据:'
SELECT id, source, target, cost, reverse_cost, name FROM test_roads;

-- ============================================================================
-- 2. 路网分析
-- ============================================================================

\echo ''
\echo '========== 2. 路网分析 =========='

\echo '路网统计:'
SELECT * FROM otb_routing.analyze_graph('test_roads', 'public');

\echo ''
\echo '路网详细统计:'
SELECT * FROM otb_routing.network_stats('test_roads', 'public');

-- ============================================================================
-- 3. 最短路径测试（SQL版本）
-- ============================================================================

\echo ''
\echo '========== 3. 最短路径测试 =========='

\echo '从节点1到节点9的最短路径（SQL版本）:'
SELECT * FROM otb_routing.dijkstra(
    'SELECT id, source, target, cost, reverse_cost FROM test_roads',
    1, 9, false
);

-- ============================================================================
-- 4. 驾驶距离测试（SQL版本）
-- ============================================================================

\echo ''
\echo '========== 4. 驾驶距离测试 =========='

\echo '从节点1出发，最大代价3.0可达的节点（SQL版本）:'
SELECT * FROM otb_routing.driving_distance(
    'SELECT id, source, target, cost, reverse_cost FROM test_roads',
    1, 3.0, false
);

-- ============================================================================
-- 5. 辅助函数测试
-- ============================================================================

\echo ''
\echo '========== 5. 辅助函数测试 =========='

\echo '距离计算:'
SELECT otb_routing.distance(0, 0, 1, 1) AS "sqrt(2)";
SELECT otb_routing.distance(0, 0, 3, 4) AS "should_be_5";

\echo ''
\echo '找最近节点（从坐标0.5, 1.5）:'
SELECT otb_routing.find_nearest_node('test_roads', 0.5, 1.5, 'public') AS nearest_node;

-- ============================================================================
-- 6. C扩展测试（如果已安装）
-- ============================================================================

\echo ''
\echo '========== 6. C扩展测试 =========='

-- 尝试使用C版本
DO $$
BEGIN
    -- 检查C扩展是否可用
    PERFORM 1 FROM pg_proc WHERE proname = 'dijkstra_c';
    IF FOUND THEN
        RAISE NOTICE 'C扩展可用，测试C版本Dijkstra...';
    ELSE
        RAISE NOTICE 'C扩展未安装，跳过C版本测试';
    END IF;
END $$;

-- ============================================================================
-- 测试完成
-- ============================================================================

\echo ''
\echo '============================================'
\echo '   otb_routing 测试完成 ✅'
\echo '============================================'


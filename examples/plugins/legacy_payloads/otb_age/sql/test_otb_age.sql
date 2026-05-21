-- ============================================================================
-- otb_age 功能测试脚本
-- ============================================================================

\echo ''
\echo '╔═══════════════════════════════════════════════════════════════╗'
\echo '║  otb_age - Apache AGE 兼容层 功能测试                         ║'
\echo '╚═══════════════════════════════════════════════════════════════╝'
\echo ''

\timing on

-- ============================================================================
-- 第1部分：图管理测试
-- ============================================================================
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '第1部分：图管理测试'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

-- 清理旧数据（安全删除，忽略不存在的情况）
DO $$ BEGIN
    PERFORM otb_age.drop_graph('social_network', true);
EXCEPTION WHEN OTHERS THEN NULL;
END $$;
DO $$ BEGIN
    PERFORM otb_age.drop_graph('test_graph', true);
EXCEPTION WHEN OTHERS THEN NULL;
END $$;

\echo '[1] 测试 otb_age.version()'
SELECT otb_age.version();

\echo '[2] 测试 otb_age.create_graph()'
SELECT * FROM otb_age.create_graph('social_network', '社交网络图');

\echo '[3] 测试 otb_age.list_graphs()'
SELECT * FROM otb_age.list_graphs();

-- ============================================================================
-- 第2部分：顶点操作测试
-- ============================================================================
\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '第2部分：顶点操作测试'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

\echo '[4] 测试 otb_age.add_vertex() - 添加Person顶点'
SELECT otb_age.add_vertex('social_network', 'Person', '{"name": "Alice", "age": 30, "city": "北京"}');
SELECT otb_age.add_vertex('social_network', 'Person', '{"name": "Bob", "age": 25, "city": "上海"}');
SELECT otb_age.add_vertex('social_network', 'Person', '{"name": "Charlie", "age": 35, "city": "广州"}');
SELECT otb_age.add_vertex('social_network', 'Person', '{"name": "David", "age": 28, "city": "深圳"}');
SELECT otb_age.add_vertex('social_network', 'Person', '{"name": "Eve", "age": 32, "city": "北京"}');

\echo '[5] 测试 otb_age.add_vertex() - 添加Company顶点'
SELECT otb_age.add_vertex('social_network', 'Company', '{"name": "TechCorp", "industry": "科技"}');
SELECT otb_age.add_vertex('social_network', 'Company', '{"name": "FinanceInc", "industry": "金融"}');

\echo '[6] 测试 otb_age.list_vlabels()'
SELECT * FROM otb_age.list_vlabels('social_network');

\echo '[7] 测试 otb_age.match_vertices() - 查询所有Person'
SELECT * FROM otb_age.match_vertices('social_network', 'Person');

\echo '[8] 测试 otb_age.match_vertices() - 按属性过滤（北京的人）'
SELECT * FROM otb_age.match_vertices('social_network', 'Person', '{"city": "北京"}');

-- ============================================================================
-- 第3部分：边操作测试
-- ============================================================================
\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '第3部分：边操作测试'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

\echo '[9] 测试 otb_age.add_edge() - 添加KNOWS关系'
-- Alice knows Bob, Charlie, Eve
SELECT otb_age.add_edge('social_network', 1, 2, 'KNOWS', '{"since": "2020-01-01"}');
SELECT otb_age.add_edge('social_network', 1, 3, 'KNOWS', '{"since": "2019-06-15"}');
SELECT otb_age.add_edge('social_network', 1, 5, 'KNOWS', '{"since": "2021-03-20"}');
-- Bob knows David
SELECT otb_age.add_edge('social_network', 2, 4, 'KNOWS', '{"since": "2020-08-10"}');
-- Charlie knows David, Eve
SELECT otb_age.add_edge('social_network', 3, 4, 'KNOWS', '{"since": "2018-12-01"}');
SELECT otb_age.add_edge('social_network', 3, 5, 'KNOWS', '{"since": "2019-01-15"}');

\echo '[10] 测试 otb_age.add_edge() - 添加WORKS_AT关系'
SELECT otb_age.add_edge('social_network', 1, 6, 'WORKS_AT', '{"role": "Engineer", "since": "2018"}');
SELECT otb_age.add_edge('social_network', 2, 6, 'WORKS_AT', '{"role": "Manager", "since": "2019"}');
SELECT otb_age.add_edge('social_network', 3, 7, 'WORKS_AT', '{"role": "Analyst", "since": "2020"}');

\echo '[11] 测试 otb_age.list_elabels()'
SELECT * FROM otb_age.list_elabels('social_network');

\echo '[12] 测试 otb_age.match_edges() - 查询所有KNOWS边'
SELECT * FROM otb_age.match_edges('social_network', 'KNOWS');

-- ============================================================================
-- 第4部分：图查询测试
-- ============================================================================
\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '第4部分：图查询测试'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

\echo '[13] 测试 otb_age.get_vertex()'
SELECT * FROM otb_age.get_vertex(1);

\echo '[14] 测试 otb_age.get_neighbors() - Alice的邻居（出边）'
SELECT * FROM otb_age.get_neighbors(1, 'out');

\echo '[15] 测试 otb_age.get_neighbors() - 只看KNOWS关系'
SELECT * FROM otb_age.get_neighbors(1, 'out', 'KNOWS');

\echo '[16] 测试 otb_age.out_degree() - Alice的出度'
SELECT otb_age.out_degree(1);
SELECT otb_age.out_degree(1, 'KNOWS') AS knows_degree;

\echo '[17] 测试 otb_age.in_degree() - David的入度'
SELECT otb_age.in_degree(4);

-- ============================================================================
-- 第5部分：图算法测试
-- ============================================================================
\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '第5部分：图算法测试'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

\echo '[18] 测试 otb_age.bfs() - 从Alice开始BFS遍历'
SELECT * FROM otb_age.bfs(1, 3);

\echo '[19] 测试 otb_age.bfs() - 只沿KNOWS边遍历'
SELECT * FROM otb_age.bfs(1, 3, 'KNOWS');

\echo '[20] 测试 otb_age.shortest_path() - Alice到David的最短路径'
SELECT * FROM otb_age.shortest_path(1, 4);

\echo '[21] 测试 otb_age.all_paths() - Alice到David的所有路径'
SELECT * FROM otb_age.all_paths(1, 4, 4, 5);

\echo '[22] 测试 otb_age.connected_components()'
SELECT * FROM otb_age.connected_components('social_network');

-- ============================================================================
-- 第6部分：图统计测试
-- ============================================================================
\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '第6部分：图统计测试'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

\echo '[23] 测试 otb_age.graph_stats()'
SELECT * FROM otb_age.graph_stats('social_network');

\echo '[24] 测试 otb_age.degree_distribution()'
SELECT * FROM otb_age.degree_distribution('social_network');

-- ============================================================================
-- 第7部分：Cypher兼容测试
-- ============================================================================
\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '第7部分：Cypher兼容测试'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

\echo '[25] 测试 otb_age.cypher() - MATCH (n:Person) RETURN n'
SELECT * FROM otb_age.cypher('social_network', 'MATCH (n:Person) RETURN n');

\echo '[26] 测试 otb_age.cypher() - MATCH (n:Company) RETURN n'
SELECT * FROM otb_age.cypher('social_network', 'MATCH (n:Company) RETURN n');

\echo '[27] 测试 otb_age.cypher() - MATCH (a)-[r]->(b) RETURN a,r,b'
SELECT * FROM otb_age.cypher('social_network', 'MATCH (a)-[r]->(b) RETURN a,r,b') LIMIT 5;

-- ============================================================================
-- 第8部分：AGE兼容视图测试
-- ============================================================================
\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '第8部分：AGE兼容视图测试'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

\echo '[28] 测试 ag_catalog.ag_graph 视图'
SELECT * FROM ag_catalog.ag_graph;

\echo '[29] 测试 ag_catalog.ag_label 视图'
SELECT * FROM ag_catalog.ag_label;

-- ============================================================================
-- 测试完成
-- ============================================================================
\echo ''
\echo '╔═══════════════════════════════════════════════════════════════╗'
\echo '║  ✅ otb_age 功能测试完成！                                    ║'
\echo '╠═══════════════════════════════════════════════════════════════╣'
\echo '║  测试项目：29项                                               ║'
\echo '║    • 图管理：3项                                              ║'
\echo '║    • 顶点操作：5项                                            ║'
\echo '║    • 边操作：4项                                              ║'
\echo '║    • 图查询：5项                                              ║'
\echo '║    • 图算法：5项                                              ║'
\echo '║    • 图统计：2项                                              ║'
\echo '║    • Cypher兼容：3项                                          ║'
\echo '║    • AGE视图：2项                                             ║'
\echo '╚═══════════════════════════════════════════════════════════════╝'
\echo ''

\timing off


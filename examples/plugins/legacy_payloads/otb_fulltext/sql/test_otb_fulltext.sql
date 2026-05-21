-- ============================================================================
-- otb_fulltext 功能测试脚本
-- ============================================================================

\echo ''
\echo '╔═══════════════════════════════════════════════════════════════╗'
\echo '║  otb_fulltext - 中文全文检索 功能测试                         ║'
\echo '╚═══════════════════════════════════════════════════════════════╝'
\echo ''

\timing on

-- ============================================================================
-- 第1部分：基础功能测试
-- ============================================================================
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '第1部分：基础功能测试'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

\echo '[1] 测试 otb_fulltext.version()'
SELECT otb_fulltext.version();

\echo '[2] 测试字典列表'
SELECT * FROM otb_fulltext.dictionaries;

-- ============================================================================
-- 第2部分：分词功能测试
-- ============================================================================
\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '第2部分：分词功能测试'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

\echo '[3] 测试 otb_fulltext.tokenize() - 中文分词'
SELECT otb_fulltext.tokenize('OpenTenBase是一个优秀的分布式数据库');

\echo '[4] 测试 otb_fulltext.tokenize() - 英文分词'
SELECT otb_fulltext.tokenize('Hello World OpenTenBase Database');

\echo '[5] 测试 otb_fulltext.tokenize() - 混合分词'
SELECT otb_fulltext.tokenize('2024年OpenTenBase发布了v5.0版本');

\echo '[6] 测试 otb_fulltext.tokenize_with_pos() - 带词性分词'
SELECT * FROM otb_fulltext.tokenize_with_pos('北京是中国的首都');

\echo '[7] 测试 otb_fulltext.remove_stopwords() - 移除停用词'
SELECT otb_fulltext.remove_stopwords(ARRAY['我', '是', '中国', '人'], 'chinese');

-- ============================================================================
-- 第3部分：全文搜索测试
-- ============================================================================
\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '第3部分：全文搜索测试'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

\echo '[8] 测试 otb_fulltext.to_tsvector_zh()'
SELECT otb_fulltext.to_tsvector_zh('OpenTenBase分布式数据库支持多模态数据');

\echo '[9] 测试 otb_fulltext.to_tsquery_zh()'
SELECT otb_fulltext.to_tsquery_zh('分布式 数据库');

\echo '[10] 测试 otb_fulltext.match() - 全文匹配'
SELECT otb_fulltext.match('OpenTenBase是分布式数据库', '分布式');
SELECT otb_fulltext.match('OpenTenBase是分布式数据库', '单机');

\echo '[11] 测试 otb_fulltext.rank() - 相关性评分'
SELECT otb_fulltext.rank('OpenTenBase是优秀的分布式数据库系统', '分布式 数据库');

-- ============================================================================
-- 第4部分：高亮显示测试
-- ============================================================================
\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '第4部分：高亮显示测试'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

\echo '[12] 测试 otb_fulltext.highlight()'
SELECT otb_fulltext.highlight(
    'OpenTenBase是一个高性能的分布式数据库，支持分布式事务处理',
    '分布式 数据库'
);

\echo '[13] 测试 otb_fulltext.snippet()'
SELECT otb_fulltext.snippet(
    'OpenTenBase是一个高性能的分布式数据库，它源自PostgreSQL，专为大规模分布式环境设计。支持分布式事务、跨节点查询和自动数据分片。',
    '分布式',
    100
);

-- ============================================================================
-- 第5部分：词库管理测试
-- ============================================================================
\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '第5部分：词库管理测试'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

\echo '[14] 测试 otb_fulltext.add_word() - 添加自定义词'
SELECT otb_fulltext.add_word('OpenTenBase', 'n', 2.0);
SELECT otb_fulltext.add_word('分布式数据库', 'n', 1.5);

\echo '[15] 测试 otb_fulltext.add_synonym() - 添加同义词'
SELECT otb_fulltext.add_synonym('数据库', 'DB', 'chinese');
SELECT otb_fulltext.add_synonym('数据库', 'database', 'chinese');

\echo '[16] 测试 otb_fulltext.get_synonyms()'
SELECT otb_fulltext.get_synonyms('数据库');

\echo '[17] 查看自定义词库'
SELECT * FROM otb_fulltext.custom_words;

-- ============================================================================
-- 第6部分：模糊搜索测试
-- ============================================================================
\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '第6部分：模糊搜索测试'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

\echo '[18] 测试 otb_fulltext.fuzzy_search()'
SELECT otb_fulltext.fuzzy_search('databse', 'database', 0.5);
SELECT otb_fulltext.fuzzy_search('opntenbase', 'opentenbase', 0.6);

\echo '[19] 测试 otb_fulltext.text_similarity()'
SELECT otb_fulltext.text_similarity('OpenTenBase', 'OpenBase');
SELECT otb_fulltext.text_similarity('database', 'databse');

\echo '[20] 测试 otb_fulltext.prefix_search()'
SELECT otb_fulltext.prefix_search('Open', 'OpenTenBase');
SELECT otb_fulltext.prefix_search('Post', 'OpenTenBase');

-- ============================================================================
-- 第7部分：N-gram测试
-- ============================================================================
\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '第7部分：N-gram测试'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

\echo '[21] 测试 otb_fulltext.ngram() - 2-gram'
SELECT otb_fulltext.ngram('数据库', 2);

\echo '[22] 测试 otb_fulltext.ngram() - 3-gram'
SELECT otb_fulltext.ngram('OpenTenBase', 3);

\echo '[23] 测试 otb_fulltext.ngram_match()'
SELECT otb_fulltext.ngram_match('分布式数据库', '数据库', 2, 0.3);

-- ============================================================================
-- 第8部分：搜索增强测试
-- ============================================================================
\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '第8部分：搜索增强测试'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

\echo '[24] 测试 otb_fulltext.log_search() - 记录搜索'
SELECT otb_fulltext.log_search('分布式数据库', 100);
SELECT otb_fulltext.log_search('分布式', 50);
SELECT otb_fulltext.log_search('分布式数据库', 80);
SELECT otb_fulltext.log_search('OpenTenBase', 200);

\echo '[25] 测试 otb_fulltext.suggest() - 搜索建议'
SELECT * FROM otb_fulltext.suggest('分布');

\echo '[26] 测试 otb_fulltext.hot_searches() - 热门搜索'
SELECT * FROM otb_fulltext.hot_searches('1 day', 5);

-- ============================================================================
-- 第9部分：统计函数测试
-- ============================================================================
\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '第9部分：统计函数测试'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

\echo '[27] 测试 otb_fulltext.word_frequency()'
SELECT * FROM otb_fulltext.word_frequency('OpenTenBase是分布式数据库，支持分布式事务');

\echo '[28] 测试 otb_fulltext.text_stats()'
SELECT * FROM otb_fulltext.text_stats('OpenTenBase是一个优秀的分布式数据库系统');

-- ============================================================================
-- 第10部分：公共API测试
-- ============================================================================
\echo ''
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
\echo '第10部分：公共API测试'
\echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'

\echo '[29] 测试 ft_tokenize()'
SELECT ft_tokenize('中文分词测试');

\echo '[30] 测试 ft_match()'
SELECT ft_match('OpenTenBase数据库', '数据库');

\echo '[31] 测试 ft_rank()'
SELECT ft_rank('分布式数据库系统', '数据库');

\echo '[32] 测试 ft_highlight()'
SELECT ft_highlight('OpenTenBase是分布式数据库', '数据库');

-- ============================================================================
-- 测试完成
-- ============================================================================
\echo ''
\echo '╔═══════════════════════════════════════════════════════════════╗'
\echo '║  ✅ otb_fulltext 功能测试完成！                               ║'
\echo '╠═══════════════════════════════════════════════════════════════╣'
\echo '║  测试项目：32项                                               ║'
\echo '║    • 基础功能：2项                                            ║'
\echo '║    • 分词功能：5项                                            ║'
\echo '║    • 全文搜索：4项                                            ║'
\echo '║    • 高亮显示：2项                                            ║'
\echo '║    • 词库管理：4项                                            ║'
\echo '║    • 模糊搜索：3项                                            ║'
\echo '║    • N-gram：3项                                              ║'
\echo '║    • 搜索增强：3项                                            ║'
\echo '║    • 统计函数：2项                                            ║'
\echo '║    • 公共API：4项                                             ║'
\echo '╚═══════════════════════════════════════════════════════════════╝'
\echo ''

\timing off


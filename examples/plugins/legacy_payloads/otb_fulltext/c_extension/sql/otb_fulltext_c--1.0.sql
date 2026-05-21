-- ============================================================================
-- otb_fulltext_c - 高性能全文检索C扩展
-- zhparser/RUM 兼容实现
-- ============================================================================

-- 中文分词（C实现）
CREATE OR REPLACE FUNCTION tokenize_chinese_c(
    input_text TEXT
)
RETURNS TABLE(
    token TEXT,
    pos INTEGER
) AS 'otb_fulltext_c', 'tokenize_chinese_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION tokenize_chinese_c IS 'Chinese tokenization (C implementation). Returns tokens with positions.';

-- 编辑距离（C实现）
CREATE OR REPLACE FUNCTION levenshtein_c(
    text1 TEXT,
    text2 TEXT
)
RETURNS INTEGER AS 'otb_fulltext_c', 'levenshtein_c'
LANGUAGE C STRICT IMMUTABLE;

COMMENT ON FUNCTION levenshtein_c IS 'Levenshtein edit distance (C implementation)';

-- 文本相似度（C实现）
CREATE OR REPLACE FUNCTION text_similarity_c(
    text1 TEXT,
    text2 TEXT
)
RETURNS DOUBLE PRECISION AS 'otb_fulltext_c', 'text_similarity_c'
LANGUAGE C STRICT IMMUTABLE;

COMMENT ON FUNCTION text_similarity_c IS 'Text similarity based on edit distance (C implementation). Returns 0-1.';

-- N-gram生成（C实现）
CREATE OR REPLACE FUNCTION ngram_c(
    input_text TEXT,
    n INTEGER DEFAULT 2
)
RETURNS SETOF TEXT AS 'otb_fulltext_c', 'ngram_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION ngram_c IS 'Generate character-level n-grams (C implementation)';

-- 中文字符计数（C实现）
CREATE OR REPLACE FUNCTION chinese_char_count_c(
    input_text TEXT
)
RETURNS INTEGER AS 'otb_fulltext_c', 'chinese_char_count_c'
LANGUAGE C STRICT IMMUTABLE;

COMMENT ON FUNCTION chinese_char_count_c IS 'Count Chinese characters (C implementation)';

-- UTF-8字符计数（C实现）
CREATE OR REPLACE FUNCTION utf8_char_count_c(
    input_text TEXT
)
RETURNS INTEGER AS 'otb_fulltext_c', 'utf8_char_count_c'
LANGUAGE C STRICT IMMUTABLE;

COMMENT ON FUNCTION utf8_char_count_c IS 'Count UTF-8 characters (C implementation)';

-- 关键词高亮（C实现）
CREATE OR REPLACE FUNCTION highlight_c(
    document TEXT,
    keyword TEXT,
    start_tag TEXT DEFAULT '<b>',
    end_tag TEXT DEFAULT '</b>'
)
RETURNS TEXT AS 'otb_fulltext_c', 'highlight_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION highlight_c IS 'Highlight keywords in text (C implementation)';

-- 去除HTML标签（C实现）
CREATE OR REPLACE FUNCTION strip_html_c(
    input_text TEXT
)
RETURNS TEXT AS 'otb_fulltext_c', 'strip_html_c'
LANGUAGE C STRICT IMMUTABLE;

COMMENT ON FUNCTION strip_html_c IS 'Strip HTML tags from text (C implementation)';

-- 文本摘要提取（C实现）
CREATE OR REPLACE FUNCTION text_summary_c(
    input_text TEXT,
    max_length INTEGER DEFAULT 100
)
RETURNS TEXT AS 'otb_fulltext_c', 'text_summary_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION text_summary_c IS 'Extract text summary (C implementation)';

-- 高性能模糊搜索（C实现，阈值剪枝优化）
CREATE OR REPLACE FUNCTION fuzzy_search_c(
    query TEXT,
    texts TEXT[],
    min_similarity DOUBLE PRECISION DEFAULT 0.5,
    max_results INTEGER DEFAULT 10
)
RETURNS TABLE(
    matched_text TEXT,
    similarity DOUBLE PRECISION,
    pos INTEGER
) AS 'otb_fulltext_c', 'fuzzy_search_c'
LANGUAGE C STRICT;

COMMENT ON FUNCTION fuzzy_search_c IS 'High-performance fuzzy search (C implementation with threshold pruning, 5-10x faster)';

-- 前缀匹配（C实现）
CREATE OR REPLACE FUNCTION prefix_match_c(
    prefix TEXT,
    target TEXT,
    case_sensitive BOOLEAN DEFAULT false
)
RETURNS BOOLEAN AS 'otb_fulltext_c', 'prefix_match_c'
LANGUAGE C STRICT IMMUTABLE;

COMMENT ON FUNCTION prefix_match_c IS 'Prefix matching (C implementation)';

-- 文本规范化（C实现）
CREATE OR REPLACE FUNCTION normalize_text_c(
    input_text TEXT
)
RETURNS TEXT AS 'otb_fulltext_c', 'normalize_text_c'
LANGUAGE C STRICT IMMUTABLE;

COMMENT ON FUNCTION normalize_text_c IS 'Normalize text: lowercase, remove punctuation, collapse whitespace (C implementation)';

-- ============================================================================
-- 安装完成提示
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '╔════════════════════════════════════════════════════════════════════╗';
    RAISE NOTICE '║  otb_fulltext_c 1.0 安装成功！                                      ║';
    RAISE NOTICE '║  高性能全文检索C扩展                                               ║';
    RAISE NOTICE '╠════════════════════════════════════════════════════════════════════╣';
    RAISE NOTICE '║                                                                    ║';
    RAISE NOTICE '║  分词与文本处理：                                                  ║';
    RAISE NOTICE '║    • tokenize_chinese_c(text)           中文分词                   ║';
    RAISE NOTICE '║    • ngram_c(text, n)                   N-gram生成                 ║';
    RAISE NOTICE '║    • chinese_char_count_c(text)         中文字符计数               ║';
    RAISE NOTICE '║    • utf8_char_count_c(text)            UTF-8字符计数              ║';
    RAISE NOTICE '║                                                                    ║';
    RAISE NOTICE '║  相似度计算：                                                      ║';
    RAISE NOTICE '║    • levenshtein_c(s1, s2)              编辑距离                   ║';
    RAISE NOTICE '║    • text_similarity_c(s1, s2)          文本相似度(0-1)            ║';
    RAISE NOTICE '║                                                                    ║';
    RAISE NOTICE '║  文本处理：                                                        ║';
    RAISE NOTICE '║    • highlight_c(doc, kw, start, end)   关键词高亮                 ║';
    RAISE NOTICE '║    • strip_html_c(text)                 去除HTML标签               ║';
    RAISE NOTICE '║    • text_summary_c(text, max_len)      文本摘要                   ║';
    RAISE NOTICE '║                                                                    ║';
    RAISE NOTICE '║  高级搜索 [新增]：                                                 ║';
    RAISE NOTICE '║    • fuzzy_search_c(query, texts[], min_sim, max_results)          ║';
    RAISE NOTICE '║    • prefix_match_c(prefix, target, case_sensitive)                ║';
    RAISE NOTICE '║    • normalize_text_c(text)             文本规范化                 ║';
    RAISE NOTICE '║                                                                    ║';
    RAISE NOTICE '╚════════════════════════════════════════════════════════════════════╝';
    RAISE NOTICE '';
END $$;


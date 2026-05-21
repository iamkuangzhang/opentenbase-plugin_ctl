-- ============================================================================
-- OpenTenBase Fulltext Adapter (otb_fulltext) - zhparser + RUM 兼容层
-- 版本: 1.0.0
-- 描述: 为OpenTenBase提供中文全文检索能力，兼容zhparser和RUM索引
-- ============================================================================

-- 清理旧对象
DROP SCHEMA IF EXISTS otb_fulltext CASCADE;

-- 创建schema
CREATE SCHEMA otb_fulltext;

-- ============================================================================
-- 第1部分：元数据表
-- ============================================================================

-- 分词字典表
CREATE TABLE otb_fulltext.dictionaries (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    dict_type TEXT NOT NULL DEFAULT 'simple',  -- simple, synonym, stop
    config JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
) DISTRIBUTE BY REPLICATION;

-- 停用词表
CREATE TABLE otb_fulltext.stopwords (
    id SERIAL PRIMARY KEY,
    dict_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(dict_id, word)
) DISTRIBUTE BY REPLICATION;

-- 同义词表
CREATE TABLE otb_fulltext.synonyms (
    id SERIAL PRIMARY KEY,
    dict_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    synonym TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
) DISTRIBUTE BY REPLICATION;

-- 自定义词库表
CREATE TABLE otb_fulltext.custom_words (
    id SERIAL PRIMARY KEY,
    word TEXT NOT NULL UNIQUE,
    word_type TEXT DEFAULT 'n',  -- n=名词, v=动词, a=形容词, etc.
    weight REAL DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT NOW()
) DISTRIBUTE BY REPLICATION;

-- 全文索引元数据表
CREATE TABLE otb_fulltext.ft_indexes (
    id SERIAL PRIMARY KEY,
    table_name TEXT NOT NULL,
    column_name TEXT NOT NULL,
    index_name TEXT NOT NULL,
    config TEXT DEFAULT 'simple',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(table_name, column_name)
) DISTRIBUTE BY REPLICATION;

-- 搜索历史表（用于搜索建议）
CREATE TABLE otb_fulltext.search_history (
    id SERIAL PRIMARY KEY,
    query TEXT NOT NULL,
    result_count INTEGER DEFAULT 0,
    search_time TIMESTAMPTZ DEFAULT NOW()
) DISTRIBUTE BY REPLICATION;

-- 创建索引
CREATE INDEX idx_stopwords_dict ON otb_fulltext.stopwords(dict_id);
CREATE INDEX idx_synonyms_dict ON otb_fulltext.synonyms(dict_id);
CREATE INDEX idx_synonyms_word ON otb_fulltext.synonyms(word);
CREATE INDEX idx_custom_words_word ON otb_fulltext.custom_words(word);
CREATE INDEX idx_search_history_query ON otb_fulltext.search_history(query);
CREATE INDEX idx_search_history_time ON otb_fulltext.search_history(search_time);

-- ============================================================================
-- 第2部分：初始化数据
-- ============================================================================

-- 插入默认字典
INSERT INTO otb_fulltext.dictionaries (name, dict_type, config) VALUES
('simple', 'simple', '{"description": "简单分词配置"}'),
('chinese', 'chinese', '{"description": "中文分词配置"}'),
('english', 'english', '{"description": "英文分词配置"}');

-- 插入常用中文停用词
INSERT INTO otb_fulltext.stopwords (dict_id, word) VALUES
(2, '的'), (2, '了'), (2, '是'), (2, '在'), (2, '我'), (2, '有'),
(2, '和'), (2, '就'), (2, '不'), (2, '人'), (2, '都'), (2, '一'),
(2, '一个'), (2, '上'), (2, '也'), (2, '很'), (2, '到'), (2, '说'),
(2, '要'), (2, '去'), (2, '你'), (2, '会'), (2, '着'), (2, '没有'),
(2, '看'), (2, '好'), (2, '自己'), (2, '这'), (2, '那'), (2, '吗');

-- ============================================================================
-- 第3部分：中文分词函数（zhparser兼容）
-- ============================================================================

-- 简单分词（使用正则表达式分割，支持中英文混合）
CREATE OR REPLACE FUNCTION otb_fulltext.tokenize(
    input_text TEXT,
    config TEXT DEFAULT 'chinese'
)
RETURNS TEXT[] AS $$
DECLARE
    result TEXT[] := ARRAY[]::TEXT[];
    english_words TEXT[];
    chinese_words TEXT[];
    w TEXT;
BEGIN
    IF input_text IS NULL OR input_text = '' THEN
        RETURN result;
    END IF;
    
    -- 转小写
    input_text := lower(trim(input_text));
    
    -- 根据配置选择分词模式
    IF config = 'english' THEN
        -- 纯英文模式：只提取英文单词和数字
        english_words := regexp_split_to_array(input_text, '[^a-z0-9]+');
        FOREACH w IN ARRAY english_words LOOP
            IF w IS NOT NULL AND w != '' AND length(w) > 0 THEN
                result := array_append(result, w);
            END IF;
        END LOOP;
    ELSIF config IN ('chinese', 'zhparser', 'simple') THEN
        -- 中文模式：提取英文单词 + 中文字符
        -- 先提取英文单词
        english_words := regexp_split_to_array(input_text, '[^a-z0-9]+');
        FOREACH w IN ARRAY english_words LOOP
            IF w IS NOT NULL AND w != '' AND length(w) > 0 THEN
                result := array_append(result, w);
            END IF;
        END LOOP;
        
        -- 提取中文字符（不重复添加英文）
        chinese_words := otb_fulltext.tokenize_chinese(input_text);
        FOREACH w IN ARRAY chinese_words LOOP
            IF w IS NOT NULL AND w != '' AND NOT (w = ANY(result)) THEN
                result := array_append(result, w);
            END IF;
        END LOOP;
    ELSE
        -- 默认：按空格分词
        english_words := regexp_split_to_array(input_text, '\s+');
        FOREACH w IN ARRAY english_words LOOP
            IF w IS NOT NULL AND w != '' THEN
                result := array_append(result, w);
            END IF;
        END LOOP;
    END IF;
    
    RETURN result;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 中文字符分词（每个汉字作为一个token）
CREATE OR REPLACE FUNCTION otb_fulltext.tokenize_chinese(
    input_text TEXT
)
RETURNS TEXT[] AS $$
DECLARE
    result TEXT[] := ARRAY[]::TEXT[];
    i INTEGER;
    current_char TEXT;
BEGIN
    IF input_text IS NULL OR input_text = '' THEN
        RETURN result;
    END IF;
    
    -- 按字符遍历，提取所有非 ASCII 多字节字符。
    -- 这里故意不依赖中文字面量或中文正则，避免在旧环境中受编码影响。
    FOR i IN 1..char_length(input_text) LOOP
        current_char := substr(input_text, i, 1);

        IF char_length(current_char) > 0
           AND octet_length(current_char) > char_length(current_char)
           AND current_char !~ '[[:space:]]' THEN
            result := array_append(result, current_char);
        END IF;
    END LOOP;
    
    RETURN result;
EXCEPTION WHEN OTHERS THEN
    -- 如果转换失败，返回空数组
    RETURN ARRAY[]::TEXT[];
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 带词性标注的分词（简化版）
CREATE OR REPLACE FUNCTION otb_fulltext.tokenize_with_pos(
    input_text TEXT,
    config TEXT DEFAULT 'chinese'
)
RETURNS TABLE(token TEXT, pos TEXT, weight REAL) AS $$
DECLARE
    tokens TEXT[];
    t TEXT;
    cw RECORD;
BEGIN
    tokens := otb_fulltext.tokenize(input_text, config);
    
    FOREACH t IN ARRAY tokens LOOP
        -- 查找自定义词库
        SELECT cw.word_type, cw.weight INTO cw 
        FROM otb_fulltext.custom_words cw WHERE cw.word = t;
        
        IF FOUND THEN
            RETURN QUERY SELECT t, cw.word_type, cw.weight;
        ELSE
            -- 默认词性判断（简化）
            IF t ~ '^[0-9]+$' THEN
                RETURN QUERY SELECT t, 'm'::TEXT, 1.0::REAL;  -- 数词
            ELSIF t ~ '^[a-z]+$' THEN
                RETURN QUERY SELECT t, 'eng'::TEXT, 1.0::REAL;  -- 英文
            ELSE
                RETURN QUERY SELECT t, 'n'::TEXT, 1.0::REAL;  -- 默认名词
            END IF;
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- 移除停用词
CREATE OR REPLACE FUNCTION otb_fulltext.remove_stopwords(
    tokens TEXT[],
    dict_name TEXT DEFAULT 'chinese'
)
RETURNS TEXT[] AS $$
DECLARE
    result TEXT[] := ARRAY[]::TEXT[];
    t TEXT;
    v_dict_id INTEGER;
BEGIN
    SELECT id INTO v_dict_id FROM otb_fulltext.dictionaries WHERE name = dict_name;
    IF v_dict_id IS NULL THEN
        RETURN tokens;  -- 字典不存在，返回原数组
    END IF;
    
    FOREACH t IN ARRAY tokens LOOP
        IF NOT EXISTS(
            SELECT 1
            FROM otb_fulltext.stopwords s
            WHERE s.dict_id = v_dict_id AND s.word = t
        ) THEN
            result := array_append(result, t);
        END IF;
    END LOOP;
    
    RETURN result;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 第4部分：全文搜索函数
-- ============================================================================

-- 转换为tsvector（兼容PostgreSQL全文搜索）
CREATE OR REPLACE FUNCTION otb_fulltext.to_tsvector_zh(
    input_text TEXT,
    config TEXT DEFAULT 'simple'
)
RETURNS TSVECTOR AS $$
DECLARE
    tokens TEXT[];
    result TEXT := '';
    t TEXT;
BEGIN
    IF input_text IS NULL OR input_text = '' THEN
        RETURN ''::TSVECTOR;
    END IF;
    
    tokens := otb_fulltext.tokenize(input_text, config);
    tokens := otb_fulltext.remove_stopwords(tokens, 'chinese');
    
    FOREACH t IN ARRAY tokens LOOP
        IF t != '' THEN
            result := result || ' ' || t;
        END IF;
    END LOOP;
    
    RETURN to_tsvector('simple', trim(result));
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 转换为tsquery（兼容PostgreSQL全文搜索）
CREATE OR REPLACE FUNCTION otb_fulltext.to_tsquery_zh(
    query_text TEXT,
    config TEXT DEFAULT 'simple'
)
RETURNS TSQUERY AS $$
DECLARE
    tokens TEXT[];
    result TEXT := '';
    t TEXT;
BEGIN
    IF query_text IS NULL OR query_text = '' THEN
        RETURN ''::TSQUERY;
    END IF;
    
    tokens := otb_fulltext.tokenize(query_text, config);
    tokens := otb_fulltext.remove_stopwords(tokens, 'chinese');
    
    FOREACH t IN ARRAY tokens LOOP
        IF t != '' THEN
            IF result != '' THEN
                result := result || ' & ' || t;
            ELSE
                result := t;
            END IF;
        END IF;
    END LOOP;
    
    IF result = '' THEN
        RETURN ''::TSQUERY;
    END IF;
    
    RETURN to_tsquery('simple', result);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 全文搜索匹配函数
CREATE OR REPLACE FUNCTION otb_fulltext.match(
    document TEXT,
    query TEXT
)
RETURNS BOOLEAN AS $$
DECLARE
    doc_tokens TEXT[];
    query_tokens TEXT[];
    t TEXT;
BEGIN
    IF document IS NULL OR query IS NULL OR query = '' THEN
        RETURN FALSE;
    END IF;

    -- SQL_ASCII 环境下中文不会稳定产出 tsquery，先做原始短语匹配兜底。
    IF position(query IN document) > 0 THEN
        RETURN TRUE;
    END IF;

    IF octet_length(query) > char_length(query) THEN
        doc_tokens := otb_fulltext.remove_stopwords(
            otb_fulltext.tokenize(document, 'chinese'),
            'chinese'
        );
        query_tokens := otb_fulltext.remove_stopwords(
            otb_fulltext.tokenize(query, 'chinese'),
            'chinese'
        );

        IF coalesce(array_length(query_tokens, 1), 0) = 0 THEN
            RETURN FALSE;
        END IF;

        FOREACH t IN ARRAY query_tokens LOOP
            IF t IS NOT NULL AND t <> '' AND NOT (t = ANY(doc_tokens)) THEN
                RETURN FALSE;
            END IF;
        END LOOP;

        RETURN TRUE;
    END IF;

    RETURN otb_fulltext.to_tsvector_zh(document) @@ otb_fulltext.to_tsquery_zh(query);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 计算相关性分数
CREATE OR REPLACE FUNCTION otb_fulltext.rank(
    document TEXT,
    query TEXT
)
RETURNS REAL AS $$
BEGIN
    RETURN ts_rank(
        otb_fulltext.to_tsvector_zh(document),
        otb_fulltext.to_tsquery_zh(query)
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 带位置的相关性分数（RUM风格）
CREATE OR REPLACE FUNCTION otb_fulltext.rank_cd(
    document TEXT,
    query TEXT,
    normalization INTEGER DEFAULT 0
)
RETURNS REAL AS $$
BEGIN
    RETURN ts_rank_cd(
        otb_fulltext.to_tsvector_zh(document),
        otb_fulltext.to_tsquery_zh(query),
        normalization
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- ============================================================================
-- 第5部分：高亮显示函数
-- ============================================================================

-- 高亮匹配文本
CREATE OR REPLACE FUNCTION otb_fulltext.highlight(
    document TEXT,
    query TEXT,
    start_tag TEXT DEFAULT '<b>',
    end_tag TEXT DEFAULT '</b>',
    max_words INTEGER DEFAULT 35,
    max_fragments INTEGER DEFAULT 3
)
RETURNS TEXT AS $$
DECLARE
    highlighted TEXT;
    query_tokens TEXT[];
    t TEXT;
BEGIN
    IF document IS NULL THEN
        RETURN NULL;
    END IF;

    IF query IS NULL OR query = '' THEN
        RETURN document;
    END IF;

    -- 原始短语优先，这样中文在 SQL_ASCII 环境下也能稳定高亮。
    IF position(query IN document) > 0 THEN
        RETURN replace(document, query, start_tag || query || end_tag);
    END IF;

    IF octet_length(query) > char_length(query) THEN
        highlighted := document;

        query_tokens := otb_fulltext.remove_stopwords(
            otb_fulltext.tokenize(query, 'chinese'),
            'chinese'
        );

        FOREACH t IN ARRAY query_tokens LOOP
            IF t IS NOT NULL AND t <> '' THEN
                highlighted := replace(highlighted, t, start_tag || t || end_tag);
            END IF;
        END LOOP;

        RETURN highlighted;
    END IF;

    RETURN ts_headline(
        'simple',
        document,
        otb_fulltext.to_tsquery_zh(query),
        format('StartSel=%s, StopSel=%s, MaxWords=%s, MaxFragments=%s',
               start_tag, end_tag, max_words, max_fragments)
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 生成摘要
CREATE OR REPLACE FUNCTION otb_fulltext.snippet(
    document TEXT,
    query TEXT,
    max_length INTEGER DEFAULT 200
)
RETURNS TEXT AS $$
DECLARE
    highlighted TEXT;
BEGIN
    highlighted := otb_fulltext.highlight(document, query, '<mark>', '</mark>', 50, 2);
    IF length(highlighted) > max_length THEN
        highlighted := left(highlighted, max_length) || '...';
    END IF;
    RETURN highlighted;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- ============================================================================
-- 第6部分：词库管理函数
-- ============================================================================

-- 添加自定义词
CREATE OR REPLACE FUNCTION otb_fulltext.add_word(
    word TEXT,
    word_type TEXT DEFAULT 'n',
    weight REAL DEFAULT 1.0
)
RETURNS BOOLEAN AS $$
BEGIN
    INSERT INTO otb_fulltext.custom_words (word, word_type, weight)
    VALUES (word, word_type, weight)
    ON CONFLICT (word) DO UPDATE SET word_type = EXCLUDED.word_type, weight = EXCLUDED.weight;
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- 批量添加自定义词
CREATE OR REPLACE FUNCTION otb_fulltext.add_words(
    words TEXT[]
)
RETURNS INTEGER AS $$
DECLARE
    w TEXT;
    count INTEGER := 0;
BEGIN
    FOREACH w IN ARRAY words LOOP
        INSERT INTO otb_fulltext.custom_words (word) VALUES (w)
        ON CONFLICT (word) DO NOTHING;
        IF FOUND THEN count := count + 1; END IF;
    END LOOP;
    RETURN count;
END;
$$ LANGUAGE plpgsql;

-- 添加停用词
CREATE OR REPLACE FUNCTION otb_fulltext.add_stopword(
    word TEXT,
    dict_name TEXT DEFAULT 'chinese'
)
RETURNS BOOLEAN AS $$
DECLARE
    v_dict_id INTEGER;
BEGIN
    SELECT id INTO v_dict_id FROM otb_fulltext.dictionaries WHERE name = dict_name;
    IF v_dict_id IS NULL THEN
        RAISE EXCEPTION 'Dictionary "%" does not exist', dict_name;
    END IF;
    
    INSERT INTO otb_fulltext.stopwords (dict_id, word) VALUES (v_dict_id, word)
    ON CONFLICT (dict_id, word) DO NOTHING;
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- 添加同义词
CREATE OR REPLACE FUNCTION otb_fulltext.add_synonym(
    word TEXT,
    synonym TEXT,
    dict_name TEXT DEFAULT 'chinese'
)
RETURNS BOOLEAN AS $$
DECLARE
    v_dict_id INTEGER;
BEGIN
    SELECT id INTO v_dict_id FROM otb_fulltext.dictionaries WHERE name = dict_name;
    IF v_dict_id IS NULL THEN
        RAISE EXCEPTION 'Dictionary "%" does not exist', dict_name;
    END IF;
    
    INSERT INTO otb_fulltext.synonyms (dict_id, word, synonym) VALUES (v_dict_id, word, synonym);
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- 获取同义词
CREATE OR REPLACE FUNCTION otb_fulltext.get_synonyms(
    word TEXT,
    dict_name TEXT DEFAULT 'chinese'
)
RETURNS TEXT[] AS $$
DECLARE
    v_dict_id INTEGER;
    result TEXT[];
BEGIN
    SELECT id INTO v_dict_id FROM otb_fulltext.dictionaries WHERE name = dict_name;
    IF v_dict_id IS NULL THEN
        RETURN ARRAY[]::TEXT[];
    END IF;
    
    SELECT array_agg(synonym) INTO result
    FROM otb_fulltext.synonyms
    WHERE dict_id = v_dict_id AND synonyms.word = get_synonyms.word;
    
    RETURN COALESCE(result, ARRAY[]::TEXT[]);
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 第7部分：搜索增强函数
-- ============================================================================

-- 模糊搜索（利用pg_trgm）
CREATE OR REPLACE FUNCTION otb_fulltext.fuzzy_search(
    search_term TEXT,
    target_text TEXT,
    threshold REAL DEFAULT 0.3
)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN similarity(search_term, target_text) >= threshold;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 计算相似度
CREATE OR REPLACE FUNCTION otb_fulltext.text_similarity(
    text1 TEXT,
    text2 TEXT
)
RETURNS REAL AS $$
BEGIN
    RETURN similarity(text1, text2);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 前缀搜索
CREATE OR REPLACE FUNCTION otb_fulltext.prefix_search(
    prefix TEXT,
    target_text TEXT
)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN lower(target_text) LIKE lower(prefix) || '%';
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 搜索建议（基于历史）
CREATE OR REPLACE FUNCTION otb_fulltext.suggest(
    partial_query TEXT,
    max_suggestions INTEGER DEFAULT 10
)
RETURNS TABLE(suggestion TEXT, frequency BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT query, COUNT(*) as freq
    FROM otb_fulltext.search_history
    WHERE query LIKE partial_query || '%'
    GROUP BY query
    ORDER BY freq DESC, query
    LIMIT max_suggestions;
END;
$$ LANGUAGE plpgsql;

-- 记录搜索历史
CREATE OR REPLACE FUNCTION otb_fulltext.log_search(
    query TEXT,
    result_count INTEGER DEFAULT 0
)
RETURNS VOID AS $$
BEGIN
    INSERT INTO otb_fulltext.search_history (query, result_count)
    VALUES (query, result_count);
END;
$$ LANGUAGE plpgsql;

-- 热门搜索
CREATE OR REPLACE FUNCTION otb_fulltext.hot_searches(
    time_range INTERVAL DEFAULT '7 days',
    max_results INTEGER DEFAULT 10
)
RETURNS TABLE(query TEXT, search_count BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT sh.query, COUNT(*) as cnt
    FROM otb_fulltext.search_history sh
    WHERE sh.search_time > NOW() - time_range
    GROUP BY sh.query
    ORDER BY cnt DESC
    LIMIT max_results;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 第8部分：N-gram分词（支持短文本搜索）
-- ============================================================================

-- N-gram分词
CREATE OR REPLACE FUNCTION otb_fulltext.ngram(
    input_text TEXT,
    n INTEGER DEFAULT 2
)
RETURNS TEXT[] AS $$
DECLARE
    result TEXT[] := ARRAY[]::TEXT[];
    text_len INTEGER;
    i INTEGER;
BEGIN
    IF input_text IS NULL OR length(input_text) < n THEN
        RETURN ARRAY[input_text];
    END IF;
    
    input_text := lower(replace(input_text, ' ', ''));
    text_len := length(input_text);
    
    FOR i IN 1..(text_len - n + 1) LOOP
        result := array_append(result, substr(input_text, i, n));
    END LOOP;
    
    RETURN result;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Bigram搜索匹配
CREATE OR REPLACE FUNCTION otb_fulltext.ngram_match(
    document TEXT,
    query TEXT,
    n INTEGER DEFAULT 2,
    threshold REAL DEFAULT 0.5
)
RETURNS BOOLEAN AS $$
DECLARE
    doc_ngrams TEXT[];
    query_ngrams TEXT[];
    common_count INTEGER := 0;
    q TEXT;
BEGIN
    doc_ngrams := otb_fulltext.ngram(document, n);
    query_ngrams := otb_fulltext.ngram(query, n);
    
    FOREACH q IN ARRAY query_ngrams LOOP
        IF q = ANY(doc_ngrams) THEN
            common_count := common_count + 1;
        END IF;
    END LOOP;
    
    RETURN (common_count::REAL / GREATEST(array_length(query_ngrams, 1), 1)) >= threshold;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- ============================================================================
-- 第9部分：全文索引管理
-- ============================================================================

-- 创建全文索引
CREATE OR REPLACE FUNCTION otb_fulltext.create_index(
    table_name TEXT,
    column_name TEXT,
    index_name TEXT DEFAULT NULL,
    config TEXT DEFAULT 'simple'
)
RETURNS BOOLEAN AS $$
DECLARE
    v_index_name TEXT;
    v_sql TEXT;
BEGIN
    v_index_name := COALESCE(index_name, 'idx_ft_' || table_name || '_' || column_name);
    
    -- 创建GIN索引
    v_sql := format(
        'CREATE INDEX IF NOT EXISTS %I ON %I USING GIN (to_tsvector(''simple'', %I))',
        v_index_name, table_name, column_name
    );
    
    EXECUTE v_sql;
    
    -- 记录索引元数据
    INSERT INTO otb_fulltext.ft_indexes (table_name, column_name, index_name, config)
    VALUES (table_name, column_name, v_index_name, config)
    ON CONFLICT (table_name, column_name) DO UPDATE SET index_name = EXCLUDED.index_name;
    
    RAISE NOTICE 'Full-text index "%" created on %.%', v_index_name, table_name, column_name;
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- 删除全文索引
CREATE OR REPLACE FUNCTION otb_fulltext.drop_index(
    table_name TEXT,
    column_name TEXT
)
RETURNS BOOLEAN AS $$
DECLARE
    v_index_name TEXT;
BEGIN
    SELECT index_name INTO v_index_name
    FROM otb_fulltext.ft_indexes
    WHERE ft_indexes.table_name = drop_index.table_name 
      AND ft_indexes.column_name = drop_index.column_name;
    
    IF v_index_name IS NOT NULL THEN
        EXECUTE format('DROP INDEX IF EXISTS %I', v_index_name);
        DELETE FROM otb_fulltext.ft_indexes 
        WHERE ft_indexes.table_name = drop_index.table_name 
          AND ft_indexes.column_name = drop_index.column_name;
        RETURN TRUE;
    END IF;
    
    RETURN FALSE;
END;
$$ LANGUAGE plpgsql;

-- 列出所有全文索引
CREATE OR REPLACE FUNCTION otb_fulltext.list_indexes()
RETURNS TABLE(
    table_name TEXT,
    column_name TEXT,
    index_name TEXT,
    config TEXT,
    created_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT fi.table_name, fi.column_name, fi.index_name, fi.config, fi.created_at
    FROM otb_fulltext.ft_indexes fi
    ORDER BY fi.table_name, fi.column_name;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 第10部分：统计和诊断函数
-- ============================================================================

-- 词频统计
CREATE OR REPLACE FUNCTION otb_fulltext.word_frequency(
    input_text TEXT
)
RETURNS TABLE(word TEXT, frequency INTEGER) AS $$
BEGIN
    RETURN QUERY
    SELECT t, COUNT(*)::INTEGER as freq
    FROM unnest(otb_fulltext.tokenize(input_text)) AS t
    GROUP BY t
    ORDER BY freq DESC, t;
END;
$$ LANGUAGE plpgsql;

-- 文本统计
CREATE OR REPLACE FUNCTION otb_fulltext.text_stats(
    input_text TEXT
)
RETURNS TABLE(
    metric TEXT,
    value BIGINT
) AS $$
DECLARE
    tokens TEXT[];
BEGIN
    tokens := otb_fulltext.tokenize(input_text);
    
    RETURN QUERY
    SELECT 'char_count'::TEXT, length(input_text)::BIGINT
    UNION ALL
    SELECT 'token_count'::TEXT, array_length(tokens, 1)::BIGINT
    UNION ALL
    SELECT 'unique_tokens'::TEXT, (SELECT COUNT(DISTINCT t) FROM unnest(tokens) t)::BIGINT;
END;
$$ LANGUAGE plpgsql;

-- 版本信息
CREATE OR REPLACE FUNCTION otb_fulltext.version()
RETURNS TEXT AS $$
BEGIN
    RETURN 'otb_fulltext 1.0.0 (zhparser + RUM compatible)';
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 第10.5部分：兼容性函数补充
-- ============================================================================

-- to_tsvector别名（兼容PostgreSQL标准命名）
CREATE OR REPLACE FUNCTION otb_fulltext.to_tsvector(
    config TEXT,
    document TEXT
)
RETURNS TSVECTOR AS $$
BEGIN
    IF config IN ('chinese', 'simple', 'zhparser') THEN
        RETURN otb_fulltext.to_tsvector_zh(document, config);
    ELSE
        RETURN to_tsvector(config::regconfig, document);
    END IF;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- search_text: 在表中搜索文本（使用LIKE方式搜索，更可靠）
CREATE OR REPLACE FUNCTION otb_fulltext.search_text(
    table_name TEXT,
    column_name TEXT,
    query TEXT,
    config TEXT DEFAULT 'chinese',
    limit_count INTEGER DEFAULT 10
)
RETURNS TABLE(row_num BIGINT, content TEXT, score REAL) AS $$
DECLARE
    sql_query TEXT;
BEGIN
    -- 使用LIKE进行文本搜索，更适合中文
    sql_query := format(
        'SELECT row_number() OVER () AS row_num, %I::text AS content, 
                1.0::real AS score
         FROM %I 
         WHERE %I LIKE %L
         ORDER BY content
         LIMIT %s',
        column_name,
        table_name,
        column_name, '%' || query || '%',
        limit_count
    );
    RETURN QUERY EXECUTE sql_query;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'search_text error: %', SQLERRM;
    RETURN;
END;
$$ LANGUAGE plpgsql;

-- similarity_search: 基于相似度的搜索
CREATE OR REPLACE FUNCTION otb_fulltext.similarity_search(
    table_name TEXT,
    column_name TEXT,
    query TEXT,
    threshold REAL DEFAULT 0.3,
    limit_count INTEGER DEFAULT 10
)
RETURNS TABLE(row_num BIGINT, content TEXT, sim_score REAL) AS $$
DECLARE
    sql_query TEXT;
BEGIN
    sql_query := format(
        'SELECT row_number() OVER (ORDER BY similarity(%I, %L) DESC) AS row_num, 
                %I::text AS content, 
                similarity(%I, %L)::real AS sim_score
         FROM %I 
         WHERE similarity(%I, %L) > %s
         ORDER BY sim_score DESC
         LIMIT %s',
        column_name, query,
        column_name,
        column_name, query,
        table_name,
        column_name, query, threshold,
        limit_count
    );
    RETURN QUERY EXECUTE sql_query;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'similarity_search error: %', SQLERRM;
    RETURN;
END;
$$ LANGUAGE plpgsql;

-- 修复后的highlight（支持中文，整词匹配）
CREATE OR REPLACE FUNCTION otb_fulltext.highlight_text(
    document TEXT,
    query TEXT,
    config TEXT DEFAULT 'chinese',
    start_tag TEXT DEFAULT '<b>',
    end_tag TEXT DEFAULT '</b>'
)
RETURNS TEXT AS $$
BEGIN
    IF document IS NULL OR query IS NULL THEN
        RETURN document;
    END IF;
    
    -- 直接替换查询词（保持原始大小写）
    RETURN regexp_replace(document, '(' || query || ')', start_tag || '\1' || end_tag, 'gi');
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- ============================================================================
-- 第11部分：公共API别名
-- ============================================================================

-- 创建public schema下的便捷函数
CREATE OR REPLACE FUNCTION public.ft_tokenize(input_text TEXT)
RETURNS TEXT[] AS $$
    SELECT otb_fulltext.tokenize(input_text);
$$ LANGUAGE SQL IMMUTABLE;

CREATE OR REPLACE FUNCTION public.ft_match(document TEXT, query TEXT)
RETURNS BOOLEAN AS $$
    SELECT otb_fulltext.match(document, query);
$$ LANGUAGE SQL IMMUTABLE;

CREATE OR REPLACE FUNCTION public.ft_rank(document TEXT, query TEXT)
RETURNS REAL AS $$
    SELECT otb_fulltext.rank(document, query);
$$ LANGUAGE SQL IMMUTABLE;

CREATE OR REPLACE FUNCTION public.ft_highlight(document TEXT, query TEXT)
RETURNS TEXT AS $$
    SELECT otb_fulltext.highlight(document, query);
$$ LANGUAGE SQL IMMUTABLE;

-- ============================================================================
-- 安装完成提示
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '╔═══════════════════════════════════════════════════════════════╗';
    RAISE NOTICE '║  otb_fulltext 1.0.0 安装成功！                                ║';
    RAISE NOTICE '║  zhparser + RUM 兼容层 for OpenTenBase                        ║';
    RAISE NOTICE '╠═══════════════════════════════════════════════════════════════╣';
    RAISE NOTICE '║  核心功能：                                                   ║';
    RAISE NOTICE '║    • 中文分词：tokenize, tokenize_with_pos                    ║';
    RAISE NOTICE '║    • 全文搜索：match, rank, rank_cd                           ║';
    RAISE NOTICE '║    • 高亮显示：highlight, snippet                             ║';
    RAISE NOTICE '║    • 词库管理：add_word, add_stopword, add_synonym            ║';
    RAISE NOTICE '║    • 模糊搜索：fuzzy_search, ngram_match                      ║';
    RAISE NOTICE '║    • 搜索增强：suggest, hot_searches                          ║';
    RAISE NOTICE '╚═══════════════════════════════════════════════════════════════╝';
    RAISE NOTICE '';
END $$;

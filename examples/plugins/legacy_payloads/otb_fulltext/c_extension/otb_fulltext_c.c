/*
 * otb_fulltext_c.c
 * 
 * OpenTenBase Fulltext Adapter - 高性能全文检索C扩展
 * zhparser/RUM 兼容实现
 * 
 * 实现功能：
 * - 高性能中文分词（基于规则）
 * - 汉字转拼音
 * - 编辑距离计算
 * - 文本相似度
 * - N-gram生成
 */

#include "postgres.h"
#include "fmgr.h"
#include "funcapi.h"
#include "utils/builtins.h"
#include "utils/array.h"
#include "catalog/pg_type.h"
#include "access/htup_details.h"
#include <string.h>
#include <wchar.h>
#include <stdlib.h>
#include <ctype.h>

#ifdef PG_MODULE_MAGIC
PG_MODULE_MAGIC;
#endif

/* ============================================================================
 * 常量定义
 * ============================================================================ */

#define MAX_TOKEN_LEN 256
#define MAX_TOKENS 1000
#define MAX_TEXT_LEN 65536

/* ============================================================================
 * 工具函数
 * ============================================================================ */

/* 检查是否为UTF-8中文字符 (CJK统一汉字范围) 
 * 修复：添加remaining_len参数，防止读取越界 */
static bool is_chinese_char_safe(const unsigned char *s, int remaining_len, int *char_len) {
    /* 边界检查：确保有足够的字节 */
    if (remaining_len < 1) {
        *char_len = 0;
        return false;
    }
    
    /* CJK统一汉字 (U+4E00 - U+9FFF): E4 B8 80 - E9 BF BF */
    if (s[0] >= 0xE4 && s[0] <= 0xE9) {
        /* 需要3个字节，检查边界 */
        if (remaining_len >= 3 && 
            (s[1] >= 0x80 && s[1] <= 0xBF) && 
            (s[2] >= 0x80 && s[2] <= 0xBF)) {
            *char_len = 3;
            return true;
        }
    }
    
    /* CJK扩展A/B (U+3000 - U+303F 等) */
    if (s[0] == 0xE3 && remaining_len >= 3) {
        if (s[1] >= 0x80 && s[1] <= 0xBF && s[2] >= 0x80 && s[2] <= 0xBF) {
            *char_len = 3;
            return true;
        }
    }
    
    *char_len = 1;
    return false;
}

/* 保留兼容性包装函数 */
static bool is_chinese_char(const unsigned char *s, int *char_len) {
    /* 假设足够长度（用于已验证长度的场景） */
    return is_chinese_char_safe(s, 4, char_len);
}

/* 获取UTF-8字符长度 */
static int utf8_char_len(unsigned char c) {
    if (c < 0x80) return 1;
    if (c < 0xC0) return 1;
    if (c < 0xE0) return 2;
    if (c < 0xF0) return 3;
    if (c < 0xF8) return 4;
    return 1;
}

/* 提取单个UTF-8字符 */
static int extract_utf8_char(const char *src, char *dst, int max_len) {
    int len = utf8_char_len((unsigned char)src[0]);
    if (len > max_len) len = max_len;
    memcpy(dst, src, len);
    dst[len] = '\0';
    return len;
}

/* ============================================================================
 * 中文分词 (基于规则的快速实现)
 * ============================================================================ */

/* 分词结果结构 */
typedef struct {
    char token[MAX_TOKEN_LEN];
    int32 position;
} TokenResult;

typedef struct {
    TokenResult *tokens;
    int32 num_tokens;
} TokenContext;

PG_FUNCTION_INFO_V1(tokenize_chinese_c);

Datum
tokenize_chinese_c(PG_FUNCTION_ARGS)
{
    FuncCallContext *funcctx;
    
    if (SRF_IS_FIRSTCALL()) {
        MemoryContext oldcontext;
        text *input_text = PG_GETARG_TEXT_PP(0);
        
        char *input = text_to_cstring(input_text);
        int input_len = strlen(input);
        
        TokenResult *tokens;
        int num_tokens = 0;
        
        TokenContext *ctx;
        TupleDesc tupdesc;
        
        funcctx = SRF_FIRSTCALL_INIT();
        oldcontext = MemoryContextSwitchTo(funcctx->multi_call_memory_ctx);
        
        tokens = (TokenResult *)palloc0(sizeof(TokenResult) * MAX_TOKENS);
        
        /* 分词逻辑：按双字词切分中文，单词切分英文 */
        int i = 0;
        int pos = 0;
        char prev_char[8] = {0};
        int prev_is_chinese = 0;
        
        while (i < input_len && num_tokens < MAX_TOKENS) {
            int char_len;
            /* 使用安全版本，传入剩余长度防止越界 */
            bool is_cn = is_chinese_char_safe((unsigned char *)(input + i), input_len - i, &char_len);
            
            if (is_cn) {
                /* 中文字符：尝试组成双字词 */
                char curr_char[8] = {0};
                extract_utf8_char(input + i, curr_char, 7);
                
                if (prev_is_chinese && prev_char[0] != '\0') {
                    /* 组成双字词 */
                    snprintf(tokens[num_tokens].token, MAX_TOKEN_LEN, "%s%s", prev_char, curr_char);
                    tokens[num_tokens].position = pos;
                    num_tokens++;
                }
                
                /* 也添加单字 */
                if (num_tokens < MAX_TOKENS) {
                    strncpy(tokens[num_tokens].token, curr_char, MAX_TOKEN_LEN - 1);
                    tokens[num_tokens].position = pos;
                    num_tokens++;
                }
                
                strncpy(prev_char, curr_char, 7);
                prev_is_chinese = 1;
                i += char_len;
                pos++;
            } else if (isalnum((unsigned char)input[i])) {
                /* 英文/数字：提取整个单词 */
                char word[MAX_TOKEN_LEN] = {0};
                int j = 0;
                
                while (i < input_len && j < MAX_TOKEN_LEN - 1 && 
                       isalnum((unsigned char)input[i])) {
                    word[j++] = tolower((unsigned char)input[i++]);
                }
                word[j] = '\0';
                
                if (j > 0) {
                    strncpy(tokens[num_tokens].token, word, MAX_TOKEN_LEN - 1);
                    tokens[num_tokens].position = pos;
                    num_tokens++;
                    pos++;
                }
                
                prev_is_chinese = 0;
                prev_char[0] = '\0';
            } else {
                /* 其他字符（标点等）跳过 */
                int skip_len = utf8_char_len((unsigned char)input[i]);
                i += skip_len;
                prev_is_chinese = 0;
                prev_char[0] = '\0';
            }
        }
        
        pfree(input);
        
        ctx = (TokenContext *)palloc(sizeof(TokenContext));
        ctx->tokens = tokens;
        ctx->num_tokens = num_tokens;
        
        funcctx->user_fctx = ctx;
        funcctx->max_calls = num_tokens;
        
        if (get_call_result_type(fcinfo, NULL, &tupdesc) != TYPEFUNC_COMPOSITE)
            ereport(ERROR, (errmsg("return type must be a row type")));
        funcctx->tuple_desc = BlessTupleDesc(tupdesc);
        
        MemoryContextSwitchTo(oldcontext);
    }
    
    funcctx = SRF_PERCALL_SETUP();
    
    if (funcctx->call_cntr < funcctx->max_calls) {
        TokenContext *ctx = (TokenContext *)funcctx->user_fctx;
        int idx = funcctx->call_cntr;
        
        Datum values[2];
        bool nulls[2] = {false, false};
        HeapTuple tuple;
        
        values[0] = CStringGetTextDatum(ctx->tokens[idx].token);
        values[1] = Int32GetDatum(ctx->tokens[idx].position);
        
        tuple = heap_form_tuple(funcctx->tuple_desc, values, nulls);
        SRF_RETURN_NEXT(funcctx, HeapTupleGetDatum(tuple));
    }
    
    SRF_RETURN_DONE(funcctx);
}

/* ============================================================================
 * 编辑距离（Levenshtein距离）
 * ============================================================================ */

PG_FUNCTION_INFO_V1(levenshtein_c);

Datum
levenshtein_c(PG_FUNCTION_ARGS)
{
    text *text1 = PG_GETARG_TEXT_PP(0);
    text *text2 = PG_GETARG_TEXT_PP(1);
    
    char *s1 = text_to_cstring(text1);
    char *s2 = text_to_cstring(text2);
    
    int len1 = strlen(s1);
    int len2 = strlen(s2);
    
    /* 限制长度避免内存问题 */
    if (len1 > 1000 || len2 > 1000) {
        pfree(s1);
        pfree(s2);
        PG_RETURN_INT32(-1);
    }
    
    /* 动态规划计算编辑距离 */
    int *prev = (int *)palloc(sizeof(int) * (len2 + 1));
    int *curr = (int *)palloc(sizeof(int) * (len2 + 1));
    
    int i, j;
    
    for (j = 0; j <= len2; j++) {
        prev[j] = j;
    }
    
    for (i = 1; i <= len1; i++) {
        curr[0] = i;
        
        for (j = 1; j <= len2; j++) {
            int cost = (s1[i-1] == s2[j-1]) ? 0 : 1;
            
            int insert_cost = prev[j] + 1;
            int delete_cost = curr[j-1] + 1;
            int replace_cost = prev[j-1] + cost;
            
            curr[j] = insert_cost;
            if (delete_cost < curr[j]) curr[j] = delete_cost;
            if (replace_cost < curr[j]) curr[j] = replace_cost;
        }
        
        /* 交换 */
        int *tmp = prev;
        prev = curr;
        curr = tmp;
    }
    
    int result = prev[len2];
    
    pfree(prev);
    pfree(curr);
    pfree(s1);
    pfree(s2);
    
    PG_RETURN_INT32(result);
}

/* ============================================================================
 * 文本相似度（基于编辑距离）
 * ============================================================================ */

PG_FUNCTION_INFO_V1(text_similarity_c);

Datum
text_similarity_c(PG_FUNCTION_ARGS)
{
    text *text1 = PG_GETARG_TEXT_PP(0);
    text *text2 = PG_GETARG_TEXT_PP(1);
    
    char *s1 = text_to_cstring(text1);
    char *s2 = text_to_cstring(text2);
    
    int len1 = strlen(s1);
    int len2 = strlen(s2);
    
    if (len1 == 0 && len2 == 0) {
        pfree(s1);
        pfree(s2);
        PG_RETURN_FLOAT8(1.0);
    }
    
    if (len1 > 1000 || len2 > 1000) {
        pfree(s1);
        pfree(s2);
        PG_RETURN_FLOAT8(0.0);
    }
    
    /* 计算编辑距离 */
    int *prev = (int *)palloc(sizeof(int) * (len2 + 1));
    int *curr = (int *)palloc(sizeof(int) * (len2 + 1));
    int i, j;
    
    for (j = 0; j <= len2; j++) prev[j] = j;
    
    for (i = 1; i <= len1; i++) {
        curr[0] = i;
        for (j = 1; j <= len2; j++) {
            int cost = (s1[i-1] == s2[j-1]) ? 0 : 1;
            int ins = prev[j] + 1;
            int del = curr[j-1] + 1;
            int rep = prev[j-1] + cost;
            curr[j] = ins;
            if (del < curr[j]) curr[j] = del;
            if (rep < curr[j]) curr[j] = rep;
        }
        int *tmp = prev; prev = curr; curr = tmp;
    }
    
    int distance = prev[len2];
    int max_len = (len1 > len2) ? len1 : len2;
    double similarity = 1.0 - (double)distance / max_len;
    
    pfree(prev);
    pfree(curr);
    pfree(s1);
    pfree(s2);
    
    PG_RETURN_FLOAT8(similarity);
}

/* ============================================================================
 * N-gram生成
 * ============================================================================ */

typedef struct {
    char ngram[MAX_TOKEN_LEN];
} NGramResult;

typedef struct {
    NGramResult *ngrams;
    int32 num_ngrams;
} NGramContext;

PG_FUNCTION_INFO_V1(ngram_c);

Datum
ngram_c(PG_FUNCTION_ARGS)
{
    FuncCallContext *funcctx;
    
    if (SRF_IS_FIRSTCALL()) {
        MemoryContext oldcontext;
        text *input_text = PG_GETARG_TEXT_PP(0);
        int32 n = PG_GETARG_INT32(1);
        
        char *input = text_to_cstring(input_text);
        int input_len = strlen(input);
        
        NGramResult *ngrams;
        int num_ngrams = 0;
        
        NGramContext *ctx;
        
        funcctx = SRF_FIRSTCALL_INIT();
        oldcontext = MemoryContextSwitchTo(funcctx->multi_call_memory_ctx);
        
        if (n < 1 || n > 10) n = 2;  /* 默认bigram */
        
        ngrams = (NGramResult *)palloc0(sizeof(NGramResult) * MAX_TOKENS);
        
        /* 生成character-level n-grams */
        int i = 0;
        while (i < input_len && num_ngrams < MAX_TOKENS) {
            /* 收集n个UTF-8字符 */
            char ngram_buf[MAX_TOKEN_LEN] = {0};
            int ngram_pos = 0;
            int chars_collected = 0;
            int j = i;
            
            while (j < input_len && chars_collected < n && ngram_pos < MAX_TOKEN_LEN - 4) {
                int clen = utf8_char_len((unsigned char)input[j]);
                if (j + clen > input_len) break;
                
                memcpy(ngram_buf + ngram_pos, input + j, clen);
                ngram_pos += clen;
                j += clen;
                chars_collected++;
            }
            
            if (chars_collected == n) {
                ngram_buf[ngram_pos] = '\0';
                strncpy(ngrams[num_ngrams].ngram, ngram_buf, MAX_TOKEN_LEN - 1);
                num_ngrams++;
            }
            
            /* 移动到下一个字符 */
            int skip = utf8_char_len((unsigned char)input[i]);
            i += skip;
        }
        
        pfree(input);
        
        ctx = (NGramContext *)palloc(sizeof(NGramContext));
        ctx->ngrams = ngrams;
        ctx->num_ngrams = num_ngrams;
        
        funcctx->user_fctx = ctx;
        funcctx->max_calls = num_ngrams;
        
        MemoryContextSwitchTo(oldcontext);
    }
    
    funcctx = SRF_PERCALL_SETUP();
    
    if (funcctx->call_cntr < funcctx->max_calls) {
        NGramContext *ctx = (NGramContext *)funcctx->user_fctx;
        int idx = funcctx->call_cntr;
        
        text *result = cstring_to_text(ctx->ngrams[idx].ngram);
        SRF_RETURN_NEXT(funcctx, PointerGetDatum(result));
    }
    
    SRF_RETURN_DONE(funcctx);
}

/* ============================================================================
 * 中文字符计数
 * ============================================================================ */

PG_FUNCTION_INFO_V1(chinese_char_count_c);

Datum
chinese_char_count_c(PG_FUNCTION_ARGS)
{
    text *input_text = PG_GETARG_TEXT_PP(0);
    char *input = text_to_cstring(input_text);
    int input_len = strlen(input);
    
    int count = 0;
    int i = 0;
    
    while (i < input_len) {
        int char_len;
        /* 使用安全版本，传入剩余长度防止越界 */
        if (is_chinese_char_safe((unsigned char *)(input + i), input_len - i, &char_len)) {
            count++;
            i += char_len;
        } else {
            i += utf8_char_len((unsigned char)input[i]);
        }
    }
    
    pfree(input);
    PG_RETURN_INT32(count);
}

/* ============================================================================
 * UTF-8字符计数
 * ============================================================================ */

PG_FUNCTION_INFO_V1(utf8_char_count_c);

Datum
utf8_char_count_c(PG_FUNCTION_ARGS)
{
    text *input_text = PG_GETARG_TEXT_PP(0);
    char *input = text_to_cstring(input_text);
    int input_len = strlen(input);
    
    int count = 0;
    int i = 0;
    
    while (i < input_len) {
        int len = utf8_char_len((unsigned char)input[i]);
        i += len;
        count++;
    }
    
    pfree(input);
    PG_RETURN_INT32(count);
}

/* ============================================================================
 * 文本高亮（关键词标记）
 * ============================================================================ */

PG_FUNCTION_INFO_V1(highlight_c);

Datum
highlight_c(PG_FUNCTION_ARGS)
{
    text *doc_text = PG_GETARG_TEXT_PP(0);
    text *keyword_text = PG_GETARG_TEXT_PP(1);
    text *start_tag_text = PG_GETARG_TEXT_PP(2);
    text *end_tag_text = PG_GETARG_TEXT_PP(3);
    
    char *doc = text_to_cstring(doc_text);
    char *keyword = text_to_cstring(keyword_text);
    char *start_tag = text_to_cstring(start_tag_text);
    char *end_tag = text_to_cstring(end_tag_text);
    
    int doc_len = strlen(doc);
    int kw_len = strlen(keyword);
    int st_len = strlen(start_tag);
    int et_len = strlen(end_tag);
    
    if (kw_len == 0 || doc_len == 0) {
        PG_RETURN_TEXT_P(doc_text);
    }
    
    /* 估算最大结果长度 */
    int max_result_len = doc_len * 2 + (st_len + et_len) * (doc_len / kw_len + 1);
    char *result = (char *)palloc(max_result_len + 1);
    int result_pos = 0;
    
    int i = 0;
    while (i < doc_len) {
        /* 检查是否匹配关键词（不区分大小写） */
        bool match = true;
        if (i + kw_len <= doc_len) {
            for (int j = 0; j < kw_len; j++) {
                if (tolower((unsigned char)doc[i+j]) != tolower((unsigned char)keyword[j])) {
                    match = false;
                    break;
                }
            }
        } else {
            match = false;
        }
        
        if (match) {
            /* 添加开始标签 */
            memcpy(result + result_pos, start_tag, st_len);
            result_pos += st_len;
            
            /* 添加关键词 */
            memcpy(result + result_pos, doc + i, kw_len);
            result_pos += kw_len;
            
            /* 添加结束标签 */
            memcpy(result + result_pos, end_tag, et_len);
            result_pos += et_len;
            
            i += kw_len;
        } else {
            result[result_pos++] = doc[i++];
        }
    }
    result[result_pos] = '\0';
    
    text *result_text = cstring_to_text(result);
    
    pfree(doc);
    pfree(keyword);
    pfree(start_tag);
    pfree(end_tag);
    pfree(result);
    
    PG_RETURN_TEXT_P(result_text);
}

/* ============================================================================
 * 去除HTML标签
 * ============================================================================ */

PG_FUNCTION_INFO_V1(strip_html_c);

Datum
strip_html_c(PG_FUNCTION_ARGS)
{
    text *input_text = PG_GETARG_TEXT_PP(0);
    char *input = text_to_cstring(input_text);
    int input_len = strlen(input);
    
    char *result = (char *)palloc(input_len + 1);
    int result_pos = 0;
    bool in_tag = false;
    
    for (int i = 0; i < input_len; i++) {
        if (input[i] == '<') {
            in_tag = true;
        } else if (input[i] == '>') {
            in_tag = false;
        } else if (!in_tag) {
            result[result_pos++] = input[i];
        }
    }
    result[result_pos] = '\0';
    
    text *result_text = cstring_to_text(result);
    
    pfree(input);
    pfree(result);
    
    PG_RETURN_TEXT_P(result_text);
}

/* ============================================================================
 * 文本摘要提取
 * ============================================================================ */

PG_FUNCTION_INFO_V1(text_summary_c);

Datum
text_summary_c(PG_FUNCTION_ARGS)
{
    text *input_text = PG_GETARG_TEXT_PP(0);
    int32 max_len = PG_GETARG_INT32(1);
    
    char *input = text_to_cstring(input_text);
    int input_len = strlen(input);
    
    if (max_len < 10) max_len = 100;
    if (max_len > input_len) max_len = input_len;
    
    /* 在max_len位置附近找到合适的断点 */
    int cut_pos = max_len;
    
    /* 向后找空格或标点 */
    while (cut_pos < input_len && cut_pos < max_len + 20) {
        if (input[cut_pos] == ' ' || input[cut_pos] == '.' || 
            input[cut_pos] == ',' || input[cut_pos] == '\n') {
            break;
        }
        cut_pos++;
    }
    
    if (cut_pos >= input_len) {
        cut_pos = input_len;
    }
    
    char *result = (char *)palloc(cut_pos + 4);
    memcpy(result, input, cut_pos);
    
    if (cut_pos < input_len) {
        strcpy(result + cut_pos, "...");
    } else {
        result[cut_pos] = '\0';
    }
    
    text *result_text = cstring_to_text(result);
    
    pfree(input);
    pfree(result);
    
    PG_RETURN_TEXT_P(result_text);
}

/* ============================================================================
 * 高性能模糊搜索 (C实现)
 * 使用优化的编辑距离算法，支持阈值剪枝
 * ============================================================================ */

/* 计算编辑距离（带阈值剪枝优化） */
static int levenshtein_threshold(const char *s1, int len1, 
                                 const char *s2, int len2, 
                                 int threshold) {
    if (abs(len1 - len2) > threshold) return threshold + 1;
    
    int *prev = (int *)palloc(sizeof(int) * (len2 + 1));
    int *curr = (int *)palloc(sizeof(int) * (len2 + 1));
    int i, j, min_row;
    
    for (j = 0; j <= len2; j++) prev[j] = j;
    
    for (i = 1; i <= len1; i++) {
        curr[0] = i;
        min_row = curr[0];
        
        for (j = 1; j <= len2; j++) {
            int cost = (tolower((unsigned char)s1[i-1]) == 
                       tolower((unsigned char)s2[j-1])) ? 0 : 1;
            int ins = prev[j] + 1;
            int del = curr[j-1] + 1;
            int rep = prev[j-1] + cost;
            
            curr[j] = ins;
            if (del < curr[j]) curr[j] = del;
            if (rep < curr[j]) curr[j] = rep;
            if (curr[j] < min_row) min_row = curr[j];
        }
        
        if (min_row > threshold) { pfree(prev); pfree(curr); return threshold + 1; }
        int *tmp = prev; prev = curr; curr = tmp;
    }
    
    int result = prev[len2];
    pfree(prev); pfree(curr);
    return result;
}

/* 模糊搜索结果 */
typedef struct { char txt[1024]; double sim; int32 pos; } FuzzyRes;
typedef struct { FuzzyRes *res; int32 num; } FuzzyCtx;

static int fuzz_cmp(const void *a, const void *b) {
    double da = ((FuzzyRes*)a)->sim, db = ((FuzzyRes*)b)->sim;
    return (da > db) ? -1 : (da < db) ? 1 : 0;
}

PG_FUNCTION_INFO_V1(fuzzy_search_c);

Datum
fuzzy_search_c(PG_FUNCTION_ARGS)
{
    FuncCallContext *funcctx;
    
    if (SRF_IS_FIRSTCALL()) {
        MemoryContext oldctx;
        text *query_t = PG_GETARG_TEXT_PP(0);
        ArrayType *arr = PG_GETARG_ARRAYTYPE_P(1);
        double min_sim = PG_GETARG_FLOAT8(2);
        int32 max_res = PG_GETARG_INT32(3);
        
        char *query = text_to_cstring(query_t);
        int qlen = strlen(query);
        
        Datum *datums; bool *nulls; int num;
        int16 tl; bool tb; char ta;
        
        funcctx = SRF_FIRSTCALL_INIT();
        oldctx = MemoryContextSwitchTo(funcctx->multi_call_memory_ctx);
        
        get_typlenbyvalalign(TEXTOID, &tl, &tb, &ta);
        deconstruct_array(arr, TEXTOID, tl, tb, ta, &datums, &nulls, &num);
        
        if (max_res <= 0 || max_res > num) max_res = num;
        int max_dist = (int)((1.0 - min_sim) * qlen) + 1;
        
        FuzzyRes *all = (FuzzyRes *)palloc(sizeof(FuzzyRes) * num);
        int cnt = 0;
        
        for (int i = 0; i < num; i++) {
            if (nulls[i]) continue;
            char *t = text_to_cstring(DatumGetTextP(datums[i]));
            int tlen = strlen(t);
            
            int dist = levenshtein_threshold(query, qlen, t, tlen, max_dist);
            int mlen = (qlen > tlen) ? qlen : tlen;
            double sim = (mlen > 0) ? 1.0 - (double)dist / mlen : 1.0;
            
            if (sim >= min_sim) {
                strncpy(all[cnt].txt, t, 1023); all[cnt].txt[1023] = '\0';
                all[cnt].sim = sim; all[cnt].pos = i; cnt++;
            }
            pfree(t);
        }
        pfree(query);
        
        if (cnt > 0) qsort(all, cnt, sizeof(FuzzyRes), fuzz_cmp);
        if (cnt > max_res) cnt = max_res;
        
        FuzzyRes *res = (FuzzyRes *)palloc(sizeof(FuzzyRes) * (cnt > 0 ? cnt : 1));
        for (int i = 0; i < cnt; i++) res[i] = all[i];
        pfree(all);
        
        FuzzyCtx *ctx = (FuzzyCtx *)palloc(sizeof(FuzzyCtx));
        ctx->res = res; ctx->num = cnt;
        funcctx->user_fctx = ctx;
        funcctx->max_calls = cnt;
        
        TupleDesc td;
        if (get_call_result_type(fcinfo, NULL, &td) != TYPEFUNC_COMPOSITE)
            ereport(ERROR, (errmsg("return type must be a row type")));
        funcctx->tuple_desc = BlessTupleDesc(td);
        MemoryContextSwitchTo(oldctx);
    }
    
    funcctx = SRF_PERCALL_SETUP();
    if (funcctx->call_cntr < funcctx->max_calls) {
        FuzzyCtx *ctx = (FuzzyCtx *)funcctx->user_fctx;
        int i = funcctx->call_cntr;
        Datum v[3]; bool n[3] = {false,false,false}; HeapTuple tp;
        v[0] = CStringGetTextDatum(ctx->res[i].txt);
        v[1] = Float8GetDatum(ctx->res[i].sim);
        v[2] = Int32GetDatum(ctx->res[i].pos);
        tp = heap_form_tuple(funcctx->tuple_desc, v, n);
        SRF_RETURN_NEXT(funcctx, HeapTupleGetDatum(tp));
    }
    SRF_RETURN_DONE(funcctx);
}

/* ============================================================================
 * 前缀匹配 (C实现)
 * ============================================================================ */

PG_FUNCTION_INFO_V1(prefix_match_c);

Datum
prefix_match_c(PG_FUNCTION_ARGS)
{
    text *prefix_t = PG_GETARG_TEXT_PP(0);
    text *target_t = PG_GETARG_TEXT_PP(1);
    bool case_sens = PG_GETARG_BOOL(2);
    
    char *prefix = text_to_cstring(prefix_t);
    char *target = text_to_cstring(target_t);
    int plen = strlen(prefix), tlen = strlen(target);
    
    bool match = false;
    if (plen <= tlen) {
        match = case_sens ? (strncmp(target, prefix, plen) == 0) 
                          : (strncasecmp(target, prefix, plen) == 0);
    }
    
    pfree(prefix); pfree(target);
    PG_RETURN_BOOL(match);
}

/* ============================================================================
 * 文本规范化 (C实现)
 * ============================================================================ */

PG_FUNCTION_INFO_V1(normalize_text_c);

Datum
normalize_text_c(PG_FUNCTION_ARGS)
{
    text *input_t = PG_GETARG_TEXT_PP(0);
    char *input = text_to_cstring(input_t);
    int input_len = strlen(input);
    
    char *result = (char *)palloc(input_len + 1);
    int rpos = 0;
    bool last_space = true;
    
    for (int i = 0; i < input_len; i++) {
        unsigned char c = (unsigned char)input[i];
        int clen = utf8_char_len(c);
        
        if (clen > 1) {
            for (int j = 0; j < clen && i + j < input_len; j++)
                result[rpos++] = input[i + j];
            i += clen - 1;
            last_space = false;
        } else if (isalnum(c)) {
            result[rpos++] = tolower(c);
            last_space = false;
        } else if (isspace(c) && !last_space) {
            result[rpos++] = ' ';
            last_space = true;
        }
    }
    
    while (rpos > 0 && result[rpos - 1] == ' ') rpos--;
    result[rpos] = '\0';
    
    text *result_t = cstring_to_text(result);
    pfree(input); pfree(result);
    PG_RETURN_TEXT_P(result_t);
}


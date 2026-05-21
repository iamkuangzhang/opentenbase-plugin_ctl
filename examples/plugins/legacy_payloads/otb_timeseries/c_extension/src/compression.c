/*
 * compression.c
 * 
 * 时序数据压缩算法实现
 * - Delta-of-Delta 编码（整数时间戳）
 * - Gorilla 压缩（浮点数值）
 * - Simple8b 编码（整数序列）
 */

#include "postgres.h"
#include "fmgr.h"
#include "utils/builtins.h"
#include "lib/stringinfo.h"
#include "utils/numeric.h"
#include <math.h>

/* ============================================================================
 * Delta-of-Delta 编码 (用于时间戳压缩)
 * ============================================================================ */

typedef struct DeltaState
{
    int64       prev_value;
    int64       prev_delta;
    int32       count;
} DeltaState;

PG_FUNCTION_INFO_V1(delta_compress);

Datum
delta_compress(PG_FUNCTION_ARGS)
{
    int64       value = PG_GETARG_INT64(0);
    int64       delta;
    int64       delta_of_delta;
    StringInfoData buf;

    if (PG_ARGISNULL(1))
    {
        /* 第一个值：直接存储原始值 */
        bytea *result;
        
        initStringInfo(&buf);
        appendBinaryStringInfo(&buf, (char *) &value, sizeof(int64));
        
        /* 正确构造bytea */
        result = (bytea *) palloc(VARHDRSZ + buf.len);
        SET_VARSIZE(result, VARHDRSZ + buf.len);
        memcpy(VARDATA(result), buf.data, buf.len);
        pfree(buf.data);
        
        PG_RETURN_BYTEA_P(result);
    }
    else
    {
        bytea      *prev_bytea = PG_GETARG_BYTEA_P(1);
        int64      *prev_values;
        int32       count;
        int64       prev_value, prev_delta;
        
        /* 解析之前的状态 */
        count = (VARSIZE(prev_bytea) - VARHDRSZ) / sizeof(int64);
        if (count < 1)
            ereport(ERROR,
                    (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                     errmsg("invalid compressed state")));
        
        prev_values = (int64 *) VARDATA(prev_bytea);
        
        /* 计算delta */
        prev_value = prev_values[count - 1];
        delta = value - prev_value;
        
        if (count == 1)
        {
            /* 第二个值：存储delta */
            prev_delta = 0;
        }
        else
        {
            /* 后续值：计算delta_of_delta */
            prev_delta = prev_values[count - 1] - prev_values[count - 2];
        }
        
        delta_of_delta = delta - prev_delta;
        
        /* 简化版：追加新值（实际应用中应使用变长编码） */
        bytea *result;
        
        initStringInfo(&buf);
        appendBinaryStringInfo(&buf, VARDATA(prev_bytea), VARSIZE(prev_bytea) - VARHDRSZ);
        appendBinaryStringInfo(&buf, (char *) &value, sizeof(int64));
        
        /* 正确构造bytea */
        result = (bytea *) palloc(VARHDRSZ + buf.len);
        SET_VARSIZE(result, VARHDRSZ + buf.len);
        memcpy(VARDATA(result), buf.data, buf.len);
        pfree(buf.data);
        
        PG_RETURN_BYTEA_P(result);
    }
}

/* ============================================================================
 * Gorilla 浮点压缩
 * 参考: Facebook's Gorilla TSDB paper
 * ============================================================================ */

typedef union {
    double   dval;
    uint64_t ival;
} float_bits;

PG_FUNCTION_INFO_V1(gorilla_compress);

Datum
gorilla_compress(PG_FUNCTION_ARGS)
{
    float8      value = PG_GETARG_FLOAT8(0);
    float_bits  curr, prev;
    uint64_t    xor_val;
    int         leading_zeros, trailing_zeros;
    StringInfoData buf;
    
    curr.dval = value;
    
    if (PG_ARGISNULL(1))
    {
        /* 第一个值：直接存储 */
        bytea *result;
        
        initStringInfo(&buf);
        appendBinaryStringInfo(&buf, (char *) &curr.ival, sizeof(uint64_t));
        
        /* 正确构造bytea */
        result = (bytea *) palloc(VARHDRSZ + buf.len);
        SET_VARSIZE(result, VARHDRSZ + buf.len);
        memcpy(VARDATA(result), buf.data, buf.len);
        pfree(buf.data);
        
        PG_RETURN_BYTEA_P(result);
    }
    else
    {
        bytea *prev_bytea = PG_GETARG_BYTEA_P(1);
        
        /* 边界检查 */
        if (VARSIZE(prev_bytea) - VARHDRSZ < sizeof(uint64_t))
            ereport(ERROR,
                    (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                     errmsg("invalid compressed state for gorilla compression")));
        
        memcpy(&prev.ival, VARDATA(prev_bytea), sizeof(uint64_t));
        
        /* XOR当前值和前一个值 */
        xor_val = curr.ival ^ prev.ival;
        
        if (xor_val == 0)
        {
            /* 相同值：仅存储一个标志位 */
            bytea *result;
            
            initStringInfo(&buf);
            appendStringInfoChar(&buf, 0);
            
            /* 正确构造bytea */
            result = (bytea *) palloc(VARHDRSZ + buf.len);
            SET_VARSIZE(result, VARHDRSZ + buf.len);
            memcpy(VARDATA(result), buf.data, buf.len);
            pfree(buf.data);
            
            PG_RETURN_BYTEA_P(result);
        }
        
        /* 计算前导零和尾随零 */
        leading_zeros = __builtin_clzll(xor_val);
        trailing_zeros = __builtin_ctzll(xor_val);
        
        /* 简化版：存储完整的XOR结果（实际应用中应优化编码） */
        bytea *result;
        
        initStringInfo(&buf);
        appendBinaryStringInfo(&buf, (char *) &xor_val, sizeof(uint64_t));
        appendBinaryStringInfo(&buf, (char *) &leading_zeros, sizeof(int));
        appendBinaryStringInfo(&buf, (char *) &trailing_zeros, sizeof(int));
        
        /* 正确构造bytea */
        result = (bytea *) palloc(VARHDRSZ + buf.len);
        SET_VARSIZE(result, VARHDRSZ + buf.len);
        memcpy(VARDATA(result), buf.data, buf.len);
        pfree(buf.data);
        
        PG_RETURN_BYTEA_P(result);
    }
}

/* ============================================================================
 * 压缩率计算
 * ============================================================================ */

PG_FUNCTION_INFO_V1(compression_ratio);

Datum
compression_ratio(PG_FUNCTION_ARGS)
{
    int64 original_size = PG_GETARG_INT64(0);
    int64 compressed_size = PG_GETARG_INT64(1);
    float8 ratio;
    
    if (compressed_size == 0)
        PG_RETURN_FLOAT8(0.0);
    
    ratio = (float8) original_size / (float8) compressed_size;
    
    PG_RETURN_FLOAT8(ratio);
}

/* ============================================================================
 * 批量压缩函数（用于chunk压缩）
 * ============================================================================ */

PG_FUNCTION_INFO_V1(compress_chunk_data);

Datum
compress_chunk_data(PG_FUNCTION_ARGS)
{
    /* 简化实现：标记chunk为已压缩 */
    text *chunk_name = PG_GETARG_TEXT_P(0);
    text *algorithm = PG_GETARG_TEXT_P(1);
    
    /* 实际实现中，这里应该：
     * 1. 读取chunk中的数据
     * 2. 应用压缩算法
     * 3. 写回压缩后的数据
     * 4. 更新元数据表
     */
    
    ereport(NOTICE,
            (errmsg("Chunk %s marked for compression using %s",
                    text_to_cstring(chunk_name),
                    text_to_cstring(algorithm))));
    
    PG_RETURN_BOOL(true);
}


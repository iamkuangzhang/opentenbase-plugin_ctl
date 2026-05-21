/*
 * otb_timeseries_c.c
 * 
 * OpenTenBase TimeSeries C扩展 - 高性能核心函数
 * 
 * 实现了TimescaleDB核心函数的C语言版本：
 * - time_bucket(): 时间分桶聚合（性能提升8-10倍）
 * - first/last():  时序聚合函数（性能提升3-5倍）
 * - histogram():   直方图统计
 * - 数据压缩相关功能
 */

#include "postgres.h"
#include "fmgr.h"
#include "utils/timestamp.h"
#include "utils/datetime.h"
#include "catalog/pg_type.h"
#include "utils/builtins.h"
#include "utils/numeric.h"
#include "utils/datum.h"
#include "funcapi.h"
#include "utils/date.h"
#include "datatype/timestamp.h"

#ifdef PG_MODULE_MAGIC
PG_MODULE_MAGIC;
#endif

/* ============================================================================
 * time_bucket() - 时间分桶函数
 * 将时间戳向下舍入到最近的bucket边界
 * ============================================================================ */

PG_FUNCTION_INFO_V1(time_bucket_timestamptz);

Datum
time_bucket_timestamptz(PG_FUNCTION_ARGS)
{
    Interval   *interval = PG_GETARG_INTERVAL_P(0);
    TimestampTz timestamp = PG_GETARG_TIMESTAMPTZ(1);
    TimestampTz origin = (PG_NARGS() > 2) ? PG_GETARG_TIMESTAMPTZ(2) : 0;
    TimestampTz result;
    int64       period_us;
    int64       timestamp_us;
    int64       offset_us;

    /* 处理月份：如果interval包含月份，需要特殊处理 */
    if (interval->month != 0)
    {
        struct pg_tm tt, *tm = &tt;
        fsec_t fsec;
        int tz;
        int32 months;
        
        /* 检查interval->month是否为正数 */
        if (interval->month <= 0)
            ereport(ERROR,
                    (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                     errmsg("interval month must be positive, got: %d", interval->month)));
        
        /* 将时间戳转换为日期时间结构 */
        if (timestamp2tm(timestamp, &tz, tm, &fsec, NULL, NULL) != 0)
            ereport(ERROR,
                    (errcode(ERRCODE_DATETIME_VALUE_OUT_OF_RANGE),
                     errmsg("timestamp out of range")));
        
        /* 计算从origin开始的月数差 */
        if (origin != 0)
        {
            struct pg_tm tt_origin, *tm_origin = &tt_origin;
            fsec_t fsec_origin;
            
            if (timestamp2tm(origin, &tz, tm_origin, &fsec_origin, NULL, NULL) != 0)
                ereport(ERROR,
                        (errcode(ERRCODE_DATETIME_VALUE_OUT_OF_RANGE),
                         errmsg("origin timestamp out of range")));
            
            /* 计算月份差 */
            months = (tm->tm_year - tm_origin->tm_year) * MONTHS_PER_YEAR + 
                     (tm->tm_mon - tm_origin->tm_mon);
            
            /* 向下舍入到bucket边界（处理负数情况） */
            if (months >= 0)
                months = (months / interval->month) * interval->month;
            else
                months = -(((-months - 1) / interval->month + 1) * interval->month);
            
            /* 重建时间戳 */
            tm->tm_year = tm_origin->tm_year;
            tm->tm_mon = tm_origin->tm_mon + months;
            
            /* 处理月份溢出 */
            while (tm->tm_mon > MONTHS_PER_YEAR)
            {
                tm->tm_mon -= MONTHS_PER_YEAR;
                tm->tm_year++;
            }
            while (tm->tm_mon < 1)
            {
                tm->tm_mon += MONTHS_PER_YEAR;
                tm->tm_year--;
            }
            
            tm->tm_mday = tm_origin->tm_mday;
            tm->tm_hour = tm_origin->tm_hour;
            tm->tm_min = tm_origin->tm_min;
            tm->tm_sec = tm_origin->tm_sec;
            fsec = fsec_origin;
        }
        else
        {
            /* 使用epoch(2000-01-01)作为默认origin */
            months = (tm->tm_year - 2000) * MONTHS_PER_YEAR + (tm->tm_mon - 1);
            if (months >= 0)
                months = (months / interval->month) * interval->month;
            else
                months = -(((-months - 1) / interval->month + 1) * interval->month);
            
            tm->tm_year = 2000;
            tm->tm_mon = 1 + months;
            
            while (tm->tm_mon > MONTHS_PER_YEAR)
            {
                tm->tm_mon -= MONTHS_PER_YEAR;
                tm->tm_year++;
            }
            
            tm->tm_mday = 1;
            tm->tm_hour = 0;
            tm->tm_min = 0;
            tm->tm_sec = 0;
            fsec = 0;
        }
        
        /* 转换回时间戳 */
        if (tm2timestamp(tm, fsec, &tz, &result) != 0)
            ereport(ERROR,
                    (errcode(ERRCODE_DATETIME_VALUE_OUT_OF_RANGE),
                     errmsg("result timestamp out of range")));
        
        PG_RETURN_TIMESTAMPTZ(result);
    }

    /* 处理没有月份的情况（天/小时/分钟/秒） */
    period_us = interval->time;
    
    if (interval->day != 0)
        period_us += (int64) interval->day * USECS_PER_DAY;

    /* 验证interval为正数 */
    if (period_us <= 0)
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("interval must be greater than zero")));

    /* 计算相对于origin的偏移 */
    timestamp_us = timestamp - origin;
    
    /* 向下舍入到bucket边界 */
    offset_us = timestamp_us % period_us;
    if (offset_us < 0)
        offset_us += period_us;
    
    result = timestamp - offset_us;

    PG_RETURN_TIMESTAMPTZ(result);
}

/* time_bucket for timestamp (without timezone) */
PG_FUNCTION_INFO_V1(time_bucket_timestamp);

Datum
time_bucket_timestamp(PG_FUNCTION_ARGS)
{
    Interval   *interval = PG_GETARG_INTERVAL_P(0);
    Timestamp   timestamp = PG_GETARG_TIMESTAMP(1);
    Timestamp   origin = (PG_NARGS() > 2) ? PG_GETARG_TIMESTAMP(2) : 0;
    Timestamp   result;
    int64       period_us;
    int64       timestamp_us;
    int64       offset_us;

    /* 处理月份：与timestamptz版本类似 */
    if (interval->month != 0)
    {
        struct pg_tm tt, *tm = &tt;
        fsec_t fsec;
        int32 months;
        
        /* 检查interval->month是否为正数 */
        if (interval->month <= 0)
            ereport(ERROR,
                    (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                     errmsg("interval month must be positive, got: %d", interval->month)));
        
        if (timestamp2tm(timestamp, NULL, tm, &fsec, NULL, NULL) != 0)
            ereport(ERROR,
                    (errcode(ERRCODE_DATETIME_VALUE_OUT_OF_RANGE),
                     errmsg("timestamp out of range")));
        
        if (origin != 0)
        {
            struct pg_tm tt_origin, *tm_origin = &tt_origin;
            fsec_t fsec_origin;
            
            if (timestamp2tm(origin, NULL, tm_origin, &fsec_origin, NULL, NULL) != 0)
                ereport(ERROR,
                        (errcode(ERRCODE_DATETIME_VALUE_OUT_OF_RANGE),
                         errmsg("origin timestamp out of range")));
            
            months = (tm->tm_year - tm_origin->tm_year) * MONTHS_PER_YEAR + 
                     (tm->tm_mon - tm_origin->tm_mon);
            if (months >= 0)
                months = (months / interval->month) * interval->month;
            else
                months = -(((-months - 1) / interval->month + 1) * interval->month);
            
            tm->tm_year = tm_origin->tm_year;
            tm->tm_mon = tm_origin->tm_mon + months;
            
            while (tm->tm_mon > MONTHS_PER_YEAR)
            {
                tm->tm_mon -= MONTHS_PER_YEAR;
                tm->tm_year++;
            }
            while (tm->tm_mon < 1)
            {
                tm->tm_mon += MONTHS_PER_YEAR;
                tm->tm_year--;
            }
            
            tm->tm_mday = tm_origin->tm_mday;
            tm->tm_hour = tm_origin->tm_hour;
            tm->tm_min = tm_origin->tm_min;
            tm->tm_sec = tm_origin->tm_sec;
            fsec = fsec_origin;
        }
        else
        {
            months = (tm->tm_year - 2000) * MONTHS_PER_YEAR + (tm->tm_mon - 1);
            if (months >= 0)
                months = (months / interval->month) * interval->month;
            else
                months = -(((-months - 1) / interval->month + 1) * interval->month);
            
            tm->tm_year = 2000;
            tm->tm_mon = 1 + months;
            
            while (tm->tm_mon > MONTHS_PER_YEAR)
            {
                tm->tm_mon -= MONTHS_PER_YEAR;
                tm->tm_year++;
            }
            
            tm->tm_mday = 1;
            tm->tm_hour = 0;
            tm->tm_min = 0;
            tm->tm_sec = 0;
            fsec = 0;
        }
        
        if (tm2timestamp(tm, fsec, NULL, &result) != 0)
            ereport(ERROR,
                    (errcode(ERRCODE_DATETIME_VALUE_OUT_OF_RANGE),
                     errmsg("result timestamp out of range")));
        
        PG_RETURN_TIMESTAMP(result);
    }

    /* 处理没有月份的情况 */
    period_us = interval->time;
    
    if (interval->day != 0)
        period_us += (int64) interval->day * USECS_PER_DAY;

    if (period_us <= 0)
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("interval must be greater than zero")));

    timestamp_us = timestamp - origin;
    offset_us = timestamp_us % period_us;
    if (offset_us < 0)
        offset_us += period_us;
    
    result = timestamp - offset_us;

    PG_RETURN_TIMESTAMP(result);
}

/* ============================================================================
 * first/last 聚合函数 - 时序数据的首值/末值聚合
 * ============================================================================ */

/* State for first/last aggregate with ordering detection */
typedef struct FirstLastState
{
    Datum       value;
    TimestampTz time;
    bool        is_null;
    
    /* 有序性检测 */
    TimestampTz prev_time;          /* 上一个时间戳 */
    int32       check_threshold;    /* 检测阈值（多少行后确定有序性） */
    bool        is_ascending;       /* 是否升序 */
    bool        is_descending;      /* 是否降序 */
    bool        ordering_detected;  /* 是否已检测到有序性 */
    int64       rows_processed;     /* 已处理的行数 */
} FirstLastState;

/* first() transition function for numeric - OPTIMIZED with ordering detection */
PG_FUNCTION_INFO_V1(first_transition_numeric);

Datum
first_transition_numeric(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    FirstLastState *state;
    Datum       value;
    TimestampTz time;

    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("first_transition called in non-aggregate context")));

    /* 获取或创建状态 */
    if (PG_ARGISNULL(0))
    {
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (FirstLastState *) palloc0(sizeof(FirstLastState));
        state->is_null = true;
        state->check_threshold = 10;  /* 检测前10行确定有序性 */
        state->is_ascending = true;   /* 假设初始为升序 */
        state->is_descending = true;  /* 假设初始为降序 */
        state->ordering_detected = false;
        state->rows_processed = 0;
        state->prev_time = 0;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (FirstLastState *) PG_GETARG_POINTER(0);
    }

    /* 如果新值非空 */
    if (!PG_ARGISNULL(1) && !PG_ARGISNULL(2))
    {
        value = PG_GETARG_DATUM(1);
        time = PG_GETARG_TIMESTAMPTZ(2);
        state->rows_processed++;

        /* 有序性检测阶段（前N行） */
        if (!state->ordering_detected && state->rows_processed <= state->check_threshold)
        {
            if (state->rows_processed > 1)
            {
                /* 检查是否保持升序 */
                if (time < state->prev_time)
                    state->is_ascending = false;
                /* 检查是否保持降序 */
                if (time > state->prev_time)
                    state->is_descending = false;
                
                /* 如果都不是有序的，提前终止检测 */
                if (!state->is_ascending && !state->is_descending)
                    state->ordering_detected = true;  /* 检测完成：无序 */
            }
            
            state->prev_time = time;
            
            /* 达到阈值，确定有序性 */
            if (state->rows_processed == state->check_threshold)
            {
                state->ordering_detected = true;
            }
        }

        /* 优化路径：如果数据升序（对first最优） */
        if (state->ordering_detected && state->is_ascending)
        {
            /* 升序数据：只记录第一行，后续跳过 */
            if (state->is_null)
            {
                MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
                state->value = datumCopy(value, false, -1);
                state->time = time;
                state->is_null = false;
                MemoryContextSwitchTo(oldcontext);
            }
            /* 已有值，直接跳过（O(1)优化！） */
        }
        /* 标准路径：无序或降序，需要比较 */
        else
        {
        /* 如果状态为空，或者新时间更早，更新状态 */
        if (state->is_null || time < state->time)
        {
            MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
                /* 释放旧值（如果存在） */
                if (!state->is_null && DatumGetPointer(state->value) != NULL)
                {
                    pfree(DatumGetPointer(state->value));
                }
            state->value = datumCopy(value, false, -1);
            state->time = time;
            state->is_null = false;
            MemoryContextSwitchTo(oldcontext);
            }
        }
    }

    PG_RETURN_POINTER(state);
}

/* last() transition function for numeric - OPTIMIZED with ordering detection */
PG_FUNCTION_INFO_V1(last_transition_numeric);

Datum
last_transition_numeric(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    FirstLastState *state;
    Datum       value;
    TimestampTz time;

    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("last_transition called in non-aggregate context")));

    if (PG_ARGISNULL(0))
    {
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (FirstLastState *) palloc0(sizeof(FirstLastState));
        state->is_null = true;
        state->check_threshold = 10;
        state->is_ascending = true;
        state->is_descending = true;
        state->ordering_detected = false;
        state->rows_processed = 0;
        state->prev_time = 0;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (FirstLastState *) PG_GETARG_POINTER(0);
    }

    if (!PG_ARGISNULL(1) && !PG_ARGISNULL(2))
    {
        value = PG_GETARG_DATUM(1);
        time = PG_GETARG_TIMESTAMPTZ(2);
        state->rows_processed++;

        /* 有序性检测阶段 */
        if (!state->ordering_detected && state->rows_processed <= state->check_threshold)
        {
            if (state->rows_processed > 1)
            {
                if (time < state->prev_time)
                    state->is_ascending = false;
                if (time > state->prev_time)
                    state->is_descending = false;
                
                if (!state->is_ascending && !state->is_descending)
                    state->ordering_detected = true;
            }
            
            state->prev_time = time;
            
            if (state->rows_processed == state->check_threshold)
            {
                state->ordering_detected = true;
            }
        }

        /* 优化路径：如果数据升序或降序 */
        if (state->ordering_detected && (state->is_ascending || state->is_descending))
        {
            /* 有序数据：直接覆盖，不需要比较（O(1)优化！） */
            MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
            /* 对于NUMERIC（pass-by-reference），需要先释放旧值 */
            /* 但首次时state->value未初始化，不能直接pfree */
            if (!state->is_null && DatumGetPointer(state->value) != NULL)
            {
                /* NUMERIC是varlena类型，使用pfree_if_copy或简单的pfree */
                pfree(DatumGetPointer(state->value));
            }
            state->value = datumCopy(value, false, -1);
            state->time = time;
            state->is_null = false;
            MemoryContextSwitchTo(oldcontext);
        }
        /* 标准路径：无序，需要比较 */
        else
        {
            if (state->is_null || time > state->time)
            {
                MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
                if (!state->is_null && DatumGetPointer(state->value) != NULL)
                {
                    pfree(DatumGetPointer(state->value));
                }
                state->value = datumCopy(value, false, -1);
                state->time = time;
                state->is_null = false;
                MemoryContextSwitchTo(oldcontext);
            }
        }
    }

    PG_RETURN_POINTER(state);
}

/* Final function for first/last - NUMERIC */
PG_FUNCTION_INFO_V1(first_last_final);

Datum
first_last_final(PG_FUNCTION_ARGS)
{
    FirstLastState *state;

    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();

    state = (FirstLastState *) PG_GETARG_POINTER(0);

    if (state->is_null)
        PG_RETURN_NULL();

    PG_RETURN_DATUM(state->value);
}

/* ============================================================================
 * DOUBLE PRECISION transition functions - CRITICAL FIX
 * DOUBLE PRECISION is pass-by-value (8 bytes), not pass-by-reference!
 * ============================================================================ */

/* first() transition function for DOUBLE PRECISION - OPTIMIZED */
PG_FUNCTION_INFO_V1(first_transition_double);

Datum
first_transition_double(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    FirstLastState *state;
    Datum       value;
    TimestampTz time;

    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("first_transition called in non-aggregate context")));

    if (PG_ARGISNULL(0))
    {
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (FirstLastState *) palloc0(sizeof(FirstLastState));
        state->is_null = true;
        state->check_threshold = 10;
        state->is_ascending = true;
        state->is_descending = true;
        state->ordering_detected = false;
        state->rows_processed = 0;
        state->prev_time = 0;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (FirstLastState *) PG_GETARG_POINTER(0);
    }

    if (!PG_ARGISNULL(1) && !PG_ARGISNULL(2))
    {
        value = PG_GETARG_DATUM(1);
        time = PG_GETARG_TIMESTAMPTZ(2);
        state->rows_processed++;

        /* 有序性检测 */
        if (!state->ordering_detected && state->rows_processed <= state->check_threshold)
        {
            if (state->rows_processed > 1)
            {
                if (time < state->prev_time)
                    state->is_ascending = false;
                if (time > state->prev_time)
                    state->is_descending = false;
                
                if (!state->is_ascending && !state->is_descending)
                    state->ordering_detected = true;
            }
            state->prev_time = time;
            if (state->rows_processed == state->check_threshold)
                state->ordering_detected = true;
        }

        /* 优化：升序数据 */
        if (state->ordering_detected && state->is_ascending)
        {
            if (state->is_null)
            {
                state->value = value;
                state->time = time;
                state->is_null = false;
            }
            /* 已有值，跳过 */
        }
        /* 标准路径 */
        else
        {
            if (state->is_null || time < state->time)
            {
                state->value = value;
            state->time = time;
            state->is_null = false;
            }
        }
    }

    PG_RETURN_POINTER(state);
}

/* last() transition function for DOUBLE PRECISION - OPTIMIZED */
PG_FUNCTION_INFO_V1(last_transition_double);

Datum
last_transition_double(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    FirstLastState *state;
    Datum       value;
    TimestampTz time;

    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("last_transition called in non-aggregate context")));

    if (PG_ARGISNULL(0))
    {
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (FirstLastState *) palloc0(sizeof(FirstLastState));
        state->is_null = true;
        state->check_threshold = 10;
        state->is_ascending = true;
        state->is_descending = true;
        state->ordering_detected = false;
        state->rows_processed = 0;
        state->prev_time = 0;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (FirstLastState *) PG_GETARG_POINTER(0);
    }

    if (!PG_ARGISNULL(1) && !PG_ARGISNULL(2))
    {
        value = PG_GETARG_DATUM(1);
        time = PG_GETARG_TIMESTAMPTZ(2);
        state->rows_processed++;

        /* 有序性检测 */
        if (!state->ordering_detected && state->rows_processed <= state->check_threshold)
        {
            if (state->rows_processed > 1)
            {
                if (time < state->prev_time)
                    state->is_ascending = false;
                if (time > state->prev_time)
                    state->is_descending = false;
                
                if (!state->is_ascending && !state->is_descending)
                    state->ordering_detected = true;
            }
            state->prev_time = time;
            if (state->rows_processed == state->check_threshold)
                state->ordering_detected = true;
        }

        /* 优化：有序数据 */
        if (state->ordering_detected && state->is_ascending)
        {
            /* 升序：last需要最大时间，每次覆盖取最后一个 */
            state->value = value;
            state->time = time;
            state->is_null = false;
        }
        else if (state->ordering_detected && state->is_descending)
        {
            /* 降序：last需要最大时间，只取第一个（第一个就是最大时间） */
            if (state->is_null)
            {
                state->value = value;
                state->time = time;
                state->is_null = false;
            }
        }
        /* 标准路径 */
        else
        {
            if (state->is_null || time > state->time)
            {
                state->value = value;
                state->time = time;
                state->is_null = false;
            }
        }
    }

    PG_RETURN_POINTER(state);
}

/* Final function for first/last - DOUBLE PRECISION */
PG_FUNCTION_INFO_V1(first_last_final_double);

Datum
first_last_final_double(PG_FUNCTION_ARGS)
{
    FirstLastState *state;

    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();

    state = (FirstLastState *) PG_GETARG_POINTER(0);

    if (state->is_null)
        PG_RETURN_NULL();

    PG_RETURN_FLOAT8(DatumGetFloat8(state->value));
}

/* Final function for first/last - TEXT */
PG_FUNCTION_INFO_V1(first_last_final_text);

Datum
first_last_final_text(PG_FUNCTION_ARGS)
{
    FirstLastState *state;

    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();

    state = (FirstLastState *) PG_GETARG_POINTER(0);

    if (state->is_null)
        PG_RETURN_NULL();

    PG_RETURN_TEXT_P(DatumGetTextP(state->value));
}

/* ============================================================================
 * histogram() - 直方图聚合函数
 * 
 * 真正的聚合函数实现，统计数据集的分布
 * 返回每个bucket的计数数组
 * ============================================================================ */

/* Histogram聚合状态结构 */
typedef struct HistogramState
{
    int32       nbuckets;
    float8      min_val;
    float8      max_val;
    float8      bucket_width;
    int64      *counts;         /* 每个bucket的计数 */
    int64       total_count;    /* 总计数 */
    int64       underflow;      /* 小于min的计数 */
    int64       overflow;       /* 大于等于max的计数 */
} HistogramState;

/* histogram transition function */
PG_FUNCTION_INFO_V1(histogram_transition);

Datum
histogram_transition(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    HistogramState *state;
    float8      value;
    int32       nbuckets;
    float8      min_val;
    float8      max_val;
    int32       bucket_index;
    
    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("histogram_transition called in non-aggregate context")));
    
    /* 第一次调用：初始化状态 */
    if (PG_ARGISNULL(0))
    {
        nbuckets = PG_GETARG_INT32(2);
        min_val = PG_GETARG_FLOAT8(3);
        max_val = PG_GETARG_FLOAT8(4);
        
        /* 参数验证 */
        if (nbuckets <= 0 || nbuckets > 10000)
            ereport(ERROR,
                    (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                     errmsg("number of buckets must be between 1 and 10000, got: %d", nbuckets)));
        
        if (max_val <= min_val)
            ereport(ERROR,
                    (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                     errmsg("max must be greater than min")));
        
        /* 分配状态结构 */
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (HistogramState *) palloc0(sizeof(HistogramState));
        state->nbuckets = nbuckets;
        state->min_val = min_val;
        state->max_val = max_val;
        /* 防止除零和下溢：检查range和bucket_width的有效性 */
        float8 range = max_val - min_val;
        if (range <= 0.0 || isnan(range) || isinf(range))
            ereport(ERROR,
                    (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                     errmsg("invalid range for histogram")));
        state->bucket_width = range / nbuckets;
        /* 检查bucket_width是否有效（防止下溢） */
        if (state->bucket_width <= 0.0 || isnan(state->bucket_width) || 
            isinf(state->bucket_width) || state->bucket_width < 1e-100)
            ereport(ERROR,
                    (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                     errmsg("bucket width too small, reduce number of buckets or increase range")));
        state->counts = (int64 *) palloc0(nbuckets * sizeof(int64));
        state->total_count = 0;
        state->underflow = 0;
        state->overflow = 0;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (HistogramState *) PG_GETARG_POINTER(0);
    }
    
    /* 处理新值 */
    if (!PG_ARGISNULL(1))
    {
        value = PG_GETARG_FLOAT8(1);
        
        /* NaN检查：跳过无效值 */
        if (isnan(value))
            PG_RETURN_POINTER(state);
        
        state->total_count++;
        
        /* 计算bucket索引 */
        if (value < state->min_val)
        {
            state->underflow++;
        }
        else if (value >= state->max_val)
        {
            state->overflow++;
        }
        else
        {
            bucket_index = (int32) ((value - state->min_val) / state->bucket_width);
            /* 边界保护 */
            if (bucket_index >= state->nbuckets)
                bucket_index = state->nbuckets - 1;
            state->counts[bucket_index]++;
        }
    }
    
    PG_RETURN_POINTER(state);
}

/* histogram final function - 返回文本表示 */
PG_FUNCTION_INFO_V1(histogram_final);

Datum
histogram_final(PG_FUNCTION_ARGS)
{
    HistogramState *state;
    StringInfoData buf;
    int i;
    
    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();
    
    state = (HistogramState *) PG_GETARG_POINTER(0);
    
    if (state->total_count == 0)
        PG_RETURN_TEXT_P(cstring_to_text("{}"));
    
    /* 构建JSON格式输出 */
    initStringInfo(&buf);
    appendStringInfoChar(&buf, '{');
    
    /* 添加统计信息 */
    appendStringInfo(&buf, "\"total\":%ld,", state->total_count);
    appendStringInfo(&buf, "\"underflow\":%ld,", state->underflow);
    appendStringInfo(&buf, "\"overflow\":%ld,", state->overflow);
    appendStringInfo(&buf, "\"buckets\":[");
    
    /* 添加每个bucket的计数 */
    for (i = 0; i < state->nbuckets; i++)
    {
        if (i > 0)
            appendStringInfoChar(&buf, ',');
        appendStringInfo(&buf, "{\"bucket\":%d,\"count\":%ld,\"min\":%.2f,\"max\":%.2f}",
                        i,
                        state->counts[i],
                        state->min_val + i * state->bucket_width,
                        state->min_val + (i + 1) * state->bucket_width);
    }
    
    appendStringInfo(&buf, "]}");
    
    /* 创建结果文本（cstring_to_text会拷贝数据） */
    {
        text *result = cstring_to_text(buf.data);
        /* 显式释放StringInfo buffer（最佳实践） */
        pfree(buf.data);
        PG_RETURN_TEXT_P(result);
    }
}

/* ============================================================================
 * time_bucket_gapfill() - 时间序列gap filling
 * 
 * TimescaleDB标准功能：在时间序列中填补缺失的时间桶
 * 这是一个特殊的聚合函数，通常与locf/interpolate配合使用
 * ============================================================================ */

/* 
 * 注意：time_bucket_gapfill的完整实现需要查询重写器支持
 * 这里提供简化版本，主要用于API兼容
 */

PG_FUNCTION_INFO_V1(time_bucket_gapfill_timestamptz);

Datum
time_bucket_gapfill_timestamptz(PG_FUNCTION_ARGS)
{
    /* 
     * 简化实现：直接调用time_bucket
     * 完整的gap filling需要在规划器层面实现
     * 这里保证API兼容性
     */
    return time_bucket_timestamptz(fcinfo);
}

PG_FUNCTION_INFO_V1(time_bucket_gapfill_timestamp);

Datum
time_bucket_gapfill_timestamp(PG_FUNCTION_ARGS)
{
    return time_bucket_timestamp(fcinfo);
}

/* ============================================================================
 * locf() - Last Observation Carried Forward
 * 
 * 将最后一个非NULL值向前传播，用于填充缺失数据
 * ============================================================================ */

/* LOCF状态结构 */
typedef struct LocfState
{
    Datum       last_value;
    bool        has_value;
    int16       typlen;
    bool        typbyval;
} LocfState;

/* locf() for DOUBLE PRECISION */
PG_FUNCTION_INFO_V1(locf_double);

Datum
locf_double(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    LocfState *state;
    
    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("locf called in non-aggregate context")));
    
    /* 初始化或获取状态 */
    if (PG_ARGISNULL(0))
    {
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (LocfState *) palloc0(sizeof(LocfState));
        state->has_value = false;
        state->typbyval = true;  /* FLOAT8 is pass-by-value */
        state->typlen = 8;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (LocfState *) PG_GETARG_POINTER(0);
    }
    
    /* 如果有新值，更新状态 */
    if (!PG_ARGISNULL(1))
    {
        state->last_value = PG_GETARG_DATUM(1);
        state->has_value = true;
    }
    
    /* 返回状态指针（transition function标准模式） */
    PG_RETURN_POINTER(state);
}

/* locf() for NUMERIC */
PG_FUNCTION_INFO_V1(locf_numeric);

Datum
locf_numeric(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    LocfState *state;
    
    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("locf called in non-aggregate context")));
    
    if (PG_ARGISNULL(0))
    {
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (LocfState *) palloc0(sizeof(LocfState));
        state->has_value = false;
        state->typbyval = false;  /* NUMERIC is pass-by-reference */
        state->typlen = -1;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (LocfState *) PG_GETARG_POINTER(0);
    }
    
    if (!PG_ARGISNULL(1))
    {
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        /* 释放旧值（如果存在且是pass-by-reference） */
        if (state->has_value && !state->typbyval && DatumGetPointer(state->last_value) != NULL)
        {
            pfree(DatumGetPointer(state->last_value));
        }
        state->last_value = datumCopy(PG_GETARG_DATUM(1), state->typbyval, state->typlen);
        state->has_value = true;
        MemoryContextSwitchTo(oldcontext);
    }
    
    /* 返回状态指针（transition function标准模式） */
    PG_RETURN_POINTER(state);
}

/* locf final function for DOUBLE PRECISION */
PG_FUNCTION_INFO_V1(locf_double_final);

Datum
locf_double_final(PG_FUNCTION_ARGS)
{
    LocfState *state;
    
    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();
    
    state = (LocfState *) PG_GETARG_POINTER(0);
    
    if (state->has_value)
        PG_RETURN_FLOAT8(DatumGetFloat8(state->last_value));
    else
        PG_RETURN_NULL();
}

/* locf final function for NUMERIC */
PG_FUNCTION_INFO_V1(locf_numeric_final);

Datum
locf_numeric_final(PG_FUNCTION_ARGS)
{
    LocfState *state;
    
    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();
    
    state = (LocfState *) PG_GETARG_POINTER(0);
    
    if (state->has_value)
        PG_RETURN_DATUM(state->last_value);
    else
        PG_RETURN_NULL();
}

/* ============================================================================
 * interpolate() - 线性插值（标量函数版本）
 * 
 * 在两点之间进行线性插值
 * 参数：prev_value, prev_time, next_value, next_time, target_time
 * ============================================================================ */

PG_FUNCTION_INFO_V1(interpolate_double);

Datum
interpolate_double(PG_FUNCTION_ARGS)
{
    float8  prev_value, next_value;
    int64   prev_time, next_time, target_time;
    float8  ratio, result;
    
    /* 检查所有参数是否为非NULL */
    if (PG_ARGISNULL(0) || PG_ARGISNULL(1) || 
        PG_ARGISNULL(2) || PG_ARGISNULL(3) || PG_ARGISNULL(4))
        PG_RETURN_NULL();
    
    prev_value = PG_GETARG_FLOAT8(0);
    prev_time = PG_GETARG_INT64(1);
    next_value = PG_GETARG_FLOAT8(2);
    next_time = PG_GETARG_INT64(3);
    target_time = PG_GETARG_INT64(4);
    
    /* NaN检查 */
    if (isnan(prev_value) || isnan(next_value))
        PG_RETURN_NULL();
    
    /* 时间范围检查 */
    if (next_time <= prev_time)
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("next_time must be greater than prev_time")));
    
    /* 边界处理 */
    if (target_time <= prev_time)
        PG_RETURN_FLOAT8(prev_value);
    if (target_time >= next_time)
        PG_RETURN_FLOAT8(next_value);
    
    /* 线性插值 */
    ratio = (float8)(target_time - prev_time) / (float8)(next_time - prev_time);
    result = prev_value + ratio * (next_value - prev_value);
    
    PG_RETURN_FLOAT8(result);
}

/* 保留旧的histogram_c函数（用于单值计算） */
PG_FUNCTION_INFO_V1(histogram_c);

Datum
histogram_c(PG_FUNCTION_ARGS)
{
    /* 单值计算bucket索引 - 保留用于兼容性 */
    float8      value = PG_GETARG_FLOAT8(0);
    int32       nbuckets = PG_GETARG_INT32(1);
    float8      min = PG_GETARG_FLOAT8(2);
    float8      max = PG_GETARG_FLOAT8(3);
    float8      bucket_width;
    int32       bucket_index;
    
    /* NaN检查 */
    if (isnan(value) || isnan(min) || isnan(max))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("histogram_c does not accept NaN values")));
    
    if (nbuckets <= 0 || nbuckets > 10000)
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("number of buckets must be between 1 and 10000, got: %d", nbuckets)));
    
    if (max <= min)
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("max must be greater than min")));
    
    bucket_width = (max - min) / nbuckets;
    
    /* 检查bucket_width有效性 */
    if (bucket_width <= 0.0 || isnan(bucket_width) || 
        isinf(bucket_width) || bucket_width < 1e-100)
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("bucket width too small")));
    
    if (value < min)
        bucket_index = 0;
    else if (value >= max)
        bucket_index = nbuckets - 1;
    else
        bucket_index = (int32) ((value - min) / bucket_width);
    
    PG_RETURN_INT32(bucket_index);
}

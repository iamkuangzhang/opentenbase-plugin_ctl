/*
 * hyperfunctions.c
 * 
 * OpenTenBase TimeSeries Hyperfunctions
 * 高级时序分析函数（TimescaleDB兼容）
 * 
 * 实现的Hyperfunctions:
 * 1. time_weight() - 时间加权平均
 * 2. counter_agg() - 计数器聚合（处理重置）
 * 3. gauge_agg() - 仪表盘聚合
 * 4. stats_agg() - 统计聚合
 * 5. approx_percentile() - 近似百分位数
 */

#include "postgres.h"
#include "fmgr.h"
#include "utils/timestamp.h"
#include "utils/builtins.h"
#include "access/htup_details.h"
#include "utils/numeric.h"
#include "catalog/pg_type.h"
#include "funcapi.h"
#include <math.h>

/* ============================================================================
 * 1. TIME_WEIGHT() - 时间加权平均
 * 计算考虑时间间隔的加权平均值
 * ============================================================================ */

typedef struct TimeWeightState
{
    float8      prev_value;
    TimestampTz prev_time;
    float8      weighted_sum;
    int64       total_duration;
    bool        first_row;
} TimeWeightState;

PG_FUNCTION_INFO_V1(time_weight_transition);

Datum
time_weight_transition(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    TimeWeightState *state;
    float8 value;
    TimestampTz time;
    int64 duration;
    
    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("time_weight_transition called in non-aggregate context")));
    
    /* 初始化状态 */
    if (PG_ARGISNULL(0))
    {
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (TimeWeightState *) palloc0(sizeof(TimeWeightState));
        state->first_row = true;
        state->weighted_sum = 0.0;
        state->total_duration = 0;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (TimeWeightState *) PG_GETARG_POINTER(0);
    }
    
    /* 处理新值 */
    if (!PG_ARGISNULL(1) && !PG_ARGISNULL(2))
    {
        value = PG_GETARG_FLOAT8(1);
        time = PG_GETARG_TIMESTAMPTZ(2);
        
        if (!state->first_row)
        {
            /* 计算时间间隔（微秒），使用绝对值处理乱序数据 */
            duration = time - state->prev_time;
            if (duration < 0) duration = -duration;  /* 取绝对值 */
            if (duration > 0)
            {
                /* 使用前一个值和当前时间间隔计算加权和 */
                state->weighted_sum += state->prev_value * duration;
                state->total_duration += duration;
            }
        }
        
        state->prev_value = value;
        state->prev_time = time;
        state->first_row = false;
    }
    
    PG_RETURN_POINTER(state);
}

PG_FUNCTION_INFO_V1(time_weight_final);

Datum
time_weight_final(PG_FUNCTION_ARGS)
{
    TimeWeightState *state;
    float8 result;
    
    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();
    
    state = (TimeWeightState *) PG_GETARG_POINTER(0);
    
    if (state->total_duration == 0)
        PG_RETURN_NULL();
    
    /* 计算时间加权平均 */
    result = state->weighted_sum / state->total_duration;
    
    PG_RETURN_FLOAT8(result);
}

/* ============================================================================
 * 2. COUNTER_AGG() - 计数器聚合（处理重置）
 * 用于单调递增计数器，自动检测并处理重置
 * ============================================================================ */

typedef struct CounterAggState
{
    float8      last_value;
    float8      cumulative_sum;
    bool        has_data;
    int32       reset_count;
} CounterAggState;

PG_FUNCTION_INFO_V1(counter_agg_transition);

Datum
counter_agg_transition(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    CounterAggState *state;
    float8 value;
    
    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("counter_agg_transition called in non-aggregate context")));
    
    /* 初始化状态 */
    if (PG_ARGISNULL(0))
    {
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (CounterAggState *) palloc0(sizeof(CounterAggState));
        state->has_data = false;
        state->cumulative_sum = 0.0;
        state->reset_count = 0;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (CounterAggState *) PG_GETARG_POINTER(0);
    }
    
    /* 处理新值 */
    if (!PG_ARGISNULL(1))
    {
        value = PG_GETARG_FLOAT8(1);
        
        if (state->has_data)
        {
            /* 检测计数器重置（当前值小于上一个值） */
            if (value < state->last_value)
            {
                /* 计数器重置，累加上一个值 */
                state->cumulative_sum += state->last_value;
                state->reset_count++;
            }
            else
            {
                /* 正常递增 */
                state->cumulative_sum += (value - state->last_value);
            }
        }
        
        state->last_value = value;
        state->has_data = true;
    }
    
    PG_RETURN_POINTER(state);
}

PG_FUNCTION_INFO_V1(counter_agg_final);

Datum
counter_agg_final(PG_FUNCTION_ARGS)
{
    CounterAggState *state;
    
    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();
    
    state = (CounterAggState *) PG_GETARG_POINTER(0);
    
    if (!state->has_data)
        PG_RETURN_NULL();
    
    /* 返回累计增量（处理重置后的总和） */
    PG_RETURN_FLOAT8(state->cumulative_sum);
}

/* ============================================================================
 * 3. GAUGE_AGG() - 仪表盘聚合
 * 返回包含min/max/avg/sum等统计信息的复合类型
 * ============================================================================ */

typedef struct GaugeAggState
{
    float8      sum;
    float8      min;
    float8      max;
    int64       count;
    float8      sum_squares;  /* 用于计算stddev */
} GaugeAggState;

PG_FUNCTION_INFO_V1(gauge_agg_transition);

Datum
gauge_agg_transition(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    GaugeAggState *state;
    float8 value;
    
    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("gauge_agg_transition called in non-aggregate context")));
    
    /* 初始化状态 */
    if (PG_ARGISNULL(0))
    {
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (GaugeAggState *) palloc0(sizeof(GaugeAggState));
        state->count = 0;
        state->sum = 0.0;
        state->sum_squares = 0.0;
        state->min = INFINITY;
        state->max = -INFINITY;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (GaugeAggState *) PG_GETARG_POINTER(0);
    }
    
    /* 处理新值 */
    if (!PG_ARGISNULL(1))
    {
        value = PG_GETARG_FLOAT8(1);
        
        state->count++;
        state->sum += value;
        state->sum_squares += value * value;
        
        if (value < state->min)
            state->min = value;
        if (value > state->max)
            state->max = value;
    }
    
    PG_RETURN_POINTER(state);
}

PG_FUNCTION_INFO_V1(gauge_agg_final);

Datum
gauge_agg_final(PG_FUNCTION_ARGS)
{
    GaugeAggState *state;
    TupleDesc tupdesc;
    Datum values[5];
    bool nulls[5] = {false, false, false, false, false};
    HeapTuple tuple;
    float8 avg, stddev, variance;
    
    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();
    
    state = (GaugeAggState *) PG_GETARG_POINTER(0);
    
    if (state->count == 0)
        PG_RETURN_NULL();
    
    /* 构造返回的复合类型 */
    if (get_call_result_type(fcinfo, NULL, &tupdesc) != TYPEFUNC_COMPOSITE)
        ereport(ERROR,
                (errcode(ERRCODE_FEATURE_NOT_SUPPORTED),
                 errmsg("function returning record called in context that cannot accept type record")));
    
    tupdesc = BlessTupleDesc(tupdesc);
    
    /* 计算统计信息 */
    avg = state->sum / state->count;
    
    if (state->count > 1)
    {
        variance = (state->sum_squares - state->sum * state->sum / state->count) / (state->count - 1);
        stddev = sqrt(fmax(0.0, variance));  /* 防止负数 */
    }
    else
    {
        stddev = 0.0;
    }
    
    /* 设置返回值：(min, max, avg, sum, stddev) */
    values[0] = Float8GetDatum(state->min);
    values[1] = Float8GetDatum(state->max);
    values[2] = Float8GetDatum(avg);
    values[3] = Float8GetDatum(state->sum);
    values[4] = Float8GetDatum(stddev);
    
    tuple = heap_form_tuple(tupdesc, values, nulls);
    
    PG_RETURN_DATUM(HeapTupleGetDatum(tuple));
}

/* ============================================================================
 * 4. STATS_AGG() - 统计聚合
 * 类似gauge_agg但返回更完整的统计信息
 * ============================================================================ */

PG_FUNCTION_INFO_V1(stats_agg_transition);

Datum
stats_agg_transition(PG_FUNCTION_ARGS)
{
    /* 复用gauge_agg的实现 */
    return gauge_agg_transition(fcinfo);
}

PG_FUNCTION_INFO_V1(stats_agg_final);

Datum
stats_agg_final(PG_FUNCTION_ARGS)
{
    GaugeAggState *state;
    TupleDesc tupdesc;
    Datum values[6];
    bool nulls[6] = {false, false, false, false, false, false};
    HeapTuple tuple;
    float8 avg, stddev, variance;
    
    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();
    
    state = (GaugeAggState *) PG_GETARG_POINTER(0);
    
    if (state->count == 0)
        PG_RETURN_NULL();
    
    /* 构造返回的复合类型 */
    if (get_call_result_type(fcinfo, NULL, &tupdesc) != TYPEFUNC_COMPOSITE)
        ereport(ERROR,
                (errcode(ERRCODE_FEATURE_NOT_SUPPORTED),
                 errmsg("function returning record called in context that cannot accept type record")));
    
    tupdesc = BlessTupleDesc(tupdesc);
    
    /* 计算统计信息 */
    avg = state->sum / state->count;
    
    if (state->count > 1)
    {
        variance = (state->sum_squares - state->sum * state->sum / state->count) / (state->count - 1);
        stddev = sqrt(fmax(0.0, variance));
    }
    else
    {
        variance = 0.0;
        stddev = 0.0;
    }
    
    /* 设置返回值：(count, min, max, avg, sum, stddev) */
    values[0] = Int64GetDatum(state->count);
    values[1] = Float8GetDatum(state->min);
    values[2] = Float8GetDatum(state->max);
    values[3] = Float8GetDatum(avg);
    values[4] = Float8GetDatum(state->sum);
    values[5] = Float8GetDatum(stddev);
    
    tuple = heap_form_tuple(tupdesc, values, nulls);
    
    PG_RETURN_DATUM(HeapTupleGetDatum(tuple));
}

/* ============================================================================
 * 5. APPROX_PERCENTILE() - 近似百分位数
 * 使用简化的分位数估算算法
 * ============================================================================ */

#define PERCENTILE_BUFFER_SIZE 1000

typedef struct ApproxPercentileState
{
    float8     *values;
    int32       count;
    int32       capacity;
} ApproxPercentileState;

PG_FUNCTION_INFO_V1(approx_percentile_transition);

Datum
approx_percentile_transition(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    ApproxPercentileState *state;
    float8 value;
    
    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("approx_percentile_transition called in non-aggregate context")));
    
    /* 初始化状态 */
    if (PG_ARGISNULL(0))
    {
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (ApproxPercentileState *) palloc0(sizeof(ApproxPercentileState));
        state->capacity = PERCENTILE_BUFFER_SIZE;
        state->values = (float8 *) palloc(state->capacity * sizeof(float8));
        state->count = 0;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (ApproxPercentileState *) PG_GETARG_POINTER(0);
    }
    
    /* 处理新值 */
    if (!PG_ARGISNULL(1))
    {
        value = PG_GETARG_FLOAT8(1);
        
        /* 如果缓冲区满了，扩容 */
        if (state->count >= state->capacity)
        {
            MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
            state->capacity *= 2;
            state->values = (float8 *) repalloc(state->values, state->capacity * sizeof(float8));
            MemoryContextSwitchTo(oldcontext);
        }
        
        state->values[state->count++] = value;
    }
    
    PG_RETURN_POINTER(state);
}

/* 比较函数用于qsort */
static int
float8_cmp(const void *a, const void *b)
{
    float8 fa = *(const float8 *)a;
    float8 fb = *(const float8 *)b;
    
    if (fa < fb) return -1;
    if (fa > fb) return 1;
    return 0;
}

PG_FUNCTION_INFO_V1(approx_percentile_final);

Datum
approx_percentile_final(PG_FUNCTION_ARGS)
{
    ApproxPercentileState *state;
    float8 percentile;
    float8 result;
    int32 index;
    float8 fraction;
    
    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();
    
    state = (ApproxPercentileState *) PG_GETARG_POINTER(0);
    percentile = PG_GETARG_FLOAT8(1);  /* 0.0 - 1.0 */
    
    if (state->count == 0)
        PG_RETURN_NULL();
    
    /* 验证percentile范围 */
    if (percentile < 0.0 || percentile > 1.0)
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("percentile must be between 0.0 and 1.0")));
    
    /* 排序数据 */
    qsort(state->values, state->count, sizeof(float8), float8_cmp);
    
    /* 计算百分位数 */
    if (percentile == 0.0)
    {
        result = state->values[0];
    }
    else if (percentile == 1.0)
    {
        result = state->values[state->count - 1];
    }
    else
    {
        /* 线性插值 */
        float8 exact_index = percentile * (state->count - 1);
        index = (int32) floor(exact_index);
        fraction = exact_index - index;
        
        if (index >= state->count - 1)
        {
            result = state->values[state->count - 1];
        }
        else
        {
            result = state->values[index] + 
                     fraction * (state->values[index + 1] - state->values[index]);
        }
    }
    
    PG_RETURN_FLOAT8(result);
}

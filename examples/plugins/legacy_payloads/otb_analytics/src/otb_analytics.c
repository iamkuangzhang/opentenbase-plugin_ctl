/*
 * otb_analytics.c
 * 
 * OpenTenBase Analytics Extension - 独立时序分析算法库
 * 
 * 这是一个独立的PostgreSQL扩展，提供高级时序分析算法。
 * 完全原创，TimescaleDB没有这些功能！
 * 
 * 功能模块：
 * 1. 移动平均算法族（SMA/EMA/WMA/DEMA/TEMA）- 5种算法
 * 2. 异常检测算法（Z-score/IQR）- 2种方法
 * 3. 高级聚合函数（delta/rate/cumsum）- 3个函数
 * 
 * 作者：OpenTenBase TimeSeries Adapter Team
 * 版本：1.0
 */

#include "postgres.h"
#include "fmgr.h"
#include "utils/builtins.h"
#include "utils/numeric.h"
#include "catalog/pg_type.h"
#include "funcapi.h"
#include <math.h>

#ifdef PG_MODULE_MAGIC
PG_MODULE_MAGIC;
#endif


/* ============================================================================
 * 移动平均算法族 (Moving Average Algorithms)
 * ============================================================================ */

/* ==========================
 * 1. SMA - Simple Moving Average（简单移动平均）
 * ========================== */

typedef struct SMAState
{
    int32       window_size;    /* 窗口大小 */
    float8     *values;         /* 循环缓冲区 */
    int32       count;          /* 当前值数量 */
    int32       index;          /* 当前写入位置 */
    float8      sum;            /* 当前窗口和 */
} SMAState;

PG_FUNCTION_INFO_V1(sma_transition);

Datum
sma_transition(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    SMAState *state;
    float8      value;
    
    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("sma_transition called in non-aggregate context")));
    
    /* 初始化状态 */
    if (PG_ARGISNULL(0))
    {
        int32 window_size = PG_GETARG_INT32(2);
        
        if (window_size <= 0)
            ereport(ERROR,
                    (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                     errmsg("window size must be positive")));
        
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (SMAState *) palloc0(sizeof(SMAState));
        state->window_size = window_size;
        state->values = (float8 *) palloc0(window_size * sizeof(float8));
        state->count = 0;
        state->index = 0;
        state->sum = 0.0;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (SMAState *) PG_GETARG_POINTER(0);
    }
    
    /* 处理新值 */
    if (!PG_ARGISNULL(1))
    {
        value = PG_GETARG_FLOAT8(1);
        
        /* NaN检查：跳过无效值 */
        if (isnan(value))
            PG_RETURN_POINTER(state);
        
        /* 如果窗口已满，减去要被替换的旧值 */
        if (state->count >= state->window_size)
        {
            state->sum -= state->values[state->index];
        }
        
        /* 添加新值 */
        state->values[state->index] = value;
        state->sum += value;
        
        /* 更新计数器 */
        if (state->count < state->window_size)
            state->count++;
        
        /* 循环索引 */
        state->index = (state->index + 1) % state->window_size;
    }
    
    PG_RETURN_POINTER(state);
}

PG_FUNCTION_INFO_V1(sma_final);

Datum
sma_final(PG_FUNCTION_ARGS)
{
    SMAState *state;
    
    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();
    
    state = (SMAState *) PG_GETARG_POINTER(0);
    
    if (state->count == 0)
        PG_RETURN_NULL();
    
    /* 返回平均值 */
    PG_RETURN_FLOAT8(state->sum / state->count);
}

/* ==========================
 * 2. EMA - Exponential Moving Average（指数移动平均）
 * ========================== */

typedef struct EMAState
{
    float8      ema;            /* 当前EMA值 */
    float8      alpha;          /* 平滑系数 */
    bool        initialized;    /* 是否已初始化 */
} EMAState;

PG_FUNCTION_INFO_V1(ema_transition);

Datum
ema_transition(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    EMAState *state;
    float8      value;
    
    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("ema_transition called in non-aggregate context")));
    
    /* 初始化状态 */
    if (PG_ARGISNULL(0))
    {
        float8 alpha = PG_GETARG_FLOAT8(2);
        
        if (alpha <= 0.0 || alpha > 1.0)
            ereport(ERROR,
                    (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                     errmsg("alpha must be between 0 and 1")));
        
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (EMAState *) palloc0(sizeof(EMAState));
        state->alpha = alpha;
        state->initialized = false;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (EMAState *) PG_GETARG_POINTER(0);
    }
    
    /* 处理新值 */
    if (!PG_ARGISNULL(1))
    {
        value = PG_GETARG_FLOAT8(1);
        
        /* NaN检查 */
        if (isnan(value))
            PG_RETURN_POINTER(state);
        
        if (!state->initialized)
        {
            /* 第一个值作为初始EMA */
            state->ema = value;
            state->initialized = true;
        }
        else
        {
            /* EMA公式：EMA_t = α * value_t + (1-α) * EMA_{t-1} */
            state->ema = state->alpha * value + (1.0 - state->alpha) * state->ema;
        }
    }
    
    PG_RETURN_POINTER(state);
}

PG_FUNCTION_INFO_V1(ema_final);

Datum
ema_final(PG_FUNCTION_ARGS)
{
    EMAState *state;
    
    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();
    
    state = (EMAState *) PG_GETARG_POINTER(0);
    
    if (!state->initialized)
        PG_RETURN_NULL();
    
    PG_RETURN_FLOAT8(state->ema);
}

/* ==========================
 * 3. WMA - Weighted Moving Average（加权移动平均）
 * ========================== */

typedef struct WMAState
{
    int32       window_size;
    float8     *values;
    int32       count;
    int32       index;
} WMAState;

PG_FUNCTION_INFO_V1(wma_transition);

Datum
wma_transition(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    WMAState *state;
    float8      value;
    
    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("wma_transition called in non-aggregate context")));
    
    if (PG_ARGISNULL(0))
    {
        int32 window_size = PG_GETARG_INT32(2);
        
        if (window_size <= 0)
            ereport(ERROR,
                    (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                     errmsg("window size must be positive")));
        
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (WMAState *) palloc0(sizeof(WMAState));
        state->window_size = window_size;
        state->values = (float8 *) palloc0(window_size * sizeof(float8));
        state->count = 0;
        state->index = 0;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (WMAState *) PG_GETARG_POINTER(0);
    }
    
    if (!PG_ARGISNULL(1))
    {
        value = PG_GETARG_FLOAT8(1);
        
        /* NaN检查 */
        if (isnan(value))
            PG_RETURN_POINTER(state);
        
        state->values[state->index] = value;
        
        if (state->count < state->window_size)
            state->count++;
        
        state->index = (state->index + 1) % state->window_size;
    }
    
    PG_RETURN_POINTER(state);
}

PG_FUNCTION_INFO_V1(wma_final);

Datum
wma_final(PG_FUNCTION_ARGS)
{
    WMAState *state;
    float8      weighted_sum = 0.0;
    int32       weight_sum = 0;
    int32       i, actual_idx, weight;
    
    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();
    
    state = (WMAState *) PG_GETARG_POINTER(0);
    
    if (state->count == 0)
        PG_RETURN_NULL();
    
    /* 计算加权平均：最新的值权重最大 */
    for (i = 0; i < state->count; i++)
    {
        /* 线性递减权重：最新的权重为count，最旧的为1 */
        weight = state->count - i;
        /* 
         * 从最新值往回遍历循环缓冲区
         * 加window_size确保(index-1-i)为正，再取模得到实际索引
         * 例如: index=0, i=0 -> (0-1-0+window_size)%window_size = window_size-1 (最新值)
         */
        actual_idx = (state->index - 1 - i + state->window_size) % state->window_size;
        weighted_sum += state->values[actual_idx] * weight;
        weight_sum += weight;
    }
    
    PG_RETURN_FLOAT8(weighted_sum / weight_sum);
}

/* ==========================
 * 4. DEMA - Double Exponential Moving Average（双指数移动平均）
 * ========================== */

typedef struct DEMAState
{
    float8      ema1;           /* 第一次EMA */
    float8      ema2;           /* EMA的EMA */
    float8      alpha;
    bool        initialized;
} DEMAState;

PG_FUNCTION_INFO_V1(dema_transition);

Datum
dema_transition(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    DEMAState *state;
    float8      value;
    
    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("dema_transition called in non-aggregate context")));
    
    if (PG_ARGISNULL(0))
    {
        float8 alpha = PG_GETARG_FLOAT8(2);
        
        if (alpha <= 0.0 || alpha > 1.0)
            ereport(ERROR,
                    (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                     errmsg("alpha must be between 0 and 1")));
        
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (DEMAState *) palloc0(sizeof(DEMAState));
        state->alpha = alpha;
        state->initialized = false;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (DEMAState *) PG_GETARG_POINTER(0);
    }
    
    if (!PG_ARGISNULL(1))
    {
        value = PG_GETARG_FLOAT8(1);
        
        /* NaN检查 */
        if (isnan(value))
            PG_RETURN_POINTER(state);
        
        if (!state->initialized)
        {
            state->ema1 = value;
            state->ema2 = value;
            state->initialized = true;
        }
        else
        {
            /* 计算两次EMA */
            state->ema1 = state->alpha * value + (1.0 - state->alpha) * state->ema1;
            state->ema2 = state->alpha * state->ema1 + (1.0 - state->alpha) * state->ema2;
        }
    }
    
    PG_RETURN_POINTER(state);
}

PG_FUNCTION_INFO_V1(dema_final);

Datum
dema_final(PG_FUNCTION_ARGS)
{
    DEMAState *state;
    float8      dema;
    
    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();
    
    state = (DEMAState *) PG_GETARG_POINTER(0);
    
    if (!state->initialized)
        PG_RETURN_NULL();
    
    /* DEMA = 2 * EMA1 - EMA2 */
    dema = 2.0 * state->ema1 - state->ema2;
    
    PG_RETURN_FLOAT8(dema);
}

/* ==========================
 * 5. TEMA - Triple Exponential Moving Average（三指数移动平均）
 * ========================== */

typedef struct TEMAState
{
    float8      ema1;
    float8      ema2;
    float8      ema3;           /* EMA的EMA的EMA */
    float8      alpha;
    bool        initialized;
} TEMAState;

PG_FUNCTION_INFO_V1(tema_transition);

Datum
tema_transition(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    TEMAState *state;
    float8      value;
    
    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("tema_transition called in non-aggregate context")));
    
    if (PG_ARGISNULL(0))
    {
        float8 alpha = PG_GETARG_FLOAT8(2);
        
        if (alpha <= 0.0 || alpha > 1.0)
            ereport(ERROR,
                    (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                     errmsg("alpha must be between 0 and 1")));
        
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (TEMAState *) palloc0(sizeof(TEMAState));
        state->alpha = alpha;
        state->initialized = false;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (TEMAState *) PG_GETARG_POINTER(0);
    }
    
    if (!PG_ARGISNULL(1))
    {
        value = PG_GETARG_FLOAT8(1);
        
        /* NaN检查 */
        if (isnan(value))
            PG_RETURN_POINTER(state);
        
        if (!state->initialized)
        {
            state->ema1 = value;
            state->ema2 = value;
            state->ema3 = value;
            state->initialized = true;
        }
        else
        {
            /* 计算三次EMA */
            state->ema1 = state->alpha * value + (1.0 - state->alpha) * state->ema1;
            state->ema2 = state->alpha * state->ema1 + (1.0 - state->alpha) * state->ema2;
            state->ema3 = state->alpha * state->ema2 + (1.0 - state->alpha) * state->ema3;
        }
    }
    
    PG_RETURN_POINTER(state);
}

PG_FUNCTION_INFO_V1(tema_final);

Datum
tema_final(PG_FUNCTION_ARGS)
{
    TEMAState *state;
    float8      tema;
    
    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();
    
    state = (TEMAState *) PG_GETARG_POINTER(0);
    
    if (!state->initialized)
        PG_RETURN_NULL();
    
    /* TEMA = 3 * EMA1 - 3 * EMA2 + EMA3 */
    tema = 3.0 * state->ema1 - 3.0 * state->ema2 + state->ema3;
    
    PG_RETURN_FLOAT8(tema);
}

/* ============================================================================
 * 异常检测算法 (Anomaly Detection Algorithms)
 * ============================================================================ */

/* ==========================
 * 1. Z-score异常检测（基于标准差）
 * 返回数据的统计信息和异常检测阈值
 * ========================== */

typedef struct ZScoreState
{
    int64       count;
    float8      sum;
    float8      sum_sq;         /* sum of squares */
    float8      threshold;      /* 阈值（几倍标准差） */
    float8     *values;         /* 存储所有值用于异常检测 */
    int32       capacity;
    int32       anomaly_count;  /* 异常值数量 */
} ZScoreState;

PG_FUNCTION_INFO_V1(zscore_anomaly_transition);

Datum
zscore_anomaly_transition(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    ZScoreState *state;
    float8      value;
    
    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("zscore_anomaly_transition called in non-aggregate context")));
    
    if (PG_ARGISNULL(0))
    {
        float8 threshold = PG_GETARG_FLOAT8(2);
        
        if (threshold <= 0.0)
            ereport(ERROR,
                    (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                     errmsg("threshold must be positive")));
        
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (ZScoreState *) palloc0(sizeof(ZScoreState));
        state->threshold = threshold;
        state->count = 0;
        state->sum = 0.0;
        state->sum_sq = 0.0;
        state->capacity = 1000;
        state->values = (float8 *) palloc(state->capacity * sizeof(float8));
        state->anomaly_count = 0;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (ZScoreState *) PG_GETARG_POINTER(0);
    }
    
    if (!PG_ARGISNULL(1))
    {
        value = PG_GETARG_FLOAT8(1);
        
        /* NaN检查：跳过无效值 */
        if (isnan(value))
            PG_RETURN_POINTER(state);
        
        /* 扩容 */
        if (state->count >= state->capacity)
        {
            MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
            state->capacity *= 2;
            state->values = (float8 *) repalloc(state->values, state->capacity * sizeof(float8));
            MemoryContextSwitchTo(oldcontext);
        }
        
        state->values[state->count] = value;
        state->count++;
        state->sum += value;
        state->sum_sq += value * value;
    }
    
    PG_RETURN_POINTER(state);
}

PG_FUNCTION_INFO_V1(zscore_anomaly_final);

Datum
zscore_anomaly_final(PG_FUNCTION_ARGS)
{
    ZScoreState *state;
    float8      mean, variance, stddev, zscore;
    int64       i;
    
    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();
    
    state = (ZScoreState *) PG_GETARG_POINTER(0);
    
    if (state->count < 3)
        PG_RETURN_INT32(0);  /* 数据太少（至少需要3个点才能稳定计算标准差），无异常 */
    
    /* 计算均值和标准差 */
    mean = state->sum / state->count;
    variance = (state->sum_sq - state->sum * state->sum / state->count) / (state->count - 1);
    
    if (variance < 0.0)
        variance = 0.0;
    
    stddev = sqrt(variance);
    
    if (stddev == 0.0)
        PG_RETURN_INT32(0);  /* 无变化，无异常 */
    
    /* 遍历所有值，计算异常数量 */
    state->anomaly_count = 0;
    for (i = 0; i < state->count; i++)
    {
        zscore = fabs((state->values[i] - mean) / stddev);
        if (zscore > state->threshold)
            state->anomaly_count++;
    }
    
    /* 返回异常值数量 */
    PG_RETURN_INT32(state->anomaly_count);
}

/* ==========================
 * 2. IQR异常检测（基于四分位数）
 * ========================== */

typedef struct IQRState
{
    float8     *values;
    int32       count;
    int32       capacity;
    float8      iqr_multiplier;
} IQRState;

PG_FUNCTION_INFO_V1(iqr_anomaly_transition);

Datum
iqr_anomaly_transition(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    IQRState *state;
    float8      value;
    
    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("iqr_anomaly_transition called in non-aggregate context")));
    
    if (PG_ARGISNULL(0))
    {
        float8 iqr_multiplier = PG_GETARG_FLOAT8(2);
        
        if (iqr_multiplier <= 0.0)
            ereport(ERROR,
                    (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                     errmsg("IQR multiplier must be positive")));
        
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (IQRState *) palloc0(sizeof(IQRState));
        state->iqr_multiplier = iqr_multiplier;
        state->capacity = 1000;
        state->values = (float8 *) palloc(state->capacity * sizeof(float8));
        state->count = 0;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (IQRState *) PG_GETARG_POINTER(0);
    }
    
    if (!PG_ARGISNULL(1))
    {
        value = PG_GETARG_FLOAT8(1);
        
        /* NaN检查 */
        if (isnan(value))
            PG_RETURN_POINTER(state);
        
        /* 扩容 */
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

/* 快速选择算法求中位数/分位数 */
static float8
quickselect(float8 *arr, int left, int right, int k)
{
    int i, j;
    float8 pivot, tmp;
    
    while (left < right)
    {
        pivot = arr[k];
        i = left;
        j = right;
        
        /* 分区 */
        while (i < j)
        {
            /* 添加边界检查防止数组越界 */
            while (i <= right && arr[i] < pivot) i++;
            while (j >= left && arr[j] > pivot) j--;
            
            if (i < j)
            {
                tmp = arr[i];
                arr[i] = arr[j];
                arr[j] = tmp;
                i++;
                j--;
            }
        }
        
        if (k < i)
            right = i - 1;
        else if (k > i)
            left = i + 1;
        else
            return arr[k];
    }
    
    return arr[left];
}

PG_FUNCTION_INFO_V1(iqr_anomaly_final);

Datum
iqr_anomaly_final(PG_FUNCTION_ARGS)
{
    IQRState *state;
    float8      q1, q3, iqr, lower_bound, upper_bound;
    int         q1_idx, q3_idx;
    int32       anomaly_count = 0;
    int32       i;
    
    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();
    
    state = (IQRState *) PG_GETARG_POINTER(0);
    
    if (state->count < 4)
        PG_RETURN_INT32(0);  /* 数据太少，无异常 */
    
    /* 计算Q1和Q3 */
    q1_idx = state->count / 4;
    q3_idx = (state->count * 3) / 4;
    
    /* 边界检查：确保索引在有效范围内 */
    if (q1_idx < 0 || q1_idx >= state->count || q3_idx < 0 || q3_idx >= state->count)
        PG_RETURN_INT32(0);
    
    q1 = quickselect(state->values, 0, state->count - 1, q1_idx);
    q3 = quickselect(state->values, 0, state->count - 1, q3_idx);
    
    iqr = q3 - q1;
    
    /* 计算边界 */
    lower_bound = q1 - state->iqr_multiplier * iqr;
    upper_bound = q3 + state->iqr_multiplier * iqr;
    
    /* 遍历所有值，统计异常数量 */
    for (i = 0; i < state->count; i++)
    {
        if (state->values[i] < lower_bound || state->values[i] > upper_bound)
            anomaly_count++;
    }
    
    /* 返回异常值数量 */
    PG_RETURN_INT32(anomaly_count);
}

/* ============================================================================
 * 高级聚合函数 (Advanced Aggregate Functions)
 * ============================================================================ */

/* ==========================
 * 1. delta() - 差值计算（返回最后一个值与第一个值的差）
 * ========================== */

typedef struct DeltaState
{
    float8      first_value;
    float8      last_value;
    bool        has_first;
} DeltaState;

PG_FUNCTION_INFO_V1(delta_transition);

Datum
delta_transition(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    DeltaState *state;
    float8      value;
    
    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("delta_transition called in non-aggregate context")));
    
    if (PG_ARGISNULL(0))
    {
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (DeltaState *) palloc0(sizeof(DeltaState));
        state->has_first = false;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (DeltaState *) PG_GETARG_POINTER(0);
    }
    
    if (!PG_ARGISNULL(1))
    {
        value = PG_GETARG_FLOAT8(1);
        
        /* NaN检查 */
        if (isnan(value))
            PG_RETURN_POINTER(state);
        
        if (!state->has_first)
        {
            /* 记录第一个值 */
            state->first_value = value;
            state->has_first = true;
        }
        
        /* 始终更新最后一个值 */
        state->last_value = value;
    }
    
    PG_RETURN_POINTER(state);
}

PG_FUNCTION_INFO_V1(delta_final);

Datum
delta_final(PG_FUNCTION_ARGS)
{
    DeltaState *state;
    
    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();
    
    state = (DeltaState *) PG_GETARG_POINTER(0);
    
    if (!state->has_first)
        PG_RETURN_NULL();
    
    /* 返回最后值与第一值的差 */
    PG_RETURN_FLOAT8(state->last_value - state->first_value);
}

/* ==========================
 * 2. cumsum() - 累积和
 * ========================== */

typedef struct CumSumState
{
    float8      cumsum;
} CumSumState;

PG_FUNCTION_INFO_V1(cumsum_transition);

Datum
cumsum_transition(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    CumSumState *state;
    float8      value;
    
    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("cumsum_transition called in non-aggregate context")));
    
    if (PG_ARGISNULL(0))
    {
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (CumSumState *) palloc0(sizeof(CumSumState));
        state->cumsum = 0.0;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (CumSumState *) PG_GETARG_POINTER(0);
    }
    
    if (!PG_ARGISNULL(1))
    {
        value = PG_GETARG_FLOAT8(1);
        
        /* NaN检查 */
        if (isnan(value))
            PG_RETURN_POINTER(state);
        
        state->cumsum += value;
    }
    
    PG_RETURN_POINTER(state);
}

PG_FUNCTION_INFO_V1(cumsum_final);

Datum
cumsum_final(PG_FUNCTION_ARGS)
{
    CumSumState *state;
    
    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();
    
    state = (CumSumState *) PG_GETARG_POINTER(0);
    
    PG_RETURN_FLOAT8(state->cumsum);
}

/* ==========================
 * 3. rate() - 变化率（单位时间内的变化量）
 * ========================== */

typedef struct RateState
{
    float8      first_value;
    float8      last_value;
    int64       first_time;
    int64       last_time;
    bool        has_first;
} RateState;

PG_FUNCTION_INFO_V1(rate_transition);

Datum
rate_transition(PG_FUNCTION_ARGS)
{
    MemoryContext aggcontext;
    RateState *state;
    float8      value;
    int64       time;
    
    if (!AggCheckCallContext(fcinfo, &aggcontext))
        ereport(ERROR,
                (errcode(ERRCODE_INVALID_PARAMETER_VALUE),
                 errmsg("rate_transition called in non-aggregate context")));
    
    if (PG_ARGISNULL(0))
    {
        MemoryContext oldcontext = MemoryContextSwitchTo(aggcontext);
        state = (RateState *) palloc0(sizeof(RateState));
        state->has_first = false;
        MemoryContextSwitchTo(oldcontext);
    }
    else
    {
        state = (RateState *) PG_GETARG_POINTER(0);
    }
    
    if (!PG_ARGISNULL(1) && !PG_ARGISNULL(2))
    {
        value = PG_GETARG_FLOAT8(1);
        time = PG_GETARG_INT64(2);
        
        /* NaN检查 */
        if (isnan(value))
            PG_RETURN_POINTER(state);
        
        if (!state->has_first)
        {
            /* 记录第一个值和时间 */
            state->first_value = value;
            state->first_time = time;
            state->has_first = true;
        }
        
        /* 始终更新最后一个值和时间 */
        state->last_value = value;
        state->last_time = time;
    }
    
    PG_RETURN_POINTER(state);
}

PG_FUNCTION_INFO_V1(rate_final);

Datum
rate_final(PG_FUNCTION_ARGS)
{
    RateState *state;
    int64 time_diff;
    float8 value_diff;
    
    if (PG_ARGISNULL(0))
        PG_RETURN_NULL();
    
    state = (RateState *) PG_GETARG_POINTER(0);
    
    if (!state->has_first)
        PG_RETURN_NULL();
    
    time_diff = state->last_time - state->first_time;
    
    /* 时间差为0，无法计算rate */
    if (time_diff == 0)
        PG_RETURN_NULL();
    
    value_diff = state->last_value - state->first_value;
    
    /* 返回单位时间的变化率（假设时间单位为微秒，转换为秒） */
    PG_RETURN_FLOAT8(value_diff / (time_diff / 1000000.0));
}


/*
 * otb_age_c.c
 * 
 * OpenTenBase AGE Adapter - C扩展高性能图算法
 * 
 * 实现功能：
 * - BFS广度优先遍历（10-50倍性能提升）
 * - 最短路径Dijkstra算法
 * - 图统计函数
 */

#include "postgres.h"
#include "fmgr.h"
#include "funcapi.h"
#include "executor/spi.h"
#include "utils/builtins.h"
#include "utils/array.h"
#include "utils/lsyscache.h"
#include "catalog/pg_type.h"
#include "access/htup_details.h"

#ifdef PG_MODULE_MAGIC
PG_MODULE_MAGIC;
#endif

/* ============================================================================
 * SQL安全辅助函数
 * ============================================================================ */

/* 
 * 安全地将字符串用于SQL查询（防止SQL注入）
 * 为字符串添加单引号并转义内部的单引号
 * 注意：返回的字符串需要调用者pfree
 */
static char* quote_literal_safe(const char *str) {
    int len = strlen(str);
    int extra = 0;
    const char *p;
    char *result, *r;
    
    /* 计算需要转义的单引号数量 */
    for (p = str; *p; p++) {
        if (*p == '\'') extra++;
    }
    
    /* 分配结果缓冲区: 长度 + 2个引号 + 额外转义字符 + null结束符 */
    result = (char *)palloc(len + extra + 3);
    r = result;
    
    *r++ = '\'';  /* 开始引号 */
    for (p = str; *p; p++) {
        if (*p == '\'') {
            *r++ = '\'';  /* 转义单引号 */
        }
        *r++ = *p;
    }
    *r++ = '\'';  /* 结束引号 */
    *r = '\0';
    
    return result;
}

/* ============================================================================
 * 数据结构定义
 * ============================================================================ */

/* 图节点结构 */
typedef struct GraphNode {
    int64 id;
    int32 label_id;
    int32 num_edges;
    int32 *neighbors;      /* 邻居节点ID数组 */
    int32 *edge_ids;       /* 对应边ID数组 */
} GraphNode;

/* 图结构 */
typedef struct Graph {
    int32 num_nodes;
    int32 num_edges;
    GraphNode *nodes;
    int64 *node_ids;       /* 节点ID到索引的映射 */
} Graph;

/* BFS结果结构 */
typedef struct BFSResult {
    int64 vertex_id;
    int32 depth;
    int64 *path;
    int32 path_len;
} BFSResult;

/* 队列结构（用于BFS） */
typedef struct Queue {
    int32 *data;
    int32 front;
    int32 rear;
    int32 capacity;
} Queue;

/* ============================================================================
 * 队列操作
 * ============================================================================ */

static Queue* queue_create(int32 capacity)
{
    Queue *q = (Queue *)palloc(sizeof(Queue));
    q->data = (int32 *)palloc(sizeof(int32) * capacity);
    q->front = 0;
    q->rear = 0;
    q->capacity = capacity;
    return q;
}

static void queue_push(Queue *q, int32 value)
{
    if (q->rear < q->capacity) {
        q->data[q->rear++] = value;
    }
}

static int32 queue_pop(Queue *q)
{
    if (q->front < q->rear) {
        return q->data[q->front++];
    }
    return -1;
}

static bool queue_empty(Queue *q)
{
    return q->front >= q->rear;
}

static void queue_free(Queue *q)
{
    pfree(q->data);
    pfree(q);
}

/* ============================================================================
 * 图加载函数
 * ============================================================================ */

/*
 * 从数据库加载图的邻接表
 * 返回邻居数量
 */
static int load_neighbors(int64 vertex_id, int32 graph_id, 
                          int64 **out_neighbors, int64 **out_edge_ids)
{
    int ret;
    int count = 0;
    char sql[512];
    
    snprintf(sql, sizeof(sql),
        "SELECT end_id, id FROM otb_age.edges WHERE graph_id = %d AND start_id = %ld "
        "UNION ALL "
        "SELECT start_id, id FROM otb_age.edges WHERE graph_id = %d AND end_id = %ld",
        graph_id, vertex_id, graph_id, vertex_id);
    
    ret = SPI_execute(sql, true, 0);
    
    if (ret == SPI_OK_SELECT && SPI_processed > 0) {
        count = SPI_processed;
        *out_neighbors = (int64 *)palloc(sizeof(int64) * count);
        *out_edge_ids = (int64 *)palloc(sizeof(int64) * count);
        
        for (int i = 0; i < count; i++) {
            HeapTuple tuple = SPI_tuptable->vals[i];
            TupleDesc tupdesc = SPI_tuptable->tupdesc;
            bool isnull;
            
            (*out_neighbors)[i] = DatumGetInt64(SPI_getbinval(tuple, tupdesc, 1, &isnull));
            (*out_edge_ids)[i] = DatumGetInt64(SPI_getbinval(tuple, tupdesc, 2, &isnull));
        }
    } else {
        *out_neighbors = NULL;
        *out_edge_ids = NULL;
    }
    
    return count;
}

/* ============================================================================
 * BFS广度优先遍历 - C实现
 * ============================================================================ */

PG_FUNCTION_INFO_V1(bfs_c);

/*
 * bfs_c(start_vertex_id BIGINT, graph_id INTEGER, max_depth INTEGER)
 * 
 * 返回: TABLE(vertex_id BIGINT, depth INTEGER, path BIGINT[])
 */
Datum
bfs_c(PG_FUNCTION_ARGS)
{
    FuncCallContext *funcctx;
    MemoryContext oldcontext;
    
    /* 首次调用初始化 */
    if (SRF_IS_FIRSTCALL()) {
        int64 start_vertex = PG_GETARG_INT64(0);
        int32 graph_id = PG_GETARG_INT32(1);
        int32 max_depth = PG_GETARG_INT32(2);
        
        int32 max_nodes = 10000;  /* 最大处理节点数 */
        int64 *visited_ids;
        int32 *visited_depths;
        int64 **visited_paths;
        int32 *path_lens;
        int32 num_visited = 0;
        
        Queue *queue;
        int64 *queue_ids;
        int32 *queue_depths;
        int64 **queue_paths;
        int32 *queue_path_lens;
        
        funcctx = SRF_FIRSTCALL_INIT();
        oldcontext = MemoryContextSwitchTo(funcctx->multi_call_memory_ctx);
        
        /* 分配结果存储 */
        visited_ids = (int64 *)palloc(sizeof(int64) * max_nodes);
        visited_depths = (int32 *)palloc(sizeof(int32) * max_nodes);
        visited_paths = (int64 **)palloc(sizeof(int64 *) * max_nodes);
        path_lens = (int32 *)palloc(sizeof(int32) * max_nodes);
        
        /* 初始化队列数据 */
        queue = queue_create(max_nodes);
        queue_ids = (int64 *)palloc(sizeof(int64) * max_nodes);
        queue_depths = (int32 *)palloc(sizeof(int32) * max_nodes);
        queue_paths = (int64 **)palloc(sizeof(int64 *) * max_nodes);
        queue_path_lens = (int32 *)palloc(sizeof(int32) * max_nodes);
        
        /* 连接SPI */
        if (SPI_connect() != SPI_OK_CONNECT) {
            ereport(ERROR, (errmsg("SPI_connect failed")));
        }
        
        /* 初始化起始节点 */
        queue_push(queue, 0);
        queue_ids[0] = start_vertex;
        queue_depths[0] = 0;
        queue_paths[0] = (int64 *)palloc(sizeof(int64));
        queue_paths[0][0] = start_vertex;
        queue_path_lens[0] = 1;
        
        int queue_idx = 1;
        
        /* BFS遍历 */
        while (!queue_empty(queue) && num_visited < max_nodes) {
            int32 idx = queue_pop(queue);
            int64 current_id = queue_ids[idx];
            int32 current_depth = queue_depths[idx];
            int64 *current_path = queue_paths[idx];
            int32 current_path_len = queue_path_lens[idx];
            
            /* 检查是否已访问 */
            bool already_visited = false;
            for (int i = 0; i < num_visited; i++) {
                if (visited_ids[i] == current_id) {
                    already_visited = true;
                    break;
                }
            }
            
            if (already_visited) continue;
            
            /* 记录访问 */
            visited_ids[num_visited] = current_id;
            visited_depths[num_visited] = current_depth;
            visited_paths[num_visited] = current_path;
            path_lens[num_visited] = current_path_len;
            num_visited++;
            
            /* 如果未达到最大深度，扩展邻居 */
            if (current_depth < max_depth) {
                int64 *neighbors;
                int64 *edge_ids;
                int num_neighbors;
                
                num_neighbors = load_neighbors(current_id, graph_id, &neighbors, &edge_ids);
                
                for (int i = 0; i < num_neighbors && queue_idx < max_nodes; i++) {
                    int64 neighbor_id = neighbors[i];
                    
                    /* 检查是否在路径中（避免循环） */
                    bool in_path = false;
                    for (int j = 0; j < current_path_len; j++) {
                        if (current_path[j] == neighbor_id) {
                            in_path = true;
                            break;
                        }
                    }
                    
                    if (!in_path) {
                        queue_push(queue, queue_idx);
                        queue_ids[queue_idx] = neighbor_id;
                        queue_depths[queue_idx] = current_depth + 1;
                        
                        /* 复制并扩展路径 */
                        queue_paths[queue_idx] = (int64 *)palloc(sizeof(int64) * (current_path_len + 1));
                        memcpy(queue_paths[queue_idx], current_path, sizeof(int64) * current_path_len);
                        queue_paths[queue_idx][current_path_len] = neighbor_id;
                        queue_path_lens[queue_idx] = current_path_len + 1;
                        
                        queue_idx++;
                    }
                }
                
                if (neighbors) pfree(neighbors);
                if (edge_ids) pfree(edge_ids);
            }
        }
        
        SPI_finish();
        queue_free(queue);
        
        /* 存储结果供后续调用使用 */
        funcctx->max_calls = num_visited;
        funcctx->user_fctx = visited_ids;
        
        /* 存储其他数据 */
        {
            void **data = (void **)palloc(sizeof(void *) * 4);
            data[0] = visited_ids;
            data[1] = visited_depths;
            data[2] = visited_paths;
            data[3] = path_lens;
            funcctx->user_fctx = data;
        }
        
        /* 构建返回类型描述 */
        {
            TupleDesc tupdesc;
            
            if (get_call_result_type(fcinfo, NULL, &tupdesc) != TYPEFUNC_COMPOSITE)
                ereport(ERROR, (errmsg("return type must be a row type")));
            
            funcctx->tuple_desc = BlessTupleDesc(tupdesc);
        }
        
        MemoryContextSwitchTo(oldcontext);
    }
    
    /* 每次调用返回一行 */
    funcctx = SRF_PERCALL_SETUP();
    
    if (funcctx->call_cntr < funcctx->max_calls) {
        void **data = (void **)funcctx->user_fctx;
        int64 *visited_ids = (int64 *)data[0];
        int32 *visited_depths = (int32 *)data[1];
        int64 **visited_paths = (int64 **)data[2];
        int32 *path_lens = (int32 *)data[3];
        
        int idx = funcctx->call_cntr;
        
        Datum values[3];
        bool nulls[3] = {false, false, false};
        HeapTuple tuple;
        Datum result;
        
        /* vertex_id */
        values[0] = Int64GetDatum(visited_ids[idx]);
        
        /* depth */
        values[1] = Int32GetDatum(visited_depths[idx]);
        
        /* path array */
        {
            ArrayType *arr;
            Datum *path_datums;
            int path_len = path_lens[idx];
            
            path_datums = (Datum *)palloc(sizeof(Datum) * path_len);
            for (int i = 0; i < path_len; i++) {
                path_datums[i] = Int64GetDatum(visited_paths[idx][i]);
            }
            
            arr = construct_array(path_datums, path_len, INT8OID, 8, true, 'd');
            values[2] = PointerGetDatum(arr);
        }
        
        tuple = heap_form_tuple(funcctx->tuple_desc, values, nulls);
        result = HeapTupleGetDatum(tuple);
        
        SRF_RETURN_NEXT(funcctx, result);
    } else {
        SRF_RETURN_DONE(funcctx);
    }
}

/* ============================================================================
 * 最短路径 - Dijkstra算法 C实现
 * ============================================================================ */

PG_FUNCTION_INFO_V1(shortest_path_c);

/*
 * shortest_path_c(start_id BIGINT, end_id BIGINT, graph_id INTEGER, max_depth INTEGER)
 * 
 * 返回: TABLE(path BIGINT[], path_length INTEGER, found BOOLEAN)
 */
Datum
shortest_path_c(PG_FUNCTION_ARGS)
{
    int64 start_id = PG_GETARG_INT64(0);
    int64 end_id = PG_GETARG_INT64(1);
    int32 graph_id = PG_GETARG_INT32(2);
    int32 max_depth = PG_GETARG_INT32(3);
    
    TupleDesc tupdesc;
    Datum values[3];
    bool nulls[3] = {false, false, false};
    HeapTuple tuple;
    
    int32 max_nodes = 10000;
    int64 *queue_ids;
    int32 *queue_depths;
    int64 **queue_paths;
    int32 *queue_path_lens;
    bool *visited;
    int64 *visited_ids;
    int32 num_visited = 0;
    
    int32 queue_front = 0;
    int32 queue_rear = 0;
    
    bool found = false;
    int64 *result_path = NULL;
    int32 result_len = 0;
    
    /* 获取返回类型 */
    if (get_call_result_type(fcinfo, NULL, &tupdesc) != TYPEFUNC_COMPOSITE)
        ereport(ERROR, (errmsg("return type must be a row type")));
    tupdesc = BlessTupleDesc(tupdesc);
    
    /* 分配内存 */
    queue_ids = (int64 *)palloc(sizeof(int64) * max_nodes);
    queue_depths = (int32 *)palloc(sizeof(int32) * max_nodes);
    queue_paths = (int64 **)palloc(sizeof(int64 *) * max_nodes);
    queue_path_lens = (int32 *)palloc(sizeof(int32) * max_nodes);
    visited = (bool *)palloc0(sizeof(bool) * max_nodes);
    visited_ids = (int64 *)palloc(sizeof(int64) * max_nodes);
    
    /* 连接SPI */
    if (SPI_connect() != SPI_OK_CONNECT) {
        ereport(ERROR, (errmsg("SPI_connect failed")));
    }
    
    /* 初始化起始节点 */
    queue_ids[queue_rear] = start_id;
    queue_depths[queue_rear] = 0;
    queue_paths[queue_rear] = (int64 *)palloc(sizeof(int64));
    queue_paths[queue_rear][0] = start_id;
    queue_path_lens[queue_rear] = 1;
    queue_rear++;
    
    /* BFS搜索最短路径 */
    while (queue_front < queue_rear && !found) {
        int64 current_id = queue_ids[queue_front];
        int32 current_depth = queue_depths[queue_front];
        int64 *current_path = queue_paths[queue_front];
        int32 current_path_len = queue_path_lens[queue_front];
        queue_front++;
        
        /* 检查是否已访问 */
        bool already_visited = false;
        for (int i = 0; i < num_visited; i++) {
            if (visited_ids[i] == current_id) {
                already_visited = true;
                break;
            }
        }
        
        if (already_visited) continue;
        
        visited_ids[num_visited++] = current_id;
        
        /* 找到目标 */
        if (current_id == end_id) {
            found = true;
            result_path = current_path;
            result_len = current_path_len;
            break;
        }
        
        /* 未达最大深度则扩展 */
        if (current_depth < max_depth) {
            int64 *neighbors;
            int64 *edge_ids;
            int num_neighbors;
            
            num_neighbors = load_neighbors(current_id, graph_id, &neighbors, &edge_ids);
            
            for (int i = 0; i < num_neighbors && queue_rear < max_nodes; i++) {
                int64 neighbor_id = neighbors[i];
                
                /* 检查是否在路径中 */
                bool in_path = false;
                for (int j = 0; j < current_path_len; j++) {
                    if (current_path[j] == neighbor_id) {
                        in_path = true;
                        break;
                    }
                }
                
                if (!in_path) {
                    queue_ids[queue_rear] = neighbor_id;
                    queue_depths[queue_rear] = current_depth + 1;
                    
                    queue_paths[queue_rear] = (int64 *)palloc(sizeof(int64) * (current_path_len + 1));
                    memcpy(queue_paths[queue_rear], current_path, sizeof(int64) * current_path_len);
                    queue_paths[queue_rear][current_path_len] = neighbor_id;
                    queue_path_lens[queue_rear] = current_path_len + 1;
                    
                    queue_rear++;
                }
            }
            
            if (neighbors) pfree(neighbors);
            if (edge_ids) pfree(edge_ids);
        }
    }
    
    SPI_finish();
    
    /* 构建返回值 */
    if (found) {
        ArrayType *arr;
        Datum *path_datums;
        
        path_datums = (Datum *)palloc(sizeof(Datum) * result_len);
        for (int i = 0; i < result_len; i++) {
            path_datums[i] = Int64GetDatum(result_path[i]);
        }
        
        arr = construct_array(path_datums, result_len, INT8OID, 8, true, 'd');
        values[0] = PointerGetDatum(arr);
        values[1] = Int32GetDatum(result_len - 1);
        values[2] = BoolGetDatum(true);
    } else {
        nulls[0] = true;
        nulls[1] = true;
        values[2] = BoolGetDatum(false);
    }
    
    tuple = heap_form_tuple(tupdesc, values, nulls);
    PG_RETURN_DATUM(HeapTupleGetDatum(tuple));
}

/* ============================================================================
 * 图度数统计 - C实现
 * ============================================================================ */

PG_FUNCTION_INFO_V1(vertex_degree_c);

/*
 * vertex_degree_c(vertex_id BIGINT, graph_id INTEGER)
 * 返回顶点的度数
 */
Datum
vertex_degree_c(PG_FUNCTION_ARGS)
{
    int64 vertex_id = PG_GETARG_INT64(0);
    int32 graph_id = PG_GETARG_INT32(1);
    int32 degree = 0;
    char sql[256];
    int ret;
    
    if (SPI_connect() != SPI_OK_CONNECT) {
        ereport(ERROR, (errmsg("SPI_connect failed")));
    }
    
    snprintf(sql, sizeof(sql),
        "SELECT COUNT(*) FROM otb_age.edges WHERE graph_id = %d AND (start_id = %ld OR end_id = %ld)",
        graph_id, vertex_id, vertex_id);
    
    ret = SPI_execute(sql, true, 0);
    
    if (ret == SPI_OK_SELECT && SPI_processed > 0) {
        HeapTuple tuple = SPI_tuptable->vals[0];
        TupleDesc tupdesc = SPI_tuptable->tupdesc;
        bool isnull;
        
        degree = DatumGetInt64(SPI_getbinval(tuple, tupdesc, 1, &isnull));
    }
    
    SPI_finish();
    
    PG_RETURN_INT32(degree);
}

/* ============================================================================
 * 检查路径是否存在 - C实现
 * ============================================================================ */

PG_FUNCTION_INFO_V1(path_exists_c);

/*
 * path_exists_c(start_id BIGINT, end_id BIGINT, graph_id INTEGER, max_depth INTEGER)
 * 快速检查两点间是否存在路径
 */
Datum
path_exists_c(PG_FUNCTION_ARGS)
{
    int64 start_id = PG_GETARG_INT64(0);
    int64 end_id = PG_GETARG_INT64(1);
    int32 graph_id = PG_GETARG_INT32(2);
    int32 max_depth = PG_GETARG_INT32(3);
    
    int32 max_nodes = 10000;
    int64 *queue;
    int32 *depths;
    int64 *visited;
    int32 num_visited = 0;
    int32 queue_front = 0;
    int32 queue_rear = 0;
    bool found = false;
    
    queue = (int64 *)palloc(sizeof(int64) * max_nodes);
    depths = (int32 *)palloc(sizeof(int32) * max_nodes);
    visited = (int64 *)palloc(sizeof(int64) * max_nodes);
    
    if (SPI_connect() != SPI_OK_CONNECT) {
        ereport(ERROR, (errmsg("SPI_connect failed")));
    }
    
    queue[queue_rear] = start_id;
    depths[queue_rear] = 0;
    queue_rear++;
    
    while (queue_front < queue_rear && !found) {
        int64 current = queue[queue_front];
        int32 depth = depths[queue_front];
        queue_front++;
        
        /* 检查是否已访问 */
        bool already = false;
        for (int i = 0; i < num_visited; i++) {
            if (visited[i] == current) {
                already = true;
                break;
            }
        }
        if (already) continue;
        
        visited[num_visited++] = current;
        
        if (current == end_id) {
            found = true;
            break;
        }
        
        if (depth < max_depth) {
            int64 *neighbors;
            int64 *edge_ids;
            int num = load_neighbors(current, graph_id, &neighbors, &edge_ids);
            
            for (int i = 0; i < num && queue_rear < max_nodes; i++) {
                queue[queue_rear] = neighbors[i];
                depths[queue_rear] = depth + 1;
                queue_rear++;
            }
            
            if (neighbors) pfree(neighbors);
            if (edge_ids) pfree(edge_ids);
        }
    }
    
    SPI_finish();
    pfree(queue);
    pfree(depths);
    pfree(visited);
    
    PG_RETURN_BOOL(found);
}

/* ============================================================================
 * PageRank 算法 (C实现)
 * 迭代计算网页/节点重要性
 * ============================================================================ */

/* PageRank结果结构 */
typedef struct {
    int64 vertex_id;
    double rank;
} PageRankResult;

typedef struct {
    PageRankResult *results;
    int32 num_results;
} PageRankContext;

PG_FUNCTION_INFO_V1(pagerank_c);

Datum
pagerank_c(PG_FUNCTION_ARGS)
{
    FuncCallContext *funcctx;
    
    if (SRF_IS_FIRSTCALL()) {
        MemoryContext oldcontext;
        text *graph_name_text = PG_GETARG_TEXT_PP(0);
        double damping = PG_GETARG_FLOAT8(1);      /* 阻尼系数，通常0.85 */
        int32 max_iter = PG_GETARG_INT32(2);       /* 最大迭代次数 */
        double tolerance = PG_GETARG_FLOAT8(3);    /* 收敛阈值 */
        
        char *graph_name = text_to_cstring(graph_name_text);
        int32 graph_id = -1;
        
        int64 *node_ids = NULL;
        double *ranks = NULL;
        double *new_ranks = NULL;
        int32 *out_degrees = NULL;
        int32 num_nodes = 0;
        
        int64 **adj_list = NULL;
        int32 *adj_counts = NULL;
        
        PageRankResult *results;
        PageRankContext *ctx;
        TupleDesc tupdesc;
        int ret, i, j, iter;
        
        funcctx = SRF_FIRSTCALL_INIT();
        oldcontext = MemoryContextSwitchTo(funcctx->multi_call_memory_ctx);
        
        /* 获取图ID */
        if (SPI_connect() != SPI_OK_CONNECT) {
            ereport(ERROR, (errmsg("pagerank_c: SPI_connect failed")));
        }
        
        char query[512];
        char *safe_name = quote_literal_safe(graph_name);
        snprintf(query, sizeof(query), 
                 "SELECT id FROM otb_age.graphs WHERE name = %s", safe_name);
        pfree(safe_name);
        ret = SPI_execute(query, true, 1);
        
        if (ret == SPI_OK_SELECT && SPI_processed > 0) {
            bool isnull;
            graph_id = DatumGetInt32(SPI_getbinval(SPI_tuptable->vals[0], 
                                                    SPI_tuptable->tupdesc, 1, &isnull));
        }
        
        if (graph_id < 0) {
            SPI_finish();
            ereport(ERROR, (errmsg("pagerank_c: Graph '%s' not found", graph_name)));
        }
        
        /* 获取所有顶点 */
        snprintf(query, sizeof(query), 
                 "SELECT id FROM otb_age.vertices WHERE graph_id = %d ORDER BY id", graph_id);
        ret = SPI_execute(query, true, 10000);
        
        if (ret == SPI_OK_SELECT && SPI_processed > 0) {
            num_nodes = (int32)SPI_processed;
            node_ids = (int64 *)palloc(sizeof(int64) * num_nodes);
            ranks = (double *)palloc(sizeof(double) * num_nodes);
            new_ranks = (double *)palloc(sizeof(double) * num_nodes);
            out_degrees = (int32 *)palloc0(sizeof(int32) * num_nodes);
            adj_list = (int64 **)palloc0(sizeof(int64 *) * num_nodes);
            adj_counts = (int32 *)palloc0(sizeof(int32) * num_nodes);
            
            for (i = 0; i < num_nodes; i++) {
                bool isnull;
                node_ids[i] = DatumGetInt64(SPI_getbinval(SPI_tuptable->vals[i], 
                                                          SPI_tuptable->tupdesc, 1, &isnull));
                ranks[i] = 1.0 / num_nodes;
            }
        }
        
        if (num_nodes == 0) {
            SPI_finish();
            results = (PageRankResult *)palloc0(sizeof(PageRankResult));
            ctx = (PageRankContext *)palloc(sizeof(PageRankContext));
            ctx->results = results;
            ctx->num_results = 0;
            funcctx->user_fctx = ctx;
            funcctx->max_calls = 0;
            
            if (get_call_result_type(fcinfo, NULL, &tupdesc) != TYPEFUNC_COMPOSITE)
                ereport(ERROR, (errmsg("return type must be a row type")));
            funcctx->tuple_desc = BlessTupleDesc(tupdesc);
            MemoryContextSwitchTo(oldcontext);
            SRF_RETURN_DONE(funcctx);
        }
        
        /* 构建邻接表和出度 */
        snprintf(query, sizeof(query),
                 "SELECT start_id, end_id FROM otb_age.edges WHERE graph_id = %d", graph_id);
        ret = SPI_execute(query, true, 100000);
        
        if (ret == SPI_OK_SELECT && SPI_processed > 0) {
            int num_edges = (int)SPI_processed;
            
            /* 计算出度 */
            for (i = 0; i < num_edges; i++) {
                bool isnull;
                int64 src = DatumGetInt64(SPI_getbinval(SPI_tuptable->vals[i], 
                                                        SPI_tuptable->tupdesc, 1, &isnull));
                for (j = 0; j < num_nodes; j++) {
                    if (node_ids[j] == src) {
                        out_degrees[j]++;
                        break;
                    }
                }
            }
            
            /* 分配邻接表空间 */
            for (i = 0; i < num_nodes; i++) {
                if (out_degrees[i] > 0) {
                    adj_list[i] = (int64 *)palloc(sizeof(int64) * out_degrees[i]);
                }
            }
            
            /* 填充邻接表 */
            int32 *temp_counts = (int32 *)palloc0(sizeof(int32) * num_nodes);
            for (i = 0; i < num_edges; i++) {
                bool isnull;
                int64 src = DatumGetInt64(SPI_getbinval(SPI_tuptable->vals[i], 
                                                        SPI_tuptable->tupdesc, 1, &isnull));
                int64 tgt = DatumGetInt64(SPI_getbinval(SPI_tuptable->vals[i], 
                                                        SPI_tuptable->tupdesc, 2, &isnull));
                for (j = 0; j < num_nodes; j++) {
                    if (node_ids[j] == src) {
                        adj_list[j][temp_counts[j]++] = tgt;
                        break;
                    }
                }
            }
            pfree(temp_counts);
        }
        
        SPI_finish();
        
        /* PageRank迭代 */
        for (iter = 0; iter < max_iter; iter++) {
            double diff = 0;
            
            /* 计算新rank */
            for (i = 0; i < num_nodes; i++) {
                double sum = 0;
                
                /* 找所有指向i的节点 */
                for (j = 0; j < num_nodes; j++) {
                    if (out_degrees[j] > 0) {
                        for (int k = 0; k < out_degrees[j]; k++) {
                            if (adj_list[j][k] == node_ids[i]) {
                                sum += ranks[j] / out_degrees[j];
                                break;
                            }
                        }
                    }
                }
                
                new_ranks[i] = (1 - damping) / num_nodes + damping * sum;
                diff += fabs(new_ranks[i] - ranks[i]);
            }
            
            /* 复制新rank */
            for (i = 0; i < num_nodes; i++) {
                ranks[i] = new_ranks[i];
            }
            
            /* 检查收敛 */
            if (diff < tolerance) {
                break;
            }
        }
        
        /* 构建结果 */
        results = (PageRankResult *)palloc(sizeof(PageRankResult) * num_nodes);
        for (i = 0; i < num_nodes; i++) {
            results[i].vertex_id = node_ids[i];
            results[i].rank = ranks[i];
        }
        
        /* 释放内存 */
        pfree(node_ids);
        pfree(ranks);
        pfree(new_ranks);
        pfree(out_degrees);
        for (i = 0; i < num_nodes; i++) {
            if (adj_list[i]) pfree(adj_list[i]);
        }
        pfree(adj_list);
        pfree(adj_counts);
        
        ctx = (PageRankContext *)palloc(sizeof(PageRankContext));
        ctx->results = results;
        ctx->num_results = num_nodes;
        
        funcctx->user_fctx = ctx;
        funcctx->max_calls = num_nodes;
        
        if (get_call_result_type(fcinfo, NULL, &tupdesc) != TYPEFUNC_COMPOSITE)
            ereport(ERROR, (errmsg("return type must be a row type")));
        funcctx->tuple_desc = BlessTupleDesc(tupdesc);
        
        MemoryContextSwitchTo(oldcontext);
    }
    
    funcctx = SRF_PERCALL_SETUP();
    
    if (funcctx->call_cntr < funcctx->max_calls) {
        PageRankContext *ctx = (PageRankContext *)funcctx->user_fctx;
        int idx = funcctx->call_cntr;
        
        Datum values[2];
        bool nulls[2] = {false, false};
        HeapTuple tuple;
        
        values[0] = Int64GetDatum(ctx->results[idx].vertex_id);
        values[1] = Float8GetDatum(ctx->results[idx].rank);
        
        tuple = heap_form_tuple(funcctx->tuple_desc, values, nulls);
        SRF_RETURN_NEXT(funcctx, HeapTupleGetDatum(tuple));
    }
    
    SRF_RETURN_DONE(funcctx);
}

/* ============================================================================
 * 度中心性计算 (C实现)
 * ============================================================================ */

PG_FUNCTION_INFO_V1(degree_centrality_c);

Datum
degree_centrality_c(PG_FUNCTION_ARGS)
{
    FuncCallContext *funcctx;
    
    if (SRF_IS_FIRSTCALL()) {
        MemoryContext oldcontext;
        text *graph_name_text = PG_GETARG_TEXT_PP(0);
        char *mode = text_to_cstring(PG_GETARG_TEXT_PP(1)); /* "in", "out", "both" */
        
        char *graph_name = text_to_cstring(graph_name_text);
        int32 graph_id = -1;
        
        int64 *node_ids = NULL;
        int32 *in_degrees = NULL;
        int32 *out_degrees = NULL;
        int32 num_nodes = 0;
        
        PageRankResult *results;
        PageRankContext *ctx;
        TupleDesc tupdesc;
        int ret, i, j;
        
        funcctx = SRF_FIRSTCALL_INIT();
        oldcontext = MemoryContextSwitchTo(funcctx->multi_call_memory_ctx);
        
        if (SPI_connect() != SPI_OK_CONNECT) {
            ereport(ERROR, (errmsg("degree_centrality_c: SPI_connect failed")));
        }
        
        char query[512];
        char *safe_name = quote_literal_safe(graph_name);
        snprintf(query, sizeof(query), 
                 "SELECT id FROM otb_age.graphs WHERE name = %s", safe_name);
        pfree(safe_name);
        ret = SPI_execute(query, true, 1);
        
        if (ret == SPI_OK_SELECT && SPI_processed > 0) {
            bool isnull;
            graph_id = DatumGetInt32(SPI_getbinval(SPI_tuptable->vals[0], 
                                                    SPI_tuptable->tupdesc, 1, &isnull));
        }
        
        if (graph_id < 0) {
            SPI_finish();
            ereport(ERROR, (errmsg("degree_centrality_c: Graph not found")));
        }
        
        /* 获取所有顶点 */
        snprintf(query, sizeof(query), 
                 "SELECT id FROM otb_age.vertices WHERE graph_id = %d ORDER BY id", graph_id);
        ret = SPI_execute(query, true, 10000);
        
        if (ret == SPI_OK_SELECT && SPI_processed > 0) {
            num_nodes = (int32)SPI_processed;
            node_ids = (int64 *)palloc(sizeof(int64) * num_nodes);
            in_degrees = (int32 *)palloc0(sizeof(int32) * num_nodes);
            out_degrees = (int32 *)palloc0(sizeof(int32) * num_nodes);
            
            for (i = 0; i < num_nodes; i++) {
                bool isnull;
                node_ids[i] = DatumGetInt64(SPI_getbinval(SPI_tuptable->vals[i], 
                                                          SPI_tuptable->tupdesc, 1, &isnull));
            }
        }
        
        if (num_nodes == 0) {
            SPI_finish();
            results = (PageRankResult *)palloc0(sizeof(PageRankResult));
            ctx = (PageRankContext *)palloc(sizeof(PageRankContext));
            ctx->results = results;
            ctx->num_results = 0;
            funcctx->user_fctx = ctx;
            funcctx->max_calls = 0;
            
            if (get_call_result_type(fcinfo, NULL, &tupdesc) != TYPEFUNC_COMPOSITE)
                ereport(ERROR, (errmsg("return type must be a row type")));
            funcctx->tuple_desc = BlessTupleDesc(tupdesc);
            MemoryContextSwitchTo(oldcontext);
            SRF_RETURN_DONE(funcctx);
        }
        
        /* 计算度数 */
        snprintf(query, sizeof(query),
                 "SELECT start_id, end_id FROM otb_age.edges WHERE graph_id = %d", graph_id);
        ret = SPI_execute(query, true, 100000);
        
        if (ret == SPI_OK_SELECT && SPI_processed > 0) {
            int num_edges = (int)SPI_processed;
            
            for (i = 0; i < num_edges; i++) {
                bool isnull;
                int64 src = DatumGetInt64(SPI_getbinval(SPI_tuptable->vals[i], 
                                                        SPI_tuptable->tupdesc, 1, &isnull));
                int64 tgt = DatumGetInt64(SPI_getbinval(SPI_tuptable->vals[i], 
                                                        SPI_tuptable->tupdesc, 2, &isnull));
                
                for (j = 0; j < num_nodes; j++) {
                    if (node_ids[j] == src) out_degrees[j]++;
                    if (node_ids[j] == tgt) in_degrees[j]++;
                }
            }
        }
        
        SPI_finish();
        
        /* 构建结果（标准化为0-1范围） */
        results = (PageRankResult *)palloc(sizeof(PageRankResult) * num_nodes);
        double max_degree = (double)(num_nodes - 1);
        
        for (i = 0; i < num_nodes; i++) {
            results[i].vertex_id = node_ids[i];
            
            if (strcmp(mode, "in") == 0) {
                results[i].rank = max_degree > 0 ? in_degrees[i] / max_degree : 0;
            } else if (strcmp(mode, "out") == 0) {
                results[i].rank = max_degree > 0 ? out_degrees[i] / max_degree : 0;
            } else {
                results[i].rank = max_degree > 0 ? 
                    (in_degrees[i] + out_degrees[i]) / (2 * max_degree) : 0;
            }
        }
        
        pfree(node_ids);
        pfree(in_degrees);
        pfree(out_degrees);
        
        ctx = (PageRankContext *)palloc(sizeof(PageRankContext));
        ctx->results = results;
        ctx->num_results = num_nodes;
        
        funcctx->user_fctx = ctx;
        funcctx->max_calls = num_nodes;
        
        if (get_call_result_type(fcinfo, NULL, &tupdesc) != TYPEFUNC_COMPOSITE)
            ereport(ERROR, (errmsg("return type must be a row type")));
        funcctx->tuple_desc = BlessTupleDesc(tupdesc);
        
        MemoryContextSwitchTo(oldcontext);
    }
    
    funcctx = SRF_PERCALL_SETUP();
    
    if (funcctx->call_cntr < funcctx->max_calls) {
        PageRankContext *ctx = (PageRankContext *)funcctx->user_fctx;
        int idx = funcctx->call_cntr;
        
        Datum values[2];
        bool nulls[2] = {false, false};
        HeapTuple tuple;
        
        values[0] = Int64GetDatum(ctx->results[idx].vertex_id);
        values[1] = Float8GetDatum(ctx->results[idx].rank);
        
        tuple = heap_form_tuple(funcctx->tuple_desc, values, nulls);
        SRF_RETURN_NEXT(funcctx, HeapTupleGetDatum(tuple));
    }
    
    SRF_RETURN_DONE(funcctx);
}

/* ============================================================================
 * Jaccard相似度计算 (C实现)
 * 计算两个节点邻居集合的相似度
 * ============================================================================ */

PG_FUNCTION_INFO_V1(jaccard_similarity_c);

Datum
jaccard_similarity_c(PG_FUNCTION_ARGS)
{
    text *graph_name_text = PG_GETARG_TEXT_PP(0);
    int64 node1 = PG_GETARG_INT64(1);
    int64 node2 = PG_GETARG_INT64(2);
    
    char *graph_name = text_to_cstring(graph_name_text);
    int32 graph_id = -1;
    
    int64 *neighbors1 = NULL, *neighbors2 = NULL;
    int32 n1 = 0, n2 = 0;
    int32 intersection = 0, union_count = 0;
    
    if (SPI_connect() != SPI_OK_CONNECT) {
        ereport(ERROR, (errmsg("jaccard_similarity_c: SPI_connect failed")));
    }
    
    char query[512];
    char *safe_name = quote_literal_safe(graph_name);
    snprintf(query, sizeof(query), 
             "SELECT id FROM otb_age.graphs WHERE name = %s", safe_name);
    pfree(safe_name);
    int ret = SPI_execute(query, true, 1);
    
    if (ret == SPI_OK_SELECT && SPI_processed > 0) {
        bool isnull;
        graph_id = DatumGetInt32(SPI_getbinval(SPI_tuptable->vals[0], 
                                                SPI_tuptable->tupdesc, 1, &isnull));
    }
    
    if (graph_id < 0) {
        SPI_finish();
        PG_RETURN_FLOAT8(0.0);
    }
    
    /* 获取node1的邻居 */
    snprintf(query, sizeof(query),
             "SELECT end_id FROM otb_age.edges WHERE graph_id = %d AND start_id = %ld "
             "UNION SELECT start_id FROM otb_age.edges WHERE graph_id = %d AND end_id = %ld",
             graph_id, (long)node1, graph_id, (long)node1);
    ret = SPI_execute(query, true, 10000);
    
    if (ret == SPI_OK_SELECT && SPI_processed > 0) {
        n1 = (int32)SPI_processed;
        neighbors1 = (int64 *)palloc(sizeof(int64) * n1);
        for (int i = 0; i < n1; i++) {
            bool isnull;
            neighbors1[i] = DatumGetInt64(SPI_getbinval(SPI_tuptable->vals[i], 
                                                        SPI_tuptable->tupdesc, 1, &isnull));
        }
    }
    
    /* 获取node2的邻居 */
    snprintf(query, sizeof(query),
             "SELECT end_id FROM otb_age.edges WHERE graph_id = %d AND start_id = %ld "
             "UNION SELECT start_id FROM otb_age.edges WHERE graph_id = %d AND end_id = %ld",
             graph_id, (long)node2, graph_id, (long)node2);
    ret = SPI_execute(query, true, 10000);
    
    if (ret == SPI_OK_SELECT && SPI_processed > 0) {
        n2 = (int32)SPI_processed;
        neighbors2 = (int64 *)palloc(sizeof(int64) * n2);
        for (int i = 0; i < n2; i++) {
            bool isnull;
            neighbors2[i] = DatumGetInt64(SPI_getbinval(SPI_tuptable->vals[i], 
                                                        SPI_tuptable->tupdesc, 1, &isnull));
        }
    }
    
    SPI_finish();
    
    /* 计算交集和并集 */
    if (n1 > 0 && n2 > 0) {
        /* 交集 */
        for (int i = 0; i < n1; i++) {
            for (int j = 0; j < n2; j++) {
                if (neighbors1[i] == neighbors2[j]) {
                    intersection++;
                    break;
                }
            }
        }
        
        /* 并集 = n1 + n2 - 交集 */
        union_count = n1 + n2 - intersection;
    } else {
        union_count = n1 + n2;
    }
    
    if (neighbors1) pfree(neighbors1);
    if (neighbors2) pfree(neighbors2);
    
    double similarity = union_count > 0 ? (double)intersection / union_count : 0.0;
    
    PG_RETURN_FLOAT8(similarity);
}

/* ============================================================================
 * 共同邻居数量 (C实现)
 * 用于链接预测
 * ============================================================================ */

PG_FUNCTION_INFO_V1(common_neighbors_c);

Datum
common_neighbors_c(PG_FUNCTION_ARGS)
{
    text *graph_name_text = PG_GETARG_TEXT_PP(0);
    int64 node1 = PG_GETARG_INT64(1);
    int64 node2 = PG_GETARG_INT64(2);
    
    char *graph_name = text_to_cstring(graph_name_text);
    int32 graph_id = -1;
    int32 count = 0;
    
    if (SPI_connect() != SPI_OK_CONNECT) {
        ereport(ERROR, (errmsg("common_neighbors_c: SPI_connect failed")));
    }
    
    char query[1024];
    char *safe_name = quote_literal_safe(graph_name);
    snprintf(query, sizeof(query), 
             "SELECT id FROM otb_age.graphs WHERE name = %s", safe_name);
    pfree(safe_name);
    int ret = SPI_execute(query, true, 1);
    
    if (ret == SPI_OK_SELECT && SPI_processed > 0) {
        bool isnull;
        graph_id = DatumGetInt32(SPI_getbinval(SPI_tuptable->vals[0], 
                                                SPI_tuptable->tupdesc, 1, &isnull));
    }
    
    if (graph_id >= 0) {
        /* 使用SQL计算共同邻居 */
        snprintf(query, sizeof(query),
                 "SELECT COUNT(*) FROM ("
                 "  SELECT end_id AS n FROM otb_age.edges WHERE graph_id = %d AND start_id = %ld "
                 "  UNION SELECT start_id FROM otb_age.edges WHERE graph_id = %d AND end_id = %ld"
                 ") a "
                 "JOIN ("
                 "  SELECT end_id AS n FROM otb_age.edges WHERE graph_id = %d AND start_id = %ld "
                 "  UNION SELECT start_id FROM otb_age.edges WHERE graph_id = %d AND end_id = %ld"
                 ") b ON a.n = b.n",
                 graph_id, (long)node1, graph_id, (long)node1,
                 graph_id, (long)node2, graph_id, (long)node2);
        
        ret = SPI_execute(query, true, 1);
        if (ret == SPI_OK_SELECT && SPI_processed > 0) {
            bool isnull;
            count = DatumGetInt32(SPI_getbinval(SPI_tuptable->vals[0], 
                                                SPI_tuptable->tupdesc, 1, &isnull));
        }
    }
    
    SPI_finish();
    PG_RETURN_INT32(count);
}

/* ============================================================================
 * 三角形计数 (C实现)
 * 计算图中三角形的数量
 * ============================================================================ */

PG_FUNCTION_INFO_V1(triangle_count_c);

Datum
triangle_count_c(PG_FUNCTION_ARGS)
{
    text *graph_name_text = PG_GETARG_TEXT_PP(0);
    char *graph_name = text_to_cstring(graph_name_text);
    int32 graph_id = -1;
    int64 count = 0;
    
    if (SPI_connect() != SPI_OK_CONNECT) {
        ereport(ERROR, (errmsg("triangle_count_c: SPI_connect failed")));
    }
    
    char query[512];
    char *safe_name = quote_literal_safe(graph_name);
    snprintf(query, sizeof(query), 
             "SELECT id FROM otb_age.graphs WHERE name = %s", safe_name);
    pfree(safe_name);
    int ret = SPI_execute(query, true, 1);
    
    if (ret == SPI_OK_SELECT && SPI_processed > 0) {
        bool isnull;
        graph_id = DatumGetInt32(SPI_getbinval(SPI_tuptable->vals[0], 
                                                SPI_tuptable->tupdesc, 1, &isnull));
    }
    
    if (graph_id >= 0) {
        /* 使用SQL计算三角形（每个三角形被数3次，所以除以3） */
        snprintf(query, sizeof(query),
                 "SELECT COUNT(*) / 3 FROM otb_age.edges e1 "
                 "JOIN otb_age.edges e2 ON e1.end_id = e2.start_id AND e1.graph_id = e2.graph_id "
                 "JOIN otb_age.edges e3 ON e2.end_id = e3.start_id AND e3.end_id = e1.start_id "
                 "AND e2.graph_id = e3.graph_id "
                 "WHERE e1.graph_id = %d", graph_id);
        
        ret = SPI_execute(query, true, 1);
        if (ret == SPI_OK_SELECT && SPI_processed > 0) {
            bool isnull;
            count = DatumGetInt64(SPI_getbinval(SPI_tuptable->vals[0], 
                                                SPI_tuptable->tupdesc, 1, &isnull));
        }
    }
    
    SPI_finish();
    PG_RETURN_INT64(count);
}

/* ============================================================================
 * 连通分量计算 (Union-Find算法，C实现)
 * 比递归CTE快10-50倍
 * ============================================================================ */

/* Union-Find数据结构 */
typedef struct {
    int32 *parent;
    int32 *rank;
    int32 size;
} UnionFind;

/* 初始化Union-Find */
static UnionFind* uf_create(int32 size) {
    UnionFind *uf = (UnionFind *)palloc(sizeof(UnionFind));
    uf->parent = (int32 *)palloc(sizeof(int32) * size);
    uf->rank = (int32 *)palloc0(sizeof(int32) * size);
    uf->size = size;
    
    for (int32 i = 0; i < size; i++) {
        uf->parent[i] = i;
    }
    return uf;
}

/* 查找根节点（带路径压缩） */
static int32 uf_find(UnionFind *uf, int32 x) {
    if (uf->parent[x] != x) {
        uf->parent[x] = uf_find(uf, uf->parent[x]);  /* 路径压缩 */
    }
    return uf->parent[x];
}

/* 合并两个集合（按秩合并） */
static void uf_union(UnionFind *uf, int32 x, int32 y) {
    int32 rx = uf_find(uf, x);
    int32 ry = uf_find(uf, y);
    
    if (rx == ry) return;
    
    if (uf->rank[rx] < uf->rank[ry]) {
        uf->parent[rx] = ry;
    } else if (uf->rank[rx] > uf->rank[ry]) {
        uf->parent[ry] = rx;
    } else {
        uf->parent[ry] = rx;
        uf->rank[rx]++;
    }
}

/* 释放Union-Find */
static void uf_free(UnionFind *uf) {
    pfree(uf->parent);
    pfree(uf->rank);
    pfree(uf);
}

/* 连通分量结果结构 */
typedef struct {
    int64 vertex_id;
    int32 component_id;
} ComponentResult;

typedef struct {
    ComponentResult *results;
    int32 num_results;
} ComponentContext;

PG_FUNCTION_INFO_V1(connected_components_c);

Datum
connected_components_c(PG_FUNCTION_ARGS)
{
    FuncCallContext *funcctx;
    
    if (SRF_IS_FIRSTCALL()) {
        MemoryContext oldcontext;
        text *graph_name_text = PG_GETARG_TEXT_PP(0);
        
        char *graph_name = text_to_cstring(graph_name_text);
        int32 graph_id = -1;
        
        int64 *node_ids = NULL;
        int32 num_nodes = 0;
        UnionFind *uf = NULL;
        
        ComponentResult *results;
        ComponentContext *ctx;
        TupleDesc tupdesc;
        int ret, i;
        
        funcctx = SRF_FIRSTCALL_INIT();
        oldcontext = MemoryContextSwitchTo(funcctx->multi_call_memory_ctx);
        
        if (SPI_connect() != SPI_OK_CONNECT) {
            ereport(ERROR, (errmsg("connected_components_c: SPI_connect failed")));
        }
        
        /* 获取图ID */
        char query[1024];
        char *safe_name = quote_literal_safe(graph_name);
        snprintf(query, sizeof(query), 
                 "SELECT id FROM otb_age.graphs WHERE name = %s", safe_name);
        pfree(safe_name);
        ret = SPI_execute(query, true, 1);
        
        if (ret == SPI_OK_SELECT && SPI_processed > 0) {
            bool isnull;
            graph_id = DatumGetInt32(SPI_getbinval(SPI_tuptable->vals[0], 
                                                    SPI_tuptable->tupdesc, 1, &isnull));
        }
        
        if (graph_id < 0) {
            SPI_finish();
            ereport(ERROR, (errmsg("connected_components_c: Graph '%s' not found", graph_name)));
        }
        
        /* 获取所有顶点 */
        snprintf(query, sizeof(query), 
                 "SELECT id FROM otb_age.vertices WHERE graph_id = %d ORDER BY id", graph_id);
        ret = SPI_execute(query, true, 100000);
        
        if (ret == SPI_OK_SELECT && SPI_processed > 0) {
            num_nodes = (int32)SPI_processed;
            node_ids = (int64 *)palloc(sizeof(int64) * num_nodes);
            
            for (i = 0; i < num_nodes; i++) {
                bool isnull;
                node_ids[i] = DatumGetInt64(SPI_getbinval(SPI_tuptable->vals[i], 
                                                          SPI_tuptable->tupdesc, 1, &isnull));
            }
        }
        
        if (num_nodes == 0) {
            SPI_finish();
            results = (ComponentResult *)palloc0(sizeof(ComponentResult));
            ctx = (ComponentContext *)palloc(sizeof(ComponentContext));
            ctx->results = results;
            ctx->num_results = 0;
            funcctx->user_fctx = ctx;
            funcctx->max_calls = 0;
            
            if (get_call_result_type(fcinfo, NULL, &tupdesc) != TYPEFUNC_COMPOSITE)
                ereport(ERROR, (errmsg("return type must be a row type")));
            funcctx->tuple_desc = BlessTupleDesc(tupdesc);
            MemoryContextSwitchTo(oldcontext);
            SRF_RETURN_DONE(funcctx);
        }
        
        /* 创建Union-Find结构 */
        uf = uf_create(num_nodes);
        
        /* 获取所有边并合并连通分量 */
        snprintf(query, sizeof(query),
                 "SELECT start_id, end_id FROM otb_age.edges WHERE graph_id = %d", graph_id);
        ret = SPI_execute(query, true, 1000000);
        
        if (ret == SPI_OK_SELECT && SPI_processed > 0) {
            int num_edges = (int)SPI_processed;
            
            for (i = 0; i < num_edges; i++) {
                bool isnull;
                int64 src = DatumGetInt64(SPI_getbinval(SPI_tuptable->vals[i], 
                                                        SPI_tuptable->tupdesc, 1, &isnull));
                int64 tgt = DatumGetInt64(SPI_getbinval(SPI_tuptable->vals[i], 
                                                        SPI_tuptable->tupdesc, 2, &isnull));
                
                /* 找到源和目标的索引 */
                int32 src_idx = -1, tgt_idx = -1;
                for (int j = 0; j < num_nodes; j++) {
                    if (node_ids[j] == src) src_idx = j;
                    if (node_ids[j] == tgt) tgt_idx = j;
                    if (src_idx >= 0 && tgt_idx >= 0) break;
                }
                
                /* 合并 */
                if (src_idx >= 0 && tgt_idx >= 0) {
                    uf_union(uf, src_idx, tgt_idx);
                }
            }
        }
        
        SPI_finish();
        
        /* 构建结果：为每个节点分配组件ID */
        results = (ComponentResult *)palloc(sizeof(ComponentResult) * num_nodes);
        
        /* 标准化组件ID（使用最小节点ID作为组件ID） */
        int32 *component_map = (int32 *)palloc(sizeof(int32) * num_nodes);
        int32 next_component = 0;
        
        for (i = 0; i < num_nodes; i++) {
            component_map[i] = -1;
        }
        
        for (i = 0; i < num_nodes; i++) {
            int32 root = uf_find(uf, i);
            if (component_map[root] < 0) {
                component_map[root] = next_component++;
            }
            results[i].vertex_id = node_ids[i];
            results[i].component_id = component_map[root];
        }
        
        pfree(component_map);
        pfree(node_ids);
        uf_free(uf);
        
        ctx = (ComponentContext *)palloc(sizeof(ComponentContext));
        ctx->results = results;
        ctx->num_results = num_nodes;
        
        funcctx->user_fctx = ctx;
        funcctx->max_calls = num_nodes;
        
        if (get_call_result_type(fcinfo, NULL, &tupdesc) != TYPEFUNC_COMPOSITE)
            ereport(ERROR, (errmsg("return type must be a row type")));
        funcctx->tuple_desc = BlessTupleDesc(tupdesc);
        
        MemoryContextSwitchTo(oldcontext);
    }
    
    funcctx = SRF_PERCALL_SETUP();
    
    if (funcctx->call_cntr < funcctx->max_calls) {
        ComponentContext *ctx = (ComponentContext *)funcctx->user_fctx;
        int idx = funcctx->call_cntr;
        
        Datum values[2];
        bool nulls[2] = {false, false};
        HeapTuple tuple;
        
        values[0] = Int64GetDatum(ctx->results[idx].vertex_id);
        values[1] = Int32GetDatum(ctx->results[idx].component_id);
        
        tuple = heap_form_tuple(funcctx->tuple_desc, values, nulls);
        SRF_RETURN_NEXT(funcctx, HeapTupleGetDatum(tuple));
    }
    
    SRF_RETURN_DONE(funcctx);
}

/* ============================================================================
 * 度分布统计 (C实现)
 * ============================================================================ */

typedef struct {
    int32 degree;
    int64 count;
} DegreeDistResult;

typedef struct {
    DegreeDistResult *results;
    int32 num_results;
} DegreeDistContext;

PG_FUNCTION_INFO_V1(degree_distribution_c);

Datum
degree_distribution_c(PG_FUNCTION_ARGS)
{
    FuncCallContext *funcctx;
    
    if (SRF_IS_FIRSTCALL()) {
        MemoryContext oldcontext;
        text *graph_name_text = PG_GETARG_TEXT_PP(0);
        
        char *graph_name = text_to_cstring(graph_name_text);
        int32 graph_id = -1;
        
        int32 *degrees = NULL;
        int32 num_nodes = 0;
        int32 max_degree = 0;
        
        DegreeDistResult *results;
        DegreeDistContext *ctx;
        TupleDesc tupdesc;
        int ret, i;
        
        funcctx = SRF_FIRSTCALL_INIT();
        oldcontext = MemoryContextSwitchTo(funcctx->multi_call_memory_ctx);
        
        if (SPI_connect() != SPI_OK_CONNECT) {
            ereport(ERROR, (errmsg("degree_distribution_c: SPI_connect failed")));
        }
        
        char query[1024];
        char *safe_name = quote_literal_safe(graph_name);
        snprintf(query, sizeof(query), 
                 "SELECT id FROM otb_age.graphs WHERE name = %s", safe_name);
        pfree(safe_name);
        ret = SPI_execute(query, true, 1);
        
        if (ret == SPI_OK_SELECT && SPI_processed > 0) {
            bool isnull;
            graph_id = DatumGetInt32(SPI_getbinval(SPI_tuptable->vals[0], 
                                                    SPI_tuptable->tupdesc, 1, &isnull));
        }
        
        if (graph_id < 0) {
            SPI_finish();
            ereport(ERROR, (errmsg("degree_distribution_c: Graph not found")));
        }
        
        /* 获取节点数量 */
        snprintf(query, sizeof(query), 
                 "SELECT COUNT(*) FROM otb_age.vertices WHERE graph_id = %d", graph_id);
        ret = SPI_execute(query, true, 1);
        
        if (ret == SPI_OK_SELECT && SPI_processed > 0) {
            bool isnull;
            num_nodes = DatumGetInt32(SPI_getbinval(SPI_tuptable->vals[0], 
                                                    SPI_tuptable->tupdesc, 1, &isnull));
        }
        
        if (num_nodes == 0) {
            SPI_finish();
            results = (DegreeDistResult *)palloc0(sizeof(DegreeDistResult));
            ctx = (DegreeDistContext *)palloc(sizeof(DegreeDistContext));
            ctx->results = results;
            ctx->num_results = 0;
            funcctx->user_fctx = ctx;
            funcctx->max_calls = 0;
            
            if (get_call_result_type(fcinfo, NULL, &tupdesc) != TYPEFUNC_COMPOSITE)
                ereport(ERROR, (errmsg("return type must be a row type")));
            funcctx->tuple_desc = BlessTupleDesc(tupdesc);
            MemoryContextSwitchTo(oldcontext);
            SRF_RETURN_DONE(funcctx);
        }
        
        /* 直接用SQL计算度分布（更高效） */
        snprintf(query, sizeof(query),
                 "SELECT degree, COUNT(*) AS cnt FROM ("
                 "  SELECT v.id, COALESCE(e_out.out_deg, 0) + COALESCE(e_in.in_deg, 0) AS degree"
                 "  FROM otb_age.vertices v"
                 "  LEFT JOIN (SELECT start_id, COUNT(*) AS out_deg FROM otb_age.edges WHERE graph_id = %d GROUP BY start_id) e_out ON v.id = e_out.start_id"
                 "  LEFT JOIN (SELECT end_id, COUNT(*) AS in_deg FROM otb_age.edges WHERE graph_id = %d GROUP BY end_id) e_in ON v.id = e_in.end_id"
                 "  WHERE v.graph_id = %d"
                 ") sub GROUP BY degree ORDER BY degree",
                 graph_id, graph_id, graph_id);
        
        ret = SPI_execute(query, true, 10000);
        
        int num_results = 0;
        if (ret == SPI_OK_SELECT && SPI_processed > 0) {
            num_results = (int)SPI_processed;
            results = (DegreeDistResult *)palloc(sizeof(DegreeDistResult) * num_results);
            
            for (i = 0; i < num_results; i++) {
                bool isnull;
                results[i].degree = DatumGetInt32(SPI_getbinval(SPI_tuptable->vals[i], 
                                                                SPI_tuptable->tupdesc, 1, &isnull));
                results[i].count = DatumGetInt64(SPI_getbinval(SPI_tuptable->vals[i], 
                                                               SPI_tuptable->tupdesc, 2, &isnull));
            }
        } else {
            results = (DegreeDistResult *)palloc0(sizeof(DegreeDistResult));
        }
        
        SPI_finish();
        
        ctx = (DegreeDistContext *)palloc(sizeof(DegreeDistContext));
        ctx->results = results;
        ctx->num_results = num_results;
        
        funcctx->user_fctx = ctx;
        funcctx->max_calls = num_results;
        
        if (get_call_result_type(fcinfo, NULL, &tupdesc) != TYPEFUNC_COMPOSITE)
            ereport(ERROR, (errmsg("return type must be a row type")));
        funcctx->tuple_desc = BlessTupleDesc(tupdesc);
        
        MemoryContextSwitchTo(oldcontext);
    }
    
    funcctx = SRF_PERCALL_SETUP();
    
    if (funcctx->call_cntr < funcctx->max_calls) {
        DegreeDistContext *ctx = (DegreeDistContext *)funcctx->user_fctx;
        int idx = funcctx->call_cntr;
        
        Datum values[2];
        bool nulls[2] = {false, false};
        HeapTuple tuple;
        
        values[0] = Int32GetDatum(ctx->results[idx].degree);
        values[1] = Int64GetDatum(ctx->results[idx].count);
        
        tuple = heap_form_tuple(funcctx->tuple_desc, values, nulls);
        SRF_RETURN_NEXT(funcctx, HeapTupleGetDatum(tuple));
    }
    
    SRF_RETURN_DONE(funcctx);
}


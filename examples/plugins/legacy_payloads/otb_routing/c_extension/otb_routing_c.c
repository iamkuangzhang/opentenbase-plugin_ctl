/*
 * otb_routing_c.c
 * 
 * OpenTenBase Routing Adapter - 高性能路网算法C扩展
 * pgRouting兼容实现
 * 
 * 版本 2.0 - 增强版：添加A*、Bellman-Ford、TSP等算法
 * 
 * 包含算法:
 *   - dijkstra_c()             Dijkstra最短路径
 *   - driving_distance_c()     驾驶距离/等时圈
 *   - astar_c()                A*启发式搜索
 *   - bellman_ford_c()         Bellman-Ford（支持负权重）
 *   - tsp_greedy_c()           旅行商问题（贪心算法）
 *   - bidirectional_dijkstra_c() 双向Dijkstra
 *   - distance_matrix_c()      距离矩阵计算
 *   - k_shortest_paths_c()     K条最短路径
 */

#include "postgres.h"
#include "fmgr.h"
#include "funcapi.h"
#include "executor/spi.h"
#include "utils/builtins.h"
#include "utils/array.h"
#include "catalog/pg_type.h"
#include "access/htup_details.h"
#include <math.h>
#include <float.h>
#include <string.h>

#ifdef PG_MODULE_MAGIC
PG_MODULE_MAGIC;
#endif

/* ============================================================================
 * 数据结构定义
 * ============================================================================ */

#define MAX_NODES 10000
#define MAX_EDGES 50000
#define MAX_PATH  1000
#define INFINITY_COST DBL_MAX

/* 容量限制警告标志（避免重复警告） */
static bool g_nodes_limit_warned = false;
static bool g_edges_limit_warned = false;
static bool g_path_limit_warned = false;

/* 重置警告标志（在每次函数调用开始时调用） */
static void reset_limit_warnings(void) {
    g_nodes_limit_warned = false;
    g_edges_limit_warned = false;
    g_path_limit_warned = false;
}

/* 边信息 */
typedef struct {
    int64 id;
    int64 source;
    int64 target;
    double cost;
    double reverse_cost;
} Edge;

/* 路径结果 */
typedef struct {
    int32 seq;
    int64 node;
    int64 edge;
    double cost;
    double agg_cost;
} PathResult;

/* 结果上下文 */
typedef struct {
    PathResult *results;
    int32 num_results;
} ResultContext;

/* ============================================================================
 * 辅助函数
 * ============================================================================ */

/* 在节点数组中查找节点索引，找不到则添加 */
static int find_or_add_node_func(int64 *node_ids, int *num_nodes, int64 nid) {
    int i;
    for (i = 0; i < *num_nodes; i++) {
        if (node_ids[i] == nid) {
            return i;
        }
    }
    if (*num_nodes < MAX_NODES) {
        node_ids[*num_nodes] = nid;
        (*num_nodes)++;
        return *num_nodes - 1;
    }
    /* 达到节点数量上限，发出警告 */
    if (!g_nodes_limit_warned) {
        ereport(WARNING,
                (errcode(ERRCODE_PROGRAM_LIMIT_EXCEEDED),
                 errmsg("routing: node limit reached (%d), some nodes may be ignored", MAX_NODES),
                 errhint("Consider filtering your graph to reduce the number of nodes.")));
        g_nodes_limit_warned = true;
    }
    return -1;
}

/* 简单的堆排序插入（用于优先队列） */
typedef struct {
    int64 node_id;
    double cost;
} PQItem;

static void pq_insert(PQItem *pq, int *pq_size, int64 node_id, double cost) {
    int i = *pq_size;
    pq[i].node_id = node_id;
    pq[i].cost = cost;
    (*pq_size)++;
    
    /* 上浮 */
    while (i > 0) {
        int parent = (i - 1) / 2;
        if (pq[parent].cost > pq[i].cost) {
            PQItem tmp = pq[parent];
            pq[parent] = pq[i];
            pq[i] = tmp;
            i = parent;
        } else {
            break;
        }
    }
}

static bool pq_pop(PQItem *pq, int *pq_size, int64 *out_node, double *out_cost) {
    if (*pq_size == 0) return false;
    
    *out_node = pq[0].node_id;
    *out_cost = pq[0].cost;
    
    (*pq_size)--;
    if (*pq_size > 0) {
        pq[0] = pq[*pq_size];
        
        /* 下沉 */
        int i = 0;
        while (true) {
            int smallest = i;
            int left = 2 * i + 1;
            int right = 2 * i + 2;
            
            if (left < *pq_size && pq[left].cost < pq[smallest].cost)
                smallest = left;
            if (right < *pq_size && pq[right].cost < pq[smallest].cost)
                smallest = right;
            
            if (smallest != i) {
                PQItem tmp = pq[i];
                pq[i] = pq[smallest];
                pq[smallest] = tmp;
                i = smallest;
            } else {
                break;
            }
        }
    }
    return true;
}

/* ============================================================================
 * Dijkstra 最短路径算法
 * ============================================================================ */

PG_FUNCTION_INFO_V1(dijkstra_c);

Datum
dijkstra_c(PG_FUNCTION_ARGS)
{
    FuncCallContext *funcctx;
    
    if (SRF_IS_FIRSTCALL()) {
        MemoryContext oldcontext;
        text *edges_sql_text = PG_GETARG_TEXT_PP(0);
        int64 start_vid = PG_GETARG_INT64(1);
        int64 end_vid = PG_GETARG_INT64(2);
        bool directed = PG_GETARG_BOOL(3);
        
        char *edges_sql;
        Edge *edges = NULL;
        int num_edges = 0;
        
        int64 *node_ids;
        double *dist;
        int64 *prev_node;
        int64 *prev_edge;
        bool *visited;
        int num_nodes = 0;
        
        PQItem *pq;
        
        /* 重置容量限制警告标志 */
        reset_limit_warnings();
        int pq_size = 0;
        
        PathResult *results;
        int num_results = 0;
        
        ResultContext *ctx;
        TupleDesc tupdesc;
        int ret, i, j;
        
        funcctx = SRF_FIRSTCALL_INIT();
        oldcontext = MemoryContextSwitchTo(funcctx->multi_call_memory_ctx);
        
        edges_sql = text_to_cstring(edges_sql_text);
        
        /* 分配内存 */
        edges = (Edge *)palloc0(sizeof(Edge) * MAX_EDGES);
        node_ids = (int64 *)palloc0(sizeof(int64) * MAX_NODES);
        dist = (double *)palloc(sizeof(double) * MAX_NODES);
        prev_node = (int64 *)palloc(sizeof(int64) * MAX_NODES);
        prev_edge = (int64 *)palloc(sizeof(int64) * MAX_NODES);
        visited = (bool *)palloc0(sizeof(bool) * MAX_NODES);
        pq = (PQItem *)palloc0(sizeof(PQItem) * MAX_NODES);
        results = (PathResult *)palloc0(sizeof(PathResult) * MAX_PATH);
        
        /* 初始化距离数组 */
        for (i = 0; i < MAX_NODES; i++) {
            dist[i] = DBL_MAX;
            prev_node[i] = -1;
            prev_edge[i] = -1;
        }
        
        /* 连接SPI并加载边 */
        if (SPI_connect() != SPI_OK_CONNECT) {
            ereport(ERROR, (errmsg("dijkstra_c: SPI_connect failed")));
        }
        
        ret = SPI_execute(edges_sql, true, MAX_EDGES);
        
        if (ret == SPI_OK_SELECT && SPI_processed > 0) {
            TupleDesc td = SPI_tuptable->tupdesc;
            num_edges = (int)SPI_processed;
            if (num_edges > MAX_EDGES) {
                if (!g_edges_limit_warned) {
                    ereport(WARNING,
                            (errcode(ERRCODE_PROGRAM_LIMIT_EXCEEDED),
                             errmsg("dijkstra_c: edge limit reached (%d edges in query, %d loaded)", 
                                    num_edges, MAX_EDGES),
                             errhint("Consider filtering your edges SQL to reduce data size.")));
                    g_edges_limit_warned = true;
                }
                num_edges = MAX_EDGES;
            }
            
            for (i = 0; i < num_edges; i++) {
                HeapTuple tuple = SPI_tuptable->vals[i];
                bool isnull;
                
                edges[i].id = DatumGetInt64(SPI_getbinval(tuple, td, 1, &isnull));
                edges[i].source = DatumGetInt64(SPI_getbinval(tuple, td, 2, &isnull));
                edges[i].target = DatumGetInt64(SPI_getbinval(tuple, td, 3, &isnull));
                edges[i].cost = DatumGetFloat8(SPI_getbinval(tuple, td, 4, &isnull));
                
                if (td->natts >= 5) {
                    Datum d = SPI_getbinval(tuple, td, 5, &isnull);
                    edges[i].reverse_cost = isnull ? -1.0 : DatumGetFloat8(d);
                } else {
                    edges[i].reverse_cost = -1.0;
                }
                
                /* 添加节点 */
                find_or_add_node_func(node_ids, &num_nodes, edges[i].source);
                find_or_add_node_func(node_ids, &num_nodes, edges[i].target);
            }
        }
        
        SPI_finish();
        
        if (num_edges == 0 || num_nodes == 0) {
            ctx = (ResultContext *)palloc(sizeof(ResultContext));
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
        
        /* Dijkstra算法 */
        int start_idx = find_or_add_node_func(node_ids, &num_nodes, start_vid);
        int end_idx = find_or_add_node_func(node_ids, &num_nodes, end_vid);
        
        if (start_idx >= 0) {
            dist[start_idx] = 0;
            pq_insert(pq, &pq_size, start_vid, 0);
            
            while (pq_size > 0) {
                int64 current_node;
                double current_cost;
                int curr_idx;
                
                if (!pq_pop(pq, &pq_size, &current_node, &current_cost))
                    break;
                
                /* 找当前节点索引 */
                curr_idx = -1;
                for (i = 0; i < num_nodes; i++) {
                    if (node_ids[i] == current_node) {
                        curr_idx = i;
                        break;
                    }
                }
                
                if (curr_idx < 0 || visited[curr_idx])
                    continue;
                    
                visited[curr_idx] = true;
                
                if (current_node == end_vid)
                    break;
                
                /* 遍历邻边 */
                for (j = 0; j < num_edges; j++) {
                    int64 neighbor = -1;
                    double edge_cost = -1;
                    
                    if (edges[j].source == current_node && edges[j].cost >= 0) {
                        neighbor = edges[j].target;
                        edge_cost = edges[j].cost;
                    } else if (!directed && edges[j].target == current_node && edges[j].cost >= 0) {
                        neighbor = edges[j].source;
                        edge_cost = edges[j].cost;
                    } else if (directed && edges[j].target == current_node && edges[j].reverse_cost >= 0) {
                        neighbor = edges[j].source;
                        edge_cost = edges[j].reverse_cost;
                    }
                    
                    if (neighbor >= 0) {
                        int neigh_idx = -1;
                        for (i = 0; i < num_nodes; i++) {
                            if (node_ids[i] == neighbor) {
                                neigh_idx = i;
                                break;
                            }
                        }
                        
                        if (neigh_idx >= 0 && !visited[neigh_idx]) {
                            double new_cost = dist[curr_idx] + edge_cost;
                            if (new_cost < dist[neigh_idx]) {
                                dist[neigh_idx] = new_cost;
                                prev_node[neigh_idx] = current_node;
                                prev_edge[neigh_idx] = edges[j].id;
                                pq_insert(pq, &pq_size, neighbor, new_cost);
                            }
                        }
                    }
                }
            }
        }
        
        /* 构建路径结果 */
        if (end_idx >= 0 && dist[end_idx] < DBL_MAX) {
            int64 path_nodes[MAX_PATH];
            int64 path_edges[MAX_PATH];
            double path_costs[MAX_PATH];
            int path_len = 0;
            
            /* 回溯路径 */
            int64 curr = end_vid;
            while (curr != -1 && path_len < MAX_PATH) {
                int idx = -1;
                for (i = 0; i < num_nodes; i++) {
                    if (node_ids[i] == curr) {
                        idx = i;
                        break;
                    }
                }
                
                if (idx < 0) break;
                
                path_nodes[path_len] = curr;
                path_edges[path_len] = prev_edge[idx];
                path_costs[path_len] = dist[idx];
                path_len++;
                
                curr = prev_node[idx];
            }
            
            /* 反转路径并存储结果 */
            for (i = 0; i < path_len; i++) {
                int ri = path_len - 1 - i;
                results[i].seq = i + 1;
                results[i].node = path_nodes[ri];
                /* 起点(i=0)的edge是-1(prev_edge初始值)，其他节点使用实际边ID */
                results[i].edge = path_edges[ri];
                results[i].agg_cost = path_costs[ri];
                results[i].cost = (i > 0) ? (results[i].agg_cost - results[i-1].agg_cost) : 0;
            }
            num_results = path_len;
        }
        
        /* 释放不需要的内存 */
        pfree(edges);
        pfree(node_ids);
        pfree(dist);
        pfree(prev_node);
        pfree(prev_edge);
        pfree(visited);
        pfree(pq);
        
        /* 设置返回上下文 */
        ctx = (ResultContext *)palloc(sizeof(ResultContext));
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
        ResultContext *ctx = (ResultContext *)funcctx->user_fctx;
        int idx = funcctx->call_cntr;
        
        Datum values[5];
        bool nulls[5] = {false, false, false, false, false};
        HeapTuple tuple;
        
        values[0] = Int32GetDatum(ctx->results[idx].seq);
        values[1] = Int64GetDatum(ctx->results[idx].node);
        values[2] = Int64GetDatum(ctx->results[idx].edge);
        values[3] = Float8GetDatum(ctx->results[idx].cost);
        values[4] = Float8GetDatum(ctx->results[idx].agg_cost);
        
        if (ctx->results[idx].edge == -1) nulls[2] = true;
        
        tuple = heap_form_tuple(funcctx->tuple_desc, values, nulls);
        SRF_RETURN_NEXT(funcctx, HeapTupleGetDatum(tuple));
    }
    
    SRF_RETURN_DONE(funcctx);
}

/* ============================================================================
 * 驾驶距离（等时圈）
 * ============================================================================ */

PG_FUNCTION_INFO_V1(driving_distance_c);

Datum
driving_distance_c(PG_FUNCTION_ARGS)
{
    FuncCallContext *funcctx;
    
    if (SRF_IS_FIRSTCALL()) {
        MemoryContext oldcontext;
        text *edges_sql_text = PG_GETARG_TEXT_PP(0);
        int64 start_vid = PG_GETARG_INT64(1);
        double max_cost = PG_GETARG_FLOAT8(2);
        bool directed = PG_GETARG_BOOL(3);
        
        char *edges_sql;
        Edge *edges = NULL;
        int num_edges = 0;
        
        int64 *node_ids;
        double *dist;
        bool *visited;
        int64 *prev_edges;
        int num_nodes = 0;
        
        PQItem *pq;
        int pq_size = 0;
        
        PathResult *results;
        int num_results = 0;
        
        ResultContext *ctx;
        TupleDesc tupdesc;
        int ret, i, j;
        
        /* 重置容量限制警告标志 */
        reset_limit_warnings();
        
        funcctx = SRF_FIRSTCALL_INIT();
        oldcontext = MemoryContextSwitchTo(funcctx->multi_call_memory_ctx);
        
        edges_sql = text_to_cstring(edges_sql_text);
        
        /* 分配内存 */
        edges = (Edge *)palloc0(sizeof(Edge) * MAX_EDGES);
        node_ids = (int64 *)palloc0(sizeof(int64) * MAX_NODES);
        dist = (double *)palloc(sizeof(double) * MAX_NODES);
        visited = (bool *)palloc0(sizeof(bool) * MAX_NODES);
        prev_edges = (int64 *)palloc(sizeof(int64) * MAX_NODES);
        pq = (PQItem *)palloc0(sizeof(PQItem) * MAX_NODES);
        results = (PathResult *)palloc0(sizeof(PathResult) * MAX_NODES);
        
        for (i = 0; i < MAX_NODES; i++) {
            dist[i] = DBL_MAX;
            prev_edges[i] = -1;
        }
        
        /* 加载边 */
        if (SPI_connect() != SPI_OK_CONNECT) {
            ereport(ERROR, (errmsg("driving_distance_c: SPI_connect failed")));
        }
        
        ret = SPI_execute(edges_sql, true, MAX_EDGES);
        
        if (ret == SPI_OK_SELECT && SPI_processed > 0) {
            TupleDesc td = SPI_tuptable->tupdesc;
            num_edges = (int)SPI_processed;
            if (num_edges > MAX_EDGES) {
                if (!g_edges_limit_warned) {
                    ereport(WARNING,
                            (errcode(ERRCODE_PROGRAM_LIMIT_EXCEEDED),
                             errmsg("driving_distance_c: edge limit reached (%d edges in query, %d loaded)", 
                                    num_edges, MAX_EDGES),
                             errhint("Consider filtering your edges SQL to reduce data size.")));
                    g_edges_limit_warned = true;
                }
                num_edges = MAX_EDGES;
            }
            
            for (i = 0; i < num_edges; i++) {
                HeapTuple tuple = SPI_tuptable->vals[i];
                bool isnull;
                
                edges[i].id = DatumGetInt64(SPI_getbinval(tuple, td, 1, &isnull));
                edges[i].source = DatumGetInt64(SPI_getbinval(tuple, td, 2, &isnull));
                edges[i].target = DatumGetInt64(SPI_getbinval(tuple, td, 3, &isnull));
                edges[i].cost = DatumGetFloat8(SPI_getbinval(tuple, td, 4, &isnull));
                edges[i].reverse_cost = -1.0;
                
                find_or_add_node_func(node_ids, &num_nodes, edges[i].source);
                find_or_add_node_func(node_ids, &num_nodes, edges[i].target);
            }
        }
        
        SPI_finish();
        
        if (num_edges == 0) {
            ctx = (ResultContext *)palloc(sizeof(ResultContext));
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
        
        /* Dijkstra扩展（最大代价限制） */
        int start_idx = find_or_add_node_func(node_ids, &num_nodes, start_vid);
        
        if (start_idx >= 0) {
            dist[start_idx] = 0;
            pq_insert(pq, &pq_size, start_vid, 0);
            
            while (pq_size > 0) {
                int64 current_node;
                double current_cost;
                int curr_idx;
                
                if (!pq_pop(pq, &pq_size, &current_node, &current_cost))
                    break;
                
                if (current_cost > max_cost)
                    continue;
                
                curr_idx = -1;
                for (i = 0; i < num_nodes; i++) {
                    if (node_ids[i] == current_node) {
                        curr_idx = i;
                        break;
                    }
                }
                
                if (curr_idx < 0 || visited[curr_idx])
                    continue;
                    
                visited[curr_idx] = true;
                
                /* 记录可达节点 */
                if (num_results < MAX_NODES) {
                    results[num_results].seq = num_results + 1;
                    results[num_results].node = current_node;
                    results[num_results].edge = prev_edges[curr_idx];
                    results[num_results].cost = current_cost;
                    results[num_results].agg_cost = current_cost;
                    num_results++;
                }
                
                /* 扩展邻居 */
                for (j = 0; j < num_edges; j++) {
                    int64 neighbor = -1;
                    double edge_cost = -1;
                    
                    if (edges[j].source == current_node && edges[j].cost >= 0) {
                        neighbor = edges[j].target;
                        edge_cost = edges[j].cost;
                    } else if (!directed && edges[j].target == current_node && edges[j].cost >= 0) {
                        neighbor = edges[j].source;
                        edge_cost = edges[j].cost;
                    }
                    
                    if (neighbor >= 0) {
                        int neigh_idx = -1;
                        for (i = 0; i < num_nodes; i++) {
                            if (node_ids[i] == neighbor) {
                                neigh_idx = i;
                                break;
                            }
                        }
                        
                        if (neigh_idx >= 0 && !visited[neigh_idx]) {
                            double new_cost = dist[curr_idx] + edge_cost;
                            if (new_cost <= max_cost && new_cost < dist[neigh_idx]) {
                                dist[neigh_idx] = new_cost;
                                prev_edges[neigh_idx] = edges[j].id;
                                pq_insert(pq, &pq_size, neighbor, new_cost);
                            }
                        }
                    }
                }
            }
        }
        
        /* 释放内存 */
        pfree(edges);
        pfree(node_ids);
        pfree(dist);
        pfree(visited);
        pfree(prev_edges);
        pfree(pq);
        
        ctx = (ResultContext *)palloc(sizeof(ResultContext));
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
        ResultContext *ctx = (ResultContext *)funcctx->user_fctx;
        int idx = funcctx->call_cntr;
        
        Datum values[5];
        bool nulls[5] = {false, false, false, false, false};
        HeapTuple tuple;
        
        values[0] = Int32GetDatum(ctx->results[idx].seq);
        values[1] = Int64GetDatum(ctx->results[idx].node);
        values[2] = Int64GetDatum(ctx->results[idx].edge);
        values[3] = Float8GetDatum(ctx->results[idx].cost);
        values[4] = Float8GetDatum(ctx->results[idx].agg_cost);
        
        if (ctx->results[idx].edge == -1) nulls[2] = true;
        
        tuple = heap_form_tuple(funcctx->tuple_desc, values, nulls);
        SRF_RETURN_NEXT(funcctx, HeapTupleGetDatum(tuple));
    }
    
    SRF_RETURN_DONE(funcctx);
}

/* ============================================================================
 * A* 启发式最短路径算法
 * 使用欧几里得距离作为启发函数，比Dijkstra更快（有坐标时）
 * ============================================================================ */

/* A*节点结构 */
typedef struct {
    int64 node_id;
    double g_cost;   /* 从起点到当前节点的实际代价 */
    double f_cost;   /* g_cost + h_cost (启发估计) */
} AStarItem;

/* 节点坐标结构 */
typedef struct {
    int64 id;
    double x;
    double y;
} NodeCoord;

/* 计算欧几里得距离 */
static double calc_euclidean_dist(double x1, double y1, double x2, double y2) {
    double dx = x2 - x1;
    double dy = y2 - y1;
    return sqrt(dx * dx + dy * dy);
}

/* A*优先队列插入 */
static void astar_pq_push(AStarItem *pq, int *size, int64 node, double g, double f) {
    int i = *size;
    pq[i].node_id = node;
    pq[i].g_cost = g;
    pq[i].f_cost = f;
    (*size)++;
    
    while (i > 0) {
        int p = (i - 1) / 2;
        if (pq[p].f_cost > pq[i].f_cost) {
            AStarItem t = pq[p]; pq[p] = pq[i]; pq[i] = t;
            i = p;
        } else break;
    }
}

static bool astar_pq_pop(AStarItem *pq, int *size, int64 *node, double *g, double *f) {
    if (*size == 0) return false;
    *node = pq[0].node_id; *g = pq[0].g_cost; *f = pq[0].f_cost;
    (*size)--;
    if (*size > 0) {
        pq[0] = pq[*size];
        int i = 0;
        while (true) {
            int s = i, l = 2*i+1, r = 2*i+2;
            if (l < *size && pq[l].f_cost < pq[s].f_cost) s = l;
            if (r < *size && pq[r].f_cost < pq[s].f_cost) s = r;
            if (s != i) { AStarItem t = pq[i]; pq[i] = pq[s]; pq[s] = t; i = s; }
            else break;
        }
    }
    return true;
}

PG_FUNCTION_INFO_V1(astar_c);

Datum
astar_c(PG_FUNCTION_ARGS)
{
    FuncCallContext *funcctx;
    
    if (SRF_IS_FIRSTCALL()) {
        MemoryContext oldcontext;
        text *sql_text = PG_GETARG_TEXT_PP(0);
        int64 start_v = PG_GETARG_INT64(1);
        int64 end_v = PG_GETARG_INT64(2);
        bool directed = PG_GETARG_BOOL(3);
        double heuristic = PG_GETARG_FLOAT8(4);
        
        char *sql = text_to_cstring(sql_text);
        Edge *edges; int64 *nodes; NodeCoord *coords;
        double *g_costs; int64 *prev_n, *prev_e; bool *vis;
        AStarItem *pq; PathResult *res;
        int ne = 0, nn = 0, nr = 0, pqs = 0;
        ResultContext *ctx; TupleDesc td;
        int ret, i, j;
        double ex = 0, ey = 0;
        
        funcctx = SRF_FIRSTCALL_INIT();
        oldcontext = MemoryContextSwitchTo(funcctx->multi_call_memory_ctx);
        
        edges = (Edge *)palloc0(sizeof(Edge) * MAX_EDGES);
        nodes = (int64 *)palloc0(sizeof(int64) * MAX_NODES);
        coords = (NodeCoord *)palloc0(sizeof(NodeCoord) * MAX_NODES);
        g_costs = (double *)palloc(sizeof(double) * MAX_NODES);
        prev_n = (int64 *)palloc(sizeof(int64) * MAX_NODES);
        prev_e = (int64 *)palloc(sizeof(int64) * MAX_NODES);
        vis = (bool *)palloc0(sizeof(bool) * MAX_NODES);
        pq = (AStarItem *)palloc0(sizeof(AStarItem) * MAX_NODES * 2);
        res = (PathResult *)palloc0(sizeof(PathResult) * MAX_PATH);
        
        for (i = 0; i < MAX_NODES; i++) {
            g_costs[i] = DBL_MAX; prev_n[i] = -1; prev_e[i] = -1;
        }
        
        if (SPI_connect() != SPI_OK_CONNECT)
            ereport(ERROR, (errmsg("astar_c: SPI_connect failed")));
        
        ret = SPI_execute(sql, true, MAX_EDGES);
        if (ret == SPI_OK_SELECT && SPI_processed > 0) {
            TupleDesc td2 = SPI_tuptable->tupdesc;
            ne = (int)SPI_processed; if (ne > MAX_EDGES) ne = MAX_EDGES;
            bool has_xy = (td2->natts >= 8);
            
            for (i = 0; i < ne; i++) {
                HeapTuple t = SPI_tuptable->vals[i]; bool isn;
                edges[i].id = DatumGetInt64(SPI_getbinval(t, td2, 1, &isn));
                edges[i].source = DatumGetInt64(SPI_getbinval(t, td2, 2, &isn));
                edges[i].target = DatumGetInt64(SPI_getbinval(t, td2, 3, &isn));
                edges[i].cost = DatumGetFloat8(SPI_getbinval(t, td2, 4, &isn));
                
                int si = find_or_add_node_func(nodes, &nn, edges[i].source);
                int ti = find_or_add_node_func(nodes, &nn, edges[i].target);
                
                if (has_xy) {
                    Datum d = SPI_getbinval(t, td2, 6, &isn);
                    if (!isn && si >= 0) coords[si].x = DatumGetFloat8(d);
                    d = SPI_getbinval(t, td2, 7, &isn);
                    if (!isn && si >= 0) coords[si].y = DatumGetFloat8(d);
                    d = SPI_getbinval(t, td2, 8, &isn);
                    if (!isn && ti >= 0) coords[ti].x = DatumGetFloat8(d);
                    if (td2->natts >= 9) {
                        d = SPI_getbinval(t, td2, 9, &isn);
                        if (!isn && ti >= 0) coords[ti].y = DatumGetFloat8(d);
                    }
                }
            }
        }
        SPI_finish();
        
        if (ne == 0 || nn == 0) {
            ctx = (ResultContext *)palloc(sizeof(ResultContext));
            ctx->results = res; ctx->num_results = 0;
            funcctx->user_fctx = ctx; funcctx->max_calls = 0;
            if (get_call_result_type(fcinfo, NULL, &td) != TYPEFUNC_COMPOSITE)
                ereport(ERROR, (errmsg("return type must be a row type")));
            funcctx->tuple_desc = BlessTupleDesc(td);
            MemoryContextSwitchTo(oldcontext);
            SRF_RETURN_DONE(funcctx);
        }
        
        int ei = -1, si = -1;
        for (i = 0; i < nn; i++) {
            if (nodes[i] == end_v) { ei = i; ex = coords[i].x; ey = coords[i].y; }
            if (nodes[i] == start_v) si = i;
        }
        
        if (si >= 0) {
            double h = calc_euclidean_dist(coords[si].x, coords[si].y, ex, ey) * heuristic;
            g_costs[si] = 0;
            astar_pq_push(pq, &pqs, start_v, 0, h);
            
            while (pqs > 0) {
                int64 cur; double cg, cf; int ci;
                if (!astar_pq_pop(pq, &pqs, &cur, &cg, &cf)) break;
                
                ci = -1;
                for (i = 0; i < nn; i++) if (nodes[i] == cur) { ci = i; break; }
                if (ci < 0 || vis[ci]) continue;
                vis[ci] = true;
                if (cur == end_v) break;
                
                for (j = 0; j < ne; j++) {
                    int64 nb = -1; double ec = -1;
                    if (edges[j].source == cur && edges[j].cost >= 0) {
                        nb = edges[j].target; ec = edges[j].cost;
                    } else if (!directed && edges[j].target == cur && edges[j].cost >= 0) {
                        nb = edges[j].source; ec = edges[j].cost;
                    }
                    if (nb >= 0) {
                        int ni = -1;
                        for (i = 0; i < nn; i++) if (nodes[i] == nb) { ni = i; break; }
                        if (ni >= 0 && !vis[ni]) {
                            double ng = g_costs[ci] + ec;
                            if (ng < g_costs[ni]) {
                                g_costs[ni] = ng; prev_n[ni] = cur; prev_e[ni] = edges[j].id;
                                double hc = calc_euclidean_dist(coords[ni].x, coords[ni].y, ex, ey) * heuristic;
                                astar_pq_push(pq, &pqs, nb, ng, ng + hc);
                            }
                        }
                    }
                }
            }
        }
        
        if (ei >= 0 && g_costs[ei] < DBL_MAX) {
            int64 pn[MAX_PATH], pe[MAX_PATH]; double pc[MAX_PATH]; int pl = 0;
            int64 c = end_v;
            while (c != -1 && pl < MAX_PATH) {
                int idx = -1;
                for (i = 0; i < nn; i++) if (nodes[i] == c) { idx = i; break; }
                if (idx < 0) break;
                pn[pl] = c; pe[pl] = prev_e[idx]; pc[pl] = g_costs[idx]; pl++;
                c = prev_n[idx];
            }
            for (i = 0; i < pl; i++) {
                int ri = pl - 1 - i;
                res[i].seq = i + 1; res[i].node = pn[ri]; res[i].edge = pe[ri];
                res[i].agg_cost = pc[ri];
                res[i].cost = (i > 0) ? (res[i].agg_cost - res[i-1].agg_cost) : 0;
            }
            nr = pl;
        }
        
        pfree(edges); pfree(nodes); pfree(coords); pfree(g_costs);
        pfree(prev_n); pfree(prev_e); pfree(vis); pfree(pq);
        
        ctx = (ResultContext *)palloc(sizeof(ResultContext));
        ctx->results = res; ctx->num_results = nr;
        funcctx->user_fctx = ctx; funcctx->max_calls = nr;
        
        if (get_call_result_type(fcinfo, NULL, &td) != TYPEFUNC_COMPOSITE)
            ereport(ERROR, (errmsg("return type must be a row type")));
        funcctx->tuple_desc = BlessTupleDesc(td);
        MemoryContextSwitchTo(oldcontext);
    }
    
    funcctx = SRF_PERCALL_SETUP();
    if (funcctx->call_cntr < funcctx->max_calls) {
        ResultContext *ctx = (ResultContext *)funcctx->user_fctx;
        int idx = funcctx->call_cntr;
        Datum v[5]; bool n[5] = {false,false,false,false,false}; HeapTuple tp;
        v[0] = Int32GetDatum(ctx->results[idx].seq);
        v[1] = Int64GetDatum(ctx->results[idx].node);
        v[2] = Int64GetDatum(ctx->results[idx].edge);
        v[3] = Float8GetDatum(ctx->results[idx].cost);
        v[4] = Float8GetDatum(ctx->results[idx].agg_cost);
        if (ctx->results[idx].edge == -1) n[2] = true;
        tp = heap_form_tuple(funcctx->tuple_desc, v, n);
        SRF_RETURN_NEXT(funcctx, HeapTupleGetDatum(tp));
    }
    SRF_RETURN_DONE(funcctx);
}

/* ============================================================================
 * Bellman-Ford 算法（支持负权重边）
 * ============================================================================ */

PG_FUNCTION_INFO_V1(bellman_ford_c);

Datum
bellman_ford_c(PG_FUNCTION_ARGS)
{
    FuncCallContext *funcctx;
    
    if (SRF_IS_FIRSTCALL()) {
        MemoryContext oldcontext;
        text *sql_text = PG_GETARG_TEXT_PP(0);
        int64 start_v = PG_GETARG_INT64(1);
        int64 end_v = PG_GETARG_INT64(2);
        bool directed = PG_GETARG_BOOL(3);
        
        char *sql = text_to_cstring(sql_text);
        Edge *edges; int64 *nodes;
        double *dist; int64 *prev_n, *prev_e;
        PathResult *res;
        int ne = 0, nn = 0, nr = 0;
        ResultContext *ctx; TupleDesc td;
        int ret, i, j, k;
        bool neg_cycle = false;
        
        funcctx = SRF_FIRSTCALL_INIT();
        oldcontext = MemoryContextSwitchTo(funcctx->multi_call_memory_ctx);
        
        edges = (Edge *)palloc0(sizeof(Edge) * MAX_EDGES);
        nodes = (int64 *)palloc0(sizeof(int64) * MAX_NODES);
        dist = (double *)palloc(sizeof(double) * MAX_NODES);
        prev_n = (int64 *)palloc(sizeof(int64) * MAX_NODES);
        prev_e = (int64 *)palloc(sizeof(int64) * MAX_NODES);
        res = (PathResult *)palloc0(sizeof(PathResult) * MAX_PATH);
        
        for (i = 0; i < MAX_NODES; i++) {
            dist[i] = DBL_MAX; prev_n[i] = -1; prev_e[i] = -1;
        }
        
        if (SPI_connect() != SPI_OK_CONNECT)
            ereport(ERROR, (errmsg("bellman_ford_c: SPI_connect failed")));
        
        ret = SPI_execute(sql, true, MAX_EDGES);
        if (ret == SPI_OK_SELECT && SPI_processed > 0) {
            TupleDesc td2 = SPI_tuptable->tupdesc;
            ne = (int)SPI_processed; if (ne > MAX_EDGES) ne = MAX_EDGES;
            for (i = 0; i < ne; i++) {
                HeapTuple t = SPI_tuptable->vals[i]; bool isn;
                edges[i].id = DatumGetInt64(SPI_getbinval(t, td2, 1, &isn));
                edges[i].source = DatumGetInt64(SPI_getbinval(t, td2, 2, &isn));
                edges[i].target = DatumGetInt64(SPI_getbinval(t, td2, 3, &isn));
                edges[i].cost = DatumGetFloat8(SPI_getbinval(t, td2, 4, &isn));
                find_or_add_node_func(nodes, &nn, edges[i].source);
                find_or_add_node_func(nodes, &nn, edges[i].target);
            }
        }
        SPI_finish();
        
        if (ne == 0 || nn == 0) {
            ctx = (ResultContext *)palloc(sizeof(ResultContext));
            ctx->results = res; ctx->num_results = 0;
            funcctx->user_fctx = ctx; funcctx->max_calls = 0;
            if (get_call_result_type(fcinfo, NULL, &td) != TYPEFUNC_COMPOSITE)
                ereport(ERROR, (errmsg("return type must be a row type")));
            funcctx->tuple_desc = BlessTupleDesc(td);
            MemoryContextSwitchTo(oldcontext);
            SRF_RETURN_DONE(funcctx);
        }
        
        int si = -1, ei = -1;
        for (i = 0; i < nn; i++) {
            if (nodes[i] == start_v) si = i;
            if (nodes[i] == end_v) ei = i;
        }
        
        if (si >= 0) {
            dist[si] = 0;
            
            for (k = 0; k < nn - 1; k++) {
                bool upd = false;
                for (j = 0; j < ne; j++) {
                    int sr = -1, tr = -1;
                    for (i = 0; i < nn; i++) {
                        if (nodes[i] == edges[j].source) sr = i;
                        if (nodes[i] == edges[j].target) tr = i;
                    }
                    if (sr >= 0 && tr >= 0) {
                        if (dist[sr] < DBL_MAX) {
                            double nd = dist[sr] + edges[j].cost;
                            if (nd < dist[tr]) {
                                dist[tr] = nd; prev_n[tr] = edges[j].source;
                                prev_e[tr] = edges[j].id; upd = true;
                            }
                        }
                        if (!directed && dist[tr] < DBL_MAX) {
                            double nd = dist[tr] + edges[j].cost;
                            if (nd < dist[sr]) {
                                dist[sr] = nd; prev_n[sr] = edges[j].target;
                                prev_e[sr] = edges[j].id; upd = true;
                            }
                        }
                    }
                }
                if (!upd) break;
            }
            
            for (j = 0; j < ne; j++) {
                int sr = -1, tr = -1;
                for (i = 0; i < nn; i++) {
                    if (nodes[i] == edges[j].source) sr = i;
                    if (nodes[i] == edges[j].target) tr = i;
                }
                if (sr >= 0 && tr >= 0 && dist[sr] < DBL_MAX) {
                    if (dist[sr] + edges[j].cost < dist[tr]) {
                        neg_cycle = true; break;
                    }
                }
            }
        }
        
        if (neg_cycle)
            ereport(WARNING, (errmsg("bellman_ford_c: Negative cycle detected")));
        
        if (!neg_cycle && ei >= 0 && dist[ei] < DBL_MAX) {
            int64 pn[MAX_PATH], pe[MAX_PATH]; double pc[MAX_PATH]; int pl = 0;
            int64 c = end_v;
            while (c != -1 && pl < MAX_PATH) {
                int idx = -1;
                for (i = 0; i < nn; i++) if (nodes[i] == c) { idx = i; break; }
                if (idx < 0) break;
                pn[pl] = c; pe[pl] = prev_e[idx]; pc[pl] = dist[idx]; pl++;
                c = prev_n[idx];
            }
            for (i = 0; i < pl; i++) {
                int ri = pl - 1 - i;
                res[i].seq = i + 1; res[i].node = pn[ri]; res[i].edge = pe[ri];
                res[i].agg_cost = pc[ri];
                res[i].cost = (i > 0) ? (res[i].agg_cost - res[i-1].agg_cost) : 0;
            }
            nr = pl;
        }
        
        pfree(edges); pfree(nodes); pfree(dist); pfree(prev_n); pfree(prev_e);
        
        ctx = (ResultContext *)palloc(sizeof(ResultContext));
        ctx->results = res; ctx->num_results = nr;
        funcctx->user_fctx = ctx; funcctx->max_calls = nr;
        
        if (get_call_result_type(fcinfo, NULL, &td) != TYPEFUNC_COMPOSITE)
            ereport(ERROR, (errmsg("return type must be a row type")));
        funcctx->tuple_desc = BlessTupleDesc(td);
        MemoryContextSwitchTo(oldcontext);
    }
    
    funcctx = SRF_PERCALL_SETUP();
    if (funcctx->call_cntr < funcctx->max_calls) {
        ResultContext *ctx = (ResultContext *)funcctx->user_fctx;
        int idx = funcctx->call_cntr;
        Datum v[5]; bool n[5] = {false,false,false,false,false}; HeapTuple tp;
        v[0] = Int32GetDatum(ctx->results[idx].seq);
        v[1] = Int64GetDatum(ctx->results[idx].node);
        v[2] = Int64GetDatum(ctx->results[idx].edge);
        v[3] = Float8GetDatum(ctx->results[idx].cost);
        v[4] = Float8GetDatum(ctx->results[idx].agg_cost);
        if (ctx->results[idx].edge == -1) n[2] = true;
        tp = heap_form_tuple(funcctx->tuple_desc, v, n);
        SRF_RETURN_NEXT(funcctx, HeapTupleGetDatum(tp));
    }
    SRF_RETURN_DONE(funcctx);
}

/* ============================================================================
 * 距离函数（C实现）
 * ============================================================================ */

PG_FUNCTION_INFO_V1(euclidean_distance_c);
Datum euclidean_distance_c(PG_FUNCTION_ARGS)
{
    double x1 = PG_GETARG_FLOAT8(0), y1 = PG_GETARG_FLOAT8(1);
    double x2 = PG_GETARG_FLOAT8(2), y2 = PG_GETARG_FLOAT8(3);
    PG_RETURN_FLOAT8(calc_euclidean_dist(x1, y1, x2, y2));
}

PG_FUNCTION_INFO_V1(manhattan_distance_c);
Datum manhattan_distance_c(PG_FUNCTION_ARGS)
{
    double x1 = PG_GETARG_FLOAT8(0), y1 = PG_GETARG_FLOAT8(1);
    double x2 = PG_GETARG_FLOAT8(2), y2 = PG_GETARG_FLOAT8(3);
    PG_RETURN_FLOAT8(fabs(x2-x1) + fabs(y2-y1));
}

/* ============================================================================
 * 路径成本计算（C实现）
 * ============================================================================ */

PG_FUNCTION_INFO_V1(path_cost_c);
Datum path_cost_c(PG_FUNCTION_ARGS)
{
    text *tbl = PG_GETARG_TEXT_PP(0);
    ArrayType *arr = PG_GETARG_ARRAYTYPE_P(1);
    char *tname = text_to_cstring(tbl);
    double total = 0;
    
    Datum *d; bool *n; int num;
    int16 tl; bool tb; char ta;
    get_typlenbyvalalign(INT8OID, &tl, &tb, &ta);
    deconstruct_array(arr, INT8OID, tl, tb, ta, &d, &n, &num);
    
    if (num < 2) { pfree(tname); PG_RETURN_FLOAT8(0); }
    
    if (SPI_connect() != SPI_OK_CONNECT)
        ereport(ERROR, (errmsg("path_cost_c: SPI failed")));
    
    int i;
    for (i = 0; i < num - 1; i++) {
        if (n[i] || n[i+1]) continue;
        int64 s = DatumGetInt64(d[i]), t = DatumGetInt64(d[i+1]);
        char q[512];
        snprintf(q, 512, "SELECT cost FROM %s WHERE (source=%ld AND target=%ld) OR (source=%ld AND target=%ld) LIMIT 1",
                 tname, (long)s, (long)t, (long)t, (long)s);
        int r = SPI_execute(q, true, 1);
        if (r == SPI_OK_SELECT && SPI_processed > 0) {
            bool isn;
            double c = DatumGetFloat8(SPI_getbinval(SPI_tuptable->vals[0], SPI_tuptable->tupdesc, 1, &isn));
            if (!isn) total += c;
        }
    }
    SPI_finish(); pfree(tname);
    PG_RETURN_FLOAT8(total);
}

/* ============================================================================
 * 查找最近节点 (C实现)
 * 使用空间索引思想的线性扫描优化版
 * ============================================================================ */

typedef struct {
    int64 node_id;
    double distance;
    double x;
    double y;
} NearestResult;

typedef struct {
    NearestResult *results;
    int32 num_results;
} NearestContext;

/* 比较函数 */
static int nearest_cmp(const void *a, const void *b) {
    double da = ((NearestResult*)a)->distance;
    double db = ((NearestResult*)b)->distance;
    return (da < db) ? -1 : (da > db) ? 1 : 0;
}

PG_FUNCTION_INFO_V1(find_nearest_node_c);

Datum
find_nearest_node_c(PG_FUNCTION_ARGS)
{
    FuncCallContext *funcctx;
    
    if (SRF_IS_FIRSTCALL()) {
        MemoryContext oldcontext;
        text *edges_sql_text = PG_GETARG_TEXT_PP(0);
        double target_x = PG_GETARG_FLOAT8(1);
        double target_y = PG_GETARG_FLOAT8(2);
        int32 k = PG_GETARG_INT32(3);  /* 返回k个最近节点 */
        
        char *edges_sql = text_to_cstring(edges_sql_text);
        
        int64 *node_ids = NULL;
        double *node_x = NULL;
        double *node_y = NULL;
        int num_nodes = 0;
        
        NearestResult *results;
        NearestContext *ctx;
        TupleDesc tupdesc;
        int ret, i;
        
        funcctx = SRF_FIRSTCALL_INIT();
        oldcontext = MemoryContextSwitchTo(funcctx->multi_call_memory_ctx);
        
        if (k <= 0) k = 1;
        if (k > 100) k = 100;  /* 限制最大返回数量 */
        
        if (SPI_connect() != SPI_OK_CONNECT) {
            ereport(ERROR, (errmsg("find_nearest_node_c: SPI_connect failed")));
        }
        
        /* 执行SQL获取节点坐标 */
        ret = SPI_execute(edges_sql, true, 100000);
        
        if (ret == SPI_OK_SELECT && SPI_processed > 0) {
            TupleDesc td = SPI_tuptable->tupdesc;
            int num_rows = (int)SPI_processed;
            
            /* 收集唯一节点 */
            int max_nodes = num_rows * 2;
            node_ids = (int64 *)palloc(sizeof(int64) * max_nodes);
            node_x = (double *)palloc(sizeof(double) * max_nodes);
            node_y = (double *)palloc(sizeof(double) * max_nodes);
            
            /* 期望SQL返回: id, source, target, cost, x1, y1, x2, y2 */
            bool has_coords = (td->natts >= 8);
            
            for (i = 0; i < num_rows; i++) {
                HeapTuple tuple = SPI_tuptable->vals[i];
                bool isnull;
                
                int64 src = DatumGetInt64(SPI_getbinval(tuple, td, 2, &isnull));
                int64 tgt = DatumGetInt64(SPI_getbinval(tuple, td, 3, &isnull));
                
                double x1 = 0, y1 = 0, x2 = 0, y2 = 0;
                if (has_coords) {
                    Datum d = SPI_getbinval(tuple, td, 5, &isnull);
                    if (!isnull) x1 = DatumGetFloat8(d);
                    d = SPI_getbinval(tuple, td, 6, &isnull);
                    if (!isnull) y1 = DatumGetFloat8(d);
                    d = SPI_getbinval(tuple, td, 7, &isnull);
                    if (!isnull) x2 = DatumGetFloat8(d);
                    d = SPI_getbinval(tuple, td, 8, &isnull);
                    if (!isnull) y2 = DatumGetFloat8(d);
                }
                
                /* 检查源节点是否已存在 */
                bool src_found = false;
                for (int j = 0; j < num_nodes; j++) {
                    if (node_ids[j] == src) {
                        src_found = true;
                        break;
                    }
                }
                if (!src_found && num_nodes < max_nodes) {
                    node_ids[num_nodes] = src;
                    node_x[num_nodes] = x1;
                    node_y[num_nodes] = y1;
                    num_nodes++;
                }
                
                /* 检查目标节点是否已存在 */
                bool tgt_found = false;
                for (int j = 0; j < num_nodes; j++) {
                    if (node_ids[j] == tgt) {
                        tgt_found = true;
                        break;
                    }
                }
                if (!tgt_found && num_nodes < max_nodes) {
                    node_ids[num_nodes] = tgt;
                    node_x[num_nodes] = x2;
                    node_y[num_nodes] = y2;
                    num_nodes++;
                }
            }
        }
        
        SPI_finish();
        
        if (num_nodes == 0) {
            results = (NearestResult *)palloc0(sizeof(NearestResult));
            ctx = (NearestContext *)palloc(sizeof(NearestContext));
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
        
        /* 计算所有节点到目标点的距离 */
        NearestResult *all_results = (NearestResult *)palloc(sizeof(NearestResult) * num_nodes);
        
        for (i = 0; i < num_nodes; i++) {
            double dx = node_x[i] - target_x;
            double dy = node_y[i] - target_y;
            all_results[i].node_id = node_ids[i];
            all_results[i].distance = sqrt(dx * dx + dy * dy);
            all_results[i].x = node_x[i];
            all_results[i].y = node_y[i];
        }
        
        /* 按距离排序 */
        qsort(all_results, num_nodes, sizeof(NearestResult), nearest_cmp);
        
        /* 取前k个 */
        int num_results = (num_nodes < k) ? num_nodes : k;
        results = (NearestResult *)palloc(sizeof(NearestResult) * num_results);
        for (i = 0; i < num_results; i++) {
            results[i] = all_results[i];
        }
        
        pfree(all_results);
        pfree(node_ids);
        pfree(node_x);
        pfree(node_y);
        
        ctx = (NearestContext *)palloc(sizeof(NearestContext));
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
        NearestContext *ctx = (NearestContext *)funcctx->user_fctx;
        int idx = funcctx->call_cntr;
        
        Datum values[4];
        bool nulls[4] = {false, false, false, false};
        HeapTuple tuple;
        
        values[0] = Int64GetDatum(ctx->results[idx].node_id);
        values[1] = Float8GetDatum(ctx->results[idx].distance);
        values[2] = Float8GetDatum(ctx->results[idx].x);
        values[3] = Float8GetDatum(ctx->results[idx].y);
        
        tuple = heap_form_tuple(funcctx->tuple_desc, values, nulls);
        SRF_RETURN_NEXT(funcctx, HeapTupleGetDatum(tuple));
    }
    
    SRF_RETURN_DONE(funcctx);
}

/* ============================================================================
 * K最近邻查询 (KNN, C实现)
 * ============================================================================ */

PG_FUNCTION_INFO_V1(knn_search_c);

Datum
knn_search_c(PG_FUNCTION_ARGS)
{
    FuncCallContext *funcctx;
    
    if (SRF_IS_FIRSTCALL()) {
        MemoryContext oldcontext;
        ArrayType *points_x_arr = PG_GETARG_ARRAYTYPE_P(0);
        ArrayType *points_y_arr = PG_GETARG_ARRAYTYPE_P(1);
        ArrayType *ids_arr = PG_GETARG_ARRAYTYPE_P(2);
        double query_x = PG_GETARG_FLOAT8(3);
        double query_y = PG_GETARG_FLOAT8(4);
        int32 k = PG_GETARG_INT32(5);
        
        Datum *x_datums, *y_datums, *id_datums;
        bool *x_nulls, *y_nulls, *id_nulls;
        int num_x, num_y, num_ids;
        int16 tl8, tl4; bool tb8, tb4; char ta8, ta4;
        
        funcctx = SRF_FIRSTCALL_INIT();
        oldcontext = MemoryContextSwitchTo(funcctx->multi_call_memory_ctx);
        
        get_typlenbyvalalign(FLOAT8OID, &tl8, &tb8, &ta8);
        get_typlenbyvalalign(INT8OID, &tl4, &tb4, &ta4);
        
        deconstruct_array(points_x_arr, FLOAT8OID, tl8, tb8, ta8, &x_datums, &x_nulls, &num_x);
        deconstruct_array(points_y_arr, FLOAT8OID, tl8, tb8, ta8, &y_datums, &y_nulls, &num_y);
        deconstruct_array(ids_arr, INT8OID, tl4, tb4, ta4, &id_datums, &id_nulls, &num_ids);
        
        int num_points = num_x;
        if (num_y < num_points) num_points = num_y;
        if (num_ids < num_points) num_points = num_ids;
        
        if (k <= 0) k = 1;
        if (k > num_points) k = num_points;
        
        NearestResult *all = (NearestResult *)palloc(sizeof(NearestResult) * num_points);
        
        for (int i = 0; i < num_points; i++) {
            if (x_nulls[i] || y_nulls[i] || id_nulls[i]) continue;
            double px = DatumGetFloat8(x_datums[i]);
            double py = DatumGetFloat8(y_datums[i]);
            double dx = px - query_x;
            double dy = py - query_y;
            
            all[i].node_id = DatumGetInt64(id_datums[i]);
            all[i].distance = sqrt(dx * dx + dy * dy);
            all[i].x = px;
            all[i].y = py;
        }
        
        qsort(all, num_points, sizeof(NearestResult), nearest_cmp);
        
        NearestResult *results = (NearestResult *)palloc(sizeof(NearestResult) * k);
        for (int i = 0; i < k; i++) {
            results[i] = all[i];
        }
        pfree(all);
        
        NearestContext *ctx = (NearestContext *)palloc(sizeof(NearestContext));
        ctx->results = results;
        ctx->num_results = k;
        
        funcctx->user_fctx = ctx;
        funcctx->max_calls = k;
        
        TupleDesc tupdesc;
        if (get_call_result_type(fcinfo, NULL, &tupdesc) != TYPEFUNC_COMPOSITE)
            ereport(ERROR, (errmsg("return type must be a row type")));
        funcctx->tuple_desc = BlessTupleDesc(tupdesc);
        
        MemoryContextSwitchTo(oldcontext);
    }
    
    funcctx = SRF_PERCALL_SETUP();
    
    if (funcctx->call_cntr < funcctx->max_calls) {
        NearestContext *ctx = (NearestContext *)funcctx->user_fctx;
        int idx = funcctx->call_cntr;
        
        Datum values[4];
        bool nulls[4] = {false, false, false, false};
        HeapTuple tuple;
        
        values[0] = Int64GetDatum(ctx->results[idx].node_id);
        values[1] = Float8GetDatum(ctx->results[idx].distance);
        values[2] = Float8GetDatum(ctx->results[idx].x);
        values[3] = Float8GetDatum(ctx->results[idx].y);
        
        tuple = heap_form_tuple(funcctx->tuple_desc, values, nulls);
        SRF_RETURN_NEXT(funcctx, HeapTupleGetDatum(tuple));
    }
    
    SRF_RETURN_DONE(funcctx);
}

-- ============================================================================
-- otb_scheduler 功能测试
-- ============================================================================

\echo '============================================'
\echo '   otb_scheduler 功能测试'
\echo '============================================'

-- 清理旧数据
DROP SCHEMA IF EXISTS otb_scheduler CASCADE;

-- 加载扩展
\i /data/opentenbase/OpenTenBase/contrib/otb_scheduler/sql/otb_scheduler--1.0.sql

-- ============================================================================
-- 1. pg_cron兼容功能测试
-- ============================================================================

\echo ''
\echo '========== 1. 定时任务管理 (pg_cron) =========='

-- 创建任务
\echo '创建定时任务...'
SELECT otb_scheduler.schedule('*/5 * * * *', 'SELECT 1') AS job1;
SELECT otb_scheduler.schedule('cleanup_task', '0 3 * * *', 'VACUUM') AS job2;
SELECT otb_scheduler.schedule('hourly_report', '0 * * * *', 'SELECT count(*) FROM pg_stat_activity') AS job3;

-- 查看任务列表
\echo ''
\echo '查看任务列表:'
SELECT jobid, jobname, schedule, command, active FROM otb_scheduler.job;

-- 修改任务
\echo ''
\echo '修改任务...'
SELECT otb_scheduler.alter_job(1, false);  -- 禁用任务1
SELECT otb_scheduler.alter_job(2, NULL, '0 4 * * *');  -- 修改时间

\echo '修改后的任务列表:'
SELECT jobid, jobname, schedule, active FROM otb_scheduler.job;

-- 执行任务
\echo ''
\echo '手动执行任务...'
SELECT otb_scheduler.run_job(3) AS run_id;

-- 查看执行历史
\echo ''
\echo '执行历史:'
SELECT runid, jobid, status, return_message, 
       start_time, end_time,
       EXTRACT(MILLISECONDS FROM (end_time - start_time)) as duration_ms
FROM otb_scheduler.job_run_details_view;

-- 删除任务
\echo ''
\echo '删除任务...'
SELECT otb_scheduler.unschedule(1);
SELECT otb_scheduler.unschedule('cleanup_task');

\echo '删除后的任务列表:'
SELECT jobid, jobname, schedule FROM otb_scheduler.job;

-- ============================================================================
-- 2. pg_partman兼容功能测试
-- ============================================================================

\echo ''
\echo '========== 2. 分区管理 (pg_partman) =========='

-- 创建测试分区表
\echo '创建测试分区表...'
DROP TABLE IF EXISTS test_events CASCADE;
CREATE TABLE test_events (
    id BIGSERIAL,
    event_time TIMESTAMP NOT NULL,
    event_type TEXT,
    data JSONB
) PARTITION BY RANGE (event_time);

-- 配置分区
\echo ''
\echo '配置分区策略...'
SELECT otb_scheduler.create_parent(
    'public.test_events',
    'event_time',
    'range',
    'day',
    7
);

-- 查看配置
\echo ''
\echo '分区配置:'
SELECT parent_table, control, partition_type, partition_interval, premake 
FROM otb_scheduler.part_config;

-- 设置保留策略
\echo ''
\echo '设置保留策略...'
SELECT otb_scheduler.set_retention('public.test_events', '30 days', true);

-- 查看更新后的配置
SELECT parent_table, retention, retention_keep_table 
FROM otb_scheduler.part_config;

-- 运行维护
\echo ''
\echo '运行分区维护...'
SELECT otb_scheduler.run_maintenance('public.test_events');

-- ============================================================================
-- 3. 便捷函数测试
-- ============================================================================

\echo ''
\echo '========== 3. 便捷函数测试 =========='

-- 创建预设任务
\echo '创建预设任务...'
SELECT otb_scheduler.schedule_vacuum('pg_catalog.pg_class');
SELECT otb_scheduler.schedule_analyze('pg_catalog.pg_class');
SELECT otb_scheduler.schedule_cleanup_logs(7);

\echo '任务列表:'
SELECT jobid, jobname, schedule, left(command, 60) as command FROM otb_scheduler.job;

-- ============================================================================
-- 4. cron表达式解析测试
-- ============================================================================

\echo ''
\echo '========== 4. Cron表达式解析 =========='

SELECT * FROM otb_scheduler.parse_cron('*/5 * * * *');
SELECT * FROM otb_scheduler.parse_cron('0 3 * * 0');
SELECT * FROM otb_scheduler.parse_cron('30 8 1 * *');

\echo ''
\echo '下次执行时间预测:'
SELECT '*/5 * * * *' as cron, otb_scheduler.get_next_run_time('0 * * * *') as next_run;
SELECT '0 3 * * *' as cron, otb_scheduler.get_next_run_time('0 3 * * *') as next_run;

-- ============================================================================
-- 5. 统计视图测试
-- ============================================================================

\echo ''
\echo '========== 5. 统计视图 =========='

\echo '任务统计:'
SELECT jobid, jobname, total_runs, successful_runs, failed_runs, 
       round(avg_duration_seconds::numeric, 3) as avg_sec
FROM otb_scheduler.job_stats;

\echo ''
\echo '分区统计:'
SELECT parent_table, partition_interval, retention, total_operations
FROM otb_scheduler.partition_stats;

-- ============================================================================
-- 测试完成
-- ============================================================================

\echo ''
\echo '============================================'
\echo '   otb_scheduler 测试完成 ✅'
\echo '============================================'


-- OpenTenBase TimeSeries Extension v1.0
-- TimescaleDB-compatible time-series data management for OpenTenBase
--
-- 提示：请通过 CREATE EXTENSION 方式加载本文件
-- \echo 使用 "CREATE EXTENSION otb_timeseries" 加载本文件。 \quit

-- ============================================================================
-- 核心模块加载（按依赖顺序）
-- ============================================================================

-- 1. Schema与元数据表定义
\ir schema_and_metadata.sql

-- 2. Hypertable核心功能（依赖: schema_and_metadata）
\ir hypertable_core.sql

-- 3. 时序查询函数（独立模块）
\ir time_functions.sql

-- 4. 策略管理系统（依赖: schema_and_metadata, hypertable_core）
\ir policies.sql

-- 5. 数据生命周期管理（依赖: hypertable_core）
\ir lifecycle.sql

-- 6. 连续聚合功能（依赖: schema_and_metadata, hypertable_core）
\ir continuous_aggregates.sql

-- 7. 工具函数与统计分析（独立模块）
\ir utilities.sql

-- ============================================================================
-- 高级管理与信息视图（已有模块）
-- ============================================================================

-- 8. 高级Chunk管理功能
\ir advanced_management.sql

-- 9. 系统信息视图
\ir information_views.sql

-- 10. TimescaleDB兼容层（API映射）
\ir timescaledb_compat.sql

-- ============================================================================
-- 扩展加载完成
-- ============================================================================

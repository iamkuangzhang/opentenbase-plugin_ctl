# OpenTenBase TimeSeries C Extension
# 高性能时序函数（TimescaleDB核心兼容功能）
# 注意：analytics（移动平均、异常检测）已独立为otb_analytics插件

MODULE_big = otb_timeseries_c
OBJS = otb_timeseries_c.o src/compression.o src/continuous_agg.o src/hyperfunctions.o

EXTENSION = otb_timeseries_c
DATA = sql/otb_timeseries_c--1.0.sql

# PostgreSQL build system integration
PG_CONFIG = pg_config
PGXS := $(shell $(PG_CONFIG) --pgxs)
include $(PGXS)

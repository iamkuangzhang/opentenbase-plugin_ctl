# OpenTenBase TimeSeries Core Extension (SQL)
# 核心时序表管理功能

EXTENSION = otb_timeseries
DATA = sql/otb_timeseries--1.0.sql \
       sql/schema_and_metadata.sql \
       sql/hypertable_core.sql \
       sql/time_functions.sql \
       sql/policies.sql \
       sql/lifecycle.sql \
       sql/continuous_aggregates.sql \
       sql/utilities.sql \
       sql/advanced_management.sql \
       sql/information_views.sql \
       sql/timescaledb_compat.sql

# PostgreSQL build system integration
PG_CONFIG = pg_config
PGXS := $(shell $(PG_CONFIG) --pgxs)
include $(PGXS)


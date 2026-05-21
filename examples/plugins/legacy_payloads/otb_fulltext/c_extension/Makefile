# otb_fulltext_c Makefile
# 高性能全文检索C扩展

MODULE_big = otb_fulltext_c
OBJS = otb_fulltext_c.o

EXTENSION = otb_fulltext_c
DATA = sql/otb_fulltext_c--1.0.sql

PG_CONFIG = /data/opentenbase/install/opentenbase_bin_v2.0/bin/pg_config
PGXS := $(shell $(PG_CONFIG) --pgxs)
include $(PGXS)


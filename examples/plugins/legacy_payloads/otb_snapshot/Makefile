# Makefile for otb_snapshot extension

EXTENSION = otb_snapshot
EXTVERSION = 1.0

DATA = sql/otb_snapshot--$(EXTVERSION).sql

PG_CONFIG = pg_config
PGXS := $(shell $(PG_CONFIG) --pgxs)
include $(PGXS)


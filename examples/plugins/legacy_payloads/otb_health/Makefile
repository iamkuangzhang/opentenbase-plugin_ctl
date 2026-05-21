# Makefile for otb_health extension

EXTENSION = otb_health
EXTVERSION = 1.0

DATA = sql/otb_health--$(EXTVERSION).sql

PG_CONFIG = pg_config
PGXS := $(shell $(PG_CONFIG) --pgxs)
include $(PGXS)


# Makefile for otb_analytics extension

EXTENSION = otb_analytics
EXTVERSION = 1.0

MODULE_big = otb_analytics
OBJS = src/otb_analytics.o

DATA = sql/otb_analytics--$(EXTVERSION).sql
PG_CPPFLAGS = -I$(libpq_srcdir)
SHLIB_LINK = $(libpq)

PG_CONFIG = pg_config
PGXS := $(shell $(PG_CONFIG) --pgxs)
include $(PGXS)


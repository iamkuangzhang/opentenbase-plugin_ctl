# Makefile for otb_routing_c

MODULE_big = otb_routing_c
OBJS = otb_routing_c.o

EXTENSION = otb_routing_c
DATA = sql/otb_routing_c--1.0.sql

PG_CFLAGS = -lm

PG_CONFIG = pg_config
PGXS := $(shell $(PG_CONFIG) --pgxs)
include $(PGXS)


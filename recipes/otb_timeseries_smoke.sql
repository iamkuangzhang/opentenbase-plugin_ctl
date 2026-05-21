-- DataNexus platform smoke verify for otb_timeseries
-- Lightweight checks only: version, hypertable creation, time_bucket, first/last.

SET client_min_messages TO WARNING;

SELECT otb_ts.version();

DROP TABLE IF EXISTS public.__DNX_TABLE__ CASCADE;

CREATE TABLE public.__DNX_TABLE__ (
    ts timestamptz NOT NULL,
    label text NOT NULL
) DISTRIBUTE BY REPLICATION;

SELECT * FROM otb_ts.create_hypertable(
    'public.__DNX_TABLE__'::regclass,
    'ts',
    '1 day'::interval
);

INSERT INTO public.__DNX_TABLE__ VALUES
    (TIMESTAMPTZ '2026-05-20 00:00:00+00', 'a'),
    (TIMESTAMPTZ '2026-05-20 00:30:00+00', 'b'),
    (TIMESTAMPTZ '2026-05-20 01:00:00+00', 'c');

SELECT
    to_char(time_bucket('1 hour', ts), 'YYYY-MM-DD HH24:MI:SS') AS bucket,
    count(*) AS cnt
FROM public.__DNX_TABLE__
GROUP BY 1
ORDER BY 1;

SELECT
    otb_ts.first(label, ts) AS first_label,
    otb_ts.last(label, ts) AS last_label
FROM public.__DNX_TABLE__;

DROP TABLE IF EXISTS public.__DNX_TABLE__ CASCADE;

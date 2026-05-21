CREATE SCHEMA IF NOT EXISTS dnx_smoke_plugin;

CREATE TABLE IF NOT EXISTS dnx_smoke_plugin.sample_data (
    id integer PRIMARY KEY,
    note text NOT NULL
);

INSERT INTO dnx_smoke_plugin.sample_data (id, note)
SELECT 1, 'installed'
WHERE NOT EXISTS (
    SELECT 1 FROM dnx_smoke_plugin.sample_data WHERE id = 1
);

CREATE OR REPLACE FUNCTION dnx_smoke_plugin.version()
RETURNS text
LANGUAGE SQL
IMMUTABLE
AS $$
    SELECT '0.1.0'::text;
$$;

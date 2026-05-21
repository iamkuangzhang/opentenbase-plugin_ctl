# otb_timeseries Chunk Distribution Warning

## Status

Open issue. The platform records command output, but this warning should be
handled as an `otb_timeseries` plugin and OpenTenBase distribution behavior
issue, not hidden inside the platform layer.

## Reproduction

Run the M0 smoke verification:

```powershell
cd "DataNexus for OpenTenBase/platform"
$env:PYTHONPATH = 'src'
python -m datanexus verify otb_timeseries
```

The smoke recipe creates a temporary table, calls `otb_ts.create_hypertable`,
inserts sample rows, checks `time_bucket`, checks `otb_ts.first/last`, and drops
the table.

Recipe:

```text
platform/recipes/otb_timeseries_smoke.sql
```

## Warning

Observed warning pattern:

```text
chunk <temporary_chunk_table>: table "<chunk>" is using distribution type S,
but the parent table "<parent>" is using distribution type R
```

## Current Impact

- The smoke verification exits successfully.
- The warning is visible in command output and stored in action metadata as stderr summary.
- M0 does not treat this warning as a platform failure.

## Working Hypothesis

`otb_timeseries` creates chunk tables whose distribution strategy differs from
the parent table strategy selected by OpenTenBase. The platform can surface the
warning, but the root fix likely belongs in plugin DDL/chunk creation logic or
in the smoke table distribution setup.

## Follow-up Direction

- Confirm whether chunk tables should inherit parent distribution type.
- Check the plugin implementation around hypertable/chunk DDL generation.
- Decide whether the smoke recipe should create the parent table with a
distribution strategy that matches expected chunk behavior.
- Add a targeted regression test once the intended distribution behavior is
defined.

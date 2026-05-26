# M1 Status

## Completed

M1 keeps the platform CLI-first and OpenTenBase-only. It does not introduce Web
UI, plugin marketplace behavior, multi-database adaptation, or bulk deployment.

Implemented capabilities:

- `list` and `inspect` load manifests from:
  - `catalog/plugins/*.yml`
  - `examples/plugins/*/manifest.yml`
- `doctor` checks local OpenTenBase readiness and registered CN/DN reachability.
- `cluster status` performs read-only local Docker/OpenTenBase liveness checks.
- `deploy`, `verify`, and `rollback` return `ActionResult`.
- `state` persists action results with timing, return code, stage, runtime, and
  stdout/stderr summaries.
- `report` shows latest state per `(plugin_id, action)`.
- `report --json` emits machine-readable latest action state.
- `rollback` defaults to dry-run and requires `--execute` for SQL execution.
- `verify --removed` verifies object absence through a manifest `removed_probe`.

## Lifecycle Fixture

`examples/plugins/dnx_smoke_plugin` is a platform lifecycle verification plugin,
not a business plugin.

It exists to prove the Plugin Manager lifecycle chain safely:

- uninstalled deploy path
- payload copy into container
- install SQL execution
- verify SQL execution
- rollback dry-run
- rollback execute
- removed verification
- state/report visibility

## Verified Commands

The M1 local verification sequence is:

```powershell
$env:PYTHONPATH = 'src'
python -m plugin_ctl cluster status
python -m plugin_ctl deploy dnx_smoke_plugin
python -m plugin_ctl verify dnx_smoke_plugin
python -m plugin_ctl rollback dnx_smoke_plugin --execute
python -m plugin_ctl verify dnx_smoke_plugin --removed
python -m plugin_ctl deploy otb_timeseries
python -m plugin_ctl verify otb_timeseries
python -m plugin_ctl report
python -m plugin_ctl report --json
```

## Limitations

- `otb_timeseries` clean first-install proof is still pending. The current
  working database exercises `already deployed: 1.0.0`.
- `otb_timeseries` rollback remains unsupported and intentionally non-destructive.
- `cluster start` is not implemented.
- Node consistency governance is not implemented.
- Version upgrade/downgrade workflows are not implemented.
- The `otb_timeseries` chunk distribution warning remains an open issue.

## M2 Readiness

M1 can be considered complete for the platform lifecycle plumbing once the
current regression sequence remains green. Entering M2 should wait until the
team accepts that real clean deploy proof for `otb_timeseries` requires either a
temporary OpenTenBase topology or a verified isolated database path.

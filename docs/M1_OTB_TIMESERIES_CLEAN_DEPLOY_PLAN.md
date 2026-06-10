# M1 otb_timeseries Clean Deploy Plan

## Current Constraint

The current verified Docker cluster already has `otb_timeseries` installed in
the working `postgres` database. Running:

```powershell
plugin_ctl deploy otb_timeseries
```

therefore exercises the safe installed-probe path:

```text
already deployed: 1.0.0
```

M1 must not prove clean deploy by dropping the existing `otb_timeseries` schema
or functions in the working database.

## Preferred Verification Path

Use a clean temporary OpenTenBase environment when cluster bootstrap is
repeatable:

1. Start a fresh OpenTenBase Docker topology.
2. Confirm `plugin_ctl cluster status` is green.
3. Confirm `SELECT otb_ts.version();` fails before deploy.
4. Run `plugin_ctl deploy otb_timeseries`.
5. Run `plugin_ctl verify otb_timeseries`.
6. Preserve logs and `plugin_ctl report --json`.
7. Tear down the temporary environment.

This is the strongest proof because it avoids residual objects from the current
working database.

## Lower-Cost Alternative: New Database

If a fresh topology is too expensive, create a new test database in the current
cluster and run the deploy target against that database only after confirming
the plugin install is database-local.

Required checks before using this path:

- Confirm whether `otb_timeseries` install SQL creates only database-local
  schemas/functions.
- Confirm whether OpenTenBase extension/function visibility is database-scoped
  in this deployment.
- Confirm `installed_probe` fails in the new database before deploy.
- Use a separate state root or annotate report metadata so this test is not
  confused with the working `postgres` database.

## Current M1 Evidence

M1 now proves the platform deploy chain through `pluginctl_smoke_plugin`:

- uninstalled deploy path
- payload copy
- `psql -f` install execution
- verify
- rollback dry-run
- rollback execute
- removed verification
- state/report persistence

This validates the Plugin Manager lifecycle machinery. It does not yet prove
first install of the real `otb_timeseries` payload.

## Decision

Do not run destructive cleanup against the current `otb_timeseries` install.
The remaining clean deploy proof should be done with a temporary OpenTenBase
topology or a verified isolated database path.

# DataNexus Platform

This directory is the standalone platform layer for DataNexus.

## Scope

- CLI first
- OpenTenBase only
- Separate from plugin payloads under `../src`

## Plugin Layout

- `catalog/plugins/` contains manifests for existing plugin payloads.
- `examples/plugins/` contains controlled sample plugins used to verify the platform lifecycle.
- `../src/otb_*` directories are existing OpenTenBase plugin payloads, not platform core code.

`examples/plugins/dnx_smoke_plugin` is the M1 safe lifecycle fixture. It can be
deployed, verified, rolled back, and checked for removal without modifying
`otb_timeseries`.

## Current stage

M0 is frozen in [docs/M0_BASELINE.md](docs/M0_BASELINE.md). Keep those commands working
when extending M1 behavior.

M1 status is tracked in [docs/M1_STATUS.md](docs/M1_STATUS.md).
`otb_timeseries` clean deploy constraints are documented in
[docs/M1_OTB_TIMESERIES_CLEAN_DEPLOY_PLAN.md](docs/M1_OTB_TIMESERIES_CLEAN_DEPLOY_PLAN.md).
M2 plugin-centered governance is tracked in
[docs/M2_PLUGIN_GOVERNANCE.md](docs/M2_PLUGIN_GOVERNANCE.md) and
[docs/M2_GOVERNANCE_FLOW.md](docs/M2_GOVERNANCE_FLOW.md).

- `list`
- `inspect`
- `doctor`
- `verify` for the lightweight `otb_timeseries` smoke path
- `deploy` for SQL payload copy and psql execution
- `state` and `report` for local state tracking
- `rollback` with manifest-driven safety checks

## Run locally

```bash
cd "DataNexus for OpenTenBase/platform"
set PYTHONPATH=src
python -m datanexus list
python -m datanexus doctor
python -m datanexus cluster status
python -m datanexus plugin check otb_timeseries
python -m datanexus plugin lint otb_timeseries
python -m datanexus plugin plan otb_timeseries
python -m datanexus plugin precheck otb_timeseries
python -m datanexus plugin diagnose otb_timeseries
python -m datanexus plugin status otb_timeseries
python -m datanexus plugin status otb_timeseries --lang en
python -m datanexus plugin status otb_timeseries --lang both
python -m datanexus plugins status
python -m datanexus plugins status --json
python -m datanexus deploy otb_timeseries
python -m datanexus verify otb_timeseries
python -m datanexus rollback otb_timeseries
python -m datanexus state otb_timeseries
python -m datanexus report
```

Smoke plugin lifecycle:

```bash
python -m datanexus deploy dnx_smoke_plugin
python -m datanexus verify dnx_smoke_plugin
python -m datanexus rollback dnx_smoke_plugin
python -m datanexus rollback dnx_smoke_plugin --execute
python -m datanexus verify dnx_smoke_plugin --removed
```

Rollback is intentionally conservative. It only executes when a plugin manifest
declares `rollback_sql`; otherwise it records a failed rollback attempt instead
of dropping database objects implicitly.

When `rollback_sql` exists, `rollback` defaults to a dry-run plan. Use
`--execute` to apply the script.

`plugin check` and `plugins status` are plugin governance commands. They may use
OpenTenBase distributed metadata, but their output is plugin-centered and should
not be treated as a general cluster inspection workflow.

`plugin lint` checks only the manifest and package files. It does not connect to
OpenTenBase. `plugin plan` is non-executing: it explains the deploy, verify,
rollback, and removed-verification paths. It may run `installed_probe` to decide
whether deploy would skip, but it must not run install, verify, rollback, or file
copy operations.

`plugin precheck` is the next gate before deploy. It is still read-only from the
plugin lifecycle perspective: it validates package files, OpenTenBase
connectivity, version visibility, declared target roles, registered role nodes,
the plugin `installed_probe`, and whether the runtime can use `/tmp` as a remote
staging parent. It does not copy payloads and does not run lifecycle SQL.

## Language

Human-oriented plugin governance commands default to Chinese output. Use
`--lang en` for English or `--lang both` for bilingual labels. JSON output keeps
stable English keys for automation.

## State Time Fields

`ActionResult.started_at` and `ActionResult.finished_at` describe when an action
ran. `StateRecord.timestamp` describes when that result was written to the local
state file. Reports show the state write time as `timestamp`; action timing is
kept in metadata as `started_at`, `finished_at`, and `duration_ms`.

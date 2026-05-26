# M0 Baseline

This file freezes the current runnable baseline for the DataNexus OpenTenBase
platform layer. M1 work should keep these commands and expectations intact.

## Positioning

DataNexus is a CLI-first lifecycle governance platform for OpenTenBase plugins.
It is not a general plugin repository and it is not web-first at this stage.

M0 focuses on one closed loop for the `otb_timeseries` sample plugin:

- discover the plugin manifest
- inspect plugin metadata
- diagnose the local OpenTenBase Docker runtime
- deploy or skip deploy when the plugin is already installed
- run a lightweight smoke verification
- persist local action state
- report the latest state per plugin action
- reject unsupported rollback safely

## Implemented Commands

- `list`
- `inspect`
- `doctor`
- `deploy`
- `verify`
- `state`
- `report`
- `rollback`

## Verified Local Environment

The verified OpenTenBase runtime is the local Docker deployment:

- `opentenbaseCN`
- `opentenbaseDN1`
- `opentenbaseDN2`

The CLI connects through DN1 coordinator access:

- host: `127.0.0.1`
- port: `30004`
- user: `opentenbase`
- database: `postgres`

`doctor` has confirmed 4 registered CN/DN endpoints are reachable:

- `cn001` on `172.16.200.10:30004`
- `cn002` on `172.16.200.15:30004`
- `dn001` on `172.16.200.10:40004`
- `dn002` on `172.16.200.15:40004`

## Run Locally

Run from this directory:

```powershell
$env:PYTHONPATH = 'src'
python -m plugin_ctl list
python -m plugin_ctl inspect otb_timeseries
python -m plugin_ctl doctor
python -m plugin_ctl deploy otb_timeseries
python -m plugin_ctl verify otb_timeseries
python -m plugin_ctl state otb_timeseries
python -m plugin_ctl report
python -m plugin_ctl rollback otb_timeseries
```

Expected M0 behavior:

- `doctor` confirms Docker, expected containers, `psql`, plugin probe, and 4 registered CN/DN endpoints.
- `deploy otb_timeseries` currently exercises the already-installed path and records `already deployed: 1.0.0`.
- `verify otb_timeseries` passes using `platform/recipes/otb_timeseries_smoke.sql`.
- `state` and `report` read local records from `.datanexus/state.json`.
- `report` shows the latest record per `(plugin_id, action)`, so rollback failure does not hide deploy or verify success.
- `rollback otb_timeseries` does not drop database objects when the manifest has no `rollback_sql`.

## Current Implementation Notes

- Plugin manifests are real YAML parsed with `yaml.safe_load`.
- `deploy`, `verify`, and `rollback` return a shared `ActionResult` shape.
- State metadata records plugin version, return code, duration, runtime target, stdout summary, stderr summary, and action-specific metadata.
- Runtime state is local JSON under `.datanexus/`; the directory is ignored by git.

## Known Limits

- M0 has only one sample plugin manifest: `otb_timeseries`.
- Full clean-environment deploy has mock coverage. The current real Docker environment exercises the already-installed deploy path.
- Rollback is conservative. Destructive execution requires manifest `rollback_sql` and an explicit `--execute`.
- Docker container startup and OpenTenBase process startup are separate; after Docker restarts, GTM/CN/DN may need to be started again.
- `verify` still emits OpenTenBase chunk distribution warnings for `otb_timeseries`; this is tracked as a plugin/runtime issue, not treated as solved by the platform.

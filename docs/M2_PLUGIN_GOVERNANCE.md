# M2 Plugin Governance

## Direction

M2 keeps DataNexus centered on plugins. Distributed and cluster information is
used only as context for plugin governance.

DataNexus is not an OpenTenBase cluster inspection platform. It should answer:

- What does this plugin declare?
- Is the manifest complete enough for lifecycle management?
- Does the current OpenTenBase cluster satisfy the plugin's declared target
  roles?
- Can the plugin's `installed_probe` prove its current install state?
- What were the latest deploy, verify, and rollback results?
- Is the plugin currently suitable for deploy, verify, or rollback?

## Commands

Single-plugin governance check:

```powershell
python -m datanexus plugin check <plugin_id>
```

Package lint, without any database connection:

```powershell
python -m datanexus plugin lint <plugin_id>
python -m datanexus plugin lint <plugin_id> --json
```

`lint` returns `pass`, `warn`, and `fail` items. `fail` means the package is not
structurally valid enough for lifecycle management, such as missing required
manifest fields or missing SQL files. `warn` means the package may still run but
its governance surface is incomplete, such as missing `rollback_sql`,
`removed_probe`, or `distributed`.

Non-executing lifecycle plan:

```powershell
python -m datanexus plugin plan <plugin_id>
python -m datanexus plugin plan <plugin_id> --json
```

`plan` explains what deploy, verify, rollback, and removed-verification would do.
It may run only `installed_probe` to tell whether deploy would skip an already
installed plugin. It must not copy files and must not run install, verify,
rollback, or removed-probe SQL.

Read-only pre-deploy checks:

```powershell
python -m datanexus plugin precheck <plugin_id>
python -m datanexus plugin precheck <plugin_id> --json
```

`precheck` is a deploy gate, not a deployment command. It checks package lint
items, OpenTenBase connectivity, version visibility, declared target roles,
registered role nodes, `installed_probe`, and whether `/tmp` can be used as the
remote staging parent. It does not copy files and does not execute lifecycle SQL.

Aggregated diagnosis:

```powershell
python -m datanexus plugin diagnose <plugin_id>
python -m datanexus plugin diagnose <plugin_id> --json
```

`diagnose` aggregates `lint`, `plan`, and `precheck` into one user-facing
decision. It answers whether the package is ready, whether the environment is
ready, whether the plugin is installed, what the next action should be, and
what the main risk is.

Multi-plugin governance status:

```powershell
python -m datanexus plugin status <plugin_id>
python -m datanexus plugins status
python -m datanexus plugins status --json
```

Human output supports Chinese, English, or bilingual labels:

```powershell
python -m datanexus plugin status otb_timeseries --lang zh
python -m datanexus plugin status otb_timeseries --lang en
python -m datanexus plugin status otb_timeseries --lang both
```

JSON output keeps English keys to remain stable for automation.

## Plan Semantics

The plan output is plugin-first:

- `deploy_plan` says whether deploy would skip or copy the payload and run
  `install_sql`.
- `verify_plan` says which smoke SQL would run.
- `rollback_plan` says whether rollback is unsupported or would require
  `--execute`.
- `removed_verify_plan` says whether `verify --removed` has a declared probe.
- `target_roles` comes from the plugin's distributed declaration.
- `risks` records governance gaps, including missing probes, unsupported
  rollback, and the tracked `otb_timeseries` chunk-distribution warning.

This is intentionally close to the useful part of Greenplum/Cloudberry `gppkg`:
validate the package first, then show a role-aware execution plan before making
changes.

`plugins status` is the portfolio view. It should stay concise and show only the
status fields a user needs to decide what to do next: `package_ok`, `env_ready`,
`installed_state`, `next_action`, and `risk`.

## Precheck Semantics

Precheck is stricter than plan because it answers whether a real deploy attempt
has enough prerequisites to proceed:

- package file failures are reported as `fail`;
- OpenTenBase connection failure is `fail`;
- missing declared target roles are `fail`;
- unreachable registered role nodes are `fail`;
- missing optional lifecycle surfaces remain `warn`;
- an already installed plugin is not a failure, because deploy should skip.

The command is still plugin-centered. It reads cluster metadata only to evaluate
whether this plugin's declared roles can be satisfied.

## Distributed Semantics

The `distributed` manifest field is plugin-scoped. It is not a generic CN/DN
health report.

Example:

```yaml
distributed:
  required_roles:
    - coordinator
    - datanode
  probe_strategy: coordinator
  notes: Expected to affect distributed tables.
```

The governance check uses this declaration to decide whether the current
OpenTenBase environment has the roles that the plugin says it needs. Missing
`distributed` is a warning, not a hard failure, so older manifests remain
loadable.

## Non-Goals

- No cluster start.
- No automatic repair.
- No node consistency governance.
- No batch deploy.
- No Web UI.
- No cross-database adapter layer.
- No destructive rollback for `otb_timeseries`.

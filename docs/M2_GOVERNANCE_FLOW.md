# M2 Governance Flow

## Recommended Order

1. `plugin lint`
2. `plugin plan`
3. `plugin precheck`
4. `plugin diagnose`
5. `deploy`
6. `verify`
7. `report`

This order keeps the platform centered on plugin governance:

- `lint` answers whether the package is structurally valid.
- `plan` explains what would happen without making changes.
- `precheck` validates whether the current environment can support a real deploy.
- `diagnose` aggregates those three views into a user-facing decision.
- `deploy`, `verify`, and `report` are the execution and tracking steps.

## Plugin Difference

`dnx_smoke_plugin` is a controlled lifecycle fixture for platform validation.
It is intentionally small, safe, and repeatable. Use it to validate the full
governance flow without touching the real business plugin.

`otb_timeseries` is the real OpenTenBase plugin payload. Its current state is
useful for confirming that DataNexus can see an already installed plugin and
track its governance status, but it should not be used as a destructive test
target.

## Read-Only Commands

- `plugin lint`
- `plugin plan`
- `plugin precheck`
- `plugin diagnose`
- `plugins status`
- `report`
- `cluster status`

These commands inspect manifests, plans, state, or the runtime, but they do not
copy plugin payloads or execute lifecycle SQL.

## Commands That Modify Database State

- `deploy`
- `verify`
- `rollback --execute`

These commands may copy payloads, run SQL files, or change the installed state
of a plugin.

## M2 Boundaries

M2 stops at plugin governance.

- No batch deploy.
- No automatic repair.
- No node sync / clean.
- No Web UI.
- No plugin marketplace.
- No multi-database adapter layer.
- No destructive rollback for `otb_timeseries`.

## Practical Interpretation

The platform should answer one question clearly:

> Is this plugin package ready, is the environment ready, and what should I do
> next?

That is the center of the M2 flow.

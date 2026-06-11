# M1 Deploy Clean-Environment Verification Plan

## Current State

The verified real Docker environment already has `otb_timeseries` installed.
Therefore:

- `deploy otb_timeseries` currently exercises the installed-probe path.
- The command records `already deployed: 1.0.0`.
- It does not prove that a clean OpenTenBase environment can install the plugin
  from scratch.

The uninstalled path is currently covered by mock runtime tests:

- prepare remote directory
- copy plugin payload into the container
- run `psql -f` against the install SQL
- return success
- return failure for copy errors
- return failure for install SQL errors

## Implemented First Step

`examples/plugins/pluginctl_smoke_plugin` has been added as a controlled sample
plugin for platform deploy-chain verification.

It validates the uninstalled deploy path without touching `otb_timeseries`:

- copy payload
- execute install SQL
- record deploy state
- run verify SQL
- rollback preview with `rollback --dry-run`
- review rollback first with `rollback --dry-run`
- verify removal with `verify --removed`

This proves the platform lifecycle plumbing. It does not replace a future clean
install test for the real `otb_timeseries` plugin.

## Remaining Verification Options

### Option A: New Test Database

Create a separate OpenTenBase database inside the current cluster and run deploy
there.

Pros:

- Fastest to iterate.
- Reuses the current Docker topology.

Risks:

- Plugin install scripts may create cluster-wide objects or assume `postgres`.
- Existing schemas/functions may still leak if install behavior is not
  database-local.

### Option B: Clean Temporary Container/Cluster

Start a clean OpenTenBase Docker topology dedicated to deploy verification.

Pros:

- Best proof of real first-install behavior.
- Lowest risk to the user's existing working cluster.

Risks:

- Higher setup cost.
- Requires reproducible cluster bootstrap automation before it is reliable.

### Option C: Controlled Test Plugin

Add a small non-destructive fixture plugin whose install SQL creates isolated
objects and can be safely deployed repeatedly.

Pros:

- Good platform-level install-chain test.
- Avoids destructive changes to `otb_timeseries`.

Risks:

- Proves the platform deploy chain, not the full `otb_timeseries` install path.
- Adds another catalog fixture that must not be confused with product scope.

## Recommendation

Use Option C first for platform deploy-chain validation, then Option B for the
real `otb_timeseries` clean install once cluster bootstrap is under control.

Do not use destructive rollback or manual DROP of `otb_timeseries` in the
current working database just to simulate a clean environment.

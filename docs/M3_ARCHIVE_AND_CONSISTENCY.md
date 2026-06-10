# M3 Archive And Consistency

## Positioning

M3 moves OpenTenBase PluginCtl from a local single-plugin lifecycle loop toward distributed plugin package governance.

This document covers the archive, role mapping, hooks, and consistency parts of M3. The distributed lifecycle flow is documented separately in `M3_DISTRIBUTED_LIFECYCLE.md`.

## Archive Model

`plugin archive` records package-level governance snapshots. It does not replace `state` or `report`.

Archive records include:

- `plugin_id`
- `version`
- `manifest_path`
- `manifest`
- `payload`
- `roles`
- `package_state`
- `installed_at`
- `status`
- `checksum`
- `target_roles`
- `latest_actions`
- `runtime_metadata`
- `updated_at`

Meaning:

- `state/report` records action-level execution results.
- `archive` records package-level governance state.
- `checksum` is computed from the manifest and declared package files.
- `manifest.kind` distinguishes a bundled package from a reference manifest.
- `package_state.payload_complete` records whether the published repository contains all declared payload files.

The archive file is local runtime state under `.plugin_ctl/archive.json` and is not committed to Git.

## Role Governance

M3 maps `distributed.required_roles` from manifest into plugin governance steps:

- `coordinator`: usually owns `installed_probe`, `install_sql`, `verify_sql`, and `rollback_sql`.
- `datanode`: currently used for payload presence and target role declarations.
- `all`: reserved for future role hooks and package synchronization.

Supported declarative role hooks:

- `preinstall`
- `postinstall`
- `preuninstall`
- `postuninstall`

Current hook status:

- Hooks are visible in plan, roles, diagnose, archive, and consistency.
- Hooks are not executed automatically.
- Future hook execution must be gated by explicit parameters such as `--execute-hooks`.

## Consistency Check

`plugin consistency` is plugin-centered consistency governance, not a generic cluster patrol.

It checks:

- Manifest/package lint results.
- Whether an archive record exists.
- Whether archive package state is complete.
- Whether archive checksum matches current manifest/package state.
- Whether archive version matches manifest version.
- Whether runtime installed state can be proven through `installed_probe`.
- Whether archive status and runtime installed state disagree.
- Whether manifest-declared roles can be supported by the current environment.
- Whether archived remote payload paths are still visible in the runtime container when metadata is available.

Commands:

```bash
plugin_ctl plugin consistency <plugin_id>
plugin_ctl plugin consistency <plugin_id> --json
```

The command can return warnings or failures, but it never repairs state automatically.

## Current Plugin View

`pluginctl_smoke_plugin`:

- Bundled platform lifecycle verification plugin.
- Package payload is complete.
- Supports deploy, verify, rollback `--execute`, and verify `--removed`.
- Safe target for archive, roles, consistency, and distributed lifecycle regression tests.

`otb_timeseries`:

- Real business-plugin reference manifest.
- The published platform repository does not include the original full `src/otb_timeseries` payload.
- Archive marks it as a reference manifest, not a complete bundled package.
- It can identify the runtime installed state through `otb_ts.version()`.
- It does not support destructive rollback.
- Its chunk distribution warning remains a tracked issue.

## M3 Archive Boundary

Current M3 archive/consistency scope does not include:

- Web UI.
- Plugin marketplace.
- Batch deploy.
- Version upgrade system.
- Cluster start.
- Automatic repair.
- Cross-database adaptation.
- Destructive rollback for `otb_timeseries`.

# OpenTenBase PluginCtl

[简体中文](README_zh.md)

OpenTenBase PluginCtl is a CLI-first lifecycle governance tool for OpenTenBase plugins.

It focuses on plugin packaging, inspection, deployment, registration, verification, rollback, archive, and reporting. It is not a general OpenTenBase operations platform, a Web console, or a plugin marketplace.

The supported command entrypoint is:

```bash
plugin_ctl
```

## Install

```bash
git clone https://github.com/iamkuangzhang/opentenbase-plugin_ctl.git
cd opentenbase-plugin_ctl
python -m pip install -e .
```

Verify:

```bash
plugin_ctl list
plugin_ctl --help
```

## Five-Minute Trial

Use the bundled `pluginctl_smoke_plugin` first. It is a safe sample plugin for testing PluginCtl itself.

```bash
plugin_ctl list
plugin_ctl inspect pluginctl_smoke_plugin
plugin_ctl check pluginctl_smoke_plugin
plugin_ctl deploy pluginctl_smoke_plugin
plugin_ctl verify pluginctl_smoke_plugin
plugin_ctl report
```

Rollback is dry-run by default. Use `--execute` only when you want to really run the rollback SQL:

```bash
plugin_ctl rollback pluginctl_smoke_plugin
plugin_ctl rollback pluginctl_smoke_plugin --execute
plugin_ctl verify pluginctl_smoke_plugin --removed
```

## Interactive Plugin Shell

Run:

```bash
plugin_ctl
```

or:

```bash
plugin_ctl shell
```

Example:

```text
OpenTenBase PluginCtl Shell
Type "help" to show commands.
Type "quit" or "exit" to leave.

pluginctl> list
pluginctl> check pluginctl_smoke_plugin
pluginctl> deploy pluginctl_smoke_plugin
pluginctl> verify pluginctl_smoke_plugin
pluginctl> report
pluginctl> quit
```

PluginCtl Shell is a plugin lifecycle console. It manages plugin discovery, checks, deployment, verification, rollback, and reports. It does not start, stop, initialize, or monitor an OpenTenBase cluster.

## Distributed Workflow

Copy and edit the topology file:

```bash
cp cluster.toml.example cluster.toml
```

Inspect the topology:

```bash
plugin_ctl cluster inspect -f cluster.toml
```

Preview and execute physical distribution:

```bash
plugin_ctl deploy pluginctl_smoke_plugin -f cluster.toml
plugin_ctl deploy pluginctl_smoke_plugin -f cluster.toml --execute
```

Preview and execute extension registration:

```bash
plugin_ctl register pluginctl_smoke_plugin -f cluster.toml
plugin_ctl register pluginctl_smoke_plugin -f cluster.toml --execute
```

Verify:

```bash
plugin_ctl verify pluginctl_smoke_plugin -f cluster.toml
plugin_ctl plugin consistency pluginctl_smoke_plugin
plugin_ctl report
```

Important boundaries:

- `deploy -f cluster.toml` is dry-run by default.
- `deploy -f cluster.toml --execute` distributes files only and does not run `CREATE EXTENSION`.
- `register -f cluster.toml --execute` runs `CREATE EXTENSION` once on the first coordinator in `cluster.toml`, then checks other coordinators through read-only `pg_extension` queries.
- `activate` is kept only as a deprecated compatibility alias for `register`. New documents and scripts should use `register`.

## Commands

Discovery:

```bash
plugin_ctl list
plugin_ctl inspect <plugin_id>
```

Source assessment:

```bash
plugin_ctl assess <pg_extension_source_path>
plugin_ctl assess <pg_extension_source_path> --json
```

Governance:

```bash
plugin_ctl check <plugin_id>
plugin_ctl plugin lint <plugin_id>
plugin_ctl plugin plan <plugin_id>
plugin_ctl plugin precheck <plugin_id>
plugin_ctl plugin diagnose <plugin_id>
plugin_ctl plugin status <plugin_id>
plugin_ctl plugins status
```

Lifecycle:

```bash
plugin_ctl deploy <plugin_id>
plugin_ctl verify <plugin_id>
plugin_ctl rollback <plugin_id>
plugin_ctl rollback <plugin_id> --execute
plugin_ctl verify <plugin_id> --removed
```

Distributed plugin governance:

```bash
plugin_ctl cluster inspect -f cluster.toml
plugin_ctl deploy <plugin_id> -f cluster.toml
plugin_ctl deploy <plugin_id> -f cluster.toml --execute
plugin_ctl register <plugin_id> -f cluster.toml
plugin_ctl register <plugin_id> -f cluster.toml --execute
plugin_ctl verify <plugin_id> -f cluster.toml
plugin_ctl plugin roles <plugin_id>
plugin_ctl plugin consistency <plugin_id>
plugin_ctl cluster distribute <plugin_id> -f cluster.toml --dry-run
plugin_ctl cluster distribute <plugin_id> -f cluster.toml --execute
```

Archive and reporting:

```bash
plugin_ctl plugin archive list
plugin_ctl plugin archive inspect <plugin_id>
plugin_ctl state <plugin_id>
plugin_ctl report
plugin_ctl report --json
```

Runtime checks:

```bash
plugin_ctl doctor
plugin_ctl cluster status
```

## Included Plugins

- `pluginctl_smoke_plugin`: safe sample plugin for full lifecycle testing.
- `otb_timeseries`: reference manifest for a real OpenTenBase time-series plugin. Do not run destructive rollback against it.
- Legacy `otb_*` manifests: useful for package governance checks, not production-ready bundled plugins.

## Repository Layout

```text
catalog/plugins/       reference manifests
examples/plugins/      bundled sample plugins and fixtures
recipes/               smoke verification SQL
src/plugin_ctl/        Python implementation
tests/                 unit tests
docs/                  design and release documents
cluster.toml.example   distributed topology example
```

## Safety Boundary

Read-only or mostly read-only commands include `list`, `inspect`, `assess`, `plugin lint`, `plugin plan`, `plugin precheck`, `plugin diagnose`, `plugin roles`, `plugin consistency`, `plugin archive list`, `plugin archive inspect`, `plugins status`, `verify -f`, and `report`.

Commands that can modify the database or filesystem:

- `deploy <plugin_id>` runs local install SQL.
- `deploy <plugin_id> -f cluster.toml --execute` copies remote files through `scp`.
- `register <plugin_id> -f cluster.toml --execute` runs `CREATE EXTENSION` on the primary coordinator.
- `rollback <plugin_id> --execute` runs manifest-declared rollback SQL.

Role hooks are currently planned and displayed only. They are not automatically executed.

## Development

```bash
python -m unittest discover -s tests -v
git diff --check
```

Current test baseline:

```text
132 tests
```

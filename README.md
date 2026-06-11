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

## Register an External Plugin

PluginCtl does not require you to copy a plugin into its installation directory. Put the plugin package anywhere, keep a `manifest.yml` or `plugin.yml` in that directory, and register the path:

```bash
plugin_ctl add /path/to/xxx_plugin
plugin_ctl list
plugin_ctl inspect xxx_plugin
```

This writes only a local user catalog entry in `~/.plugin_ctl/catalog.json`. The plugin files stay in their original directory. Remove the entry with:

```bash
plugin_ctl remove xxx_plugin
```

## Five-Minute Trial

Use the bundled `pluginctl_smoke_plugin` first. It is a safe sample plugin for testing PluginCtl itself.

```bash
plugin_ctl init
plugin_ctl list
plugin_ctl inspect pluginctl_smoke_plugin
plugin_ctl check pluginctl_smoke_plugin
plugin_ctl deploy pluginctl_smoke_plugin
plugin_ctl register pluginctl_smoke_plugin
plugin_ctl verify pluginctl_smoke_plugin
plugin_ctl report
```

Rollback runs the manifest-declared rollback SQL. Use `--dry-run` first if you only want to preview it:

```bash
plugin_ctl rollback pluginctl_smoke_plugin --dry-run
plugin_ctl rollback pluginctl_smoke_plugin
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
pluginctl> init
pluginctl> add /path/to/xxx_plugin
pluginctl> check pluginctl_smoke_plugin
pluginctl> deploy pluginctl_smoke_plugin
pluginctl> register pluginctl_smoke_plugin
pluginctl> verify pluginctl_smoke_plugin
pluginctl> plugin lint pluginctl_smoke_plugin
pluginctl> plugin diagnose pluginctl_smoke_plugin
pluginctl> plugin archive list
pluginctl> plugins status --json
pluginctl> cluster inspect
pluginctl> report
pluginctl> remove xxx_plugin
pluginctl> quit
```

PluginCtl Shell is a plugin lifecycle console. It supports the same command groups as `plugin_ctl`; inside the shell, omit the leading `plugin_ctl` and type subcommands directly. `init` only initializes PluginCtl's default `cluster.toml` from a running OpenTenBase cluster. It does not start, stop, initialize, or monitor an OpenTenBase cluster.

## Distributed Workflow

Initialize the default topology from a running OpenTenBase cluster:

```bash
plugin_ctl init
```

This writes `~/.plugin_ctl/cluster.toml` by reading `pgxc_node` from the current coordinator. Review `host`, `ssh_user`, `lib_dir`, and `extension_dir` before running modifying commands.

Inspect the topology. `-f cluster.toml` is optional; when omitted, PluginCtl uses `./cluster.toml` or `~/.plugin_ctl/cluster.toml`.

```bash
plugin_ctl cluster inspect
```

Preview or execute physical distribution. `deploy` requires `cluster.toml`; run `plugin_ctl init` first or pass `-f cluster.toml`.

```bash
plugin_ctl deploy pluginctl_smoke_plugin --dry-run
plugin_ctl deploy pluginctl_smoke_plugin
```

Preview or execute extension registration:

```bash
plugin_ctl register pluginctl_smoke_plugin --dry-run
plugin_ctl register pluginctl_smoke_plugin
```

Verify:

```bash
plugin_ctl verify pluginctl_smoke_plugin
plugin_ctl plugin consistency pluginctl_smoke_plugin
plugin_ctl report
```

Important boundaries:

- `deploy` always requires a cluster config. It no longer runs local install SQL as a fallback.
- `deploy` distributes plugin payload files only and does not run `CREATE EXTENSION`; use `deploy --dry-run` to preview.
- `register` runs `CREATE EXTENSION` once on the first coordinator in `cluster.toml`, then checks other coordinators through read-only `pg_extension` queries; use `register --dry-run` to preview.
- `activate` is kept only as a deprecated compatibility alias for `register`. New documents and scripts should use `register`.

## Commands

Discovery:

```bash
plugin_ctl add <plugin_dir_or_manifest>
plugin_ctl remove <plugin_id>
plugin_ctl list
plugin_ctl inspect <plugin_id>
plugin_ctl plugin add <plugin_dir_or_manifest>
plugin_ctl plugin remove <plugin_id>
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
plugin_ctl rollback <plugin_id> --dry-run
plugin_ctl rollback <plugin_id>
plugin_ctl verify <plugin_id> --removed
```

Distributed plugin governance:

```bash
plugin_ctl init
plugin_ctl cluster inspect
plugin_ctl deploy <plugin_id> --dry-run
plugin_ctl deploy <plugin_id>
plugin_ctl register <plugin_id> --dry-run
plugin_ctl register <plugin_id>
plugin_ctl verify <plugin_id>
plugin_ctl plugin roles <plugin_id>
plugin_ctl plugin consistency <plugin_id>
plugin_ctl cluster distribute <plugin_id> --dry-run
plugin_ctl cluster distribute <plugin_id>
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

Read-only or mostly read-only commands include `list`, `inspect`, `assess`, `plugin lint`, `plugin plan`, `plugin precheck`, `plugin diagnose`, `plugin roles`, `plugin consistency`, `plugin archive list`, `plugin archive inspect`, `plugins status`, `verify`, and `report`.

Commands that can modify the database or filesystem:

- `add <plugin_dir_or_manifest>` and `remove <plugin_id>` update only the local PluginCtl user catalog.
- `init` writes PluginCtl's default cluster config by reading `pgxc_node`; it does not start or stop OpenTenBase.
- `deploy <plugin_id>` copies remote files through `scp` when a cluster config exists; `deploy --dry-run` only previews.
- `register <plugin_id>` runs `CREATE EXTENSION` on the primary coordinator; `register --dry-run` only previews.
- `rollback <plugin_id>` runs manifest-declared rollback SQL; `rollback --dry-run` only previews.

Role hooks are currently planned and displayed only. They are not automatically executed.

## Development

```bash
python -m unittest discover -s tests -v
git diff --check
```

Current test baseline:

```text
147 tests
```

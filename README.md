# OpenTenBase PluginCtl

[简体中文](README_zh.md)

OpenTenBase PluginCtl is a CLI-first plugin lifecycle controller for OpenTenBase.

It focuses on plugin package discovery, physical distribution, extension registration, health checks, rollback, and reports. It is not an OpenTenBase cluster operations platform, a Web console, or a plugin marketplace.

The public entrypoint is:

```bash
plugin_ctl
```

Current version:

```bash
plugin_ctl --version
# plugin_ctl 1.0.0
```

## Install

```bash
git clone https://github.com/iamkuangzhang/opentenbase-plugin_ctl.git
cd opentenbase-plugin_ctl
python -m pip install -e .
```

Verify:

```bash
plugin_ctl --help
plugin_ctl list
```

## Main Shell Flow

For normal use, enter the interactive shell first:

```bash
plugin_ctl
```

The shell defaults to English. It keeps command history in `~/.plugin_ctl/history`,
so the up/down arrow keys can browse previous commands, even after you exit and
enter the shell again. Type `CN` to switch the current session to Chinese, and
type `EN` to switch back to English. Command names stay in English.

Then use the short commands:

```text
pluginctl> help
pluginctl> CN
pluginctl> EN
pluginctl> init
pluginctl> new my_plugin
pluginctl> list
pluginctl> list --all
pluginctl> deploy my_plugin
pluginctl> register my_plugin
pluginctl> check my_plugin
pluginctl> quit
```

`init` reads the current running OpenTenBase topology and writes PluginCtl's default `cluster.toml`. It prefers `opentenbase_ctl status` when available, and falls back to direct SQL discovery through `pgxc_node` for compatibility. It does not start, stop, initialize, or monitor the OpenTenBase cluster.

Recommended cluster workflow:

```bash
su - opentenbase
opentenbase_ctl start
opentenbase_ctl status
plugin_ctl
```

## Use an Existing Plugin Directory

You do not need to copy a plugin into the PluginCtl repository. If a plugin directory contains `manifest.yml` or `plugin.yml`, deploy it directly:

```text
pluginctl> init
pluginctl> deploy ./my_existing_plugin
pluginctl> register my_existing_plugin
pluginctl> check my_existing_plugin
```

`deploy ./my_existing_plugin` automatically adds the plugin to the user catalog before deployment. The plugin files remain in their original directory.

## Public Commands

Inside `plugin_ctl` shell:

```text
help
help advanced
help <command>
init
new <plugin_id>
list [plugin_id]
list --all
deploy <plugin_id_or_path>
register <plugin_id>
check <plugin_id_or_path>
rollback <plugin_id>
quit
exit
CN
EN
```

Use `help advanced` for compatibility and debugging commands.

## Command Meaning

`new <plugin_id>` creates a beginner plugin template and automatically adds it to PluginCtl.

`list` shows user-created or user-added plugins. `list --all` also shows built-in reference plugins. `list <plugin_id>` shows one plugin manifest and recent action records.

`deploy <plugin_id_or_path>` copies the database-loadable plugin files to OpenTenBase CN/DN nodes. Before copying, PluginCtl prints a physical distribution plan: `.control` files and the extension install SQL go to `extension_dir`, `.so` files go to `lib_dir`, and SQL-only plugins show `library none`. Governance scripts such as `verify.sql` and `rollback.sql` are not copied into the OpenTenBase extension directory; they are synced only as PluginCtl metadata under `~/.plugin_ctl/packages/<plugin_id>/`. This lets `plugin_ctl list` see the deployed plugin on other nodes without copying the source directory into the user's workspace.

`register <plugin_id>` first runs read-only prechecks on the primary coordinator. It blocks if the extension is missing from `pg_available_extensions`, skips if it is already in `pg_extension`, otherwise runs `CREATE EXTENSION` once on the primary coordinator and checks other coordinators through read-only `pg_extension` queries.

`check <plugin_id_or_path>` runs the all-in-one plugin check: package lint, plan, precheck, diagnose, and current status hints.

`rollback <plugin_id>` executes the manifest-declared rollback SQL. It only rolls back database objects declared by that SQL; it does not delete physical files from CN/DN nodes. In shell mode, modifying commands show a dry-run preview and ask for confirmation before running.

## One-Stop Check

`check` accepts a known plugin id, a plugin directory, or a manifest path:

```text
pluginctl> check my_plugin
pluginctl> check ./my_plugin
pluginctl> check ./my_plugin/manifest.yml
```

It prints six grouped sections: package structure, extension files, PluginCtl management state, OpenTenBase cluster config, distributed deployment state, and registration/verification state.

Final statuses are `NEW`, `READY`, `DEPLOYED`, `REGISTERED`, `BROKEN`, `REMOVED`, and `UNKNOWN`. Only `FAIL` items make a plugin `BROKEN`; `WARN`, `SKIP`, and `INFO` are reported with next-step hints instead of being treated as fatal.

## Safety Boundary

Read-only or mostly read-only commands include `list`, `check`, `help`, and `help advanced`.

Modifying commands include:

- `deploy`: copies files to CN/DN nodes after showing the physical distribution plan.
- `register`: runs prechecks, then may run `CREATE EXTENSION` on the primary coordinator.
- `rollback`: runs rollback SQL for database objects only; it does not delete CN/DN physical files.

`remove <plugin_id>` is a management cleanup command. It removes the user catalog entry and the local PluginCtl package metadata cache, but it does not drop database objects or delete distributed extension files.

`activate` is kept only as a deprecated compatibility alias for `register`. New documents and scripts should use `register`.

## Advanced Compatibility

Older commands still exist for scripts and debugging, but they are no longer the recommended beginner workflow:

```bash
plugin_ctl add <plugin_dir_or_manifest>
plugin_ctl remove <plugin_id>
plugin_ctl inspect <plugin_id>
plugin_ctl dev init <plugin_id>
plugin_ctl plugin lint <plugin_id>
plugin_ctl plugin plan <plugin_id>
plugin_ctl plugin precheck <plugin_id>
plugin_ctl plugin diagnose <plugin_id>
plugin_ctl plugin roles <plugin_id>
plugin_ctl plugin consistency <plugin_id>
plugin_ctl plugin archive list
plugin_ctl report
```

## Bundled Plugins

- `pluginctl_smoke_plugin`: a safe sample plugin for testing the full PluginCtl lifecycle.
- `otb_timeseries`: a reference manifest for a real time-series plugin payload. It should not be destructively rolled back by PluginCtl.
- `otb_*` legacy manifests: useful for package governance checks, not production-ready bundled plugins.

## Run Tests

```bash
python -m unittest discover -s tests -v
```

Current public workflow goal:

```text
plugin_ctl
pluginctl> init
pluginctl> new my_plugin
pluginctl> deploy my_plugin
pluginctl> register my_plugin
pluginctl> check my_plugin
pluginctl> quit
```

# OpenTenBase PluginCtl

[English](README.md) | [简体中文](README_zh.md)

OpenTenBase PluginCtl is a CLI tool for managing the lifecycle of OpenTenBase plugins in both local Docker sandboxes and distributed OpenTenBase clusters.

It focuses on plugin delivery and governance:

- package inspection
- deployment planning
- physical payload distribution
- coordinator-side extension activation
- distributed white-box verification
- local lifecycle reporting

It is not a general OpenTenBase operations platform, a Web console, or a plugin marketplace.

## Current Status

This repository is currently a source-release baseline. It is usable as a CLI project, but it should still be treated as an early-stage tool.

The main tested flow is:

```bash
python -m plugin_ctl check <plugin_id>
python -m plugin_ctl deploy <plugin_id> -f cluster.toml --execute
python -m plugin_ctl activate <plugin_id> -f cluster.toml --execute
python -m plugin_ctl verify <plugin_id> -f cluster.toml
python -m plugin_ctl report
```

For local development, the original Docker-based flow is still available:

```bash
python -m plugin_ctl deploy <plugin_id>
python -m plugin_ctl verify <plugin_id>
python -m plugin_ctl rollback <plugin_id>
python -m plugin_ctl report
```

## Installation

Requirements:

- Python 3.11+
- `pip`
- Docker, only for the local OpenTenBase sandbox flow
- `ssh`, `scp`, and `psql`, only for distributed cluster operations

Install from source:

```bash
git clone https://github.com/iamkuangzhang/opentenbase-plugin_ctl.git
cd opentenbase-plugin_ctl
python -m pip install -e .
```

Verify the CLI:

```bash
plugin_ctl list
python -m plugin_ctl list
```

## Quick Start

List known plugin manifests:

```bash
python -m plugin_ctl list
```

Inspect a plugin:

```bash
python -m plugin_ctl inspect pluginctl_smoke_plugin
```

Run package-only checks that do not require Docker or a live database:

```bash
python -m plugin_ctl plugin lint pluginctl_smoke_plugin
python -m plugin_ctl plugin plan pluginctl_smoke_plugin
```

Show the latest local action report:

```bash
python -m plugin_ctl report
```

## Distributed Cluster Workflow

Copy the example topology file and edit it for your cluster:

```bash
copy cluster.toml.example cluster.toml
```

On Linux/macOS:

```bash
cp cluster.toml.example cluster.toml
```

Inspect the topology:

```bash
python -m plugin_ctl cluster inspect -f cluster.toml
```

Preview physical distribution:

```bash
python -m plugin_ctl deploy pluginctl_smoke_plugin -f cluster.toml
```

Execute physical distribution:

```bash
python -m plugin_ctl deploy pluginctl_smoke_plugin -f cluster.toml --execute
```

Activate the extension on coordinators:

```bash
python -m plugin_ctl activate pluginctl_smoke_plugin -f cluster.toml --execute
```

Run distributed white-box verification:

```bash
python -m plugin_ctl verify pluginctl_smoke_plugin -f cluster.toml
```

JSON output is available for automation:

```bash
python -m plugin_ctl verify pluginctl_smoke_plugin -f cluster.toml --json
python -m plugin_ctl report --json
```

## What Each Main Command Does

### `check`

```bash
python -m plugin_ctl check <plugin_id>
```

Runs a combined governance check. Internally it aggregates package linting, lifecycle planning, pre-deploy checks, and diagnosis.

It does not modify the database or remote filesystem. It may still check the configured local runtime, so it can report environment failures when Docker or OpenTenBase is not running.

### `deploy`

Local Docker sandbox mode:

```bash
python -m plugin_ctl deploy <plugin_id>
```

Distributed physical distribution mode:

```bash
python -m plugin_ctl deploy <plugin_id> -f cluster.toml
python -m plugin_ctl deploy <plugin_id> -f cluster.toml --execute
```

With `-f cluster.toml`, deploy means physical file distribution only:

- `.so` files go to each node's `lib_dir`.
- `.control` and `.sql` files go to each node's `extension_dir`.
- remote files are checked with SHA256 after copy.
- `CREATE EXTENSION` is not executed.

Without `--execute`, this command is a dry-run plan.

### `activate`

```bash
python -m plugin_ctl activate <plugin_id> -f cluster.toml
python -m plugin_ctl activate <plugin_id> -f cluster.toml --execute
```

Activates extension metadata on coordinator nodes.

With `--execute`, it serially runs:

```sql
CREATE EXTENSION IF NOT EXISTS <extension_name>;
```

It then checks extension version consistency across coordinators.

It does not copy files and does not connect to datanodes.

### `verify`

Local smoke verification:

```bash
python -m plugin_ctl verify <plugin_id>
```

Distributed white-box verification:

```bash
python -m plugin_ctl verify <plugin_id> -f cluster.toml
```

Distributed verification is read-only. It checks:

- coordinator extension installation and version consistency
- CN/DN SQL connectivity
- CN/DN physical payload file checksum
- prepared transaction residue in `pg_prepared_xacts`

### `report`

```bash
python -m plugin_ctl report
python -m plugin_ctl report --json
```

Shows local action records written by PluginCtl. It is useful for CLI audit trails, but it is not a substitute for live database verification.

## Advanced Commands

The following commands are kept for troubleshooting and lower-level inspection:

```bash
python -m plugin_ctl plugin lint <plugin_id>
python -m plugin_ctl plugin plan <plugin_id>
python -m plugin_ctl plugin precheck <plugin_id>
python -m plugin_ctl plugin diagnose <plugin_id>
python -m plugin_ctl plugin status <plugin_id>
python -m plugin_ctl plugin roles <plugin_id>
python -m plugin_ctl plugin consistency <plugin_id>
python -m plugin_ctl plugin archive list
python -m plugin_ctl plugin archive inspect <plugin_id>
python -m plugin_ctl plugins status
python -m plugin_ctl cluster distribute --dry-run -f cluster.toml <plugin_id>
python -m plugin_ctl cluster distribute --execute -f cluster.toml <plugin_id>
python -m plugin_ctl cluster status
python -m plugin_ctl doctor
```

## Plugin Package Layout

A plugin is described by a manifest and payload files.

Example:

```text
examples/plugins/pluginctl_smoke_plugin/
  manifest.yml
  payload/
    sql/
      install.sql
      verify.sql
      rollback.sql
    hooks/
      preinstall.sql
      postinstall.sql
      preuninstall.sql
      postuninstall.sql
```

The manifest declares:

- plugin id and version
- supported database
- payload root
- install, verify, smoke, and rollback SQL
- installed and removed probes
- distributed role requirements
- optional lifecycle hooks

## Repository Layout

```text
catalog/plugins/       reference manifests for plugin payloads
examples/plugins/      bundled example plugins and legacy payload fixtures
recipes/               smoke verification SQL
src/plugin_ctl/        Python package implementation
tests/                 unit tests
docs/                  design and status documents
cluster.toml.example   distributed cluster topology example
```

## Included Plugins

### `pluginctl_smoke_plugin`

A small bundled sample plugin used to validate PluginCtl itself. It supports deploy, verify, rollback, and removed verification.

Use this plugin first when testing the tool.

### `otb_timeseries`

A reference manifest for a real OpenTenBase time-series plugin payload. It is useful for governance and installed-state checks, but the current published repository should not be treated as proof of a complete clean-room installation path for that plugin.

## Safety Boundary

Important assumptions:

- `cluster.toml` is trusted administrator configuration.
- PluginCtl does not treat topology files as untrusted input.
- `deploy -f --execute` writes remote payload files through `scp`.
- `activate -f --execute` changes coordinator metadata through `CREATE EXTENSION`.
- `verify -f` is read-only.
- rollback is best-effort and must be explicitly executed with `--execute`.

Implementation safety properties:

- `psql`, `ssh`, `scp`, and `docker` are called with argument lists.
- `shell=True` is not used.
- extension names are validated as PostgreSQL identifiers before SQL generation.
- remote system directories are not automatically created.
- `sudo` is not attempted automatically.

## Not In Scope Yet

PluginCtl currently does not implement:

- automatic plugin source compilation
- automatic remote repair
- automatic rollback of coordinator activation
- a Web UI
- a plugin marketplace
- batch deployment and upgrade orchestration
- cross-database support beyond OpenTenBase
- an `otb_timeseries`-specific deep verification profile

## Development

Run tests:

```bash
python -m unittest discover -s tests -v
```

Check whitespace errors:

```bash
git diff --check
```

Current test baseline:

```text
109 unit tests
```

## Documentation

- [M3 Distributed Lifecycle](docs/M3_DISTRIBUTED_LIFECYCLE.md)
- [M3 Final Status](docs/M3_FINAL_STATUS.md)
- [M3 Archive And Consistency](docs/M3_ARCHIVE_AND_CONSISTENCY.md)
- [M2 Plugin Governance](docs/M2_PLUGIN_GOVERNANCE.md)
- [Release Checklist](docs/RELEASE_CHECKLIST.md)

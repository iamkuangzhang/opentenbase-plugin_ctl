# Changelog

## v1.0.0 - Public CLI Release

OpenTenBase PluginCtl v1.0.0 is the first complete public command-line release for OpenTenBase distributed plugin development and validation.

It is intended for development and test environments. It is not a production guarantee, and operators should review deployment plans before using it on important clusters.

### Added

- Added the public `plugin_ctl` command and interactive `pluginctl>` shell.
- Added persistent shell history under `~/.plugin_ctl/history`.
- Added session-local language switching with `CH` and `EN`.
- Added `new`, `new -sql`, and `new -c` plugin scaffolding.
- Added PGXS-based `build <plugin_id>` for C extensions.
- Added `BUILD_REQUIRED` status for C plugins whose source and `Makefile` exist but whose `.so` artifact has not been built.
- Added `init` topology discovery from a running OpenTenBase cluster, preferring `opentenbase_ctl` when available and falling back to `pgxc_node` discovery.
- Added distributed `deploy` for copying `.control`, install SQL, and `.so` files to CN/DN nodes.
- Added `register` for primary-coordinator `CREATE EXTENSION` plus read-only coordinator view checks.
- Added all-in-one `check` output with package, extension file, PluginCtl state, cluster config, distributed deployment, and registration/verification sections.
- Added rollback execution through manifest-declared rollback SQL.
- Added local reports, archive records, plugin governance checks, role/consistency checks, and compatibility commands for advanced users.

### Changed

- Standardized the public command name as `plugin_ctl`.
- Standardized the repository name as `opentenbase-plugin_ctl`.
- Standardized the beginner lifecycle as `init -> new/build -> deploy -> register -> check`.
- `activate` is deprecated and retained only as a compatibility alias for `register`.
- `CN/cn` is no longer used for language switching; use `CH/ch` for Chinese and `EN/en` for English.
- `check` status precedence now reflects current state: `REGISTERED` and `DEPLOYED` take priority over old rollback history.

### Security

- External commands are executed through argument lists instead of shell command strings where PluginCtl controls the invocation.
- Extension names are validated before generated SQL is used.
- `deploy` copies declared extension payload files only; governance scripts such as `verify.sql` and `rollback.sql` are kept as PluginCtl metadata.
- `register` runs `CREATE EXTENSION` once on the primary coordinator and verifies other coordinators with read-only queries.
- `rollback` is best-effort object cleanup from manifest-declared SQL and does not remove physical files from CN/DN nodes.

### Known Limitations

- v1.0.0 is focused on development and test clusters, not unattended production automation.
- Wheel and PyPI distribution are not provided yet; source checkout plus editable install is the recommended installation path.
- PluginCtl does not start, stop, initialize, or monitor OpenTenBase clusters.
- No Web UI, plugin marketplace, batch deployment, automatic repair, version upgrade orchestration, or cross-database adapter is included.
- Rollback is not a database disaster recovery mechanism.
- Role hooks are planned and checked, but not automatically executed.
- `otb_timeseries` and `otb_*` entries are reference or governance examples, not production-ready bundled plugins.

### Validation

The v1.0.0 baseline has been validated with:

```bash
plugin_ctl --version
plugin_ctl list
python -m unittest discover -s tests -v
```

The current unit test baseline is:

```text
208 tests OK
```

Real OpenTenBase validation has covered:

- Two-node OpenTenBase test environment with CN/DN topology discovery.
- SQL-only plugin scaffolding and lifecycle checks.
- C extension scaffolding with PGXS build.
- Distributed payload deployment to CN/DN nodes.
- Primary-coordinator registration.
- `SELECT hello();` returning `hello_world` for the C extension smoke test.

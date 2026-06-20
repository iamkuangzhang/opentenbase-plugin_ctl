# Security Policy

## Supported Versions

The current public version is `v1.0.0`.

This release is intended for OpenTenBase plugin development and validation in development or test environments. It is not a guarantee of unattended production safety.

## Reporting A Vulnerability

Please report security issues through GitHub issues unless the report includes private credentials, private infrastructure details, or exploit instructions.

Do not include passwords, tokens, private keys, live database credentials, or private hostnames in public reports.

## Execution Safety

OpenTenBase PluginCtl separates plugin governance from OpenTenBase cluster operations.

PluginCtl does not start, stop, initialize, or monitor OpenTenBase clusters. It assumes the target OpenTenBase cluster is already running and uses `init` only to discover topology and write PluginCtl's local `cluster.toml`.

Read-only or mostly read-only commands include:

- `list`
- `check`
- `help`
- `help advanced`
- advanced governance commands such as `plugin lint`, `plugin plan`, and `plugin consistency`

Commands that may modify the environment include:

- `deploy`, which copies declared extension payload files to CN/DN nodes.
- `register`, which may run `CREATE EXTENSION` once on the primary coordinator.
- `rollback`, which runs manifest-declared rollback SQL.
- `remove`, which removes PluginCtl catalog metadata but does not drop database objects or remote physical files.

## Important Boundaries

- Review `deploy` output before using it on important clusters.
- `register` should be treated as a database-changing command.
- `rollback` is best-effort object cleanup, not disaster recovery.
- `rollback` does not remove `.control`, install SQL, or `.so` files from CN/DN nodes.
- Role hooks are planned and checked, but not automatically executed in v1.0.0.
- PluginCtl should not be treated as a general OpenTenBase operations platform.

## Safer Usage Pattern

Recommended manual review flow:

```text
plugin_ctl
pluginctl> init
pluginctl> check <plugin_id_or_path>
pluginctl> deploy <plugin_id_or_path>
pluginctl> check <plugin_id>
pluginctl> register <plugin_id>
pluginctl> check <plugin_id>
```

For C extensions, build before deployment:

```text
pluginctl> new -c my_c_plugin
pluginctl> check my_c_plugin
pluginctl> build my_c_plugin
pluginctl> deploy my_c_plugin
pluginctl> register my_c_plugin
pluginctl> check my_c_plugin
```

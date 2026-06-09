# M3 Distributed Lifecycle

## Purpose

M3 freezes the distributed OpenTenBase plugin lifecycle around the following main flow:

```bash
python -m plugin_ctl assess ./pg_extension_source/
python -m plugin_ctl check <plugin_id>
python -m plugin_ctl deploy <plugin_id> -f cluster.toml --execute
python -m plugin_ctl register <plugin_id> -f cluster.toml --execute
python -m plugin_ctl verify <plugin_id> -f cluster.toml
python -m plugin_ctl report
```

The goal is to make plugin delivery explicit and auditable:

- Check the package and environment before changing anything.
- Physically distribute declared payload files.
- Register extension metadata once through the primary coordinator.
- Run distributed white-box verification.
- Record and inspect local action results.

## Inputs

### Plugin manifest

The plugin manifest declares the plugin identity, payload, probes, distributed roles, and optional hooks.

Important fields:

- `plugin_id`
- `version`
- `source_root`
- `payload.install_sql`
- `payload.verify_sql`
- `payload.rollback_sql`
- `payload.installed_probe`
- `payload.removed_probe`
- `payload.extension_name` or `payload.extension`
- `distributed.required_roles`
- `hooks`

### cluster.toml

`cluster.toml` is trusted administrator configuration. It describes the physical OpenTenBase topology.

Each node must declare:

- `name`
- `role`: `cn` or `dn`
- `host`
- `ssh_port`
- `db_port`
- `ssh_user`
- `db_user`
- `database`
- `lib_dir`
- `extension_dir`

The tool does not treat `cluster.toml` as untrusted user input.

## Step 0: assess

```bash
python -m plugin_ctl assess ./pg_extension_source/
python -m plugin_ctl assess ./pg_extension_source/ --json
```

`assess` statically scans a PostgreSQL extension source tree for OpenTenBase migration risks. It does not compile code, connect to OpenTenBase, or modify files.

The MVP checks `.control` files, SQL/C source presence, `LANGUAGE C` functions without explicit `SHIPPABLE` / `NOT SHIPPABLE`, C-side dynamic table DDL, transaction-control patterns, and system-catalog access.

## Step 1: check

```bash
python -m plugin_ctl check <plugin_id>
```

`check` aggregates:

- `plugin lint`
- `plugin plan`
- `plugin precheck`
- `plugin diagnose`

It is intended as a single pre-flight gate for users. It does not execute deploy, activate, scp, or destructive rollback.

## Step 2: deploy -f

Dry-run:

```bash
python -m plugin_ctl deploy <plugin_id> -f cluster.toml
```

Execute:

```bash
python -m plugin_ctl deploy <plugin_id> -f cluster.toml --execute
```

Distributed deploy currently means physical payload distribution only:

- `.so` files go to each node's `lib_dir`.
- `.control` and `.sql` files go to each node's `extension_dir`.
- Remote directory existence and writability are checked before copy.
- Files are copied through `scp`.
- Each copied file is verified through remote SHA256.

It does not run `CREATE EXTENSION`.

## Step 3: register -f

Dry-run:

```bash
python -m plugin_ctl register <plugin_id> -f cluster.toml
```

Execute:

```bash
python -m plugin_ctl register <plugin_id> -f cluster.toml --execute
```

Registration behavior:

- Reads `extension_name` from manifest, falling back to `plugin_id`.
- Validates the name as a PostgreSQL identifier.
- Runs `CREATE EXTENSION IF NOT EXISTS <extension_name>;` only on the first coordinator declared in `cluster.toml`.
- Treats that first coordinator as the primary coordinator for metadata registration.
- Verifies all coordinators through read-only `pg_extension` queries.
- Version reconciliation across coordinators is read-only and concurrent.

It does not distribute files and does not connect to datanodes.

`activate` remains available as a deprecated compatibility alias for `register`.

There is no automatic rollback of already registered metadata in M3.

## Step 4: verify -f

```bash
python -m plugin_ctl verify <plugin_id> -f cluster.toml
python -m plugin_ctl verify <plugin_id> -f cluster.toml --json
```

Distributed verify is read-only.

It checks:

- Coordinator extension state and version consistency through `pg_extension`.
- CN/DN SQL connectivity through `SELECT 1;`.
- CN/DN physical file presence and SHA256 checksum.
- CN/DN prepared transaction residue through `pg_prepared_xacts`.

It does not:

- Execute scp.
- Run `CREATE EXTENSION`.
- Register metadata.
- Run a plugin-specific timeseries profile.

Prepared transaction residue is reported as a risk requiring manual confirmation. The tool does not claim the residue was caused by the current plugin.

## Step 5: report

```bash
python -m plugin_ctl report
python -m plugin_ctl report --json
```

`report` shows local action state recorded by the CLI. It is not a replacement for database truth. Use `verify -f` for live distributed state verification.

## Advanced / Debug Commands

The following commands remain available for lower-level troubleshooting:

```bash
python -m plugin_ctl plugin lint <plugin_id>
python -m plugin_ctl plugin plan <plugin_id>
python -m plugin_ctl plugin precheck <plugin_id>
python -m plugin_ctl plugin diagnose <plugin_id>
python -m plugin_ctl assess ./pg_extension_source/
python -m plugin_ctl cluster inspect -f cluster.toml
python -m plugin_ctl cluster distribute --dry-run -f cluster.toml <plugin_id>
python -m plugin_ctl cluster distribute --execute -f cluster.toml <plugin_id>
```

They are not removed or replaced by the main flow.

## Explicit Non-Goals

M3 does not implement:

- Automatic source compilation.
- Automatic remote repair.
- Automatic rollback of activation.
- Plugin-specific `otb_timeseries` validation profile.
- Web UI.
- Plugin marketplace.
- Cross-database adaptation.
- Batch deployment.
- Automatic sudo or remote system directory creation.

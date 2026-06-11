# M3 Final Status

## Freeze Conclusion

M3 is frozen as a distributed plugin lifecycle baseline.

The frozen main flow is:

```bash
plugin_ctl check <plugin_id>
plugin_ctl deploy <plugin_id> -f cluster.toml
plugin_ctl activate <plugin_id> -f cluster.toml
plugin_ctl verify <plugin_id> -f cluster.toml
plugin_ctl report
```

Supported entrypoints:

```bash
plugin_ctl ...
```

## Implemented M3 Capabilities

### Topology

- `cluster.toml.example`
- `ClusterConfig`
- `ClusterNode`
- `load_cluster_config()`
- Coordinator and datanode convenience views.

### Physical Distribution

- Dry-run distribution planning.
- Real SSH/SCP physical distribution, with `--dry-run` available for preview.
- `.so` to `lib_dir`.
- `.control` and `.sql` to `extension_dir`.
- Remote directory existence/writability checks.
- Local and remote SHA256 reconciliation.
- Structured per-node/per-file results.

### CLI Convergence

- `check <plugin_id>` as the main governance gate.
- `deploy <plugin_id> -f cluster.toml` as the main physical distribution entry.
- Advanced `plugin ...` and `cluster distribute ...` commands retained.

### Activation

- `activate <plugin_id> -f cluster.toml`.
- Default dry-run.
- `--dry-run` previews registration; without it, registration runs `CREATE EXTENSION`.
- Serial coordinator activation.
- Concurrent coordinator version reconciliation.
- No datanode connection during activation.
- No automatic rollback of already activated coordinators.

### Distributed Verify

- `verify <plugin_id> -f cluster.toml`.
- Read-only coordinator extension check.
- Read-only CN/DN connectivity check.
- Read-only remote payload SHA256 check.
- Read-only prepared transaction scan.
- JSON output with stable English keys.

## M2 Compatibility Status

M2 Docker sandbox behavior remains intact:

- `deploy <plugin_id>` without `-f` still uses the Docker runtime path.
- `verify <plugin_id>` without `-f` still uses smoke verify.
- `rollback <plugin_id>` still uses the old local runtime; `rollback --dry-run` previews the rollback SQL.
- `OpenTenBaseRuntime` still defaults to `opentenbaseDN1`, `127.0.0.1`, port `30004`, user `opentenbase`, database `postgres`.

## Advanced / Debug Commands

Retained commands:

```bash
plugin_ctl plugin lint <plugin_id>
plugin_ctl plugin plan <plugin_id>
plugin_ctl plugin precheck <plugin_id>
plugin_ctl plugin diagnose <plugin_id>
plugin_ctl plugin check <plugin_id>
plugin_ctl plugin status <plugin_id>
plugin_ctl plugin roles <plugin_id>
plugin_ctl plugin consistency <plugin_id>
plugin_ctl plugin archive list
plugin_ctl plugin archive inspect <plugin_id>
plugin_ctl plugins status
plugin_ctl cluster inspect -f cluster.toml
plugin_ctl cluster distribute --dry-run -f cluster.toml <plugin_id>
plugin_ctl cluster distribute -f cluster.toml <plugin_id>
plugin_ctl cluster status
plugin_ctl doctor
```

## Security Boundary

- `cluster.toml` is trusted administrator configuration.
- The tool does not accept untrusted topology files as safe input.
- `psql`, `ssh`, `scp`, and `docker` are invoked with argument lists, not `shell=True`.
- Extension names are validated as PostgreSQL identifiers before SQL generation.
- `deploy -f` writes remote files only.
- `activate -f` changes coordinator metadata only.
- `verify -f` is read-only.
- No automatic sudo is attempted.
- No automatic remote system directory creation is attempted.

## Current Non-Goals

M3 intentionally does not include:

- Automatic plugin source compilation.
- Automatic repair.
- Automatic rollback of activation.
- `otb_timeseries`-specific verification profile.
- Web UI.
- Plugin marketplace.
- Cross-database support.
- Batch deployment.
- Version upgrade system.

## QA Result

Final QA checks for M3 freeze:

```bash
python -m unittest discover -s tests -v
git diff --check
```

Expected state at freeze: all tests pass and no whitespace errors.

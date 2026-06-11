# Contributing

OpenTenBase PluginCtl is currently in the v0.1.0 source release stage. Contributions should keep the project focused on OpenTenBase distributed plugin lifecycle governance.

## Scope

Accepted contribution areas:

- plugin manifest linting and planning
- safe lifecycle verification
- archive/state consistency
- role-scoped plugin governance
- documentation and examples

Out of scope for now:

- Web UI
- plugin marketplace
- batch deploy
- automatic repair
- cluster start
- cross-database adapters
- destructive rollback for `otb_timeseries`

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

Before opening a PR, run the full test suite and include the command output summary.

## Safety

Do not add commands that modify a database unless the command has clear documentation and a safe `--dry-run` preview when practical. Role hooks must remain non-executing unless a future release introduces an explicit `--run-hooks` boundary.

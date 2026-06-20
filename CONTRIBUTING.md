# Contributing

OpenTenBase PluginCtl is currently in the v1.0.0 public CLI release stage. Contributions should keep the project focused on OpenTenBase distributed plugin lifecycle governance for development and test environments.

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
- batch deployment
- automatic repair
- cluster lifecycle management
- cross-database adapters
- destructive rollback for `otb_timeseries`

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

Before opening a PR, run the full test suite and include the command output summary.

## Safety

Do not add commands that modify a database unless the command has clear documentation, a visible plan or precheck step, and an explicit execution boundary. Role hooks must remain non-executing unless a future release introduces an explicit hook execution boundary.

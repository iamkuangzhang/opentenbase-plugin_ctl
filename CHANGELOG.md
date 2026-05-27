# Changelog

## v0.1.0 - Release Candidate

OpenTenBase PluginCtl v0.1.0 is a source release candidate for CLI-first lifecycle governance of OpenTenBase distributed plugins.

### Completed

- M0: CLI baseline with `list`, `inspect`, `doctor`, lifecycle scaffolding, manifest loading, and local OpenTenBase Docker validation.
- M1: safe sample plugin lifecycle loop through `pluginctl_smoke_plugin`, including deploy, verify, rollback dry-run/execute, removed verification, state, and report.
- M2: plugin-centered governance flow with `plugin lint`, `plugin plan`, `plugin precheck`, `plugin diagnose`, `plugin check`, and `plugins status`.
- M3: distributed plugin package governance with archive records, role mapping, role hook planning, and plugin-centered consistency checks.
- M4 first stage: release-quality documentation, safety boundaries, command grouping, editable install guidance, and `plugin_ctl` console script.

### Current Commands

- Discovery: `list`, `inspect`
- Governance: `plugin lint`, `plugin plan`, `plugin precheck`, `plugin diagnose`, `plugin status`, `plugin check`, `plugins status`
- Lifecycle: `deploy`, `verify`, `rollback`
- Archive: `plugin archive list`, `plugin archive inspect`
- Distributed: `plugin roles`, `plugin consistency`
- Reporting: `state`, `report`
- Runtime: `doctor`, `cluster status`

### Known Limitations

- v0.1.0 is not a production-ready release.
- Recommended distribution is GitHub source release plus `python -m pip install -e .`.
- Wheel/PyPI packaging is deferred because top-level runtime assets such as `catalog/`, `examples/`, `docs/`, and `recipes/` still rely on source-tree layout.
- `otb_timeseries` is a reference manifest in this repository. The published repository does not bundle the full old `src/otb_timeseries` payload.
- Role hooks are not executed automatically. They are planned, linted, archived, and checked for consistency only.
- `rollback` is best-effort and must be explicitly executed with `--execute`.
- No Web UI, plugin marketplace, batch deploy, automatic repair, cluster start, version upgrade system, or cross-database adapter is included.

### Validation

The release candidate has been validated with:

```bash
python -m unittest discover -s tests -v
python -m plugin_ctl list
plugin_ctl list
python -m plugin_ctl plugin diagnose pluginctl_smoke_plugin
python -m plugin_ctl plugin consistency pluginctl_smoke_plugin
python -m plugin_ctl plugins status
```

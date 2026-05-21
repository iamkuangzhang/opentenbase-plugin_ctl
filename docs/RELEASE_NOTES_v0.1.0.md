# OpenTenBase PluginCtl v0.1.0

## Title

OpenTenBase PluginCtl v0.1.0 - Source Release Candidate

## Summary

OpenTenBase PluginCtl v0.1.0 is the first source release candidate for a CLI-first lifecycle governance tool for OpenTenBase distributed plugins.

This release focuses on plugin package governance, not general cluster operations. It provides manifest linting, lifecycle planning, prechecks, diagnosis, safe sample deploy/verify/rollback flow, archive records, role-scoped governance, and plugin-centered consistency checks.

## Highlights

- Console script: `opentenbase-pluginctl`
- Compatibility entrypoints: `datanexus`, `python -m datanexus`
- Safe sample plugin: `dnx_smoke_plugin`
- Reference manifest for real plugin: `otb_timeseries`
- Governance flow: `lint -> plan -> precheck -> diagnose -> deploy -> verify -> report`
- Distributed package governance: `archive -> roles/hooks -> consistency`
- Clear safety boundary for read-only commands, lifecycle commands, hooks, and rollback

## Installation

```bash
git clone https://github.com/iamkuangzhang/opentenbase-pluginctl.git
cd opentenbase-pluginctl
python -m pip install -e .
opentenbase-pluginctl list
```

## Five-Minute Trial

```bash
python -m datanexus list
python -m datanexus plugin lint dnx_smoke_plugin
python -m datanexus plugin plan dnx_smoke_plugin
python -m datanexus plugin precheck dnx_smoke_plugin
python -m datanexus deploy dnx_smoke_plugin
python -m datanexus verify dnx_smoke_plugin
python -m datanexus plugin diagnose dnx_smoke_plugin
python -m datanexus report
```

## Known Limitations

- This is not production-ready.
- Recommended distribution is GitHub source release plus editable install.
- Wheel/PyPI release is deferred.
- `otb_timeseries` is a reference manifest in this repository and does not include the full old payload tree.
- Role hooks are not automatically executed.
- Rollback is best-effort and requires `--execute`.
- No Web UI, plugin marketplace, batch deploy, automatic repair, cluster start, version upgrade system, or cross-database adapter.

## Validation

Validated with:

```bash
python -m unittest discover -s tests -v
python -m datanexus list
opentenbase-pluginctl list
python -m datanexus plugin diagnose dnx_smoke_plugin
python -m datanexus plugin consistency dnx_smoke_plugin
python -m datanexus plugins status
```

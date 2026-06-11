# Legacy Plugin Onboarding

## Scope

This document records the first onboarding pass for the legacy OpenTenBase plugin payloads from the original plugin_ctl project.

The current goal is governance validation:

- catalog discovery
- manifest linting
- lifecycle planning
- diagnosis
- role mapping
- consistency checks
- lightweight smoke verification through `version()`

This pass does not mean every plugin is safe for automatic deploy. Some plugins require native shared-library build steps, and some install SQL should be reviewed before execution.

## Onboarded Plugins

The following payloads are copied under:

```text
examples/plugins/legacy_payloads/
```

Catalog manifests are under:

```text
catalog/plugins/
```

Plugins:

- `otb_age`
- `otb_analytics`
- `otb_fulltext`
- `otb_health`
- `otb_routing`
- `otb_scheduler`
- `otb_snapshot`
- `otb_timeseries`

## Build And Safety Notes

Native build required before deploy:

- `otb_age`
- `otb_analytics`
- `otb_fulltext`
- `otb_routing`

Install SQL requires extra review:

- `otb_scheduler`: install SQL may drop and recreate the plugin schema.
- `otb_snapshot`: plugin functions can perform destructive data operations on user tables.
- `otb_timeseries`: do not add destructive rollback; chunk distribution warning remains tracked separately.

No legacy plugin currently declares `rollback_sql` or `removed_probe`. This is intentional for the first onboarding pass.

## Validation Commands

Run discovery:

```bash
plugin_ctl list
plugin_ctl plugins status
```

Run one plugin governance check:

```bash
plugin_ctl plugin lint otb_health
plugin_ctl plugin plan otb_health
plugin_ctl plugin diagnose otb_health
```

Run lightweight smoke verification only when the plugin is already installed:

```bash
plugin_ctl verify otb_health
```

## Current Real Environment Result

In the local OpenTenBase Docker environment, all onboarded legacy plugins were detected as installed through `installed_probe`.

The following smoke verifications passed:

- `otb_age`
- `otb_analytics`
- `otb_fulltext`
- `otb_health`
- `otb_routing`
- `otb_scheduler`
- `otb_snapshot`
- `otb_timeseries`

`otb_timeseries` still emits the known chunk distribution warning during smoke verification.

## Next Steps

- Add safe smoke SQL beyond `version()` for selected plugins.
- Design native build/package checks for plugins with C extension code.
- Add non-destructive removed probes where possible.
- Keep destructive rollback disabled for real business plugins until reviewed.

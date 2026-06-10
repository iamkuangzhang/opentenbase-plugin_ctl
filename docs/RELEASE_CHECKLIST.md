# v0.1.0 Release Checklist

## Documentation

- [x] README explains the project positioning.
- [x] README includes installation instructions.
- [x] README includes a five-minute trial flow.
- [x] README documents safety boundaries.
- [x] M4 release-quality documentation exists.
- [x] `pluginctl_smoke_plugin` is documented as a bundled sample plugin.
- [x] `otb_timeseries` is documented as a reference manifest, not a complete bundled package.
- [x] Known limitations are documented.

## Installation

- [x] Python requirement is declared as `>=3.11`.
- [x] Runtime dependency `PyYAML>=6.0` is declared.
- [x] Editable install works with `python -m pip install -e .`.
- [x] Console script `plugin_ctl` is declared.
- [x] `plugin_ctl` remains supported.

## Packaging Strategy

- [x] Python package code is included through `src/plugin_ctl`.
- [x] Source release includes `catalog/`.
- [x] Source release includes `examples/`.
- [x] Source release includes `docs/`.
- [x] Source release includes `recipes/`.
- [x] Source release includes `tests/`.
- [x] `.plugin_ctl/` is ignored and excluded from source manifest.

Decision for v0.1.0:

- Recommended distribution: GitHub source release plus editable install.
- Wheel/PyPI release: deferred.

Reason:

The CLI currently resolves platform assets from the source-tree root. A wheel install would need a dedicated asset-loading strategy for `catalog/`, `examples/`, `docs/`, and `recipes/`.

## Safety

- [x] Read-only commands are documented.
- [x] Commands that modify database or local state are documented.
- [x] Role hooks are documented as non-executing.
- [x] Future hook execution requires an explicit boundary such as `--execute-hooks`.
- [x] Rollback is documented as best-effort.
- [x] `otb_timeseries` destructive rollback is not implemented.

## Open Source Basics

- [x] `LICENSE` exists.
- [x] `CHANGELOG.md` exists.
- [x] `CONTRIBUTING.md` exists.
- [x] `SECURITY.md` exists.
- [x] README does not include old competition/private material.
- [x] `.plugin_ctl/state.json` and `.plugin_ctl/archive.json` are ignored.
- [x] Sensitive keyword scan completed. The only match is `SECURITY.md` explaining not to publish passwords/tokens; no actual credential was found.

## Validation Commands

Run before tagging:

```bash
python -m unittest discover -s tests -v
plugin_ctl list
plugin_ctl list
plugin_ctl plugin diagnose pluginctl_smoke_plugin
plugin_ctl plugin consistency pluginctl_smoke_plugin
plugin_ctl plugins status
```

If local OpenTenBase is available, optionally run:

```bash
plugin_ctl plugin precheck pluginctl_smoke_plugin
plugin_ctl deploy pluginctl_smoke_plugin
plugin_ctl verify pluginctl_smoke_plugin
plugin_ctl rollback pluginctl_smoke_plugin
plugin_ctl rollback pluginctl_smoke_plugin --execute
plugin_ctl verify pluginctl_smoke_plugin --removed
plugin_ctl report
```

Latest local validation also completed the `pluginctl_smoke_plugin` deploy, verify, rollback dry-run, rollback execute, removed verify, and report flow.

## Release Decision

Current status: v0.1.0 can be tagged as a source release candidate after final validation passes.

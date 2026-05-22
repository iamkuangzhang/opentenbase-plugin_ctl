# Third Party Notices

`otb_pgmq` is adapted from PGMQ.

- Upstream repository: https://github.com/pgmq/pgmq
- Upstream commit studied: `02cffd7`
- Upstream license: PostgreSQL License
- Copyright: Copyright (c) 2023, Tembo

The upstream license text is included in `LICENSE.upstream`.

OpenTenBase-specific changes are limited to compatibility and lifecycle packaging:

- remove metadata foreign keys rejected by OpenTenBase distribution rules;
- replace generated stored column syntax not accepted by the current OpenTenBase environment;
- replace `CREATE INDEX ... INCLUDE (...)` with a simple index;
- rewrite `archive()` writable CTEs into explicit PL/pgSQL steps;
- add `pgmq.version()` for PluginCtl installed probes;
- add PluginCtl manifest, verify, and rollback scripts.

This package does not claim full upstream PGMQ compatibility yet.

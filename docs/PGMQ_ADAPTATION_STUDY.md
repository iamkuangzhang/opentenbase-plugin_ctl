# PGMQ Adaptation Study for OpenTenBase PluginCtl

本文记录对 PGMQ 的第一轮学习和 OpenTenBase 适配判断。目标是基于 PGMQ 的真实源码做分布式改造，不再从零散原创开始。

## Reference Source

- Repository: https://github.com/pgmq/pgmq
- Local checkout: `C:\Users\28725\Desktop\datanexus_reference_repos\pgmq`
- Studied commit: `02cffd7`
- Core directory: `pgmq-extension/`
- Current extension default version in `pgmq.control`: `1.11.2`

## License Boundary

PGMQ uses the PostgreSQL License.

This allows use, copy, modify, and distribution, but we must preserve the Tembo copyright notice and license text in copied or modified files.

Practical rule for this project:

- It is acceptable to adapt PGMQ source.
- Do not remove upstream copyright/license headers.
- Add our own modification notice when creating an OpenTenBase-specific fork/package.
- Keep a clear `THIRD_PARTY_NOTICES.md` or equivalent when publishing.

## Why PGMQ Is a Better Target Than TimescaleDB

PGMQ is a better first adaptation target because:

- core behavior is SQL object based;
- no background worker is required for the basic queue;
- no C extension is required for the base path;
- queue lifecycle is easy to verify through SQL;
- the PluginCtl value is visible: package lint, plan, deploy, verify, archive, consistency, rollback.

The likely scope is still non-trivial, but it is much more manageable than a full time-series engine.

## Project Shape

Relevant upstream files:

- `pgmq-extension/pgmq.control`: extension metadata.
- `pgmq-extension/sql/pgmq.sql`: main SQL-only implementation.
- `pgmq-extension/sql/pgmq--*.sql`: upgrade scripts.
- `pgmq-extension/test/sql/*.sql`: regression tests.
- `pgmq-extension/test/expected/*.out`: expected outputs.
- `pgmq-rs/`: Rust client and CLI, not required for first OpenTenBase adaptation.

PGMQ supports two installation styles:

- PostgreSQL extension install: copy control and SQL files into the extension directory, then `CREATE EXTENSION pgmq`.
- SQL-only install: execute `pgmq-extension/sql/pgmq.sql` directly.

For OpenTenBase PluginCtl, the SQL-only path is the better first target because it lets us validate behavior without building system packages.

## Core API Surface

The base queue lifecycle includes:

- `pgmq.create(queue_name)`
- `pgmq.create_unlogged(queue_name)`
- `pgmq.create_partitioned(...)`
- `pgmq.send(...)`
- `pgmq.send_batch(...)`
- `pgmq.read(...)`
- `pgmq.read_with_poll(...)`
- `pgmq.pop(...)`
- `pgmq.archive(...)`
- `pgmq.delete(...)`
- `pgmq.metrics(...)`
- `pgmq.metrics_all()`
- `pgmq.list_queues()`
- `pgmq.drop_queue(...)`

For OpenTenBase V1 adaptation, we should start with non-partitioned logged queues only:

- create
- send
- read
- archive
- delete
- metrics
- list_queues
- drop_queue in controlled test database only

Delay these features:

- partitioned queues using `pg_partman`;
- unlogged queues;
- topic routing;
- grouped FIFO;
- polling behavior as a first-class benchmark;
- extension upgrade path.

## Compatibility Risks

The latest upstream SQL contains features that may not work unchanged on the local OpenTenBase build:

- `GENERATED ALWAYS AS (...) STORED` for `topic_bindings.compiled_regex`.
- `GENERATED ALWAYS AS IDENTITY` for queue message IDs.
- `CREATE INDEX ... INCLUDE (...)`.
- `CREATE UNLOGGED TABLE`.
- `pg_monitor` role grants.
- `pg_extension_config_dump` when installed as extension.
- `pg_partman` dependency for partitioned queues.
- declarative partitioning for partitioned queue/archive tables.
- dynamic SQL that creates per-queue tables without OpenTenBase-specific distribution clauses.

Some are probably safe on PG11-derived systems, but they must be tested in OpenTenBase rather than assumed.

## Distributed Semantics Risk

PGMQ depends on database row locking and ordering semantics:

- `FOR UPDATE SKIP LOCKED`
- visibility timeout (`vt`)
- FIFO ordering by `msg_id`
- archive/delete after read

In a distributed OpenTenBase cluster, these semantics may change depending on table distribution. The biggest design decision is not syntax; it is queue-table placement.

Open questions:

1. Should `pgmq.meta` be replicated?
2. Should each queue table be replicated or hash-distributed?
3. If hash-distributed by `msg_id`, can `read(... ORDER BY msg_id FOR UPDATE SKIP LOCKED)` preserve expected global behavior?
4. If replicated, does OpenTenBase create duplicate logical rows or preserve a single logical queue view?
5. Are row locks reliable through the coordinator entrypoint across datanodes?

Until these are answered, do not claim full distributed queue correctness.

## Proposed Adaptation Strategy

### Phase PGMQ-OTB-0: Compatibility experiment

Run upstream `pgmq.sql` in an isolated test database or temporary schema.

Record:

- first failing SQL statement, if any;
- unsupported syntax;
- OpenTenBase distribution warnings;
- whether basic `create/send/read/archive/delete` works;
- whether row locking behaves consistently with two concurrent consumers.

### Phase PGMQ-OTB-1: Minimal OpenTenBase package

Create a new package, probably:

```text
examples/plugins/otb_pgmq/
  LICENSE.upstream
  THIRD_PARTY_NOTICES.md
  manifest.yml
  payload/
    sql/
      install.sql
      verify.sql
      rollback.sql
      removed.sql
```

Do not overwrite upstream reference source. Vendor only the files needed for the OpenTenBase adaptation.

### Phase PGMQ-OTB-2: SQL compatibility patch

Patch only what OpenTenBase requires:

- replace generated stored columns if unsupported;
- avoid or guard `pg_monitor` grants if missing;
- avoid `UNLOGGED` in first version;
- remove `pg_partman` path from first package;
- add explicit OpenTenBase distribution clauses after testing;
- keep function names and behavior close to upstream PGMQ.

### Phase PGMQ-OTB-3: PluginCtl lifecycle

Use PluginCtl as the lifecycle shell:

- `plugin lint otb_pgmq`
- `plugin plan otb_pgmq`
- `plugin precheck otb_pgmq`
- `deploy otb_pgmq`
- `verify otb_pgmq`
- `plugin consistency otb_pgmq`
- `plugin archive inspect otb_pgmq --json`
- `report --json`

Verify SQL should test:

- create test queue;
- send messages;
- read with visibility timeout;
- archive;
- delete;
- metrics;
- drop controlled test queue;
- cleanup.

### Phase PGMQ-OTB-4: Distributed proof

Only after basic behavior passes:

- test two consumers from coordinator;
- test queue table distribution metadata;
- test behavior across coordinator/datanode roles;
- document whether this is coordinator-mediated queueing or true distributed queueing.

## Recommended First Product Positioning

Use this wording:

> `otb_pgmq` is an OpenTenBase adaptation of PGMQ, governed by OpenTenBase PluginCtl. The first version focuses on SQL-only queue lifecycle validation through the coordinator entrypoint. It does not yet claim full distributed queue semantics.

Avoid this wording:

> Fully distributed PGMQ for OpenTenBase.

That would require stronger correctness tests.

## Immediate Next Step

Start OpenTenBase processes, then run a temporary SQL compatibility test:

1. Create isolated database or schema.
2. Execute upstream `pgmq-extension/sql/pgmq.sql`.
3. If it fails, record the exact failing SQL and error.
4. If it succeeds, run minimal queue lifecycle:
   - `pgmq.create`
   - `pgmq.send`
   - `pgmq.read`
   - `pgmq.archive`
   - `pgmq.delete`
   - `pgmq.drop_queue`
5. Drop the isolated database/schema.

Do not publish an adapted package until this compatibility result is recorded.

## Initial OpenTenBase Compatibility Result

Date: 2026-05-22

Environment:

- Docker containers: `opentenbaseDN1`, `opentenbaseDN2`, `opentenbaseCN`
- Coordinator entrypoint: `127.0.0.1:30004`
- Temporary database: `pgmq_compat_test`
- Upstream SQL: `pgmq-extension/sql/pgmq.sql`

### Unmodified upstream result

Unmodified upstream `pgmq.sql` does not install successfully.

First failure:

```text
ERROR: Hash/Modulo distribution column does not refer to hash/modulo distribution column in referenced table.
```

Failing area:

- `pgmq.notify_insert_throttle.queue_name` references `pgmq.meta(queue_name)`.

Interpretation:

- OpenTenBase distribution rules reject the upstream metadata foreign key as written.
- This is a distributed database compatibility issue, not a PGMQ business logic issue.

### Temporary experiment patch

For discovery only, a temporary SQL copy was tested with:

- metadata foreign keys removed from `notify_insert_throttle` and `topic_bindings`;
- generated stored column `topic_bindings.compiled_regex` changed to a plain nullable column;
- `CREATE INDEX ... INCLUDE (...)` changed to a simple index.

With those temporary changes, the SQL installed successfully in the temporary database.

Additional compatibility failures discovered before the temporary patch succeeded:

```text
ERROR: syntax error at or near "("
LINE 6: compiled_regex text GENERATED ALWAYS AS (
```

```text
ERROR: syntax error at or near "INCLUDE"
LINE 1: ... topic_bindings (pattern) INCLUDE (...)
```

### Minimal queue smoke result

After the temporary compatibility patch, these operations worked:

- `pgmq.create('otb_q3')`
- `pgmq.send('otb_q3', '{"hello":"world"}'::jsonb)`
- `pgmq.read('otb_q3', 0, 1)`
- `pgmq.delete('otb_q3', 1::bigint)`
- `pgmq.metrics('otb_q3')`
- `pgmq.drop_queue('otb_q3')`

Observed successful read:

```text
msg_id | read_ct | message
------+---------+--------------------
1     | 1       | {"hello": "world"}
```

### Archive failure

`pgmq.archive('otb_q3', 1::bigint)` failed:

```text
ERROR: INSERT/UPDATE/DELETE is not supported in subquery
CONTEXT: WITH archived AS (
    DELETE FROM pgmq.q_otb_q3
    ...
)
INSERT INTO pgmq.a_otb_q3 ...
```

Interpretation:

- OpenTenBase does not support PGMQ's writable CTE pattern here.
- Archive can likely be rewritten as explicit PL/pgSQL steps:
  1. select message row into a record;
  2. insert into archive table;
  3. delete from queue table;
  4. return message id;
  5. keep transaction atomic.

This rewrite must preserve concurrent consumer semantics.

### Cleanup

The temporary database `pgmq_compat_test` was dropped after testing.

No adapted PGMQ package was committed in this step.

## Current Adaptation Verdict

PGMQ is a viable OpenTenBase adaptation target.

It is not "copy and run" compatible, but the first failures are concentrated:

1. OpenTenBase distribution and foreign key constraints.
2. Unsupported generated stored column syntax.
3. Unsupported `INCLUDE` index syntax.
4. Unsupported writable CTE in archive.

The base queue path `create/send/read/delete/metrics/drop_queue` can work after small compatibility edits.

Recommended next implementation target:

- Create `otb_pgmq` as a PluginCtl-governed adapted package.
- Start with non-partitioned logged queues.
- Exclude partitioned queues, topic routing, unlogged queues, and Rust client integration from the first version.
- Add explicit OpenTenBase compatibility comments for every deviation from upstream.

## MVP Package Status

Status: implemented as `examples/plugins/otb_pgmq`.

Files:

- `examples/plugins/otb_pgmq/manifest.yml`
- `examples/plugins/otb_pgmq/LICENSE.upstream`
- `examples/plugins/otb_pgmq/THIRD_PARTY_NOTICES.md`
- `examples/plugins/otb_pgmq/payload/sql/install.sql`
- `examples/plugins/otb_pgmq/payload/sql/verify.sql`
- `examples/plugins/otb_pgmq/payload/sql/rollback.sql`

Implemented scope:

- SQL-only installation through PluginCtl.
- Non-partitioned logged queue lifecycle.
- `pgmq.version()` installed probe.
- Smoke verify covering:
  - create queue;
  - send two messages;
  - read message;
  - archive message;
  - delete message;
  - check queue/archive counts;
  - drop smoke queue.
- Rollback drops the adapted `pgmq` schema and is intended only for this controlled `otb_pgmq` package.

Real OpenTenBase validation:

- `python -m datanexus plugin precheck otb_pgmq` passed.
- `python -m datanexus deploy otb_pgmq` passed.
- `python -m datanexus verify otb_pgmq` passed.
- `python -m datanexus rollback otb_pgmq` produced a dry-run plan.
- `python -m datanexus rollback otb_pgmq --execute` passed.
- `python -m datanexus verify otb_pgmq --removed` passed.
- A final redeploy and verify passed, leaving `otb_pgmq` installed in the local test environment.

Out of scope for this MVP:

- partitioned queues;
- `pg_partman` integration;
- unlogged queues;
- topic routing correctness;
- grouped FIFO correctness under concurrency;
- Rust client/CLI integration;
- full distributed queue correctness claims.

Next validation target:

- two concurrent coordinator consumers reading from the same queue;
- explicit table distribution inspection for `pgmq.meta`, queue tables, and archive tables;
- decide whether additional OpenTenBase `DISTRIBUTE BY ...` clauses should be added.

## Concurrent Consumer Probe

Date: 2026-05-22

Purpose:

- Check whether two coordinator-side consumers can concurrently read and delete from the same `otb_pgmq` queue without duplicate or missing reads.

Setup:

- Queue: `concurrent_probe3`
- Messages inserted: 100
- Queue table: `pgmq.q_concurrent_probe3`
- Archive table: `pgmq.a_concurrent_probe3`
- Distribution catalog: both queue and archive tables were OpenTenBase distributed tables on the two datanodes in earlier `dist_probe` inspection.

Method:

- Capture actual `msg_id` values from `pgmq.q_concurrent_probe3` as the expected set.
- Run two shell consumers in parallel.
- Each consumer loops 60 times:
  - `pgmq.read('concurrent_probe3', 30, 1)`
  - `pgmq.delete('concurrent_probe3', msg_id)`
- Compare actual consumed IDs against the expected set.

Result:

```text
expected_count=100
consumer_a_count=52
consumer_b_count=48
total_read=100
unique_read=100
duplicates_count=0
missing_count=0
unexpected_count=0
expected_min=1
expected_max=122
actual_min=1
actual_max=122
remaining_rows=0
```

Interpretation:

- The first basic two-consumer concurrency probe passed.
- No duplicate reads were observed.
- No missing messages were observed.
- All queue rows were consumed and deleted.
- `msg_id` values were not contiguous under OpenTenBase distributed execution, so tests must compare against the actual inserted ID set rather than assuming `1..N`.

Remaining work:

- Repeat with larger batches.
- Repeat from two coordinator endpoints if both are externally reachable.
- Test visibility timeout behavior when a consumer reads but does not delete.
- Test archive under concurrent consumers.
- Inspect whether explicit `DISTRIBUTE BY` clauses would produce more predictable queue placement.

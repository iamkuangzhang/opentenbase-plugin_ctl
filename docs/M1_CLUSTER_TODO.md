# M1 Cluster Status/Start TODO

`plugin_ctl cluster status` is implemented as a read-only command. `cluster
start` remains a design note and is not implemented.

## Why This Comes Before Complex Rollback

Local development repeatedly hits the same operational problem: Docker
containers can be running while the OpenTenBase processes inside them are not.
When GTM, CN, or DN processes are down, plugin lifecycle commands fail before
they can test platform behavior.

For M1, a narrow local-only cluster helper has higher practical value than
building destructive rollback behavior early.

## `plugin_ctl cluster status`

The first version checks only the current local Docker topology:

- Docker CLI is available.
- Expected containers exist and are running:
  - `opentenbaseCN`
  - `opentenbaseDN1`
  - `opentenbaseDN2`
- DN1 contains a running GTM process.
- DN1 contains running `dn001` and coordinator processes.
- DN2 contains running `dn002` and coordinator processes.
- DN1 coordinator accepts `psql` on `127.0.0.1:30004`.
- `pgxc_node` reports the expected CN/DN endpoints.
- Each registered CN/DN endpoint is reachable using the existing runtime probe.

The command returns a table similar to `doctor`, but scoped to process and
cluster liveness rather than plugin readiness. It does not start, stop, or
modify containers.

## `plugin_ctl cluster start`

This remains TODO. First version should be explicit and local-environment-only. It can call the
same validated startup commands currently used manually:

- In `opentenbaseDN1`:
  - add OpenTenBase binaries to `PATH`
  - remove stale GTM, DN, and coordinator pid files
  - start GTM on port `50001`
  - start `dn001`
  - start coordinator
- In `opentenbaseDN2`:
  - add OpenTenBase binaries to `PATH`
  - remove stale DN and coordinator pid files
  - start `dn002`
  - start coordinator

After starting processes, it should run the same checks as `cluster status`.

## Guardrails

- Do not make this a general OpenTenBase installer.
- Do not hide failed process startup; surface logs or log paths.
- Do not assume production topology.
- Keep defaults tied to the current Docker names until a config file exists.
- Prefer `cluster status` first; add `cluster start` only after status behavior is stable.

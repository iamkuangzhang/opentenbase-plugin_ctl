from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class ClusterCheck:
    name: str
    ok: bool
    detail: str


class ClusterRuntime(Protocol):
    container: str

    def docker_available(self) -> bool:
        ...

    def list_container_statuses(self) -> dict[str, str]:
        ...

    def exec(self, *args: str):
        ...

    def run_sql(self, sql: str):
        ...

    def run_sql_at(self, host: str, port: int, sql: str):
        ...


EXPECTED_CONTAINERS = ["opentenbaseCN", "opentenbaseDN1", "opentenbaseDN2"]


def _check_process(runtime_factory, container: str, name: str, pattern: str) -> ClusterCheck:
    runtime = runtime_factory(container)
    result = runtime.exec("bash", "-lc", f"ps -ef | grep -E '{pattern}' | grep -v grep")
    return ClusterCheck(
        name=name,
        ok=result.returncode == 0 and bool(result.stdout.strip()),
        detail="running" if result.returncode == 0 and result.stdout.strip() else result.stderr.strip() or "not running",
    )


def _check_registered_nodes(runtime: ClusterRuntime) -> ClusterCheck:
    node_result = runtime.run_sql(
        "SELECT node_name || '|' || node_type || '|' || node_host || '|' || node_port "
        "FROM pgxc_node WHERE node_type IN ('C', 'D') ORDER BY node_name;"
    )
    if node_result.returncode != 0:
        return ClusterCheck(
            "registered_nodes",
            False,
            node_result.stderr.strip() or node_result.stdout.strip() or "failed to read pgxc_node",
        )

    failed_nodes: list[str] = []
    seen_nodes = 0
    for line in node_result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        seen_nodes += 1
        name, node_type, host, port = line.split("|", 3)
        probe = runtime.run_sql_at(host, int(port), "SELECT 1;")
        if probe.returncode != 0 or probe.stdout.strip() != "1":
            failed_nodes.append(f"{name}({node_type}) {host}:{port}")

    if seen_nodes == 0:
        return ClusterCheck("registered_nodes", False, "no CN/DN rows found in pgxc_node")
    return ClusterCheck(
        "registered_nodes",
        not failed_nodes,
        f"{seen_nodes} registered CN/DN reachable" if not failed_nodes else "unreachable: " + ", ".join(failed_nodes),
    )


def run_cluster_status(runtime_factory) -> list[ClusterCheck]:
    runtime = runtime_factory("opentenbaseDN1")
    checks: list[ClusterCheck] = []

    if not runtime.docker_available():
        return [ClusterCheck("docker", False, "docker cli not found")]
    checks.append(ClusterCheck("docker", True, "docker cli available"))

    statuses = runtime.list_container_statuses()
    for container in EXPECTED_CONTAINERS:
        status = statuses.get(container)
        checks.append(
            ClusterCheck(
                f"container:{container}",
                status is not None and status.startswith("Up "),
                status if status is not None else "missing",
            )
        )

    checks.extend(
        [
            _check_process(runtime_factory, "opentenbaseDN1", "process:gtm", r"gtm -D /data/opentenbase/data/gtm"),
            _check_process(runtime_factory, "opentenbaseDN1", "process:dn001", r"postgres --datanode -D /data/opentenbase/data/dn001"),
            _check_process(runtime_factory, "opentenbaseDN1", "process:cn001", r"postgres --coordinator -D /data/opentenbase/data/coord"),
            _check_process(runtime_factory, "opentenbaseDN2", "process:dn002", r"postgres --datanode -D /data/opentenbase/data/dn002"),
            _check_process(runtime_factory, "opentenbaseDN2", "process:cn002", r"postgres --coordinator -D /data/opentenbase/data/coord"),
        ]
    )

    psql_result = runtime.run_sql("SELECT 1;")
    checks.append(
        ClusterCheck(
            "psql:30004",
            psql_result.returncode == 0 and psql_result.stdout.strip() == "1",
            psql_result.stdout.strip() or psql_result.stderr.strip() or "psql probe failed",
        )
    )
    checks.append(_check_registered_nodes(runtime))
    return checks

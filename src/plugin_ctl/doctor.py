from __future__ import annotations

from dataclasses import dataclass

from .runtime.opentenbase import OpenTenBaseRuntime


@dataclass(slots=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str


def run_doctor(runtime: OpenTenBaseRuntime) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []

    if runtime.docker_available():
        checks.append(DoctorCheck("docker", True, "docker cli available"))
    else:
        checks.append(DoctorCheck("docker", False, "docker cli not found"))
        return checks

    containers = runtime.list_containers()
    expected = ["opentenbaseCN", "opentenbaseDN1", "opentenbaseDN2"]
    missing = [name for name in expected if name not in containers]
    checks.append(
        DoctorCheck(
            "containers",
            not missing,
            "all expected containers running" if not missing else f"missing: {', '.join(missing)}",
        )
    )

    psql_result = runtime.run_sql("SELECT 1;")
    checks.append(
        DoctorCheck(
            "psql",
            psql_result.returncode == 0 and psql_result.stdout.strip() == "1",
            psql_result.stdout.strip() or psql_result.stderr.strip() or "psql probe failed",
        )
    )

    version_result = runtime.run_sql("SELECT otb_ts.version();")
    checks.append(
        DoctorCheck(
            "plugin_probe",
            version_result.returncode == 0,
            version_result.stdout.strip() or version_result.stderr.strip() or "plugin probe failed",
        )
    )

    node_result = runtime.run_sql(
        "SELECT node_name || '|' || node_type || '|' || node_host || '|' || node_port "
        "FROM pgxc_node WHERE node_type IN ('C', 'D') ORDER BY node_name;"
    )
    if node_result.returncode != 0:
        checks.append(
            DoctorCheck(
                "registered_nodes",
                False,
                node_result.stderr.strip() or node_result.stdout.strip() or "failed to read pgxc_node",
            )
        )
        return checks

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
        checks.append(DoctorCheck("registered_nodes", False, "no CN/DN rows found in pgxc_node"))
    else:
        checks.append(
            DoctorCheck(
                "registered_nodes",
                not failed_nodes,
                f"{seen_nodes} registered CN/DN reachable" if not failed_nodes else "unreachable: " + ", ".join(failed_nodes),
            )
        )

    return checks

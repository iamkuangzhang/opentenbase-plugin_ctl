from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tomllib
from typing import Protocol


@dataclass(slots=True)
class ClusterCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True, slots=True)
class ClusterNode:
    name: str
    role: str
    host: str
    ssh_port: int
    db_port: int
    ssh_user: str
    db_user: str
    database: str
    lib_dir: str
    extension_dir: str


@dataclass(frozen=True, slots=True)
class ClusterConfig:
    name: str
    nodes: tuple[ClusterNode, ...]

    @property
    def coordinators(self) -> tuple[ClusterNode, ...]:
        return tuple(node for node in self.nodes if node.role == "cn")

    @property
    def datanodes(self) -> tuple[ClusterNode, ...]:
        return tuple(node for node in self.nodes if node.role == "dn")


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
VALID_CLUSTER_ROLES = {"cn", "dn"}
REQUIRED_NODE_FIELDS = {
    "name",
    "role",
    "host",
    "ssh_port",
    "db_port",
    "ssh_user",
    "db_user",
    "database",
    "lib_dir",
    "extension_dir",
}


DEFAULT_CLUSTER_NAME = "local-opentenbase"
DEFAULT_SSH_PORT = 22
DEFAULT_SSH_USER = "opentenbase"
DEFAULT_DB_USER = "opentenbase"
DEFAULT_DATABASE = "postgres"
DEFAULT_LIB_DIR = "/data/opentenbase/install/opentenbase_bin_v2.0/lib/postgresql"
DEFAULT_EXTENSION_DIR = "/data/opentenbase/install/opentenbase_bin_v2.0/share/postgresql/extension"


def default_cluster_config_path() -> Path:
    override = os.getenv("OPENTENBASE_PLUGINCTL_CLUSTER_FILE")
    if override:
        return Path(override)
    return Path.home() / ".plugin_ctl" / "cluster.toml"


def find_cluster_config(explicit_path: str | Path | None = None) -> Path | None:
    if explicit_path is not None:
        return Path(explicit_path)
    cwd_candidate = Path.cwd() / "cluster.toml"
    if cwd_candidate.exists():
        return cwd_candidate
    home_candidate = default_cluster_config_path()
    if home_candidate.exists():
        return home_candidate
    return None


def require_cluster_config(explicit_path: str | Path | None = None) -> Path:
    path = find_cluster_config(explicit_path)
    if path is None:
        raise ValueError(
            "cluster config not found; run 'plugin_ctl cluster init' or pass '-f cluster.toml'"
        )
    return path


def load_cluster_config(path: str | Path) -> ClusterConfig:
    config_path = Path(path)
    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    raw_cluster = raw.get("cluster", {})
    if raw_cluster is None:
        raw_cluster = {}
    if not isinstance(raw_cluster, dict):
        raise ValueError("[cluster] must be a table when declared")
    cluster_name = str(raw_cluster.get("name") or config_path.stem)

    raw_nodes = raw.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError("cluster.toml must contain at least one [[nodes]] entry")

    seen_names: set[str] = set()
    nodes: list[ClusterNode] = []
    for index, raw_node in enumerate(raw_nodes, start=1):
        if not isinstance(raw_node, dict):
            raise ValueError(f"node #{index} must be a table")

        missing = sorted(field for field in REQUIRED_NODE_FIELDS if field not in raw_node)
        if missing:
            raise ValueError(f"node #{index} missing required fields: {', '.join(missing)}")

        name = str(raw_node["name"])
        if name in seen_names:
            raise ValueError(f"duplicate node name: {name}")
        seen_names.add(name)

        role = str(raw_node["role"])
        if role not in VALID_CLUSTER_ROLES:
            raise ValueError(f"node {name} has invalid role: {role}")

        nodes.append(
            ClusterNode(
                name=name,
                role=role,
                host=str(raw_node["host"]),
                ssh_port=int(raw_node["ssh_port"]),
                db_port=int(raw_node["db_port"]),
                ssh_user=str(raw_node["ssh_user"]),
                db_user=str(raw_node["db_user"]),
                database=str(raw_node["database"]),
                lib_dir=str(raw_node["lib_dir"]),
                extension_dir=str(raw_node["extension_dir"]),
            )
        )

    return ClusterConfig(name=cluster_name, nodes=tuple(nodes))


def discover_cluster_config(
    runtime: ClusterRuntime,
    *,
    name: str = DEFAULT_CLUSTER_NAME,
    ssh_user: str = DEFAULT_SSH_USER,
    db_user: str = DEFAULT_DB_USER,
    database: str = DEFAULT_DATABASE,
    ssh_port: int = DEFAULT_SSH_PORT,
    lib_dir: str = DEFAULT_LIB_DIR,
    extension_dir: str = DEFAULT_EXTENSION_DIR,
) -> ClusterConfig:
    result = runtime.run_sql(
        "SELECT node_name || '|' || node_type || '|' || node_host || '|' || node_port "
        "FROM pgxc_node WHERE node_type IN ('C', 'D') ORDER BY node_type, node_name;"
    )
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or result.stdout.strip() or "failed to read pgxc_node")

    nodes: list[ClusterNode] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) != 4:
            raise ValueError(f"unexpected pgxc_node row: {line}")
        node_name, node_type, host, db_port = parts
        role = {"C": "cn", "D": "dn"}.get(node_type)
        if role is None:
            continue
        nodes.append(
            ClusterNode(
                name=node_name,
                role=role,
                host=host,
                ssh_port=ssh_port,
                db_port=int(db_port),
                ssh_user=ssh_user,
                db_user=db_user,
                database=database,
                lib_dir=lib_dir,
                extension_dir=extension_dir,
            )
        )

    if not nodes:
        raise ValueError("no CN/DN rows found in pgxc_node")
    return ClusterConfig(name=name, nodes=tuple(nodes))


def render_cluster_config(config: ClusterConfig) -> str:
    lines = [
        "# Generated by OpenTenBase PluginCtl.",
        "# Review host, ssh_user, lib_dir, and extension_dir before executing physical distribution.",
        "",
        "[cluster]",
        f'name = "{config.name}"',
        "",
    ]
    for node in config.nodes:
        lines.extend(
            [
                "[[nodes]]",
                f'name = "{node.name}"',
                f'role = "{node.role}"',
                f'host = "{node.host}"',
                f"ssh_port = {node.ssh_port}",
                f"db_port = {node.db_port}",
                f'ssh_user = "{node.ssh_user}"',
                f'db_user = "{node.db_user}"',
                f'database = "{node.database}"',
                f'lib_dir = "{node.lib_dir}"',
                f'extension_dir = "{node.extension_dir}"',
                "",
            ]
        )
    return "\n".join(lines)


def write_cluster_config(config: ClusterConfig, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_cluster_config(config), encoding="utf-8")
    return target


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

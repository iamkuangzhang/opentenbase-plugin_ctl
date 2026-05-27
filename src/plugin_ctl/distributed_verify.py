from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath

from .activation import CoordinatorSqlResult, CoordinatorSqlExecutor, extension_name_for, extension_version_sql
from .cluster import ClusterConfig, ClusterNode
from .distribution import physical_payload_files
from .manifest import PluginManifest
from .runtime.opentenbase import RemoteNodeExecutor


PREPARED_XACT_SQL = "SELECT gid, prepared, owner, database FROM pg_prepared_xacts;"


@dataclass(frozen=True, slots=True)
class CoordinatorExtensionCheck:
    node: str
    connected_status: str
    extension_status: str
    detected_version: str
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class FileVerifyResult:
    node: str
    role: str
    file_type: str
    local_path: str
    remote_path: str
    file_status: str
    local_sha256: str
    remote_sha256: str
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class PreparedXactInfo:
    gid: str
    prepared: str
    owner: str
    database: str


@dataclass(frozen=True, slots=True)
class PreparedXactScan:
    node: str
    role: str
    status: str
    prepared_transactions_count: int
    transactions: tuple[PreparedXactInfo, ...]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class ConnectivityCheck:
    node: str
    role: str
    connected_status: str
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class DistributedVerifySummary:
    total_cn: int
    total_dn: int
    extension_consistent: bool
    files_checked: int
    checksum_failed: int
    prepared_leak: bool
    failed: int


@dataclass(frozen=True, slots=True)
class DistributedVerifyReport:
    cluster: str
    plugin_id: str
    extension_name: str
    mode: str
    physical_distribution: str
    create_extension: str
    coordinator_extensions: tuple[CoordinatorExtensionCheck, ...]
    file_checks: tuple[FileVerifyResult, ...]
    prepared_transactions: tuple[PreparedXactScan, ...]
    connectivity: tuple[ConnectivityCheck, ...]
    summary: DistributedVerifySummary
    errors: tuple[str, ...]


def _local_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_type(path: Path) -> str:
    if path.suffix.lower() == ".so":
        return "shared_library"
    if path.suffix.lower() == ".control":
        return "extension_control"
    if path.suffix.lower() == ".sql":
        return "sql"
    return "unsupported"


def _remote_path(node: ClusterNode, local_path: Path) -> str:
    if local_path.suffix.lower() == ".so":
        return str(PurePosixPath(node.lib_dir) / local_path.name)
    if local_path.suffix.lower() in {".control", ".sql"}:
        return str(PurePosixPath(node.extension_dir) / local_path.name)
    raise ValueError(f"unsupported payload file type: {local_path}")


def _remote_sha256(stdout: str) -> str:
    parts = stdout.strip().split()
    return parts[0] if parts else ""


def run_distributed_verify(
    cluster: ClusterConfig,
    manifest: PluginManifest,
    sql_executor: CoordinatorSqlExecutor,
    remote_executor: RemoteNodeExecutor,
) -> DistributedVerifyReport:
    extension_name = extension_name_for(manifest)
    nodes = (*cluster.coordinators, *cluster.datanodes)
    connectivity = _check_connectivity(nodes, sql_executor)
    coordinator_extensions = _check_coordinator_extensions(cluster.coordinators, extension_name, sql_executor)
    file_checks = _check_files(cluster, manifest, remote_executor)
    prepared_transactions = _scan_prepared_transactions(nodes, sql_executor)
    errors = _errors(connectivity, coordinator_extensions, file_checks, prepared_transactions)
    summary = _summary(cluster, coordinator_extensions, file_checks, prepared_transactions, connectivity, errors)
    return DistributedVerifyReport(
        cluster=cluster.name,
        plugin_id=manifest.plugin_id,
        extension_name=extension_name,
        mode="distributed-verify",
        physical_distribution="not_executed",
        create_extension="not_executed",
        coordinator_extensions=coordinator_extensions,
        file_checks=file_checks,
        prepared_transactions=prepared_transactions,
        connectivity=connectivity,
        summary=summary,
        errors=tuple(errors),
    )


def _check_connectivity(nodes: tuple[ClusterNode, ...], executor: CoordinatorSqlExecutor) -> tuple[ConnectivityCheck, ...]:
    return tuple(_connect_one(node, executor) for node in nodes)


def _connect_one(node: ClusterNode, executor: CoordinatorSqlExecutor) -> ConnectivityCheck:
    try:
        result = executor.run_sql(node, "SELECT 1;")
    except Exception as exc:
        return ConnectivityCheck(node.name, node.role, "failed", 1, "", str(exc))
    connected = result.returncode == 0 and result.stdout.strip() == "1"
    return ConnectivityCheck(
        node=node.name,
        role=node.role,
        connected_status="connected" if connected else "failed",
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def _check_coordinator_extensions(
    coordinators: tuple[ClusterNode, ...],
    extension_name: str,
    executor: CoordinatorSqlExecutor,
) -> tuple[CoordinatorExtensionCheck, ...]:
    sql = extension_version_sql(extension_name)
    checks: list[CoordinatorExtensionCheck] = []
    with ThreadPoolExecutor(max_workers=max(1, len(coordinators))) as pool:
        futures = {pool.submit(executor.run_sql, node, sql): node for node in coordinators}
        for future in as_completed(futures):
            node = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                checks.append(CoordinatorExtensionCheck(node.name, "failed", "query_failed", "", 1, "", str(exc)))
                continue
            version = result.stdout.strip()
            if result.returncode != 0:
                connected_status = "failed"
                extension_status = "query_failed"
            elif version:
                connected_status = "connected"
                extension_status = "installed"
            else:
                connected_status = "connected"
                extension_status = "missing"
            checks.append(
                CoordinatorExtensionCheck(
                    node=node.name,
                    connected_status=connected_status,
                    extension_status=extension_status,
                    detected_version=version,
                    returncode=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            )
    by_name = {check.node: check for check in checks}
    return tuple(by_name[node.name] for node in coordinators)


def _check_files(cluster: ClusterConfig, manifest: PluginManifest, executor: RemoteNodeExecutor) -> tuple[FileVerifyResult, ...]:
    payload_files = physical_payload_files(manifest)
    nodes = (*cluster.coordinators, *cluster.datanodes)
    jobs = [(node, path) for node in nodes for path in payload_files]
    if not jobs:
        return ()
    results: list[FileVerifyResult] = []
    with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
        futures = {pool.submit(_check_one_file, node, path, executor): (node, path) for node, path in jobs}
        for future in as_completed(futures):
            node, path = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(
                    FileVerifyResult(
                        node=node.name,
                        role=node.role,
                        file_type=_file_type(path),
                        local_path=str(path),
                        remote_path="",
                        file_status="query_failed",
                        local_sha256="",
                        remote_sha256="",
                        returncode=1,
                        stdout="",
                        stderr=str(exc),
                    )
                )
    return tuple(sorted(results, key=lambda item: (item.node, item.local_path, item.remote_path)))


def _check_one_file(node: ClusterNode, local_path: Path, executor: RemoteNodeExecutor) -> FileVerifyResult:
    remote_path = _remote_path(node, local_path)
    local_digest = _local_sha256(local_path) if local_path.exists() and local_path.is_file() else ""
    result = executor.sha256_file(node, remote_path)
    remote_digest = _remote_sha256(result.stdout)
    if result.returncode != 0:
        status = "missing"
    elif local_digest and local_digest == remote_digest:
        status = "ok"
    else:
        status = "checksum_failed"
    return FileVerifyResult(
        node=node.name,
        role=node.role,
        file_type=_file_type(local_path),
        local_path=str(local_path),
        remote_path=remote_path,
        file_status=status,
        local_sha256=local_digest,
        remote_sha256=remote_digest,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def _scan_prepared_transactions(nodes: tuple[ClusterNode, ...], executor: CoordinatorSqlExecutor) -> tuple[PreparedXactScan, ...]:
    scans: list[PreparedXactScan] = []
    with ThreadPoolExecutor(max_workers=max(1, len(nodes))) as pool:
        futures = {pool.submit(executor.run_sql, node, PREPARED_XACT_SQL): node for node in nodes}
        for future in as_completed(futures):
            node = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                scans.append(PreparedXactScan(node.name, node.role, "query_failed", 0, (), 1, "", str(exc)))
                continue
            if result.returncode != 0:
                scans.append(PreparedXactScan(node.name, node.role, "query_failed", 0, (), result.returncode, result.stdout, result.stderr))
                continue
            transactions = _parse_prepared_xacts(result.stdout)
            scans.append(
                PreparedXactScan(
                    node=node.name,
                    role=node.role,
                    status="leak" if transactions else "ok",
                    prepared_transactions_count=len(transactions),
                    transactions=transactions,
                    returncode=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            )
    by_name = {scan.node: scan for scan in scans}
    return tuple(by_name[node.name] for node in nodes)


def _parse_prepared_xacts(stdout: str) -> tuple[PreparedXactInfo, ...]:
    rows: list[PreparedXactInfo] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        while len(parts) < 4:
            parts.append("")
        rows.append(PreparedXactInfo(parts[0], parts[1], parts[2], parts[3]))
    return tuple(rows)


def _errors(
    connectivity: tuple[ConnectivityCheck, ...],
    coordinator_extensions: tuple[CoordinatorExtensionCheck, ...],
    file_checks: tuple[FileVerifyResult, ...],
    prepared_transactions: tuple[PreparedXactScan, ...],
) -> list[str]:
    errors: list[str] = []
    for item in connectivity:
        if item.connected_status != "connected":
            errors.append(f"{item.node}: connection failed: {item.stderr.strip() or item.stdout.strip() or item.returncode}")
    for item in coordinator_extensions:
        if item.extension_status != "installed":
            errors.append(f"{item.node}: extension {item.extension_status}")
    versions = {item.detected_version for item in coordinator_extensions if item.extension_status == "installed"}
    if len(versions) > 1:
        errors.append("coordinator extension version mismatch: " + ", ".join(sorted(versions)))
    for item in file_checks:
        if item.file_status != "ok":
            errors.append(f"{item.node}: file {item.file_status}: {item.remote_path}")
    for item in prepared_transactions:
        if item.status == "query_failed":
            errors.append(f"{item.node}: prepared transaction query failed")
        elif item.prepared_transactions_count > 0:
            errors.append(f"{item.node}: prepared transaction residue found; manual confirmation required")
    return errors


def _summary(
    cluster: ClusterConfig,
    coordinator_extensions: tuple[CoordinatorExtensionCheck, ...],
    file_checks: tuple[FileVerifyResult, ...],
    prepared_transactions: tuple[PreparedXactScan, ...],
    connectivity: tuple[ConnectivityCheck, ...],
    errors: list[str],
) -> DistributedVerifySummary:
    versions = {item.detected_version for item in coordinator_extensions if item.extension_status == "installed"}
    extension_consistent = (
        len(coordinator_extensions) == len(cluster.coordinators)
        and all(item.extension_status == "installed" for item in coordinator_extensions)
        and len(versions) == 1
    )
    checksum_failed = len([item for item in file_checks if item.file_status == "checksum_failed"])
    prepared_leak = any(item.prepared_transactions_count > 0 for item in prepared_transactions)
    failed = len(errors)
    return DistributedVerifySummary(
        total_cn=len(cluster.coordinators),
        total_dn=len(cluster.datanodes),
        extension_consistent=extension_consistent,
        files_checked=len(file_checks),
        checksum_failed=checksum_failed,
        prepared_leak=prepared_leak,
        failed=failed,
    )


def distributed_verify_report_json(report: DistributedVerifyReport) -> dict[str, object]:
    return {
        "cluster": report.cluster,
        "plugin_id": report.plugin_id,
        "extension_name": report.extension_name,
        "mode": report.mode,
        "physical_distribution": report.physical_distribution,
        "create_extension": report.create_extension,
        "coordinator_extensions": [
            {
                "node": item.node,
                "connected_status": item.connected_status,
                "extension_status": item.extension_status,
                "detected_version": item.detected_version,
                "returncode": item.returncode,
                "stdout": item.stdout,
                "stderr": item.stderr,
            }
            for item in report.coordinator_extensions
        ],
        "file_checks": [
            {
                "node": item.node,
                "role": item.role,
                "file_type": item.file_type,
                "local_path": item.local_path,
                "remote_path": item.remote_path,
                "file_status": item.file_status,
                "local_sha256": item.local_sha256,
                "remote_sha256": item.remote_sha256,
                "returncode": item.returncode,
                "stdout": item.stdout,
                "stderr": item.stderr,
            }
            for item in report.file_checks
        ],
        "prepared_transactions": [
            {
                "node": item.node,
                "role": item.role,
                "status": item.status,
                "prepared_transactions_count": item.prepared_transactions_count,
                "transactions": [
                    {
                        "gid": tx.gid,
                        "prepared": tx.prepared,
                        "owner": tx.owner,
                        "database": tx.database,
                    }
                    for tx in item.transactions
                ],
                "returncode": item.returncode,
                "stdout": item.stdout,
                "stderr": item.stderr,
            }
            for item in report.prepared_transactions
        ],
        "summary": {
            "total_cn": report.summary.total_cn,
            "total_dn": report.summary.total_dn,
            "extension_consistent": report.summary.extension_consistent,
            "files_checked": report.summary.files_checked,
            "checksum_failed": report.summary.checksum_failed,
            "prepared_leak": report.summary.prepared_leak,
            "failed": report.summary.failed,
        },
        "errors": list(report.errors),
    }

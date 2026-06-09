from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import re
import subprocess
from typing import Protocol

from .cluster import ClusterConfig, ClusterNode
from .manifest import PluginManifest


IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class CoordinatorSqlResult:
    node: str
    sql: str
    returncode: int
    stdout: str
    stderr: str


class CoordinatorSqlExecutor(Protocol):
    def run_sql(self, node: ClusterNode, sql: str) -> CoordinatorSqlResult:
        ...


@dataclass(slots=True)
class PsqlCoordinatorExecutor:
    timeout_seconds: int = 30

    def run_sql(self, node: ClusterNode, sql: str) -> CoordinatorSqlResult:
        argv = [
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-h",
            node.host,
            "-p",
            str(node.db_port),
            "-U",
            node.db_user,
            "-d",
            node.database,
            "-Atc",
            sql,
        ]
        try:
            result = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            return CoordinatorSqlResult(
                node=node.name,
                sql=sql,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        except subprocess.TimeoutExpired as exc:
            return CoordinatorSqlResult(
                node=node.name,
                sql=sql,
                returncode=124,
                stdout=exc.stdout or "",
                stderr=f"command timed out after {self.timeout_seconds}s",
            )


@dataclass(frozen=True, slots=True)
class ActivationResult:
    node: str
    status: str
    sql: str
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class VersionCheckResult:
    node: str
    status: str
    detected_version: str
    sql: str
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class ActivationSummary:
    total_cn: int
    activated: int
    failed: int
    missing: int
    version_mismatch: bool


@dataclass(frozen=True, slots=True)
class ActivationReport:
    cluster: str
    plugin_id: str
    extension_name: str
    mode: str
    physical_distribution: str
    datanodes: str
    activation: tuple[ActivationResult, ...]
    versions: tuple[VersionCheckResult, ...]
    summary: ActivationSummary
    errors: tuple[str, ...]


def extension_name_for(manifest: PluginManifest) -> str:
    raw = manifest.payload.get("extension_name") or manifest.payload.get("extension") or manifest.plugin_id
    extension_name = str(raw)
    if not IDENTIFIER_RE.fullmatch(extension_name):
        raise ValueError(f"invalid extension_name: {extension_name}")
    return extension_name


def create_extension_sql(extension_name: str) -> str:
    if not IDENTIFIER_RE.fullmatch(extension_name):
        raise ValueError(f"invalid extension_name: {extension_name}")
    return f"CREATE EXTENSION IF NOT EXISTS {extension_name};"


def extension_version_sql(extension_name: str) -> str:
    if not IDENTIFIER_RE.fullmatch(extension_name):
        raise ValueError(f"invalid extension_name: {extension_name}")
    return f"SELECT extversion FROM pg_extension WHERE extname = '{extension_name}';"


def dry_run_activation_plan(cluster: ClusterConfig, manifest: PluginManifest) -> ActivationReport:
    extension_name = extension_name_for(manifest)
    create_sql = create_extension_sql(extension_name)
    version_sql = extension_version_sql(extension_name)
    primary = cluster.coordinators[0] if cluster.coordinators else None
    activation = tuple(
        ActivationResult(
            node=node.name,
            status="planned" if primary and node.name == primary.name else "verify_only",
            sql=create_sql if primary and node.name == primary.name else "",
            returncode=0,
            stdout="",
            stderr="",
        )
        for node in cluster.coordinators
    )
    versions = tuple(
        VersionCheckResult(
            node=node.name,
            status="planned",
            detected_version="",
            sql=version_sql,
            returncode=0,
            stdout="",
            stderr="",
        )
        for node in cluster.coordinators
    )
    return ActivationReport(
        cluster=cluster.name,
        plugin_id=manifest.plugin_id,
        extension_name=extension_name,
        mode="dry-run",
        physical_distribution="not_executed",
        datanodes="not_connected",
        activation=activation,
        versions=versions,
        summary=ActivationSummary(
            total_cn=len(cluster.coordinators),
            activated=0,
            failed=0 if primary else 1,
            missing=0,
            version_mismatch=False,
        ),
        errors=() if primary else ("no coordinator declared in cluster.toml",),
    )


def execute_activation(cluster: ClusterConfig, manifest: PluginManifest, executor: CoordinatorSqlExecutor) -> ActivationReport:
    extension_name = extension_name_for(manifest)
    create_sql = create_extension_sql(extension_name)
    version_sql = extension_version_sql(extension_name)
    activation_results: list[ActivationResult] = []

    # OpenTenBase 会广播扩展元数据；只在 primary CN 执行一次 CREATE EXTENSION，
    # 其他 CN 只做 pg_extension 只读视图校验，避免多活 CN 重复注册。
    primary = cluster.coordinators[0] if cluster.coordinators else None
    if primary is None:
        return ActivationReport(
            cluster=cluster.name,
            plugin_id=manifest.plugin_id,
            extension_name=extension_name,
            mode="execute",
            physical_distribution="not_executed",
            datanodes="not_connected",
            activation=(),
            versions=(),
            summary=ActivationSummary(total_cn=0, activated=0, failed=1, missing=0, version_mismatch=False),
            errors=("no coordinator declared in cluster.toml",),
        )

    for node in cluster.coordinators:
        if node.name != primary.name:
            activation_results.append(
                ActivationResult(
                    node=node.name,
                    status="verify_only",
                    sql="",
                    returncode=0,
                    stdout="",
                    stderr="",
                )
            )
            continue
        try:
            result = executor.run_sql(node, create_sql)
        except Exception as exc:  # pragma: no cover - defensive boundary for real psql executors.
            activation_results.append(
                ActivationResult(
                    node=node.name,
                    status="failed",
                    sql=create_sql,
                    returncode=1,
                    stdout="",
                    stderr=str(exc),
                )
            )
            continue
        activation_results.append(
            ActivationResult(
                node=node.name,
                status="registered" if result.returncode == 0 else "failed",
                sql=create_sql,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        )

    version_results = _query_versions(cluster.coordinators, version_sql, executor)
    errors = _activation_errors(activation_results, version_results)
    summary = _activation_summary(cluster, activation_results, version_results)
    return ActivationReport(
        cluster=cluster.name,
        plugin_id=manifest.plugin_id,
        extension_name=extension_name,
        mode="execute",
        physical_distribution="not_executed",
        datanodes="not_connected",
        activation=tuple(activation_results),
        versions=tuple(version_results),
        summary=summary,
        errors=tuple(errors),
    )


def _query_versions(nodes: tuple[ClusterNode, ...], sql: str, executor: CoordinatorSqlExecutor) -> tuple[VersionCheckResult, ...]:
    results: list[VersionCheckResult] = []
    if not nodes:
        return ()
    with ThreadPoolExecutor(max_workers=max(1, len(nodes))) as pool:
        futures = {pool.submit(executor.run_sql, node, sql): node for node in nodes}
        for future in as_completed(futures):
            node = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                results.append(
                    VersionCheckResult(
                        node=node.name,
                        status="query_failed",
                        detected_version="",
                        sql=sql,
                        returncode=1,
                        stdout="",
                        stderr=str(exc),
                    )
                )
                continue
            detected = result.stdout.strip()
            if result.returncode != 0:
                status = "query_failed"
            elif detected:
                status = "present"
            else:
                status = "missing"
            results.append(
                VersionCheckResult(
                    node=node.name,
                    status=status,
                    detected_version=detected,
                    sql=sql,
                    returncode=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            )
    by_name = {result.node: result for result in results}
    return tuple(by_name[node.name] for node in nodes)


def _activation_summary(
    cluster: ClusterConfig,
    activation_results: list[ActivationResult],
    version_results: tuple[VersionCheckResult, ...],
) -> ActivationSummary:
    failed = len([result for result in activation_results if result.status not in {"registered", "verify_only"}])
    missing = len([result for result in version_results if result.status == "missing"])
    present_versions = [result.detected_version for result in version_results if result.status == "present"]
    version_mismatch = len(set(present_versions)) > 1
    return ActivationSummary(
        total_cn=len(cluster.coordinators),
        activated=len([result for result in activation_results if result.status == "registered"]),
        failed=failed + len([result for result in version_results if result.status == "query_failed"]),
        missing=missing,
        version_mismatch=version_mismatch,
    )


def _activation_errors(
    activation_results: list[ActivationResult],
    version_results: tuple[VersionCheckResult, ...],
) -> list[str]:
    errors: list[str] = []
    for result in activation_results:
        if result.status == "failed":
            errors.append(f"{result.node}: registration failed: {result.stderr.strip() or result.stdout.strip() or result.returncode}")
    for result in version_results:
        if result.status == "missing":
            errors.append(f"{result.node}: extension missing")
        elif result.status == "query_failed":
            errors.append(f"{result.node}: version query failed: {result.stderr.strip() or result.stdout.strip() or result.returncode}")
    present_versions = {result.detected_version for result in version_results if result.status == "present"}
    if len(present_versions) > 1:
        errors.append("version mismatch: " + ", ".join(sorted(present_versions)))
    return errors


def activation_report_json(report: ActivationReport) -> dict[str, object]:
    return {
        "cluster": report.cluster,
        "plugin_id": report.plugin_id,
        "extension_name": report.extension_name,
        "mode": report.mode,
        "physical_distribution": report.physical_distribution,
        "datanodes": report.datanodes,
        "activation": [
            {
                "node": result.node,
                "status": result.status,
                "sql": result.sql,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            for result in report.activation
        ],
        "versions": [
            {
                "node": result.node,
                "status": result.status,
                "detected_version": result.detected_version,
                "sql": result.sql,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            for result in report.versions
        ],
        "summary": {
            "total_cn": report.summary.total_cn,
            "activated": report.summary.activated,
            "failed": report.summary.failed,
            "missing": report.summary.missing,
            "version_mismatch": report.summary.version_mismatch,
        },
        "errors": list(report.errors),
    }

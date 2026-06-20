from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath

from .cluster import ClusterConfig, ClusterNode
from .manifest import PluginManifest
from .runtime.opentenbase import RemoteCommandResult, RemoteNodeExecutor


@dataclass(frozen=True, slots=True)
class PayloadDistributionResult:
    node: str
    role: str
    local_path: str
    remote_path: str
    ok: bool
    status: str
    stage: str
    detail: str
    returncode: int
    local_sha256: str = ""
    remote_sha256: str = ""
    checksum_ok: bool | None = None


@dataclass(frozen=True, slots=True)
class DistributionPlanEntry:
    node: str
    role: str
    file_type: str
    local_path: str
    remote_path: str
    exists: bool


@dataclass(frozen=True, slots=True)
class DistributionPlan:
    cluster: str
    mode: str
    plugin_id: str
    coordinators: tuple[str, ...]
    datanodes: tuple[str, ...]
    plan: tuple[DistributionPlanEntry, ...]
    errors: tuple[str, ...]


def _local_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remote_target_path(node: ClusterNode, local_path: Path) -> str:
    suffix = local_path.suffix.lower()
    if suffix == ".so":
        return str(PurePosixPath(node.lib_dir) / local_path.name)
    if suffix in {".control", ".sql"}:
        return str(PurePosixPath(node.extension_dir) / local_path.name)
    raise ValueError(f"unsupported payload file type: {local_path}")


def _remote_target_dir(node: ClusterNode, local_path: Path) -> str:
    suffix = local_path.suffix.lower()
    if suffix == ".so":
        return node.lib_dir
    if suffix in {".control", ".sql"}:
        return node.extension_dir
    raise ValueError(f"unsupported payload file type: {local_path}")


def _remote_package_root(plugin_id: str) -> str:
    return f".plugin_ctl/packages/{plugin_id}"


def _remote_package_path(manifest: PluginManifest, local_path: Path) -> str:
    try:
        relative = local_path.resolve().relative_to(manifest.project_root.resolve())
    except ValueError:
        relative = Path(local_path.name)
    return str(PurePosixPath(_remote_package_root(manifest.plugin_id)) / PurePosixPath(relative.as_posix()))


def _payload_file_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".so":
        return "shared_library"
    if suffix == ".control":
        return "extension_control"
    if suffix == ".sql":
        return "sql"
    return "unsupported"


def physical_payload_files(manifest: PluginManifest) -> tuple[Path, ...]:
    candidate_paths: list[Path] = []
    source_root = manifest.source_root
    if source_root.exists() and source_root.is_dir():
        # OpenTenBase extension 目录只需要数据库可直接加载的物理载荷：
        # control 文件、共享库，以及 CREATE EXTENSION 使用的安装 SQL。
        # verify/rollback 等治理脚本会进入 PluginCtl 元数据缓存，不直接投放到 extension 目录。
        candidate_paths.extend(
            path
            for path in sorted(source_root.rglob("*"))
            if path.is_file() and path.suffix.lower() in {".so", ".control"}
        )

    candidate_paths.append(manifest.install_sql)

    for key in ("extension_files", "library_files"):
        values = [*_as_list(getattr(manifest, key, [])), *_as_list(manifest.payload.get(key, []))]
        for value in values:
            if not isinstance(value, str):
                continue
            if Path(value).suffix.lower() not in {".so", ".control", ".sql"}:
                continue
            candidate_paths.append(manifest.project_root / value)

    # 保持稳定顺序，同时去重。
    return tuple(sorted(dict.fromkeys(candidate_paths)))


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def build_distribution_plan(cluster: ClusterConfig, manifest: PluginManifest) -> DistributionPlan:
    payload_files = physical_payload_files(manifest)
    nodes = [*cluster.coordinators, *cluster.datanodes]
    errors: list[str] = []
    entries: list[DistributionPlanEntry] = []

    if not manifest.source_root.exists() or not manifest.source_root.is_dir():
        errors.append(f"source_root missing: {manifest.source_root}")

    if not payload_files:
        errors.append(f"no physical payload files declared for plugin {manifest.plugin_id}")

    if not cluster.coordinators:
        errors.append("cluster has no coordinator nodes")
    if not cluster.datanodes:
        errors.append("cluster has no datanode nodes")

    for local_path in payload_files:
        exists = local_path.exists() and local_path.is_file()
        if not exists:
            if manifest.plugin_type == "c" and local_path.suffix.lower() == ".so":
                errors.append(f"Build artifact missing: {local_path.name}\nRun 'build {manifest.plugin_id}' before deployment.")
            else:
                errors.append(f"payload file missing: {local_path}")
        for node in nodes:
            try:
                remote_path = _remote_target_path(node, local_path)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            entries.append(
                DistributionPlanEntry(
                    node=node.name,
                    role=node.role,
                    file_type=_payload_file_type(local_path),
                    local_path=str(local_path),
                    remote_path=remote_path,
                    exists=exists,
                )
            )

    return DistributionPlan(
        cluster=cluster.name,
        mode="dry-run",
        plugin_id=manifest.plugin_id,
        coordinators=tuple(node.name for node in cluster.coordinators),
        datanodes=tuple(node.name for node in cluster.datanodes),
        plan=tuple(entries),
        errors=tuple(dict.fromkeys(errors)),
    )


def distribution_plan_json(plan: DistributionPlan) -> dict[str, object]:
    return {
        "cluster": plan.cluster,
        "mode": plan.mode,
        "plugin_id": plan.plugin_id,
        "coordinators": list(plan.coordinators),
        "datanodes": list(plan.datanodes),
        "plan": [
            {
                "node": entry.node,
                "role": entry.role,
                "file_type": entry.file_type,
                "local_path": entry.local_path,
                "remote_path": entry.remote_path,
                "exists": entry.exists,
            }
            for entry in plan.plan
        ],
        "errors": list(plan.errors),
    }


def distribution_results_json(results: list[PayloadDistributionResult]) -> list[dict[str, object]]:
    return [
        {
            "node": result.node,
            "role": result.role,
            "local_path": result.local_path,
            "remote_path": result.remote_path,
            "ok": result.ok,
            "status": result.status,
            "stage": result.stage,
            "detail": result.detail,
            "returncode": result.returncode,
            "local_sha256": result.local_sha256,
            "remote_sha256": result.remote_sha256,
            "checksum_ok": result.checksum_ok,
        }
        for result in sorted(results, key=lambda item: (item.node, item.local_path, item.remote_path))
    ]


def _remote_sha256_value(result: RemoteCommandResult) -> str:
    if result.returncode != 0:
        return ""
    first = result.stdout.strip().split()
    return first[0] if first else ""


def _directory_check(node: ClusterNode, remote_dir: str, executor: RemoteNodeExecutor) -> tuple[bool, str, int]:
    for argv, fallback_detail in [
        (["test", "-d", remote_dir], f"remote directory does not exist: {remote_dir}"),
        (["test", "-w", remote_dir], f"remote directory is not writable: {remote_dir}"),
    ]:
        try:
            result = executor.run(node, argv)
        except Exception as exc:  # pragma: no cover - defensive boundary for real SSH executors.
            return False, f"{fallback_detail}; executor error: {exc}", 1
        if result.returncode != 0:
            return False, result.stderr.strip() or result.stdout.strip() or fallback_detail, result.returncode
    return True, "remote target directory writable", 0


def _copy_with_checksum(
    node: ClusterNode,
    local_path: Path,
    remote_path: str,
    executor: RemoteNodeExecutor,
    *,
    status: str,
    stage: str,
    detail: str,
) -> PayloadDistributionResult:
    if not local_path.exists() or not local_path.is_file():
        return PayloadDistributionResult(
            node=node.name,
            role=node.role,
            local_path=str(local_path),
            remote_path=remote_path,
            ok=False,
            status="missing_local_file",
            stage=stage,
            detail=f"local file not found: {local_path}",
            returncode=1,
        )

    local_digest = _local_sha256(local_path)
    remote_dir = str(PurePosixPath(remote_path).parent)
    mkdir = executor.run(node, ["mkdir", "-p", remote_dir])
    if mkdir.returncode != 0:
        return PayloadDistributionResult(
            node=node.name,
            role=node.role,
            local_path=str(local_path),
            remote_path=remote_path,
            ok=False,
            status="directory_failed",
            stage=stage,
            detail=mkdir.stderr.strip() or mkdir.stdout.strip() or f"failed to create remote directory: {remote_dir}",
            returncode=mkdir.returncode,
            local_sha256=local_digest,
        )

    copy = executor.copy_file(node, local_path, remote_path)
    if copy.returncode != 0:
        return PayloadDistributionResult(
            node=node.name,
            role=node.role,
            local_path=str(local_path),
            remote_path=remote_path,
            ok=False,
            status="copy_failed",
            stage=stage,
            detail=copy.stderr.strip() or copy.stdout.strip() or "copy failed",
            returncode=copy.returncode,
            local_sha256=local_digest,
        )

    remote_hash_result = executor.sha256_file(node, remote_path)
    remote_digest = _remote_sha256_value(remote_hash_result)
    if remote_hash_result.returncode != 0:
        return PayloadDistributionResult(
            node=node.name,
            role=node.role,
            local_path=str(local_path),
            remote_path=remote_path,
            ok=False,
            status="checksum_failed",
            stage=stage,
            detail=remote_hash_result.stderr.strip() or remote_hash_result.stdout.strip() or "remote checksum failed",
            returncode=remote_hash_result.returncode,
            local_sha256=local_digest,
            remote_sha256=remote_digest,
            checksum_ok=False,
        )

    checksum_ok = local_digest == remote_digest
    return PayloadDistributionResult(
        node=node.name,
        role=node.role,
        local_path=str(local_path),
        remote_path=remote_path,
        ok=checksum_ok,
        status=status if checksum_ok else "checksum_failed",
        stage=stage,
        detail=detail if checksum_ok else "checksum mismatch",
        returncode=0 if checksum_ok else 1,
        local_sha256=local_digest,
        remote_sha256=remote_digest,
        checksum_ok=checksum_ok,
    )


def _distribute_one(node: ClusterNode, local_path: Path, executor: RemoteNodeExecutor) -> PayloadDistributionResult:
    try:
        remote_path = _remote_target_path(node, local_path)
        remote_dir = _remote_target_dir(node, local_path)
    except ValueError as exc:
        return PayloadDistributionResult(
            node=node.name,
            role=node.role,
            local_path=str(local_path),
            remote_path="",
            ok=False,
            status="unsupported",
            stage="classify",
            detail=str(exc),
            returncode=1,
        )

    if not local_path.exists() or not local_path.is_file():
        return PayloadDistributionResult(
            node=node.name,
            role=node.role,
            local_path=str(local_path),
            remote_path=remote_path,
            ok=False,
            status="missing_local_file",
            stage="validate",
            detail=f"local payload file not found: {local_path}",
            returncode=1,
        )

    local_digest = _local_sha256(local_path)
    directory_ok, directory_detail, directory_returncode = _directory_check(node, remote_dir, executor)
    if not directory_ok:
        return PayloadDistributionResult(
            node=node.name,
            role=node.role,
            local_path=str(local_path),
            remote_path=remote_path,
            ok=False,
            status="directory_failed",
            stage="precheck",
            detail=directory_detail,
            returncode=directory_returncode,
            local_sha256=local_digest,
        )

    try:
        copy = executor.copy_file(node, local_path, remote_path)
    except Exception as exc:  # pragma: no cover - defensive boundary for real SSH executors.
        return PayloadDistributionResult(
            node=node.name,
            role=node.role,
            local_path=str(local_path),
            remote_path=remote_path,
            ok=False,
            status="copy_failed",
            stage="copy",
            detail=f"executor error: {exc}",
            returncode=1,
            local_sha256=local_digest,
        )
    if copy.returncode != 0:
        return PayloadDistributionResult(
            node=node.name,
            role=node.role,
            local_path=str(local_path),
            remote_path=remote_path,
            ok=False,
            status="copy_failed",
            stage="copy",
            detail=copy.stderr.strip() or copy.stdout.strip() or "copy failed",
            returncode=copy.returncode,
            local_sha256=local_digest,
        )

    # 对账卡点：传输后必须读取远端 SHA256，并与本地 hash 做强校验。
    try:
        remote_hash_result = executor.sha256_file(node, remote_path)
    except Exception as exc:  # pragma: no cover - defensive boundary for real SSH executors.
        return PayloadDistributionResult(
            node=node.name,
            role=node.role,
            local_path=str(local_path),
            remote_path=remote_path,
            ok=False,
            status="checksum_failed",
            stage="checksum",
            detail=f"executor error: {exc}",
            returncode=1,
            local_sha256=local_digest,
            checksum_ok=False,
        )
    remote_digest = _remote_sha256_value(remote_hash_result)
    if remote_hash_result.returncode != 0:
        return PayloadDistributionResult(
            node=node.name,
            role=node.role,
            local_path=str(local_path),
            remote_path=remote_path,
            ok=False,
            status="checksum_failed",
            stage="checksum",
            detail=remote_hash_result.stderr.strip() or remote_hash_result.stdout.strip() or "remote checksum failed",
            returncode=remote_hash_result.returncode,
            local_sha256=local_digest,
            remote_sha256=remote_digest,
            checksum_ok=False,
        )

    checksum_ok = local_digest == remote_digest
    return PayloadDistributionResult(
        node=node.name,
        role=node.role,
        local_path=str(local_path),
        remote_path=remote_path,
        ok=checksum_ok,
        status="distributed" if checksum_ok else "checksum_failed",
        stage="done" if checksum_ok else "checksum",
        detail="distributed" if checksum_ok else "checksum mismatch",
        returncode=0 if checksum_ok else 1,
        local_sha256=local_digest,
        remote_sha256=remote_digest,
        checksum_ok=checksum_ok,
    )


def _metadata_files(manifest: PluginManifest) -> tuple[Path, ...]:
    if manifest.path is None:
        return tuple(physical_payload_files(manifest))
    files = [manifest.path, *physical_payload_files(manifest)]
    return tuple(sorted(dict.fromkeys(files)))


def _sync_metadata_one(node: ClusterNode, manifest: PluginManifest, local_path: Path, executor: RemoteNodeExecutor) -> PayloadDistributionResult:
    if manifest.path is not None and local_path == manifest.path:
        remote_path = str(PurePosixPath(_remote_package_root(manifest.plugin_id)) / "manifest.yml")
    else:
        remote_path = _remote_package_path(manifest, local_path)
    return _copy_with_checksum(
        node,
        local_path,
        remote_path,
        executor,
        status="metadata_synced",
        stage="metadata",
        detail="plugin metadata synced",
    )


def distribute_payload_to_nodes(
    cluster: ClusterConfig,
    payload_files: list[Path],
    executor: RemoteNodeExecutor,
    max_workers: int = 8,
) -> list[PayloadDistributionResult]:
    nodes = [*cluster.coordinators, *cluster.datanodes]
    jobs: list[tuple[ClusterNode, Path]] = [(node, Path(path)) for node in nodes for path in payload_files]
    if not jobs:
        return []

    workers = max(1, min(max_workers, len(jobs)))
    results: list[PayloadDistributionResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_distribute_one, node, local_path, executor): (node, local_path) for node, local_path in jobs}
        for future in as_completed(futures):
            node, local_path = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(
                    PayloadDistributionResult(
                        node=node.name,
                        role=node.role,
                        local_path=str(local_path),
                        remote_path="",
                        ok=False,
                        status="executor_failed",
                        stage="execute",
                        detail=str(exc),
                        returncode=1,
                    )
                )
    return results


def sync_plugin_metadata_to_nodes(
    cluster: ClusterConfig,
    manifest: PluginManifest,
    executor: RemoteNodeExecutor,
    max_workers: int = 8,
) -> list[PayloadDistributionResult]:
    nodes = [*cluster.coordinators, *cluster.datanodes]
    files = list(_metadata_files(manifest))
    jobs: list[tuple[ClusterNode, Path]] = [(node, path) for node in nodes for path in files]
    if not jobs:
        return []

    workers = max(1, min(max_workers, len(jobs)))
    results: list[PayloadDistributionResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_sync_metadata_one, node, manifest, path, executor): (node, path) for node, path in jobs}
        for future in as_completed(futures):
            node, path = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(
                    PayloadDistributionResult(
                        node=node.name,
                        role=node.role,
                        local_path=str(path),
                        remote_path="",
                        ok=False,
                        status="executor_failed",
                        stage="metadata",
                        detail=str(exc),
                        returncode=1,
                    )
                )
    return results

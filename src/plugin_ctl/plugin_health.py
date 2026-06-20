from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any

from .activation import CoordinatorSqlExecutor, extension_name_for
from .catalog import Catalog, find_manifest_in_plugin_dir, user_manifest_paths
from .cluster import find_cluster_config, load_cluster_config
from .distributed_verify import DistributedVerifyReport, run_distributed_verify
from .distribution import build_distribution_plan, physical_payload_files
from .manifest import ManifestError, PluginManifest, load_manifest
from .plugin_archive import ArchiveStore, manifest_package_state
from .plugin_package import lint_manifest, lint_manifest_path
from .runtime.opentenbase import RemoteNodeExecutor
from .source_assess import assess_source
from .state_store import StateStore
from .verify import run_removed_verify, run_smoke_verify


CHECK_TITLES = [
    "插件包结构",
    "扩展文件",
    "PluginCtl 管理状态",
    "OpenTenBase 集群配置",
    "分布式部署状态",
    "注册与验证状态",
]

CONTROL_VERSION_RE = re.compile(r"^\s*default_version\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
DANGEROUS_DROP_RE = re.compile(r"\bdrop\s+(schema|table|extension|function|type|database)\b", re.IGNORECASE)


@dataclass(slots=True)
class HealthItem:
    name: str
    status: str
    detail: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HealthSection:
    title: str
    items: list[HealthItem] = field(default_factory=list)


@dataclass(slots=True)
class PluginHealthReport:
    plugin_id: str
    version: str
    input: str
    manifest_path: str
    final_status: str
    next_step: str
    sections: list[HealthSection]
    recent_actions: list[dict[str, Any]]

    @property
    def ok(self) -> bool:
        return self.final_status != "BROKEN"


def build_plugin_health_report(
    root: Path,
    plugin_id_or_path: str,
    *,
    runtime: Any,
    sql_executor: CoordinatorSqlExecutor,
    remote_executor: RemoteNodeExecutor,
) -> PluginHealthReport:
    sections = [HealthSection(title) for title in CHECK_TITLES]
    manifest, manifest_path, catalog_registered, resolve_detail = _resolve_manifest(root, plugin_id_or_path)

    if manifest is None:
        sections[0].items.append(HealthItem("manifest", "FAIL", resolve_detail))
        return PluginHealthReport(
            plugin_id="unknown",
            version="",
            input=plugin_id_or_path,
            manifest_path=str(manifest_path or ""),
            final_status="BROKEN" if manifest_path else "UNKNOWN",
            next_step="确认插件目录里有 manifest.yml/plugin.yml，或先用 plugin_ctl list 查看已知插件。",
            sections=sections,
            recent_actions=[],
        )

    _check_package(root, manifest, sections[0])
    _check_extension_files(manifest, sections[1])
    recent_actions = _check_management_state(root, manifest, catalog_registered, sections[2])
    cluster_path, distributed_report = _check_cluster(root, manifest, runtime, sql_executor, remote_executor, sections[3], sections[4])
    _check_registration_and_verify(manifest, runtime, distributed_report, recent_actions, sections[5])

    final_status, next_step = _final_status(sections, recent_actions, catalog_registered, distributed_report, cluster_path)
    return PluginHealthReport(
        plugin_id=manifest.plugin_id,
        version=manifest.version,
        input=plugin_id_or_path,
        manifest_path=str(manifest.path or ""),
        final_status=final_status,
        next_step=next_step,
        sections=sections,
        recent_actions=recent_actions,
    )


def health_report_json(report: PluginHealthReport) -> dict[str, Any]:
    errors = [
        f"{section.title}:{item.name}: {item.detail}"
        for section in report.sections
        for item in section.items
        if item.status == "FAIL"
    ]
    warnings = [
        f"{section.title}:{item.name}: {item.detail}"
        for section in report.sections
        for item in section.items
        if item.status == "WARN"
    ]
    return {
        "plugin_id": report.plugin_id,
        "version": report.version,
        "input": report.input,
        "manifest_path": report.manifest_path,
        "ok": report.ok,
        "final_status": report.final_status,
        "next_step": report.next_step,
        "errors": errors,
        "warnings": warnings,
        "sections": [
            {
                "title": section.title,
                "items": [asdict(item) for item in section.items],
            }
            for section in report.sections
        ],
        "recent_actions": report.recent_actions,
    }


SECTION_TITLES_EN = [
    "Plugin package structure",
    "Extension files",
    "PluginCtl management state",
    "OpenTenBase cluster config",
    "Distributed deployment state",
    "Registration and verification state",
]


def _health_next_step(report: PluginHealthReport, lang: str) -> str:
    if lang != "en":
        return report.next_step
    if report.final_status == "BROKEN":
        return "Fix manifest, SQL/control files, or plugin package structure first."
    if report.final_status == "NEW":
        return "The plugin directory can be checked, but is not in the catalog yet; next run deploy <path>."
    if report.final_status == "REMOVED":
        return "The plugin was rolled back and removed verification passed; run deploy and register to use it again."
    if report.final_status == "REGISTERED":
        return "The plugin is registered and verified; continue with report or business tests."
    if report.final_status == "DEPLOYED":
        return "Plugin files are distributed; next run register <plugin_id>."
    if report.final_status == "READY":
        return "The plugin package is basically ready; run init to generate the default cluster.toml, then deploy."
    if report.final_status == "BUILD_REQUIRED":
        return f"C source and Makefile are ready, but the .so artifact is missing; run build {report.plugin_id} first."
    return report.next_step


def render_health_report(report: PluginHealthReport, lang: str = "en") -> str:
    english = lang == "en"
    lines = [
        f"{'Plugin' if english else '插件'}: {report.plugin_id}",
        f"{'Version' if english else '版本'}: {report.version or '-'}",
        f"manifest: {report.manifest_path or '-'}",
        "",
    ]
    for index, section in enumerate(report.sections, start=1):
        title = SECTION_TITLES_EN[index - 1] if english and index - 1 < len(SECTION_TITLES_EN) else section.title
        lines.append(f"[{index}/6] {title}")
        if not section.items:
            lines.append("  - [SKIP] no check items" if english else "  - [SKIP] 无可检查项目")
        for item in section.items:
            lines.append(f"  - [{item.status}] {item.name}: {item.detail}")
        lines.append("")

    lines.append("Recent actions:" if english else "最近操作:")
    if report.recent_actions:
        for action in report.recent_actions:
            ok = "OK" if action.get("ok") else "FAIL"
            detail = str(action.get("detail", "")).replace("\n", " ")[:120]
            lines.append(f"  - {action.get('action')}: {ok} {action.get('timestamp', '')} {detail}")
    else:
        lines.append("  - none" if english else "  - 无记录")
    lines.extend(
        [
            "",
            f"{'Result' if english else '结果'}: {report.final_status}",
            f"{'Next' if english else '下一步'}: {_health_next_step(report, lang)}",
        ]
    )
    return "\n".join(lines)


def _resolve_manifest(root: Path, plugin_id_or_path: str) -> tuple[PluginManifest | None, Path | None, bool, str]:
    catalog = Catalog(root=root)
    maybe_path = Path(plugin_id_or_path).expanduser()
    if _looks_like_path(plugin_id_or_path):
        try:
            manifest_path = find_manifest_in_plugin_dir(maybe_path)
            manifest = load_manifest(manifest_path)
            return manifest, manifest_path, _is_in_catalog(manifest), "manifest loaded from path"
        except (ManifestError, OSError) as exc:
            path = maybe_path if maybe_path.exists() else None
            return None, path, False, str(exc)

    try:
        manifest = catalog.load_one(plugin_id_or_path)
        return manifest, manifest.path, True, "manifest loaded from catalog"
    except ManifestError as exc:
        return None, None, False, str(exc)


def _looks_like_path(value: str) -> bool:
    path = Path(value).expanduser()
    return path.exists() or "/" in value or "\\" in value or value.endswith((".yml", ".yaml"))


def _is_in_catalog(manifest: PluginManifest) -> bool:
    if manifest.path is None:
        return False
    manifest_path = manifest.path.resolve()
    return any(path.resolve() == manifest_path for path in user_manifest_paths()) or _is_builtin_manifest(manifest_path)


def _is_builtin_manifest(path: Path) -> bool:
    parts = set(path.parts)
    return ("catalog" in parts and "plugins" in parts) or ("examples" in parts and "plugins" in parts)


def _check_package(root: Path, manifest: PluginManifest, section: HealthSection) -> None:
    section.items.append(HealthItem("manifest", "OK", str(manifest.path or "")))
    for item in lint_manifest(manifest):
        status = _map_status(item.status)
        section.items.append(HealthItem(item.check, status, item.detail))
    state = manifest_package_state(root, manifest)
    kind = str(state.get("manifest_kind", "unknown"))
    missing = ", ".join(str(item) for item in state.get("missing", [])) or "none"
    section.items.append(
        HealthItem(
            "package_state",
            "OK" if state.get("payload_complete") else "WARN",
            f"{kind}; payload_complete={bool(state.get('payload_complete'))}; missing={missing}",
            state,
        )
    )
    assess_root = manifest.source_root if manifest.source_root.exists() else manifest.project_root
    for assess in assess_source(assess_root):
        if assess.status != "pass":
            detail = f"{assess.path}: {assess.detail}" if assess.path else assess.detail
            status = "WARN" if assess.check == "control_file" else _map_status(assess.status)
            section.items.append(HealthItem(f"assess:{assess.check}", status, detail))


def _check_extension_files(manifest: PluginManifest, section: HealthSection) -> None:
    extension_name = _extension_name_safe(manifest)
    section.items.append(HealthItem("extension_name", "OK" if extension_name else "WARN", extension_name or "not declared"))

    payload_files = list(physical_payload_files(manifest))
    controls = [path for path in payload_files if path.suffix.lower() == ".control"]
    sql_files = [path for path in payload_files if path.suffix.lower() == ".sql"]
    library_files = [path for path in payload_files if path.suffix.lower() == ".so" and path.exists()]

    section.items.append(HealthItem("payload_files", "OK" if payload_files else "WARN", f"{len(payload_files)} physical file(s) detected"))
    _declared_optional_files(manifest, section)

    if controls:
        for control in controls:
            detail = _control_detail(manifest, control)
            status = "OK" if detail.startswith("default_version") else "WARN"
            if "mismatch" in detail:
                status = "FAIL"
            section.items.append(HealthItem("control_file", status, detail, {"path": str(control)}))
    else:
        section.items.append(HealthItem("control_file", "WARN", "no .control file detected; SQL-only or reference package"))

    if sql_files:
        for sql_path in sql_files:
            status, detail = _sql_file_detail(sql_path)
            section.items.append(HealthItem("sql_file", status, detail, {"path": str(sql_path)}))
    else:
        section.items.append(HealthItem("sql_file", "FAIL", "no .sql payload files detected"))

    declared_library_files = list(dict.fromkeys([*_as_list(manifest.library_files), *_as_list(manifest.payload.get("library_files", []))]))
    if declared_library_files or library_files:
        if library_files:
            section.items.append(HealthItem("library_files", "OK", f"{len(library_files)} .so file(s) declared/detected"))
        elif manifest.plugin_type == "c":
            missing = ", ".join(str(item) for item in declared_library_files if item) or f"{manifest.plugin_id}.so"
            section.items.append(HealthItem("build_artifact", "BUILD_REQUIRED", f"missing: {missing}; run build {manifest.plugin_id}"))
        else:
            section.items.append(HealthItem("library_files", "FAIL", "library_files declared but no .so payload file detected"))
    else:
        section.items.append(HealthItem("library_files", "INFO", "SQL-only package; no .so declared"))


def _declared_optional_files(manifest: PluginManifest, section: HealthSection) -> None:
    for field_name in ["extension_files", "library_files", "categories", "capabilities"]:
        value = manifest.payload.get(field_name)
        if value is None:
            section.items.append(HealthItem(field_name, "INFO", "not declared"))
            continue
        if isinstance(value, list):
            missing = []
            for raw in value:
                path = manifest.project_root / str(raw)
                if Path(str(raw)).is_absolute():
                    path = Path(str(raw))
                if not path.exists():
                    missing.append(str(raw))
            section.items.append(
                HealthItem(
                    field_name,
                    "OK" if not missing else "BUILD_REQUIRED" if field_name == "library_files" and manifest.plugin_type == "c" else "FAIL",
                    "declared" if not missing else "missing: " + ", ".join(missing),
                )
            )
        else:
            section.items.append(HealthItem(field_name, "OK", str(value)))


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _control_detail(manifest: PluginManifest, control: Path) -> str:
    try:
        text = control.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return f"cannot read control file: {exc}"
    match = CONTROL_VERSION_RE.search(text)
    if not match:
        return f"{control.name}: missing default_version"
    default_version = match.group(1)
    expected_name = f"{_extension_name_safe(manifest) or manifest.plugin_id}.control"
    if control.name != expected_name:
        return f"{control.name}: auxiliary control file; main control would be {expected_name}; default_version={default_version}"
    expected_sql = control.parent / "sql" / f"{control.stem}--{default_version}.sql"
    if not expected_sql.exists():
        sibling_sql = control.parent / f"{control.stem}--{default_version}.sql"
        expected_sql = sibling_sql if sibling_sql.exists() else expected_sql
    if not expected_sql.exists() and Path(manifest.install_sql).name != f"{control.stem}--{default_version}.sql":
        return f"default_version={default_version}; mismatch with install SQL {manifest.install_sql.name}"
    if not _versions_equivalent(default_version, manifest.version):
        return f"default_version={default_version}; mismatch with manifest version {manifest.version}"
    if default_version != manifest.version:
        return f"default_version={default_version}; text differs from manifest version {manifest.version}, treated as equivalent"
    return f"default_version={default_version}; extension SQL found"


def _sql_file_detail(path: Path) -> tuple[str, str]:
    if not path.exists():
        return "FAIL", f"missing: {path}"
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return "WARN", f"{path.name}: not UTF-8 text"
    if not text.strip():
        return "FAIL", f"{path.name}: empty SQL file"
    if DANGEROUS_DROP_RE.search(text):
        return "WARN", f"{path.name}: contains DROP; review rollback/destructive behavior"
    return "OK", f"{path.name}: present and non-empty"


def _check_management_state(root: Path, manifest: PluginManifest, catalog_registered: bool, section: HealthSection) -> list[dict[str, Any]]:
    section.items.append(HealthItem("catalog", "OK" if catalog_registered else "WARN", "registered" if catalog_registered else "not in catalog"))
    archive = ArchiveStore(root).get(manifest.plugin_id)
    if archive:
        section.items.append(HealthItem("archive", "OK", f"status={archive.status}, version={archive.version}", {"checksum": archive.checksum}))
    else:
        section.items.append(HealthItem("archive", "WARN", "no archive record found"))

    records = [record for record in StateStore(root).all() if record.plugin_id == manifest.plugin_id]
    latest: dict[str, Any] = {}
    for record in records:
        latest[record.action] = {
            "timestamp": record.timestamp,
            "action": record.action,
            "ok": record.ok,
            "detail": record.detail,
            "metadata": record.metadata,
        }
    for action in ["deploy", "register", "verify", "rollback", "check"]:
        record = latest.get(action)
        if record:
            section.items.append(HealthItem(f"last_{action}", "OK" if record["ok"] else "FAIL", record["detail"], record))
        else:
            section.items.append(HealthItem(f"last_{action}", "INFO", "no record"))
    return [latest[key] for key in sorted(latest)]


def _check_cluster(
    root: Path,
    manifest: PluginManifest,
    runtime: Any,
    sql_executor: CoordinatorSqlExecutor,
    remote_executor: RemoteNodeExecutor,
    cluster_section: HealthSection,
    deploy_section: HealthSection,
) -> tuple[Path | None, DistributedVerifyReport | None]:
    cluster_path = find_cluster_config()
    if cluster_path is None:
        cluster_section.items.append(HealthItem("cluster.toml", "SKIP", "not found; run plugin_ctl init"))
        deploy_section.items.append(HealthItem("remote_files", "SKIP", "cluster.toml not found; run plugin_ctl init"))
        return None, None

    try:
        cluster = load_cluster_config(cluster_path)
    except ValueError as exc:
        cluster_section.items.append(HealthItem("cluster.toml", "FAIL", str(exc), {"path": str(cluster_path)}))
        deploy_section.items.append(HealthItem("remote_files", "SKIP", "cluster config invalid"))
        return cluster_path, None

    cluster_section.items.append(
        HealthItem(
            "cluster.toml",
            "OK",
            f"{cluster.name}; CN={len(cluster.coordinators)}, DN={len(cluster.datanodes)}",
            {"path": str(cluster_path), "nodes": [node.name for node in cluster.nodes]},
        )
    )
    roles = list(manifest.distributed.get("required_roles", []))
    available = []
    if cluster.coordinators:
        available.append("coordinator")
    if cluster.datanodes:
        available.append("datanode")
    missing = [role for role in roles if role not in available]
    cluster_section.items.append(
        HealthItem(
            "required_roles",
            "OK" if not missing else "FAIL",
            f"required={roles or ['none']}; available={available or ['none']}" + (f"; missing={missing}" if missing else ""),
        )
    )

    plan = build_distribution_plan(cluster, manifest)
    plan_status = "OK"
    if plan.errors:
        plan_status = "BUILD_REQUIRED" if _distribution_errors_are_missing_build_artifacts(manifest, plan.errors) else "FAIL"
    deploy_section.items.append(
        HealthItem(
            "distribution_plan",
            plan_status,
            f"{len(plan.plan)} file-node copy item(s); errors={len(plan.errors)}",
            {"errors": list(plan.errors)},
        )
    )
    try:
        report = run_distributed_verify(cluster, manifest, sql_executor, remote_executor)
    except Exception as exc:
        deploy_section.items.append(HealthItem("distributed_probe", "SKIP", f"cannot run remote/CN checks: {exc}"))
        return cluster_path, None

    file_statuses = {item.file_status for item in report.file_checks}
    if report.file_checks:
        missing = len([item for item in report.file_checks if item.file_status == "missing"])
        checksum_failed = len([item for item in report.file_checks if item.file_status == "checksum_failed"])
        ok = len([item for item in report.file_checks if item.file_status == "ok"])
        status = "OK" if not missing and not checksum_failed else "WARN"
        deploy_section.items.append(
            HealthItem("remote_files", status, f"ok={ok}, missing={missing}, checksum_failed={checksum_failed}", {"statuses": sorted(file_statuses)})
        )
    else:
        deploy_section.items.append(HealthItem("remote_files", "SKIP", "no remote payload files checked"))
    return cluster_path, report


def _distribution_errors_are_missing_build_artifacts(manifest: PluginManifest, errors: tuple[str, ...]) -> bool:
    if manifest.plugin_type != "c":
        return False
    return bool(errors) and all(error.startswith("Build artifact missing:") for error in errors)


def _check_registration_and_verify(
    manifest: PluginManifest,
    runtime: Any,
    distributed_report: DistributedVerifyReport | None,
    recent_actions: list[dict[str, Any]],
    section: HealthSection,
) -> None:
    registered = False
    if distributed_report is not None:
        installed = [item for item in distributed_report.coordinator_extensions if item.extension_status == "installed"]
        missing = [item for item in distributed_report.coordinator_extensions if item.extension_status == "missing"]
        failed = [item for item in distributed_report.coordinator_extensions if item.extension_status == "query_failed"]
        registered = bool(installed) and not missing and not failed
        section.items.append(
            HealthItem(
                "pg_extension",
                "OK" if registered else "WARN",
                f"installed={len(installed)}, missing={len(missing)}, query_failed={len(failed)}",
            )
        )
    else:
        section.items.append(HealthItem("pg_extension", "SKIP", "cluster/CN check unavailable"))

    if not registered:
        section.items.append(HealthItem("verify_sql", "SKIP", "extension is not registered on all coordinators"))
    else:
        try:
            result = run_smoke_verify(runtime, manifest, manifest.smoke_sql)
            section.items.append(HealthItem("verify_sql", "OK" if result.ok else "FAIL", result.detail, {"returncode": result.returncode}))
        except Exception as exc:
            section.items.append(HealthItem("verify_sql", "FAIL", str(exc)))

    rollback_ok = any(action.get("action") == "rollback" and action.get("ok") for action in recent_actions)
    if rollback_ok and manifest.payload.get("removed_probe"):
        try:
            result = run_removed_verify(runtime, manifest)
            section.items.append(HealthItem("removed_probe", "OK" if result.ok else "WARN", result.detail, {"returncode": result.returncode}))
        except Exception as exc:
            section.items.append(HealthItem("removed_probe", "WARN", str(exc)))
    elif manifest.payload.get("removed_probe"):
        section.items.append(HealthItem("removed_probe", "INFO", "declared; not executed because last rollback is not successful"))
    else:
        section.items.append(HealthItem("removed_probe", "WARN", "not declared"))


def _final_status(
    sections: list[HealthSection],
    recent_actions: list[dict[str, Any]],
    catalog_registered: bool,
    distributed_report: DistributedVerifyReport | None,
    cluster_path: Path | None,
) -> tuple[str, str]:
    if any(item.status == "FAIL" for section in sections for item in section.items):
        return "BROKEN", "先修复 manifest、SQL/control 文件或插件包结构。"
    if any(item.status == "BUILD_REQUIRED" for section in sections for item in section.items):
        return "BUILD_REQUIRED", "C 插件源码和 Makefile 已就绪，但缺少 .so；请先执行 build <plugin_id>。"
    if not catalog_registered:
        return "NEW", "插件目录可检查，但还未进入 catalog；下一步可以执行 deploy <path>。"

    registered_item = _find_item(sections[5], "pg_extension")
    verify_item = _find_item(sections[5], "verify_sql")
    if registered_item and registered_item.status == "OK" and verify_item and verify_item.status == "OK":
        return "REGISTERED", "插件已注册并通过验证；可以继续 report 或业务测试。"

    remote_item = _find_item(sections[4], "remote_files")
    if remote_item and remote_item.status == "OK":
        return "DEPLOYED", "插件文件已分发，下一步执行 register <plugin_id>。"

    last_rollback = _latest_action(recent_actions, "rollback")
    if last_rollback and last_rollback.get("ok"):
        removed = _find_item(sections[5], "removed_probe")
        if removed and removed.status == "OK":
            return "REMOVED", "插件已回滚并通过移除验证；需要重新使用时执行 deploy 和 register。"

    if cluster_path is None:
        return "READY", "插件包基本可用；先执行 init 生成默认 cluster.toml，再 deploy。"
    if _has_db_skip(sections):
        return "UNKNOWN", "数据库或远端检查不可用；确认 OpenTenBase 已启动后重新 check。"
    return "READY", "插件包基本可用；下一步执行 deploy <plugin_id>。"


def _latest_action(actions: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for action in reversed(actions):
        if action.get("action") == name:
            return action
    return None


def _find_item(section: HealthSection, name: str) -> HealthItem | None:
    return next((item for item in section.items if item.name == name), None)


def _has_db_skip(sections: list[HealthSection]) -> bool:
    return any(item.status == "SKIP" and ("CN" in item.detail or "remote" in item.name or "pg_extension" in item.name) for section in sections for item in section.items)


def _extension_name_safe(manifest: PluginManifest) -> str:
    try:
        return extension_name_for(manifest)
    except Exception:
        raw = manifest.payload.get("extension_name") or manifest.payload.get("extension") or getattr(manifest, "plugin_id", "")
        return str(raw or "")


def _map_status(status: str) -> str:
    return {"pass": "OK", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}.get(status, status.upper())


def _versions_equivalent(left: str, right: str) -> bool:
    def normalize(value: str) -> list[str]:
        parts = value.split(".")
        while len(parts) > 1 and parts[-1] == "0":
            parts.pop()
        return parts

    return normalize(left) == normalize(right)

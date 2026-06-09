from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import yaml

from .manifest import ManifestError, PluginManifest, load_manifest
from .plugin_governance import GovernanceRuntime, cluster_roles, installed_state, registered_node_probe
from .plugin_roles import HOOK_NAMES, role_hooks


@dataclass(slots=True)
class LintItem:
    plugin_id: str
    check: str
    status: str
    detail: str


@dataclass(slots=True)
class PluginPlan:
    plugin_id: str
    version: str
    installed_state: str
    deploy_plan: str
    verify_plan: str
    rollback_plan: str
    removed_verify_plan: str
    target_roles: list[str]
    copied_paths: list[str] = field(default_factory=list)
    sql_files: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    recommendation: str = ""


@dataclass(slots=True)
class PrecheckItem:
    plugin_id: str
    check: str
    status: str
    detail: str


REQUIRED_FIELDS = ["plugin_id", "name", "version", "description", "database", "targets", "payload"]
REQUIRED_PAYLOAD_FIELDS = ["source_root", "install_sql", "verify_sql", "installed_probe"]
VALID_DISTRIBUTED_ROLES = {"coordinator", "datanode"}
VALID_HOOK_ROLES = {"coordinator", "datanode", "all"}
CREATE_TABLE_RE = re.compile(r"\bcreate\s+(?:unlogged\s+|temporary\s+|temp\s+)?table\b", re.IGNORECASE)


def _plugin_id(raw: dict[str, Any], fallback: str = "unknown") -> str:
    return str(raw.get("plugin_id") or fallback)


def find_plugin_manifest_path(root: Path, plugin_id: str) -> Path:
    for manifest_root in [
        root / "catalog" / "plugins",
        root / "examples" / "plugins",
    ]:
        if not manifest_root.exists():
            continue
        for path in sorted([*manifest_root.glob("*.yml"), *manifest_root.glob("*/manifest.yml")]):
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                continue
            if isinstance(raw, dict) and _plugin_id(raw) == plugin_id:
                return path
    raise ManifestError(f"plugin not found: {plugin_id}")


def lint_manifest_path(path: Path) -> list[LintItem]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [LintItem("unknown", "manifest_yaml", "fail", f"invalid YAML: {exc}")]
    if not isinstance(raw, dict):
        return [LintItem("unknown", "manifest", "fail", "manifest root must be a mapping")]

    plugin_id = _plugin_id(raw)
    items: list[LintItem] = []
    for field_name in REQUIRED_FIELDS:
        items.append(
            LintItem(
                plugin_id,
                f"field:{field_name}",
                "pass" if field_name in raw else "fail",
                "present" if field_name in raw else "missing",
            )
        )
    if any(item.status == "fail" for item in items):
        return items

    try:
        manifest = load_manifest(path)
    except ManifestError as exc:
        items.append(LintItem(plugin_id, "manifest_load", "fail", str(exc)))
        return items
    items.extend(lint_manifest(manifest))
    return items


def lint_manifest(manifest: PluginManifest) -> list[LintItem]:
    items: list[LintItem] = []
    plugin_id = manifest.plugin_id

    for payload_field in REQUIRED_PAYLOAD_FIELDS:
        items.append(
            LintItem(
                plugin_id,
                f"payload:{payload_field}",
                "pass" if manifest.payload.get(payload_field) else "fail",
                "declared" if manifest.payload.get(payload_field) else "missing",
            )
        )

    items.append(LintItem(plugin_id, "database", "pass" if manifest.database == "OpenTenBase" else "warn", manifest.database))

    if manifest.payload.get("source_root"):
        items.append(LintItem(plugin_id, "source_root", "pass" if manifest.source_root.exists() else "fail", str(manifest.source_root)))
    if manifest.payload.get("install_sql"):
        items.append(LintItem(plugin_id, "install_sql", "pass" if manifest.install_sql.exists() else "fail", str(manifest.install_sql)))
    if manifest.payload.get("verify_sql"):
        items.append(LintItem(plugin_id, "verify_sql", "pass" if manifest.verify_sql.exists() else "fail", str(manifest.verify_sql)))

    rollback_sql = manifest.rollback_sql
    if rollback_sql is None:
        items.append(LintItem(plugin_id, "rollback_sql", "warn", "not declared"))
    else:
        items.append(LintItem(plugin_id, "rollback_sql", "pass" if rollback_sql.exists() else "fail", str(rollback_sql)))

    items.append(
        LintItem(
            plugin_id,
            "removed_probe",
            "pass" if manifest.payload.get("removed_probe") else "warn",
            "declared" if manifest.payload.get("removed_probe") else "missing removed_probe",
        )
    )

    if not manifest.distributed:
        items.append(LintItem(plugin_id, "distributed", "warn", "missing distributed declaration"))
    else:
        required_roles = list(manifest.distributed.get("required_roles", []))
        invalid_roles = [role for role in required_roles if role not in VALID_DISTRIBUTED_ROLES]
        if invalid_roles:
            items.append(LintItem(plugin_id, "distributed.required_roles", "fail", "invalid roles: " + ", ".join(invalid_roles)))
        elif not required_roles:
            items.append(LintItem(plugin_id, "distributed.required_roles", "warn", "no required_roles declared"))
        else:
            items.append(LintItem(plugin_id, "distributed.required_roles", "pass", ", ".join(required_roles)))
        items.append(
            LintItem(
                plugin_id,
                "distributed.probe_strategy",
                "pass" if manifest.distributed.get("probe_strategy") else "warn",
                str(manifest.distributed.get("probe_strategy") or "missing probe_strategy"),
            )
        )

    for hook_name in manifest.hooks:
        if hook_name not in HOOK_NAMES:
            items.append(LintItem(plugin_id, f"hook:{hook_name}", "warn", "unknown lifecycle hook"))
    for hook in role_hooks(manifest):
        if hook.role not in VALID_HOOK_ROLES:
            items.append(LintItem(plugin_id, f"hook:{hook.hook}:{hook.role}", "fail", "invalid hook role"))
        elif hook.exists is False:
            items.append(LintItem(plugin_id, f"hook:{hook.hook}:{hook.role}", "fail", hook.detail))
        else:
            detail = hook.detail if hook.exists is None else f"{hook.detail} exists"
            items.append(LintItem(plugin_id, f"hook:{hook.hook}:{hook.role}", "pass", detail))

    if manifest.payload.get("requires_build"):
        items.append(LintItem(plugin_id, "payload:requires_build", "warn", "plugin uses C/shared-library code; build/install of native artifacts is required before SQL deploy"))
    if manifest.payload.get("destructive_install"):
        items.append(LintItem(plugin_id, "payload:destructive_install", "warn", "install SQL may drop or replace existing objects; review before deploy"))

    return items


def lint_items_json(items: list[LintItem]) -> list[dict[str, str]]:
    return [{"plugin_id": item.plugin_id, "check": item.check, "status": item.status, "detail": item.detail} for item in items]


def plugin_plan(runtime: GovernanceRuntime, manifest: PluginManifest) -> PluginPlan:
    state, state_detail = installed_state(runtime, manifest)
    target_roles = list(manifest.distributed.get("required_roles", []))
    copied_paths = [str(manifest.source_root)]
    sql_files = [str(manifest.install_sql), str(manifest.verify_sql)]
    risks: list[str] = []

    if state == "installed":
        deploy_plan = f"skip deploy; installed_probe returned {state_detail}"
        recommendation = "verify current installation"
    elif state == "not_installed":
        deploy_plan = f"copy {manifest.source_root} and run {manifest.install_sql}"
        recommendation = "deploy is available after reviewing this plan"
    else:
        deploy_plan = f"copy {manifest.source_root} and run {manifest.install_sql}; installed state is unknown"
        recommendation = "add installed_probe before production deploy"
        risks.append("missing installed_probe")

    verify_plan = f"run {manifest.smoke_sql}"
    if manifest.payload.get("verify_expect_stdout"):
        verify_plan += f"; expect stdout {manifest.payload['verify_expect_stdout']}"

    if manifest.rollback_sql:
        rollback_plan = f"dry-run by default; --execute runs {manifest.rollback_sql}"
        sql_files.append(str(manifest.rollback_sql))
    else:
        rollback_plan = "unsupported; manifest has no rollback_sql"
        risks.append("rollback unsupported")

    if manifest.payload.get("removed_probe"):
        removed_verify_plan = "run removed_probe with verify --removed"
    else:
        removed_verify_plan = "unsupported; manifest has no removed_probe"
        risks.append("removed verification unsupported")

    if not manifest.distributed:
        risks.append("missing distributed declaration")
    if manifest.payload.get("requires_build"):
        risks.append("native build required before deploy")
    if manifest.payload.get("destructive_install"):
        risks.append("install SQL may drop or replace existing objects")
    if manifest.plugin_id == "otb_timeseries":
        risks.append("chunk distribution warning is tracked separately")

    return PluginPlan(
        plugin_id=manifest.plugin_id,
        version=manifest.version,
        installed_state=state,
        deploy_plan=deploy_plan,
        verify_plan=verify_plan,
        rollback_plan=rollback_plan,
        removed_verify_plan=removed_verify_plan,
        target_roles=target_roles,
        copied_paths=copied_paths,
        sql_files=sql_files,
        risks=risks,
        recommendation=recommendation,
    )


def plugin_plan_json(plan: PluginPlan) -> dict[str, object]:
    return {
        "plugin_id": plan.plugin_id,
        "version": plan.version,
        "installed_state": plan.installed_state,
        "deploy_plan": plan.deploy_plan,
        "verify_plan": plan.verify_plan,
        "rollback_plan": plan.rollback_plan,
        "removed_verify_plan": plan.removed_verify_plan,
        "target_roles": plan.target_roles,
        "copied_paths": plan.copied_paths,
        "sql_files": plan.sql_files,
        "risks": plan.risks,
        "recommendation": plan.recommendation,
    }


def plugin_precheck(root: Path, runtime: Any, manifest: PluginManifest) -> list[PrecheckItem]:
    items = [PrecheckItem(item.plugin_id, f"package:{item.check}", item.status, item.detail) for item in lint_manifest(manifest)]
    plugin_id = manifest.plugin_id

    connection = runtime.run_sql("SELECT 1;")
    connection_ok = connection.returncode == 0 and connection.stdout.strip() == "1"
    items.append(
        PrecheckItem(
            plugin_id,
            "runtime:connection",
            "pass" if connection_ok else "fail",
            connection.stdout.strip() or connection.stderr.strip() or "OpenTenBase connection failed",
        )
    )
    if not connection_ok:
        return items

    version = runtime.run_sql("SELECT version();")
    items.append(
        PrecheckItem(
            plugin_id,
            "runtime:version",
            "pass" if version.returncode == 0 else "warn",
            version.stdout.strip() or version.stderr.strip() or "version unavailable",
        )
    )

    creates_tables = _install_sql_creates_tables(manifest)
    default_group = runtime.run_sql("SELECT group_name FROM pgxc_group WHERE default_group = 1 LIMIT 1;")
    default_group_ok = default_group.returncode == 0 and bool(default_group.stdout.strip())
    items.append(
        PrecheckItem(
            plugin_id,
            "runtime:default_node_group",
            "pass" if default_group_ok else "fail" if creates_tables else "warn",
            default_group.stdout.strip()
            or default_group.stderr.strip()
            or ("missing default node group; table-creating plugins need CREATE DEFAULT NODE GROUP" if creates_tables else "missing default node group"),
        )
    )

    sharding_map = runtime.run_sql(
        "SELECT count(*) FROM pgxc_shard_map m "
        "JOIN pgxc_group g ON m.disgroup = g.oid "
        "WHERE g.default_group = 1;"
    )
    sharding_count = _parse_count(sharding_map.stdout)
    sharding_map_ok = sharding_map.returncode == 0 and sharding_count > 0
    items.append(
        PrecheckItem(
            plugin_id,
            "runtime:sharding_map",
            "pass" if sharding_map_ok else "fail" if creates_tables else "warn",
            f"{sharding_count} shard map rows for default group"
            if sharding_map.returncode == 0
            else sharding_map.stderr.strip() or sharding_map.stdout.strip() or "failed to read pgxc_shard_map",
        )
    )

    required_roles = list(manifest.distributed.get("required_roles", []))
    if required_roles:
        available_roles = cluster_roles(runtime)
        missing_roles = [role for role in required_roles if role not in available_roles]
        items.append(
            PrecheckItem(
                plugin_id,
                "distributed:required_roles",
                "pass" if not missing_roles else "fail",
                "available roles: " + ", ".join(sorted(available_roles)) if not missing_roles else "missing roles: " + ", ".join(missing_roles),
            )
        )
        if not missing_roles:
            ok, detail = registered_node_probe(runtime, required_roles)
            items.append(PrecheckItem(plugin_id, "distributed:registered_nodes", "pass" if ok else "fail", detail))
    else:
        items.append(PrecheckItem(plugin_id, "distributed:required_roles", "warn", "no required_roles declared"))

    state, state_detail = installed_state(runtime, manifest)
    items.append(
        PrecheckItem(
            plugin_id,
            "runtime:installed_probe",
            "pass" if state == "not_installed" else "warn" if state == "unknown" else "pass",
            f"{state}: {state_detail}",
        )
    )

    remote_tmp = runtime.exec("bash", "-lc", "test -w /tmp")
    items.append(
        PrecheckItem(
            plugin_id,
            "runtime:remote_tmp_writable",
            "pass" if remote_tmp.returncode == 0 else "fail",
            "/tmp writable" if remote_tmp.returncode == 0 else remote_tmp.stderr.strip() or "remote /tmp is not writable",
        )
    )
    return items


def _install_sql_creates_tables(manifest: PluginManifest) -> bool:
    try:
        text = manifest.install_sql.read_text(encoding="utf-8-sig")
    except OSError:
        return False
    return CREATE_TABLE_RE.search(text) is not None


def _parse_count(stdout: str) -> int:
    for line in stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            return int(line)
    return 0


def precheck_items_json(items: list[PrecheckItem]) -> list[dict[str, str]]:
    return [{"plugin_id": item.plugin_id, "check": item.check, "status": item.status, "detail": item.detail} for item in items]

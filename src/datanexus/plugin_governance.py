from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .manifest import PluginManifest
from .state_store import StateRecord, StateStore


@dataclass(slots=True)
class PluginCheck:
    plugin_id: str
    check: str
    status: str
    detail: str

    @property
    def ok(self) -> bool:
        return self.status == "pass"


@dataclass(slots=True)
class PluginGovernance:
    plugin_id: str
    version: str
    installed_state: str
    lifecycle_ready: str
    distributed_ready: str
    last_deploy: str
    last_verify: str
    last_rollback: str
    notes: str


class GovernanceRuntime(Protocol):
    def run_sql(self, sql: str):
        ...

    def run_sql_at(self, host: str, port: int, sql: str):
        ...


ROLE_TO_NODE_TYPE = {
    "coordinator": "C",
    "datanode": "D",
}


def latest_action(records: list[StateRecord], plugin_id: str, action: str) -> StateRecord | None:
    matches = [record for record in records if record.plugin_id == plugin_id and record.action == action]
    return matches[-1] if matches else None


def summarize_record(record: StateRecord | None) -> str:
    if record is None:
        return "none"
    return f"{'ok' if record.ok else 'failed'}: {record.detail}"


def cluster_roles(runtime: GovernanceRuntime) -> set[str]:
    result = runtime.run_sql("SELECT DISTINCT node_type FROM pgxc_node WHERE node_type IN ('C', 'D') ORDER BY node_type;")
    if result.returncode != 0:
        return set()
    roles: set[str] = set()
    for line in result.stdout.splitlines():
        value = line.strip()
        if value == "C":
            roles.add("coordinator")
        if value == "D":
            roles.add("datanode")
    return roles


def registered_node_probe(runtime: GovernanceRuntime, required_roles: list[str]) -> tuple[bool, str]:
    node_types = [ROLE_TO_NODE_TYPE[role] for role in required_roles if role in ROLE_TO_NODE_TYPE]
    if not node_types:
        return True, "no registered node probe required"
    type_list = ", ".join(f"'{node_type}'" for node_type in node_types)
    result = runtime.run_sql(
        "SELECT node_name || '|' || node_type || '|' || node_host || '|' || node_port "
        f"FROM pgxc_node WHERE node_type IN ({type_list}) ORDER BY node_name;"
    )
    if result.returncode != 0:
        return False, result.stderr.strip() or result.stdout.strip() or "failed to read pgxc_node"

    seen = 0
    failed: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        seen += 1
        name, node_type, host, port = line.split("|", 3)
        probe = runtime.run_sql_at(host, int(port), "SELECT 1;")
        if probe.returncode != 0 or probe.stdout.strip() != "1":
            failed.append(f"{name}({node_type}) {host}:{port}")
    if seen == 0:
        return False, "no matching CN/DN registrations found"
    if failed:
        return False, "unreachable declared role nodes: " + ", ".join(failed)
    return True, f"{seen} declared role nodes reachable"


def installed_state(runtime: GovernanceRuntime, manifest: PluginManifest) -> tuple[str, str]:
    probe = manifest.payload.get("installed_probe")
    if not probe:
        return "unknown", "missing installed_probe"
    result = runtime.run_sql(str(probe))
    if result.returncode == 0 and result.stdout.strip():
        return "installed", result.stdout.strip()
    detail = result.stderr.strip() or result.stdout.strip() or "installed_probe returned no rows"
    return "not_installed", detail


def plugin_checks(root: Path, runtime: GovernanceRuntime, manifest: PluginManifest) -> list[PluginCheck]:
    records = StateStore(root).all()
    checks: list[PluginCheck] = []
    plugin_id = manifest.plugin_id

    checks.append(PluginCheck(plugin_id, "manifest", "pass", "manifest loaded"))

    install_exists = manifest.install_sql.exists()
    verify_exists = manifest.verify_sql.exists()
    rollback_exists = manifest.rollback_sql is not None and manifest.rollback_sql.exists()
    removed_probe = bool(manifest.payload.get("removed_probe"))
    installed_probe = bool(manifest.payload.get("installed_probe"))

    checks.append(PluginCheck(plugin_id, "install_sql", "pass" if install_exists else "fail", str(manifest.install_sql)))
    checks.append(PluginCheck(plugin_id, "verify_sql", "pass" if verify_exists else "fail", str(manifest.verify_sql)))
    checks.append(PluginCheck(plugin_id, "rollback_sql", "pass" if rollback_exists else "warn", str(manifest.rollback_sql) if manifest.rollback_sql else "not declared"))
    checks.append(PluginCheck(plugin_id, "installed_probe", "pass" if installed_probe else "warn", "declared" if installed_probe else "missing installed_probe"))
    checks.append(PluginCheck(plugin_id, "removed_probe", "pass" if removed_probe else "warn", "declared" if removed_probe else "missing removed_probe"))

    distributed = manifest.distributed
    if not distributed:
        checks.append(PluginCheck(plugin_id, "distributed", "warn", "missing distributed declaration"))
        distributed_ready = False
    else:
        required_roles = list(distributed.get("required_roles", []))
        checks.append(PluginCheck(plugin_id, "distributed", "pass", f"required_roles={', '.join(required_roles) or 'none'}"))
        available_roles = cluster_roles(runtime)
        missing_roles = [role for role in required_roles if role not in available_roles]
        if missing_roles:
            checks.append(PluginCheck(plugin_id, "distributed_roles", "fail", "missing roles: " + ", ".join(missing_roles)))
            distributed_ready = False
        else:
            ok, detail = registered_node_probe(runtime, required_roles)
            checks.append(PluginCheck(plugin_id, "distributed_roles", "pass" if ok else "fail", detail))
            distributed_ready = ok

    state, state_detail = installed_state(runtime, manifest)
    state_status = "pass" if state == "installed" else "warn"
    checks.append(PluginCheck(plugin_id, "installed_state", state_status, f"{state}: {state_detail}"))

    last_deploy = latest_action(records, plugin_id, "deploy")
    last_verify = latest_action(records, plugin_id, "verify")
    last_rollback = latest_action(records, plugin_id, "rollback")
    checks.append(PluginCheck(plugin_id, "last_deploy", "pass" if last_deploy and last_deploy.ok else "warn", summarize_record(last_deploy)))
    checks.append(PluginCheck(plugin_id, "last_verify", "pass" if last_verify and last_verify.ok else "warn", summarize_record(last_verify)))
    checks.append(PluginCheck(plugin_id, "last_rollback", "pass" if last_rollback and last_rollback.ok else "warn", summarize_record(last_rollback)))

    lifecycle_ready = install_exists and verify_exists and installed_probe
    checks.append(PluginCheck(plugin_id, "can_deploy", "pass" if lifecycle_ready and distributed_ready else "warn", "ready" if lifecycle_ready and distributed_ready else "not ready"))
    checks.append(PluginCheck(plugin_id, "can_verify", "pass" if verify_exists and state == "installed" else "warn", "ready" if verify_exists and state == "installed" else "not ready"))
    checks.append(PluginCheck(plugin_id, "can_rollback", "pass" if rollback_exists and state == "installed" else "warn", "ready" if rollback_exists and state == "installed" else "not ready"))
    return checks


def governance_status(root: Path, runtime: GovernanceRuntime, manifest: PluginManifest) -> PluginGovernance:
    checks = plugin_checks(root, runtime, manifest)
    records = StateStore(root).all()
    state_check = next(check for check in checks if check.check == "installed_state")
    distributed_check = next((check for check in checks if check.check == "distributed_roles"), None)
    distributed_decl = next(check for check in checks if check.check == "distributed")
    install_check = next(check for check in checks if check.check == "install_sql")
    verify_check = next(check for check in checks if check.check == "verify_sql")
    probe_check = next(check for check in checks if check.check == "installed_probe")

    lifecycle_ready = "yes" if install_check.ok and verify_check.ok and probe_check.ok else "no"
    if distributed_decl.status == "warn":
        distributed_ready = "warning"
    elif distributed_check and distributed_check.ok:
        distributed_ready = "yes"
    else:
        distributed_ready = "no"

    notes: list[str] = []
    if distributed_decl.status == "warn":
        notes.append("missing distributed declaration")
    if "not_installed" in state_check.detail:
        notes.append("not installed")
    if manifest.notes:
        notes.append(manifest.notes[0])

    return PluginGovernance(
        plugin_id=manifest.plugin_id,
        version=manifest.version,
        installed_state=state_check.detail.split(":", 1)[0],
        lifecycle_ready=lifecycle_ready,
        distributed_ready=distributed_ready,
        last_deploy=summarize_record(latest_action(records, manifest.plugin_id, "deploy")),
        last_verify=summarize_record(latest_action(records, manifest.plugin_id, "verify")),
        last_rollback=summarize_record(latest_action(records, manifest.plugin_id, "rollback")),
        notes="; ".join(notes),
    )


def governance_status_json(statuses: list[PluginGovernance]) -> list[dict[str, str]]:
    return [
        {
            "plugin_id": status.plugin_id,
            "version": status.version,
            "installed_state": status.installed_state,
            "lifecycle_ready": status.lifecycle_ready,
            "distributed_ready": status.distributed_ready,
            "last_deploy": status.last_deploy,
            "last_verify": status.last_verify,
            "last_rollback": status.last_rollback,
            "notes": status.notes,
        }
        for status in statuses
    ]

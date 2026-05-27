from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .manifest import PluginManifest


HOOK_NAMES = ["preinstall", "postinstall", "preuninstall", "postuninstall"]


@dataclass(slots=True)
class RoleStep:
    role: str
    step: str
    detail: str


@dataclass(slots=True)
class RoleHook:
    hook: str
    role: str
    detail: str
    exists: bool | None


def manifest_roles(manifest: PluginManifest) -> list[str]:
    roles = list(manifest.distributed.get("required_roles", []))
    if roles:
        return roles

    mapped: list[str] = []
    if manifest.targets.get("cn"):
        mapped.append("coordinator")
    if manifest.targets.get("dn"):
        mapped.append("datanode")
    return mapped


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _hook_exists(manifest: PluginManifest, detail: str) -> bool | None:
    if detail.strip().upper().startswith(("SELECT ", "DO ", "CREATE ", "ALTER ", "DROP ")):
        return None
    path = Path(detail)
    if not path.is_absolute():
        path = manifest.project_root / path
    return path.exists()


def role_hooks(manifest: PluginManifest) -> list[RoleHook]:
    hooks: list[RoleHook] = []
    if not manifest.hooks:
        return hooks

    for hook_name in HOOK_NAMES:
        raw_hook = manifest.hooks.get(hook_name)
        if not raw_hook:
            continue
        if isinstance(raw_hook, dict):
            for role, values in raw_hook.items():
                for value in _as_list(values):
                    detail = str(value)
                    hooks.append(RoleHook(hook_name, str(role), detail, _hook_exists(manifest, detail)))
        else:
            for value in _as_list(raw_hook):
                detail = str(value)
                hooks.append(RoleHook(hook_name, "all", detail, _hook_exists(manifest, detail)))
    return hooks


def role_steps(manifest: PluginManifest) -> list[RoleStep]:
    roles = manifest_roles(manifest)
    if not roles:
        return [RoleStep("unknown", "warning", "missing distributed.required_roles and targets mapping")]

    steps: list[RoleStep] = []
    for role in roles:
        steps.append(RoleStep(role, "probe", manifest.payload.get("installed_probe", "missing installed_probe")))
        if role == "coordinator":
            steps.append(RoleStep(role, "install_sql", str(manifest.install_sql)))
            steps.append(RoleStep(role, "verify_sql", str(manifest.smoke_sql)))
            if manifest.rollback_sql:
                steps.append(RoleStep(role, "rollback_sql", str(manifest.rollback_sql)))
        elif role == "datanode":
            steps.append(RoleStep(role, "payload_presence", str(manifest.source_root)))
        else:
            steps.append(RoleStep(role, "warning", f"unsupported role: {role}"))
    for hook in role_hooks(manifest):
        steps.append(RoleStep(hook.role, f"hook:{hook.hook}", hook.detail))
    return steps


def role_steps_json(steps: list[RoleStep]) -> list[dict[str, str]]:
    return [{"role": step.role, "step": step.step, "detail": step.detail} for step in steps]


def role_hooks_json(hooks: list[RoleHook]) -> list[dict[str, object]]:
    return [{"hook": hook.hook, "role": hook.role, "detail": hook.detail, "exists": hook.exists} for hook in hooks]


def role_summary(manifest: PluginManifest) -> dict[str, Any]:
    return {
        "plugin_id": manifest.plugin_id,
        "version": manifest.version,
        "roles": manifest_roles(manifest),
        "probe_strategy": manifest.distributed.get("probe_strategy", ""),
        "steps": role_steps_json(role_steps(manifest)),
        "hooks": role_hooks_json(role_hooks(manifest)),
    }

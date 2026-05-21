from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .manifest import PluginManifest


@dataclass(slots=True)
class RoleStep:
    role: str
    step: str
    detail: str


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
    return steps


def role_steps_json(steps: list[RoleStep]) -> list[dict[str, str]]:
    return [{"role": step.role, "step": step.step, "detail": step.detail} for step in steps]


def role_summary(manifest: PluginManifest) -> dict[str, Any]:
    return {
        "plugin_id": manifest.plugin_id,
        "version": manifest.version,
        "roles": manifest_roles(manifest),
        "probe_strategy": manifest.distributed.get("probe_strategy", ""),
        "steps": role_steps_json(role_steps(manifest)),
    }

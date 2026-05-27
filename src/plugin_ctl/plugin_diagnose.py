from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .i18n import message
from .manifest import PluginManifest
from .plugin_package import LintItem, PluginPlan, PrecheckItem, lint_manifest, plugin_plan, plugin_precheck


@dataclass(slots=True)
class PluginDiagnosis:
    plugin_id: str
    version: str
    package_ok: bool
    env_ready: bool
    installed_state: str
    next_action: str
    conclusion_key: str
    conclusion: str
    risk: str
    lint: list[LintItem] = field(default_factory=list)
    plan: PluginPlan | None = None
    precheck: list[PrecheckItem] = field(default_factory=list)


def _unique_join(values: list[str]) -> str:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return "; ".join(ordered) if ordered else "none"


def _risk_items(lint: list[LintItem], precheck: list[PrecheckItem], plan: PluginPlan) -> list[str]:
    risks: list[str] = []
    for item in lint:
        if item.status != "pass":
            risks.append(f"{item.check}: {item.detail}")
    for item in precheck:
        if item.check.startswith("package:"):
            continue
        if item.status != "pass":
            risks.append(f"{item.check}: {item.detail}")
    risks.extend(plan.risks)
    return risks


def _next_action(package_ok: bool, env_ready: bool, installed_state: str) -> tuple[str, str]:
    if not package_ok:
        return "fix_manifest", "diagnose_conclusion_fix_manifest"
    if installed_state == "unknown":
        return "fix_manifest", "diagnose_conclusion_unknown"
    if not env_ready:
        return "fix_environment", "diagnose_conclusion_fix_environment"
    if installed_state == "not_installed":
        return "deploy", "diagnose_conclusion_deploy"
    if installed_state == "installed":
        return "verify", "diagnose_conclusion_verify"
    return "review", "diagnose_conclusion_review"


def diagnose_plugin(root: Path, runtime: Any, manifest: PluginManifest) -> PluginDiagnosis:
    lint_items = lint_manifest(manifest)
    plan = plugin_plan(runtime, manifest)
    precheck_items = plugin_precheck(root, runtime, manifest)

    package_ok = not any(item.status == "fail" for item in lint_items)
    env_items = [item for item in precheck_items if not item.check.startswith("package:")]
    env_ready = not any(item.status == "fail" for item in env_items)
    installed_state = plan.installed_state
    next_action, conclusion_key = _next_action(package_ok, env_ready, installed_state)
    risk = _unique_join(_risk_items(lint_items, precheck_items, plan))

    return PluginDiagnosis(
        plugin_id=manifest.plugin_id,
        version=manifest.version,
        package_ok=package_ok,
        env_ready=env_ready,
        installed_state=installed_state,
        next_action=next_action,
        conclusion_key=conclusion_key,
        conclusion=message(conclusion_key, "en"),
        risk=risk,
        lint=lint_items,
        plan=plan,
        precheck=precheck_items,
    )


def diagnosis_json(diagnosis: PluginDiagnosis) -> dict[str, object]:
    return {
        "plugin_id": diagnosis.plugin_id,
        "version": diagnosis.version,
        "package_ok": diagnosis.package_ok,
        "env_ready": diagnosis.env_ready,
        "installed_state": diagnosis.installed_state,
        "next_action": diagnosis.next_action,
        "conclusion_key": diagnosis.conclusion_key,
        "conclusion": diagnosis.conclusion,
        "risk": diagnosis.risk,
        "lint": [
            {"plugin_id": item.plugin_id, "check": item.check, "status": item.status, "detail": item.detail}
            for item in diagnosis.lint
        ],
        "plan": {
            "plugin_id": diagnosis.plan.plugin_id if diagnosis.plan else diagnosis.plugin_id,
            "version": diagnosis.plan.version if diagnosis.plan else diagnosis.version,
            "installed_state": diagnosis.plan.installed_state if diagnosis.plan else diagnosis.installed_state,
            "deploy_plan": diagnosis.plan.deploy_plan if diagnosis.plan else "",
            "verify_plan": diagnosis.plan.verify_plan if diagnosis.plan else "",
            "rollback_plan": diagnosis.plan.rollback_plan if diagnosis.plan else "",
            "removed_verify_plan": diagnosis.plan.removed_verify_plan if diagnosis.plan else "",
            "target_roles": diagnosis.plan.target_roles if diagnosis.plan else [],
            "copied_paths": diagnosis.plan.copied_paths if diagnosis.plan else [],
            "sql_files": diagnosis.plan.sql_files if diagnosis.plan else [],
            "risks": diagnosis.plan.risks if diagnosis.plan else [],
            "recommendation": diagnosis.plan.recommendation if diagnosis.plan else "",
        },
        "precheck": [
            {"plugin_id": item.plugin_id, "check": item.check, "status": item.status, "detail": item.detail}
            for item in diagnosis.precheck
        ],
    }


def diagnosis_summary_json(diagnosis: PluginDiagnosis) -> dict[str, object]:
    return {
        "plugin_id": diagnosis.plugin_id,
        "version": diagnosis.version,
        "package_ok": diagnosis.package_ok,
        "env_ready": diagnosis.env_ready,
        "installed_state": diagnosis.installed_state,
        "next_action": diagnosis.next_action,
        "risk": diagnosis.risk,
    }


def diagnosis_summary_row(diagnosis: PluginDiagnosis, lang: str, value_fn, text_fn, message_fn) -> list[str]:
    return [
        diagnosis.plugin_id,
        diagnosis.version,
        value_fn("yes" if diagnosis.package_ok else "no", lang),
        value_fn("yes" if diagnosis.env_ready else "no", lang),
        value_fn(diagnosis.installed_state, lang),
        value_fn(diagnosis.next_action, lang),
        diagnosis.risk,
    ]


def diagnosis_rows(diagnoses: list[PluginDiagnosis], lang: str, value_fn, text_fn) -> tuple[list[str], list[list[str]]]:
    headers = [
        "plugin_id",
        text_fn("version", lang),
        text_fn("package_ok", lang),
        text_fn("env_ready", lang),
        text_fn("installed_state", lang),
        text_fn("next_action", lang),
        text_fn("risk", lang),
    ]
    rows = [
        [
            diagnosis.plugin_id,
            diagnosis.version,
            value_fn("yes" if diagnosis.package_ok else "no", lang),
            value_fn("yes" if diagnosis.env_ready else "no", lang),
            value_fn(diagnosis.installed_state, lang),
            value_fn(diagnosis.next_action, lang),
            diagnosis.risk,
        ]
        for diagnosis in diagnoses
    ]
    return headers, rows

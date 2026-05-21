from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import __version__
from .action_result import ActionResult
from .catalog import Catalog
from .cluster import run_cluster_status
from .deploy import deploy_sql_payload
from .doctor import run_doctor
from .i18n import message, normalize_lang, text, value
from .manifest import ManifestError
from .plugin_archive import ArchiveStore, archive_list_json, archive_record_json, build_archive_record
from .plugin_consistency import consistency_check, consistency_items_json
from .plugin_diagnose import diagnose_plugin, diagnosis_json, diagnosis_summary_json, diagnosis_rows
from .plugin_governance import governance_status, governance_status_json, plugin_checks
from .plugin_package import (
    find_plugin_manifest_path,
    lint_items_json,
    lint_manifest_path,
    plugin_plan,
    plugin_plan_json,
    plugin_precheck,
    precheck_items_json,
)
from .plugin_roles import role_steps, role_steps_json, role_summary
from .report import latest_by_plugin_action, latest_by_plugin_action_json, row_for_record
from .rollback import rollback_plugin
from .state_store import StateStore
from .runtime.opentenbase import OpenTenBaseRuntime
from .verify import run_removed_verify, run_smoke_verify
from .util import render_table


def platform_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="datanexus")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--root", type=Path, default=platform_root(), help="platform directory root")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="list plugin manifests")

    inspect_parser = subparsers.add_parser("inspect", help="show a plugin manifest")
    inspect_parser.add_argument("plugin_id")

    doctor_parser = subparsers.add_parser("doctor", help="check local OpenTenBase runtime")
    doctor_parser.add_argument("--container", default="opentenbaseDN1")
    doctor_parser.add_argument("--host", default="127.0.0.1")
    doctor_parser.add_argument("--port", type=int, default=30004)
    doctor_parser.add_argument("--user", default="opentenbase")
    doctor_parser.add_argument("--database", default="postgres")

    cluster_parser = subparsers.add_parser("cluster", help="inspect local OpenTenBase cluster status")
    cluster_subparsers = cluster_parser.add_subparsers(dest="cluster_command", required=True)
    cluster_subparsers.add_parser("status", help="read-only local Docker/OpenTenBase status")

    plugin_parser = subparsers.add_parser("plugin", help="plugin governance commands")
    plugin_subparsers = plugin_parser.add_subparsers(dest="plugin_command", required=True)
    plugin_check_parser = plugin_subparsers.add_parser("check", help="check one plugin governance state")
    plugin_check_parser.add_argument("plugin_id")
    plugin_check_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help="human output language")
    plugin_status_parser = plugin_subparsers.add_parser("status", help="show one plugin summary")
    plugin_status_parser.add_argument("plugin_id")
    plugin_status_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help="human output language")
    plugin_lint_parser = plugin_subparsers.add_parser("lint", help="lint one plugin package without connecting to database")
    plugin_lint_parser.add_argument("plugin_id")
    plugin_lint_parser.add_argument("--json", action="store_true", help="emit lint result as JSON")
    plugin_lint_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help="human output language")
    plugin_plan_parser = plugin_subparsers.add_parser("plan", help="show non-executing lifecycle plan for one plugin")
    plugin_plan_parser.add_argument("plugin_id")
    plugin_plan_parser.add_argument("--json", action="store_true", help="emit plan as JSON")
    plugin_plan_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help="human output language")
    plugin_precheck_parser = plugin_subparsers.add_parser("precheck", help="run read-only pre-deploy checks for one plugin")
    plugin_precheck_parser.add_argument("plugin_id")
    plugin_precheck_parser.add_argument("--json", action="store_true", help="emit precheck result as JSON")
    plugin_precheck_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help="human output language")
    plugin_diagnose_parser = plugin_subparsers.add_parser("diagnose", help="aggregate lint, plan, and precheck for one plugin")
    plugin_diagnose_parser.add_argument("plugin_id")
    plugin_diagnose_parser.add_argument("--json", action="store_true", help="emit diagnosis result as JSON")
    plugin_diagnose_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help="human output language")
    plugin_roles_parser = plugin_subparsers.add_parser("roles", help="show plugin role-scoped governance steps")
    plugin_roles_parser.add_argument("plugin_id")
    plugin_roles_parser.add_argument("--json", action="store_true", help="emit role mapping as JSON")
    plugin_consistency_parser = plugin_subparsers.add_parser("consistency", help="run read-only plugin consistency checks")
    plugin_consistency_parser.add_argument("plugin_id")
    plugin_consistency_parser.add_argument("--json", action="store_true", help="emit consistency checks as JSON")
    plugin_archive_parser = plugin_subparsers.add_parser("archive", help="inspect plugin archive records")
    plugin_archive_subparsers = plugin_archive_parser.add_subparsers(dest="archive_command", required=True)
    plugin_archive_list_parser = plugin_archive_subparsers.add_parser("list", help="list archived plugin package records")
    plugin_archive_list_parser.add_argument("--json", action="store_true", help="emit archive records as JSON")
    plugin_archive_inspect_parser = plugin_archive_subparsers.add_parser("inspect", help="inspect one archived plugin package record")
    plugin_archive_inspect_parser.add_argument("plugin_id")
    plugin_archive_inspect_parser.add_argument("--json", action="store_true", help="emit archive record as JSON")

    plugins_parser = subparsers.add_parser("plugins", help="multi-plugin governance commands")
    plugins_subparsers = plugins_parser.add_subparsers(dest="plugins_command", required=True)
    plugins_status_parser = plugins_subparsers.add_parser("status", help="show governance status for all plugins")
    plugins_status_parser.add_argument("--json", action="store_true", help="emit plugin governance status as JSON")
    plugins_status_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help="human output language")

    for name in ["deploy", "verify", "state", "rollback", "report"]:
        cmd = subparsers.add_parser(name, help=f"{name} command scaffold")
        if name in {"deploy", "verify", "state", "rollback"}:
            cmd.add_argument("plugin_id", nargs="?")
        if name == "verify":
            cmd.add_argument("--removed", action="store_true", help="verify that plugin objects are absent using removed_probe")
        if name == "rollback":
            cmd.add_argument("--execute", action="store_true", help="execute rollback_sql instead of showing the rollback plan")
        if name == "report":
            cmd.add_argument("--json", action="store_true", help="emit latest action report as JSON")

    return parser


def cmd_list(root: Path) -> int:
    catalog = Catalog(root=root)
    manifests = catalog.load_all()
    if not manifests:
        print("No plugin manifests found.")
        return 0

    rows = [[m.plugin_id, m.name, m.version, m.payload.get("source_root", "")] for m in manifests]
    print(render_table(["plugin_id", "name", "version", "source_root"], rows))
    return 0


def cmd_inspect(root: Path, plugin_id: str) -> int:
    catalog = Catalog(root=root)
    manifest = catalog.load_one(plugin_id)
    payload = {
        "plugin_id": manifest.plugin_id,
        "name": manifest.name,
        "version": manifest.version,
        "description": manifest.description,
        "database": manifest.database,
        "targets": manifest.targets,
        "distributed": manifest.distributed,
        "hooks": manifest.hooks,
        "payload": manifest.payload,
        "notes": manifest.notes,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    runtime = OpenTenBaseRuntime(
        container=args.container,
        host=args.host,
        port=args.port,
        user=args.user,
        database=args.database,
    )
    checks = run_doctor(runtime)
    rows = [["check", "ok", "detail"]]
    rows.extend([[check.name, "yes" if check.ok else "no", check.detail] for check in checks])
    print(render_table(rows[0], rows[1:]))
    return 0 if all(check.ok for check in checks) else 1


def cmd_cluster_status() -> int:
    checks = run_cluster_status(lambda container: OpenTenBaseRuntime(container=container))
    rows = [[check.name, "yes" if check.ok else "no", check.detail] for check in checks]
    print(render_table(["check", "ok", "detail"], rows))
    return 0 if all(check.ok for check in checks) else 1


def cmd_plugin_check(root: Path, plugin_id: str, *, lang: str | None = None) -> int:
    output_lang = normalize_lang(lang)
    manifest = Catalog(root=root).load_one(plugin_id)
    runtime = OpenTenBaseRuntime()
    checks = plugin_checks(root, runtime, manifest)
    rows = [[check.plugin_id, check.check, value(check.status, output_lang), check.detail] for check in checks]
    print(render_table(["plugin_id", text("check", output_lang), text("status", output_lang), text("detail", output_lang)], rows))
    return 0 if all(check.status != "fail" for check in checks) else 1


def _recommendation(status, lang: str) -> str:
    if status.installed_state == "installed":
        if status.last_verify.startswith("ok:"):
            return message("keep_current_verify_when_needed", lang)
        return message("run_verify_to_confirm", lang)
    if status.lifecycle_ready == "yes" and status.distributed_ready == "yes":
        return message("ready_to_deploy", lang)
    return message("resolve_readiness_gaps", lang)


def cmd_plugin_status(root: Path, plugin_id: str, *, lang: str | None = None) -> int:
    output_lang = normalize_lang(lang)
    manifest = Catalog(root=root).load_one(plugin_id)
    runtime = OpenTenBaseRuntime()
    status = governance_status(root, runtime, manifest)
    rows = [
        [text("plugin", output_lang), status.plugin_id],
        [text("version", output_lang), status.version],
        [text("installed_state", output_lang), value(status.installed_state, output_lang)],
        [text("lifecycle_ready", output_lang), value(status.lifecycle_ready, output_lang)],
        [text("distributed_ready", output_lang), value(status.distributed_ready, output_lang)],
        [text("last_deploy", output_lang), status.last_deploy],
        [text("last_verify", output_lang), status.last_verify],
        [text("last_rollback", output_lang), status.last_rollback],
        [text("notes", output_lang), status.notes],
        [text("recommendation", output_lang), _recommendation(status, output_lang)],
    ]
    print(render_table([text("check", output_lang), text("detail", output_lang)], rows))
    return 0


def cmd_plugins_status(root: Path, *, as_json: bool = False, lang: str | None = None) -> int:
    output_lang = normalize_lang(lang)
    catalog = Catalog(root=root)
    runtime = OpenTenBaseRuntime()
    diagnoses = [diagnose_plugin(root, runtime, manifest) for manifest in catalog.load_all()]
    if as_json:
        print(json.dumps([diagnosis_summary_json(diagnosis) for diagnosis in diagnoses], indent=2, ensure_ascii=False))
        return 0
    headers, rows = diagnosis_rows(diagnoses, output_lang, value, text)
    print(
        render_table(headers, rows)
    )
    return 0


def _manifest_path_for(root: Path, plugin_id: str) -> Path:
    return find_plugin_manifest_path(root, plugin_id)


def cmd_plugin_lint(root: Path, plugin_id: str, *, as_json: bool = False, lang: str | None = None) -> int:
    output_lang = normalize_lang(lang)
    items = lint_manifest_path(_manifest_path_for(root, plugin_id))
    if as_json:
        print(json.dumps(lint_items_json(items), indent=2, ensure_ascii=False))
    else:
        rows = [[item.plugin_id, item.check, value(item.status, output_lang), item.detail] for item in items]
        print(render_table(["plugin_id", text("check", output_lang), text("status", output_lang), text("detail", output_lang)], rows))
    return 1 if any(item.status == "fail" for item in items) else 0


def cmd_plugin_plan(root: Path, plugin_id: str, *, as_json: bool = False, lang: str | None = None) -> int:
    output_lang = normalize_lang(lang)
    manifest = Catalog(root=root).load_one(plugin_id)
    plan = plugin_plan(OpenTenBaseRuntime(), manifest)
    if as_json:
        print(json.dumps(plugin_plan_json(plan), indent=2, ensure_ascii=False))
        return 0
    rows = [
        [text("plugin", output_lang), plan.plugin_id],
        [text("version", output_lang), plan.version],
        [text("installed_state", output_lang), value(plan.installed_state, output_lang)],
        [text("target_roles", output_lang), ", ".join(plan.target_roles) or "none"],
        [text("deploy_plan", output_lang), plan.deploy_plan],
        [text("verify_plan", output_lang), plan.verify_plan],
        [text("rollback_plan", output_lang), plan.rollback_plan],
        [text("removed_verify_plan", output_lang), plan.removed_verify_plan],
        [text("risk", output_lang), "; ".join(plan.risks) or "none"],
        [text("recommendation", output_lang), plan.recommendation],
    ]
    print(render_table([text("check", output_lang), text("detail", output_lang)], rows))
    return 0


def cmd_plugin_precheck(root: Path, plugin_id: str, *, as_json: bool = False, lang: str | None = None) -> int:
    output_lang = normalize_lang(lang)
    manifest = Catalog(root=root).load_one(plugin_id)
    items = plugin_precheck(root, OpenTenBaseRuntime(), manifest)
    if as_json:
        print(json.dumps(precheck_items_json(items), indent=2, ensure_ascii=False))
    else:
        rows = [[item.plugin_id, item.check, value(item.status, output_lang), item.detail] for item in items]
        print(render_table(["plugin_id", text("check", output_lang), text("status", output_lang), text("detail", output_lang)], rows))
    return 1 if any(item.status == "fail" for item in items) else 0


def cmd_plugin_diagnose(root: Path, plugin_id: str, *, as_json: bool = False, lang: str | None = None) -> int:
    output_lang = normalize_lang(lang)
    manifest = Catalog(root=root).load_one(plugin_id)
    diagnosis = diagnose_plugin(root, OpenTenBaseRuntime(), manifest)
    ArchiveStore(root).upsert(build_archive_record(root, manifest, diagnosis))
    exit_code = 0 if diagnosis.next_action in {"deploy", "verify", "review"} else 1
    if as_json:
        print(json.dumps(diagnosis_json(diagnosis), indent=2, ensure_ascii=False))
    else:
        rows = [
            [text("plugin", output_lang), diagnosis.plugin_id],
            [text("version", output_lang), diagnosis.version],
            [text("package_ok", output_lang), value("yes" if diagnosis.package_ok else "no", output_lang)],
            [text("env_ready", output_lang), value("yes" if diagnosis.env_ready else "no", output_lang)],
            [text("installed_state", output_lang), value(diagnosis.installed_state, output_lang)],
            [text("next_action", output_lang), value(diagnosis.next_action, output_lang)],
            [text("risk", output_lang), diagnosis.risk],
            [text("conclusion", output_lang), message(diagnosis.conclusion_key, output_lang)],
        ]
        print(render_table([text("check", output_lang), text("detail", output_lang)], rows))
    return exit_code


def cmd_plugin_roles(root: Path, plugin_id: str, *, as_json: bool = False) -> int:
    manifest = Catalog(root=root).load_one(plugin_id)
    if as_json:
        print(json.dumps(role_summary(manifest), indent=2, ensure_ascii=False))
        return 0
    rows = [[step.role, step.step, step.detail] for step in role_steps(manifest)]
    print(render_table(["role", "step", "detail"], rows))
    return 0


def cmd_plugin_consistency(root: Path, plugin_id: str, *, as_json: bool = False) -> int:
    manifest = Catalog(root=root).load_one(plugin_id)
    items = consistency_check(root, OpenTenBaseRuntime(), manifest)
    if as_json:
        print(json.dumps(consistency_items_json(items), indent=2, ensure_ascii=False))
    else:
        rows = [[item.plugin_id, item.check, item.status, item.detail] for item in items]
        print(render_table(["plugin_id", "check", "status", "detail"], rows))
    return 1 if any(item.status == "fail" for item in items) else 0


def cmd_plugin_archive_list(root: Path, *, as_json: bool = False) -> int:
    records = ArchiveStore(root).all()
    if as_json:
        print(json.dumps(archive_list_json(records), indent=2, ensure_ascii=False))
        return 0
    if not records:
        print("No archive records found.")
        return 0
    rows = [[record.plugin_id, record.version, record.status, ", ".join(record.target_roles), record.installed_at, record.updated_at] for record in records]
    print(render_table(["plugin_id", "version", "status", "target_roles", "installed_at", "updated_at"], rows))
    return 0


def cmd_plugin_archive_inspect(root: Path, plugin_id: str, *, as_json: bool = False) -> int:
    record = ArchiveStore(root).get(plugin_id)
    if record is None:
        print("{}" if as_json else f"No archive record found for {plugin_id}.")
        return 0
    payload = archive_record_json(record)
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    rows = [[key, json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)] for key, value in payload.items()]
    print(render_table(["field", "value"], rows))
    return 0


def _runtime_metadata(runtime: OpenTenBaseRuntime) -> dict[str, Any]:
    return {
        "cluster": "local-docker-opentenbase",
        "container": runtime.container,
        "host": runtime.host,
        "port": runtime.port,
        "database": runtime.database,
        "user": runtime.user,
    }


def _summarize_text(value: str, limit: int = 300) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def record_action_result(root: Path, manifest_version: str, runtime: OpenTenBaseRuntime, result: ActionResult) -> None:
    metadata = {
        **_runtime_metadata(runtime),
        **result.metadata,
        "version": manifest_version,
        "stage": result.metadata.get("stage", ""),
        "returncode": result.returncode,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "duration_ms": result.duration_ms,
        "stdout_summary": _summarize_text(result.stdout),
        "stderr_summary": _summarize_text(result.stderr),
    }
    StateStore(root).append(
        plugin_id=result.plugin_id,
        action=result.action,
        ok=result.ok,
        detail=result.detail,
        metadata=metadata,
    )


def refresh_archive(root: Path, manifest, runtime: OpenTenBaseRuntime) -> None:
    diagnosis = diagnose_plugin(root, runtime, manifest)
    ArchiveStore(root).upsert(build_archive_record(root, manifest, diagnosis))


def cmd_verify(root: Path, plugin_id: str, *, removed: bool = False) -> int:
    catalog = Catalog(root=root)
    manifest = catalog.load_one(plugin_id)
    runtime = OpenTenBaseRuntime()
    smoke_result = run_removed_verify(runtime, manifest) if removed else run_smoke_verify(runtime, manifest, manifest.smoke_sql)
    record_action_result(root, manifest.version, runtime, smoke_result)
    refresh_archive(root, manifest, runtime)
    if smoke_result.stdout:
        print(smoke_result.stdout)
    if smoke_result.stderr:
        print(smoke_result.stderr)
    if smoke_result.ok:
        print(f"{manifest.plugin_id}: {'removed' if removed else 'smoke'} verify passed")
        return 0
    print(f"{manifest.plugin_id}: {'removed' if removed else 'smoke'} verify failed")
    return smoke_result.returncode or 1


def cmd_deploy(root: Path, plugin_id: str) -> int:
    catalog = Catalog(root=root)
    manifest = catalog.load_one(plugin_id)
    runtime = OpenTenBaseRuntime()
    result = deploy_sql_payload(runtime, manifest)
    result.metadata.update(
        {
            "source_root": str(manifest.source_root),
            "install_sql": str(manifest.install_sql),
        }
    )
    record_action_result(root, manifest.version, runtime, result)
    refresh_archive(root, manifest, runtime)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    if result.ok:
        print(f"{manifest.plugin_id}: deploy passed")
        return 0
    print(result.detail)
    print(f"{manifest.plugin_id}: deploy failed")
    return result.returncode or 1


def cmd_state(root: Path, plugin_id: str | None) -> int:
    store = StateStore(root)
    if plugin_id:
        record = store.latest(plugin_id)
        if record is None:
            print(f"No state found for {plugin_id}.")
            return 0
        rows = [row_for_record(record)]
        print(
            render_table(
                [
                    "timestamp",
                    "plugin_id",
                    "action",
                    "ok",
                    "version",
                    "stage",
                    "returncode",
                    "duration_ms",
                    "stdout",
                    "stderr",
                    "detail",
                ],
                rows,
            )
        )
        return 0

    records = store.all()
    if not records:
        print("No state records found.")
        return 0
    rows = [row_for_record(r) for r in records]
    print(
        render_table(
            [
                "timestamp",
                "plugin_id",
                "action",
                "ok",
                "version",
                "stage",
                "returncode",
                "duration_ms",
                "stdout",
                "stderr",
                "detail",
            ],
            rows,
        )
    )
    return 0


def cmd_report(root: Path, *, as_json: bool = False) -> int:
    store = StateStore(root)
    records = store.all()
    if not records:
        print("[]" if as_json else "No report data yet.")
        return 0
    if as_json:
        print(json.dumps(latest_by_plugin_action_json(records), indent=2, ensure_ascii=False))
        return 0
    rows = latest_by_plugin_action(records)
    print(
        render_table(
            ["plugin_id", "action", "ok", "version", "stage", "returncode", "duration_ms", "stdout", "stderr", "timestamp", "detail"],
            rows,
        )
    )
    return 0


def cmd_rollback(root: Path, plugin_id: str, *, execute: bool = False) -> int:
    catalog = Catalog(root=root)
    manifest = catalog.load_one(plugin_id)
    runtime = OpenTenBaseRuntime()
    result = rollback_plugin(runtime, manifest, execute=execute)
    result.metadata.setdefault("rollback_sql", str(manifest.rollback_sql) if manifest.rollback_sql else None)
    record_action_result(root, manifest.version, runtime, result)
    refresh_archive(root, manifest, runtime)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    if result.ok:
        if result.metadata.get("dry_run"):
            print(result.detail)
            print(f"{manifest.plugin_id}: rollback dry-run completed")
            return 0
        print(f"{manifest.plugin_id}: rollback passed")
        return 0
    print(result.detail)
    print(f"{manifest.plugin_id}: rollback not completed")
    return result.returncode or 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "list":
            return cmd_list(args.root)
        if args.command == "inspect":
            return cmd_inspect(args.root, args.plugin_id)
        if args.command == "doctor":
            return cmd_doctor(args)
        if args.command == "cluster":
            if args.cluster_command == "status":
                return cmd_cluster_status()
        if args.command == "plugin":
            if args.plugin_command == "check":
                return cmd_plugin_check(args.root, args.plugin_id, lang=args.lang)
            if args.plugin_command == "status":
                return cmd_plugin_status(args.root, args.plugin_id, lang=args.lang)
            if args.plugin_command == "lint":
                return cmd_plugin_lint(args.root, args.plugin_id, as_json=args.json, lang=args.lang)
            if args.plugin_command == "plan":
                return cmd_plugin_plan(args.root, args.plugin_id, as_json=args.json, lang=args.lang)
            if args.plugin_command == "precheck":
                return cmd_plugin_precheck(args.root, args.plugin_id, as_json=args.json, lang=args.lang)
            if args.plugin_command == "diagnose":
                return cmd_plugin_diagnose(args.root, args.plugin_id, as_json=args.json, lang=args.lang)
            if args.plugin_command == "roles":
                return cmd_plugin_roles(args.root, args.plugin_id, as_json=args.json)
            if args.plugin_command == "consistency":
                return cmd_plugin_consistency(args.root, args.plugin_id, as_json=args.json)
            if args.plugin_command == "archive":
                if args.archive_command == "list":
                    return cmd_plugin_archive_list(args.root, as_json=args.json)
                if args.archive_command == "inspect":
                    return cmd_plugin_archive_inspect(args.root, args.plugin_id, as_json=args.json)
        if args.command == "plugins":
            if args.plugins_command == "status":
                return cmd_plugins_status(args.root, as_json=args.json, lang=args.lang)
        if args.command == "verify":
            return cmd_verify(args.root, args.plugin_id or "otb_timeseries", removed=args.removed)
        if args.command == "state":
            return cmd_state(args.root, args.plugin_id)
        if args.command == "report":
            return cmd_report(args.root, as_json=args.json)
        if args.command == "deploy":
            return cmd_deploy(args.root, args.plugin_id or "otb_timeseries")
        if args.command == "rollback":
            return cmd_rollback(args.root, args.plugin_id or "otb_timeseries", execute=args.execute)
    except ManifestError as exc:
        parser.error(str(exc))

    return 0

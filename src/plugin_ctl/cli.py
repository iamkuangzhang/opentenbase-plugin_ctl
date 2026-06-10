from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from . import __version__
from .action_result import ActionResult
from .activation import (
    PsqlCoordinatorExecutor,
    activation_report_json,
    dry_run_activation_plan,
    execute_activation,
)
from .catalog import Catalog
from .cluster import ClusterConfig, ClusterNode, load_cluster_config, run_cluster_status
from .deploy import deploy_sql_payload
from .distribution import (
    build_distribution_plan,
    distribute_payload_to_nodes,
    distribution_plan_json,
    distribution_results_json,
    physical_payload_files,
)
from .distributed_verify import distributed_verify_report_json, run_distributed_verify
from .doctor import run_doctor
from .i18n import message, normalize_lang, text, value
from .manifest import ManifestError
from .plugin_archive import ArchiveStore, archive_list_json, archive_record_json, build_archive_record
from .plugin_consistency import consistency_check, consistency_items_json
from .plugin_diagnose import PluginDiagnosis, diagnose_plugin, diagnosis_json, diagnosis_summary_json, diagnosis_rows
from .plugin_governance import governance_status, governance_status_json, plugin_checks
from .plugin_package import (
    LintItem,
    PluginPlan,
    PrecheckItem,
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
from .shell import run_shell
from .source_assess import assess_items_json, assess_source
from .state_store import StateStore
from .runtime.opentenbase import OpenTenBaseRuntime, ScpSshRemoteExecutor
from .verify import run_removed_verify, run_smoke_verify
from .util import render_table


TOP_LEVEL_COMMANDS = {
    "shell",
    "list",
    "inspect",
    "check",
    "assess",
    "register",
    "activate",
    "doctor",
    "cluster",
    "plugin",
    "plugins",
    "deploy",
    "verify",
    "state",
    "rollback",
    "report",
}


def platform_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _has_top_level_command(argv: list[str]) -> bool:
    return any(arg in TOP_LEVEL_COMMANDS for arg in argv)


def _only_root_global_args(argv: list[str]) -> bool:
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--root":
            if index + 1 >= len(argv):
                return False
            index += 2
            continue
        if arg.startswith("--root="):
            index += 1
            continue
        return False
    return True


def _root_from_global_args(argv: list[str]) -> Path:
    root = platform_root()
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--root" and index + 1 < len(argv):
            root = Path(argv[index + 1])
            index += 2
            continue
        if arg.startswith("--root="):
            root = Path(arg.split("=", 1)[1])
        index += 1
    return root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plugin_ctl",
        description="OpenTenBase PluginCtl: plugin-centered lifecycle governance for OpenTenBase.",
        epilog=(
            "main flow: check -> deploy -> register -> verify -> report; "
            "advanced/debug: plugin lint/plan/precheck/diagnose, cluster distribute; "
            "other groups: discovery=list/inspect; lifecycle=rollback; archive=plugin archive list/inspect; "
            "distributed=plugin roles/consistency; runtime=doctor/cluster status"
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--root", type=Path, default=platform_root(), help="platform directory root")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("shell", help="interactive plugin lifecycle shell")
    subparsers.add_parser("list", help="discovery: list plugin manifests")

    inspect_parser = subparsers.add_parser("inspect", help="discovery: show a plugin manifest")
    inspect_parser.add_argument("plugin_id")

    check_parser = subparsers.add_parser("check", help="main flow: aggregate lint, plan, precheck, and diagnose")
    check_parser.add_argument("plugin_id")
    check_parser.add_argument("--json", action="store_true", help="emit aggregated check result as JSON")
    check_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help="human output language")

    assess_parser = subparsers.add_parser("assess", help="governance: statically assess PostgreSQL extension source migration risks")
    assess_parser.add_argument("source_path", type=Path)
    assess_parser.add_argument("--json", action="store_true", help="emit assessment result as JSON")

    def add_register_args(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("plugin_id")
        command_parser.add_argument("-f", "--cluster-file", type=Path, required=True, help="cluster.toml path")
        mode = command_parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="show registration and view-check plan only")
        mode.add_argument("--execute", action="store_true", help="execute CREATE EXTENSION once on the primary coordinator")
        command_parser.add_argument("--json", action="store_true", help="emit registration report as JSON")

    register_parser = subparsers.add_parser("register", help="main flow: register extension metadata once, then verify CN views")
    add_register_args(register_parser)
    activate_parser = subparsers.add_parser("activate", help="deprecated alias for register")
    add_register_args(activate_parser)

    doctor_parser = subparsers.add_parser("doctor", help="runtime: check local OpenTenBase runtime")
    doctor_parser.add_argument("--container", default="opentenbaseDN1")
    doctor_parser.add_argument("--host", default="127.0.0.1")
    doctor_parser.add_argument("--port", type=int, default=30004)
    doctor_parser.add_argument("--user", default="opentenbase")
    doctor_parser.add_argument("--database", default="postgres")

    cluster_parser = subparsers.add_parser("cluster", help="runtime/distributed: inspect OpenTenBase cluster status and topology")
    cluster_subparsers = cluster_parser.add_subparsers(dest="cluster_command", required=True)
    cluster_subparsers.add_parser("status", help="read-only local Docker/OpenTenBase status")
    cluster_inspect_parser = cluster_subparsers.add_parser("inspect", help="distributed: inspect a cluster.toml topology")
    cluster_inspect_parser.add_argument("-f", "--file", type=Path, required=True, help="cluster.toml path")
    cluster_inspect_parser.add_argument("--json", action="store_true", help="emit topology as JSON")
    cluster_distribute_parser = cluster_subparsers.add_parser("distribute", help="distributed: dry-run or execute physical payload distribution")
    distribute_mode = cluster_distribute_parser.add_mutually_exclusive_group()
    distribute_mode.add_argument("--dry-run", action="store_true", help="build a plan only; do not scp or modify remote nodes")
    distribute_mode.add_argument("--execute", action="store_true", help="execute physical scp distribution and SHA256 verification")
    cluster_distribute_parser.add_argument("-f", "--file", type=Path, required=True, help="cluster.toml path")
    cluster_distribute_parser.add_argument("plugin_id")
    cluster_distribute_parser.add_argument("--json", action="store_true", help="emit distribution plan/result as JSON")

    plugin_parser = subparsers.add_parser("plugin", help="plugin governance, archive, and distributed checks")
    plugin_subparsers = plugin_parser.add_subparsers(dest="plugin_command", required=True)
    plugin_check_parser = plugin_subparsers.add_parser("check", help="governance: check one plugin governance state")
    plugin_check_parser.add_argument("plugin_id")
    plugin_check_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help="human output language")
    plugin_status_parser = plugin_subparsers.add_parser("status", help="governance: show one plugin summary")
    plugin_status_parser.add_argument("plugin_id")
    plugin_status_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help="human output language")
    plugin_lint_parser = plugin_subparsers.add_parser("lint", help="governance: lint one plugin package without connecting to database")
    plugin_lint_parser.add_argument("plugin_id")
    plugin_lint_parser.add_argument("--json", action="store_true", help="emit lint result as JSON")
    plugin_lint_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help="human output language")
    plugin_plan_parser = plugin_subparsers.add_parser("plan", help="governance: show non-executing lifecycle plan for one plugin")
    plugin_plan_parser.add_argument("plugin_id")
    plugin_plan_parser.add_argument("--json", action="store_true", help="emit plan as JSON")
    plugin_plan_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help="human output language")
    plugin_precheck_parser = plugin_subparsers.add_parser("precheck", help="governance: run read-only pre-deploy checks for one plugin")
    plugin_precheck_parser.add_argument("plugin_id")
    plugin_precheck_parser.add_argument("--json", action="store_true", help="emit precheck result as JSON")
    plugin_precheck_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help="human output language")
    plugin_diagnose_parser = plugin_subparsers.add_parser("diagnose", help="governance: aggregate lint, plan, and precheck for one plugin")
    plugin_diagnose_parser.add_argument("plugin_id")
    plugin_diagnose_parser.add_argument("--json", action="store_true", help="emit diagnosis result as JSON")
    plugin_diagnose_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help="human output language")
    plugin_roles_parser = plugin_subparsers.add_parser("roles", help="distributed: show plugin role-scoped governance steps")
    plugin_roles_parser.add_argument("plugin_id")
    plugin_roles_parser.add_argument("--json", action="store_true", help="emit role mapping as JSON")
    plugin_consistency_parser = plugin_subparsers.add_parser("consistency", help="distributed: run read-only plugin consistency checks")
    plugin_consistency_parser.add_argument("plugin_id")
    plugin_consistency_parser.add_argument("--json", action="store_true", help="emit consistency checks as JSON")
    plugin_archive_parser = plugin_subparsers.add_parser("archive", help="archive: inspect plugin archive records")
    plugin_archive_subparsers = plugin_archive_parser.add_subparsers(dest="archive_command", required=True)
    plugin_archive_list_parser = plugin_archive_subparsers.add_parser("list", help="archive: list archived plugin package records")
    plugin_archive_list_parser.add_argument("--json", action="store_true", help="emit archive records as JSON")
    plugin_archive_inspect_parser = plugin_archive_subparsers.add_parser("inspect", help="archive: inspect one archived plugin package record")
    plugin_archive_inspect_parser.add_argument("plugin_id")
    plugin_archive_inspect_parser.add_argument("--json", action="store_true", help="emit archive record as JSON")

    plugins_parser = subparsers.add_parser("plugins", help="governance: multi-plugin governance commands")
    plugins_subparsers = plugins_parser.add_subparsers(dest="plugins_command", required=True)
    plugins_status_parser = plugins_subparsers.add_parser("status", help="governance: show governance status for all plugins")
    plugins_status_parser.add_argument("--json", action="store_true", help="emit plugin governance status as JSON")
    plugins_status_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help="human output language")

    command_help = {
        "deploy": "main flow: deploy locally, or physically distribute with -f cluster.toml",
        "verify": "lifecycle: verify one plugin package",
        "state": "reporting: show local action state",
        "rollback": "lifecycle: rollback one plugin package; dry-run unless --execute is set",
        "report": "reporting: show latest action report",
    }
    for name in ["deploy", "verify", "state", "rollback", "report"]:
        cmd = subparsers.add_parser(name, help=command_help[name])
        if name in {"deploy", "verify", "state", "rollback"}:
            cmd.add_argument("plugin_id", nargs="?")
        if name == "verify":
            cmd.add_argument("--removed", action="store_true", help="verify that plugin objects are absent using removed_probe")
            cmd.add_argument("-f", "--cluster-file", type=Path, help="cluster.toml path for distributed white-box verification")
            cmd.add_argument("--json", action="store_true", help="with -f, emit distributed verify report as JSON")
        if name == "deploy":
            deploy_mode = cmd.add_mutually_exclusive_group()
            deploy_mode.add_argument("--dry-run", action="store_true", help="with -f, build physical distribution plan only")
            deploy_mode.add_argument("--execute", action="store_true", help="with -f, execute physical file distribution only")
            cmd.add_argument("-f", "--cluster-file", type=Path, help="cluster.toml path for distributed physical file distribution")
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


def _node_json(node: ClusterNode) -> dict[str, object]:
    return {
        "name": node.name,
        "role": node.role,
        "host": node.host,
        "ssh_port": node.ssh_port,
        "db_port": node.db_port,
        "ssh_user": node.ssh_user,
        "db_user": node.db_user,
        "database": node.database,
        "lib_dir": node.lib_dir,
        "extension_dir": node.extension_dir,
    }


def _cluster_inspect_json(config: ClusterConfig) -> dict[str, object]:
    return {
        "cluster": config.name,
        "coordinators": [_node_json(node) for node in config.coordinators],
        "datanodes": [_node_json(node) for node in config.datanodes],
        "result": "OK",
        "errors": [],
    }


def _render_nodes(title: str, nodes: tuple[ClusterNode, ...]) -> str:
    rows = [
        [
            node.name,
            node.host,
            str(node.ssh_port),
            str(node.db_port),
            node.ssh_user,
            node.db_user,
            node.database,
            node.lib_dir,
            node.extension_dir,
        ]
        for node in nodes
    ]
    if not rows:
        return f"{title}: none"
    return title + ":\n" + render_table(
        ["name", "host", "ssh_port", "db_port", "ssh_user", "db_user", "database", "lib_dir", "extension_dir"],
        rows,
    )


def cmd_cluster_inspect(cluster_file: Path, *, as_json: bool = False) -> int:
    config = load_cluster_config(cluster_file)
    if as_json:
        print(json.dumps(_cluster_inspect_json(config), indent=2, ensure_ascii=False))
        return 0
    print(f"Cluster: {config.name}")
    print(_render_nodes("Coordinators", config.coordinators))
    print(_render_nodes("Datanodes", config.datanodes))
    print("Result: OK")
    return 0


def _distribution_summary(results) -> dict[str, int]:
    failed = [result for result in results if not result.ok]
    checksum_failed = [result for result in results if result.status == "checksum_failed"]
    return {
        "total": len(results),
        "succeeded": len(results) - len(failed),
        "failed": len(failed),
        "checksum_failed": len(checksum_failed),
    }


def _distribution_errors(results) -> list[str]:
    return [
        f"{result.node}: {result.local_path} -> {result.remote_path}: {result.status}: {result.detail}"
        for result in results
        if not result.ok
    ]


def _execute_distribution_json(config: ClusterConfig, plugin_id: str, results) -> dict[str, object]:
    summary = _distribution_summary(results)
    result_items = distribution_results_json(results)
    return {
        "cluster": config.name,
        "mode": "execute",
        "plugin_id": plugin_id,
        "coordinators": [node.name for node in config.coordinators],
        "datanodes": [node.name for node in config.datanodes],
        "plan": result_items,
        "summary": summary,
        "results": result_items,
        "errors": _distribution_errors(results),
    }


def cmd_cluster_distribute(
    root: Path,
    cluster_file: Path,
    plugin_id: str,
    *,
    dry_run: bool = False,
    execute: bool = False,
    as_json: bool = False,
) -> int:
    config = load_cluster_config(cluster_file)
    manifest = Catalog(root=root).load_one(plugin_id)
    plan = build_distribution_plan(config, manifest)
    mode = "execute" if execute else "dry-run"

    if not execute:
        payload = distribution_plan_json(plan)
        if as_json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 1 if plan.errors else 0

        print(f"Cluster: {plan.cluster}")
        print(f"Plugin: {plan.plugin_id}")
        print(f"Mode: {mode}")
        rows = [
            [
                entry.node,
                entry.role,
                entry.file_type,
                "yes" if entry.exists else "no",
                entry.local_path,
                entry.remote_path,
            ]
            for entry in plan.plan
        ]
        if rows:
            print(render_table(["node", "role", "type", "exists", "local_path", "remote_path"], rows))
        else:
            print("No payload files in plan.")
        if plan.errors:
            print("Errors:")
            for error in plan.errors:
                print(f"- {error}")
            return 1
        print("Result: OK")
        return 0

    if plan.errors:
        payload = {
            **distribution_plan_json(plan),
            "mode": "execute",
            "summary": {"total": 0, "succeeded": 0, "failed": len(plan.errors), "checksum_failed": 0},
        }
        if as_json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"Cluster: {plan.cluster}")
            print(f"Plugin: {plan.plugin_id}")
            print("Mode: execute")
            print("Errors:")
            for error in plan.errors:
                print(f"- {error}")
            print("Result: FAILED")
        return 1

    payload_files = list(physical_payload_files(manifest))
    results = distribute_payload_to_nodes(config, payload_files, ScpSshRemoteExecutor())
    if as_json:
        print(json.dumps(_execute_distribution_json(config, plugin_id, results), indent=2, ensure_ascii=False))
        return 0 if all(result.ok for result in results) else 1

    print(f"Cluster: {config.name}")
    print(f"Plugin: {plugin_id}")
    print("Mode: execute")
    rows = [
        [
            result.node,
            result.role,
            result.status,
            result.stage,
            str(result.returncode),
            result.local_sha256,
            result.remote_sha256,
            result.local_path,
            result.remote_path,
        ]
        for result in sorted(results, key=lambda item: (item.node, item.local_path, item.remote_path))
    ]
    if rows:
        print(render_table(["node", "role", "status", "stage", "returncode", "local_sha256", "remote_sha256", "local_path", "remote_path"], rows))
    else:
        print("No payload files distributed.")
    summary = _distribution_summary(results)
    print(
        "Summary: "
        f"total={summary['total']} succeeded={summary['succeeded']} "
        f"failed={summary['failed']} checksum_failed={summary['checksum_failed']}"
    )
    errors = _distribution_errors(results)
    if errors:
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        print("Result: FAILED")
        return 1
    print("Result: OK")
    return 0


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


def _aggregated_check(root: Path, plugin_id: str) -> tuple[list[LintItem], PluginPlan, list[PrecheckItem], PluginDiagnosis]:
    manifest_path = _manifest_path_for(root, plugin_id)
    manifest = Catalog(root=root).load_one(plugin_id)
    runtime = OpenTenBaseRuntime()
    lint_items = lint_manifest_path(manifest_path)
    plan = plugin_plan(runtime, manifest)
    precheck_items = plugin_precheck(root, runtime, manifest)
    diagnosis = diagnose_plugin(root, runtime, manifest)
    return lint_items, plan, precheck_items, diagnosis


def _aggregated_check_errors(lint_items: list[LintItem], precheck_items: list[PrecheckItem], diagnosis: PluginDiagnosis) -> list[str]:
    errors: list[str] = []
    errors.extend(f"lint:{item.check}: {item.detail}" for item in lint_items if item.status == "fail")
    errors.extend(f"precheck:{item.check}: {item.detail}" for item in precheck_items if item.status == "fail")
    if diagnosis.next_action not in {"deploy", "verify", "review"}:
        errors.append(f"diagnose:{diagnosis.next_action}: {diagnosis.risk}")
    return errors


def cmd_check(root: Path, plugin_id: str, *, as_json: bool = False, lang: str | None = None) -> int:
    output_lang = normalize_lang(lang)
    lint_items, plan, precheck_items, diagnosis = _aggregated_check(root, plugin_id)
    errors = _aggregated_check_errors(lint_items, precheck_items, diagnosis)
    if as_json:
        print(
            json.dumps(
                {
                    "plugin_id": plugin_id,
                    "ok": not errors,
                    "lint": lint_items_json(lint_items),
                    "plan": plugin_plan_json(plan),
                    "precheck": precheck_items_json(precheck_items),
                    "diagnose": diagnosis_json(diagnosis),
                    "errors": errors,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 1 if errors else 0

    print(f"Plugin: {plugin_id}")
    print("== lint ==")
    print(render_table(["plugin_id", text("check", output_lang), text("status", output_lang), text("detail", output_lang)], [[item.plugin_id, item.check, value(item.status, output_lang), item.detail] for item in lint_items]))
    print("== plan ==")
    print(
        render_table(
            [text("check", output_lang), text("detail", output_lang)],
            [
                [text("installed_state", output_lang), value(plan.installed_state, output_lang)],
                [text("target_roles", output_lang), ", ".join(plan.target_roles) or "none"],
                [text("deploy_plan", output_lang), plan.deploy_plan],
                [text("verify_plan", output_lang), plan.verify_plan],
                [text("rollback_plan", output_lang), plan.rollback_plan],
                [text("risk", output_lang), "; ".join(plan.risks) or "none"],
                [text("recommendation", output_lang), plan.recommendation],
            ],
        )
    )
    print("== precheck ==")
    print(render_table(["plugin_id", text("check", output_lang), text("status", output_lang), text("detail", output_lang)], [[item.plugin_id, item.check, value(item.status, output_lang), item.detail] for item in precheck_items]))
    print("== diagnose ==")
    print(
        render_table(
            [text("check", output_lang), text("detail", output_lang)],
            [
                [text("package_ok", output_lang), value("yes" if diagnosis.package_ok else "no", output_lang)],
                [text("env_ready", output_lang), value("yes" if diagnosis.env_ready else "no", output_lang)],
                [text("installed_state", output_lang), value(diagnosis.installed_state, output_lang)],
                [text("next_action", output_lang), value(diagnosis.next_action, output_lang)],
                [text("risk", output_lang), diagnosis.risk],
                [text("conclusion", output_lang), message(diagnosis.conclusion_key, output_lang)],
            ],
        )
    )
    if errors:
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        print("Result: FAILED")
        return 1
    print("Result: OK")
    return 0


def cmd_assess(source_path: Path, *, as_json: bool = False) -> int:
    items = assess_source(source_path)
    if as_json:
        print(json.dumps({"source_path": str(source_path), "items": assess_items_json(items)}, indent=2, ensure_ascii=False))
    else:
        rows = [[item.check, item.status, item.path, str(item.line or ""), item.detail] for item in items]
        print(render_table(["check", "status", "path", "line", "detail"], rows))
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


def _render_distributed_verify_report(report) -> None:
    print(f"Cluster: {report.cluster}")
    print(f"Plugin: {report.plugin_id}")
    print(f"Extension: {report.extension_name}")
    print(f"Mode: {report.mode}")
    print(f"Physical distribution: {report.physical_distribution}")
    print(f"CREATE EXTENSION: {report.create_extension}")
    print("Coordinator extension check:")
    print(
        render_table(
            ["node", "connected_status", "extension_status", "detected_version", "returncode"],
            [[item.node, item.connected_status, item.extension_status, item.detected_version, str(item.returncode)] for item in report.coordinator_extensions],
        )
    )
    print("Physical file checksum check:")
    print(
        render_table(
            ["node", "role", "file_type", "local_path", "remote_path", "file_status", "local_sha256", "remote_sha256"],
            [
                [
                    item.node,
                    item.role,
                    item.file_type,
                    item.local_path,
                    item.remote_path,
                    item.file_status,
                    item.local_sha256,
                    item.remote_sha256,
                ]
                for item in report.file_checks
            ],
        )
    )
    print("Prepared transaction scan:")
    print(
        render_table(
            ["node", "role", "prepared_transactions_count", "status"],
            [[item.node, item.role, str(item.prepared_transactions_count), item.status] for item in report.prepared_transactions],
        )
    )
    print(
        "Summary: "
        f"total_cn={report.summary.total_cn} total_dn={report.summary.total_dn} "
        f"extension_consistent={report.summary.extension_consistent} "
        f"files_checked={report.summary.files_checked} checksum_failed={report.summary.checksum_failed} "
        f"prepared_leak={report.summary.prepared_leak} failed={report.summary.failed}"
    )
    if report.errors:
        print("Errors:")
        for error in report.errors:
            print(f"- {error}")
        print("Result: FAILED")
    else:
        print("Result: OK")


def cmd_verify_distributed(root: Path, plugin_id: str, cluster_file: Path, *, as_json: bool = False) -> int:
    config = load_cluster_config(cluster_file)
    manifest = Catalog(root=root).load_one(plugin_id)
    report = run_distributed_verify(config, manifest, PsqlCoordinatorExecutor(), ScpSshRemoteExecutor())
    if as_json:
        print(json.dumps(distributed_verify_report_json(report), indent=2, ensure_ascii=False))
    else:
        _render_distributed_verify_report(report)
    return 1 if report.errors else 0


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


def cmd_deploy_physical_distribution(
    root: Path,
    plugin_id: str,
    cluster_file: Path,
    *,
    dry_run: bool = False,
    execute: bool = False,
) -> int:
    config = load_cluster_config(cluster_file)
    manifest = Catalog(root=root).load_one(plugin_id)
    plan = build_distribution_plan(config, manifest)
    mode = "execute" if execute else "dry-run"

    if not execute:
        print(f"Cluster: {plan.cluster}")
        print(f"Plugin: {plan.plugin_id}")
        print(f"Mode: {mode}")
        print("Physical distribution: planned")
        print("Activate: skipped")
        print("CREATE EXTENSION: not executed")
        rows = [
            [
                entry.node,
                entry.role,
                entry.file_type,
                "yes" if entry.exists else "no",
                entry.local_path,
                entry.remote_path,
            ]
            for entry in plan.plan
        ]
        if rows:
            print(render_table(["node", "role", "type", "exists", "local_path", "remote_path"], rows))
        else:
            print("No payload files in plan.")
        if plan.errors:
            print("Errors:")
            for error in plan.errors:
                print(f"- {error}")
            print("Result: FAILED")
            return 1
        print("Result: OK")
        return 0

    if plan.errors:
        print(f"Cluster: {plan.cluster}")
        print(f"Plugin: {plan.plugin_id}")
        print("Mode: execute")
        print("Physical distribution: blocked")
        print("Activate: skipped")
        print("CREATE EXTENSION: not executed")
        print("Errors:")
        for error in plan.errors:
            print(f"- {error}")
        print("Result: FAILED")
        return 1

    results = distribute_payload_to_nodes(config, list(physical_payload_files(manifest)), ScpSshRemoteExecutor())
    print(f"Cluster: {config.name}")
    print(f"Plugin: {plugin_id}")
    print("Mode: execute")
    print("Physical distribution: executed")
    print("Activate: skipped")
    print("CREATE EXTENSION: not executed")
    rows = [
        [
            result.node,
            result.role,
            result.status,
            result.stage,
            str(result.returncode),
            result.local_sha256,
            result.remote_sha256,
            result.local_path,
            result.remote_path,
        ]
        for result in sorted(results, key=lambda item: (item.node, item.local_path, item.remote_path))
    ]
    if rows:
        print(render_table(["node", "role", "status", "stage", "returncode", "local_sha256", "remote_sha256", "local_path", "remote_path"], rows))
    summary = _distribution_summary(results)
    print(
        "Summary: "
        f"total={summary['total']} succeeded={summary['succeeded']} "
        f"failed={summary['failed']} checksum_failed={summary['checksum_failed']}"
    )
    errors = _distribution_errors(results)
    if errors:
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        print("Result: FAILED")
        return 1
    print("Result: OK")
    return 0


def _render_activation_report(report) -> None:
    print(f"Cluster: {report.cluster}")
    print(f"Plugin: {report.plugin_id}")
    print(f"Extension: {report.extension_name}")
    print(f"Mode: {report.mode}")
    print(f"Physical distribution: {report.physical_distribution}")
    print(f"Datanodes: {report.datanodes}")
    print(f"CREATE EXTENSION: {'executed on primary CN only' if report.mode == 'execute' else 'planned on primary CN only'}")
    activation_rows = [
        [
            result.node,
            result.status,
            str(result.returncode),
            result.sql,
            result.stdout.strip(),
            result.stderr.strip(),
        ]
        for result in report.activation
    ]
    if activation_rows:
        print("Registration:")
        print(render_table(["node", "register_status", "returncode", "sql", "stdout", "stderr"], activation_rows))
    version_rows = [
        [
            result.node,
            result.status,
            result.detected_version,
            str(result.returncode),
            result.sql,
            result.stderr.strip(),
        ]
        for result in report.versions
    ]
    if version_rows:
        print("Version check:")
        print(render_table(["node", "version_status", "detected_version", "returncode", "sql", "stderr"], version_rows))
    print(
        "Summary: "
        f"total_cn={report.summary.total_cn} activated={report.summary.activated} "
        f"failed={report.summary.failed} missing={report.summary.missing} "
        f"version_mismatch={report.summary.version_mismatch}"
    )
    if report.errors:
        print("Errors:")
        for error in report.errors:
            print(f"- {error}")
        print("Result: FAILED")
    else:
        print("Result: OK")


def cmd_register(root: Path, plugin_id: str, cluster_file: Path, *, execute: bool = False, as_json: bool = False, deprecated_alias: bool = False) -> int:
    config = load_cluster_config(cluster_file)
    manifest = Catalog(root=root).load_one(plugin_id)
    report = execute_activation(config, manifest, PsqlCoordinatorExecutor()) if execute else dry_run_activation_plan(config, manifest)
    if as_json:
        print(json.dumps(activation_report_json(report), indent=2, ensure_ascii=False))
    else:
        if deprecated_alias:
            print("Warning: activate is deprecated; use register.")
        _render_activation_report(report)
    return 1 if report.errors else 0


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
    if argv is None:
        argv = sys.argv[1:]
    if not _has_top_level_command(argv):
        parser = build_parser()
        if "-h" in argv or "--help" in argv or "--version" in argv or not _only_root_global_args(argv):
            parser.parse_args(argv)
            return 0
        root = _root_from_global_args(argv)
        if sys.stdin.isatty():
            return run_shell(root)
        parser.print_help()
        return 0

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "shell":
            return run_shell(args.root)
        if args.command == "list":
            return cmd_list(args.root)
        if args.command == "inspect":
            return cmd_inspect(args.root, args.plugin_id)
        if args.command == "check":
            return cmd_check(args.root, args.plugin_id, as_json=args.json, lang=args.lang)
        if args.command == "assess":
            return cmd_assess(args.source_path, as_json=args.json)
        if args.command == "register":
            return cmd_register(args.root, args.plugin_id, args.cluster_file, execute=args.execute, as_json=args.json)
        if args.command == "activate":
            return cmd_register(args.root, args.plugin_id, args.cluster_file, execute=args.execute, as_json=args.json, deprecated_alias=True)
        if args.command == "doctor":
            return cmd_doctor(args)
        if args.command == "cluster":
            if args.cluster_command == "status":
                return cmd_cluster_status()
            if args.cluster_command == "inspect":
                return cmd_cluster_inspect(args.file, as_json=args.json)
            if args.cluster_command == "distribute":
                return cmd_cluster_distribute(args.root, args.file, args.plugin_id, dry_run=args.dry_run, execute=args.execute, as_json=args.json)
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
            plugin_id = args.plugin_id or "otb_timeseries"
            if args.cluster_file:
                return cmd_verify_distributed(args.root, plugin_id, args.cluster_file, as_json=args.json)
            return cmd_verify(args.root, plugin_id, removed=args.removed)
        if args.command == "state":
            return cmd_state(args.root, args.plugin_id)
        if args.command == "report":
            return cmd_report(args.root, as_json=args.json)
        if args.command == "deploy":
            plugin_id = args.plugin_id or "otb_timeseries"
            if args.cluster_file:
                return cmd_deploy_physical_distribution(
                    args.root,
                    plugin_id,
                    args.cluster_file,
                    dry_run=args.dry_run,
                    execute=args.execute,
                )
            return cmd_deploy(args.root, plugin_id)
        if args.command == "rollback":
            return cmd_rollback(args.root, args.plugin_id or "otb_timeseries", execute=args.execute)
    except (FileNotFoundError, ManifestError, ValueError) as exc:
        parser.error(str(exc))

    return 0

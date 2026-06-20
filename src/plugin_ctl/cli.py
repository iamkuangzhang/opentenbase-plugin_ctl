from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any

from . import __version__
from .action_result import ActionResult
from .activation import (
    PsqlCoordinatorExecutor,
    activation_report_json,
    create_extension_sql,
    dry_run_activation_plan,
    execute_activation,
    extension_name_for,
)
from .catalog import Catalog
from .cluster import (
    DEFAULT_DATABASE,
    DEFAULT_DB_USER,
    DEFAULT_EXTENSION_DIR,
    DEFAULT_LIB_DIR,
    DEFAULT_SSH_PORT,
    DEFAULT_SSH_USER,
    ClusterConfig,
    ClusterNode,
    default_cluster_config_path,
    discover_cluster_config,
    find_cluster_config,
    load_cluster_config,
    require_cluster_config,
    run_cluster_status,
    write_cluster_config,
)
from .dev_init import create_plugin_skeleton
from .distribution import (
    build_distribution_plan,
    distribute_payload_to_nodes,
    distribution_plan_json,
    distribution_results_json,
    physical_payload_files,
    sync_plugin_metadata_to_nodes,
)
from .distributed_verify import distributed_verify_report_json, run_distributed_verify
from .doctor import run_doctor
from .i18n import message, normalize_lang, text, value
from .manifest import ManifestError
from .opentenbase_ctl_backend import OpenTenBaseCtlBackend, OpenTenBaseCtlError
from .plugin_archive import ArchiveStore, archive_list_json, archive_record_json, build_archive_record
from .plugin_consistency import consistency_check, consistency_items_json
from .plugin_diagnose import PluginDiagnosis, diagnose_plugin, diagnosis_json, diagnosis_summary_json, diagnosis_rows
from .plugin_governance import governance_status, governance_status_json, plugin_checks
from .plugin_health import build_plugin_health_report, health_report_json, render_health_report
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
from .runtime.opentenbase import OpenTenBaseCtlRemoteExecutor, OpenTenBaseRuntime, ScpSshRemoteExecutor
from .verify import run_removed_verify, run_smoke_verify
from .util import render_table


TOP_LEVEL_COMMANDS = {
    "shell",
    "add",
    "remove",
    "new",
    "list",
    "inspect",
    "check",
    "assess",
    "register",
    "activate",
    "doctor",
    "init",
    "dev",
    "cluster",
    "plugin",
    "plugins",
    "deploy",
    "verify",
    "state",
    "rollback",
    "report",
}


@dataclass(frozen=True, slots=True)
class RegisterPrecheckItem:
    name: str
    status: str
    detail: str
    sql: str = ""


@dataclass(frozen=True, slots=True)
class RegisterPrecheckReport:
    plugin_id: str
    extension_name: str
    primary_coordinator: str
    sql: str
    already_registered: bool
    items: tuple[RegisterPrecheckItem, ...]

    @property
    def ok(self) -> bool:
        return not any(item.status == "FAIL" for item in self.items)


class PluginCtlArgumentParser(argparse.ArgumentParser):
    def format_help(self) -> str:
        return """usage: plugin_ctl [-h] [--version] [--root ROOT] {shell,init,new,list,deploy,register,check,rollback} ...

OpenTenBase PluginCtl: plugin-centered lifecycle governance for OpenTenBase.

positional arguments:
  {shell,init,new,list,deploy,register,check,rollback}
    shell               interactive plugin lifecycle shell
    init                discover OpenTenBase topology and write the default cluster.toml
    new                 create a starter plugin and add it to PluginCtl
    list                list plugins or show one plugin
    deploy              add if needed, then copy plugin files to OpenTenBase nodes
    register            run CREATE EXTENSION once on the primary coordinator
    check               run all-in-one plugin health and governance checks
    rollback            run manifest-declared rollback SQL

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
  --root ROOT           platform directory root

Type "plugin_ctl" to enter the interactive shell.
Inside the shell, type "help advanced" for compatibility and debugging commands.

groups: discovery, governance, lifecycle, archive, distributed, reporting, runtime
"""


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
    parser = PluginCtlArgumentParser(
        prog="plugin_ctl",
        description="OpenTenBase PluginCtl: plugin-centered lifecycle governance for OpenTenBase.",
        epilog=(
            "main flow: init -> new/list -> deploy -> register -> check -> rollback; "
            "advanced/debug: plugin lint/plan/precheck/diagnose, cluster distribute; "
            "other groups: discovery=list/inspect; lifecycle=rollback; archive=plugin archive list/inspect; "
            "distributed=plugin roles/consistency; runtime=doctor/cluster status"
        ),
    )
    parser.add_argument("--version", action="version", version=f"plugin_ctl {__version__}")
    parser.add_argument("--root", type=Path, default=platform_root(), help="platform directory root")

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="{shell,init,new,list,deploy,register,check,rollback}",
        parser_class=argparse.ArgumentParser,
    )

    subparsers.add_parser("shell", help="interactive plugin lifecycle shell")
    add_parser = subparsers.add_parser("add", help=argparse.SUPPRESS)
    add_parser.add_argument("plugin_path", type=Path)
    add_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help=argparse.SUPPRESS)
    remove_parser = subparsers.add_parser("remove", help=argparse.SUPPRESS)
    remove_parser.add_argument("plugin_id")
    remove_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help=argparse.SUPPRESS)
    new_parser = subparsers.add_parser("new", help="main flow: create a starter plugin and add it to PluginCtl")
    new_parser.add_argument("plugin_id")
    new_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help=argparse.SUPPRESS)
    list_parser = subparsers.add_parser("list", help="main flow: list plugins or show one plugin")
    list_parser.add_argument("plugin_id", nargs="?")
    list_parser.add_argument("--all", action="store_true", help="include built-in reference plugins")
    list_parser.add_argument("--builtin", action="store_true", help="show only built-in reference plugins")
    list_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help=argparse.SUPPRESS)

    inspect_parser = subparsers.add_parser("inspect", help=argparse.SUPPRESS)
    inspect_parser.add_argument("plugin_id")

    check_parser = subparsers.add_parser("check", help="main flow: aggregate lint, plan, precheck, and diagnose")
    check_parser.add_argument("plugin_id_or_path")
    check_parser.add_argument("--json", action="store_true", help="emit aggregated check result as JSON")
    check_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help="human output language")

    assess_parser = subparsers.add_parser("assess", help=argparse.SUPPRESS)
    assess_parser.add_argument("source_path", type=Path)
    assess_parser.add_argument("--json", action="store_true", help="emit assessment result as JSON")

    def add_register_args(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("plugin_id")
        command_parser.add_argument("-f", "--cluster-file", type=Path, help="cluster.toml path; defaults to ./cluster.toml or ~/.plugin_ctl/cluster.toml")
        command_parser.add_argument("--dry-run", action="store_true", help="show registration and view-check plan only")
        command_parser.add_argument("--json", action="store_true", help="emit registration report as JSON")

    register_parser = subparsers.add_parser("register", help="main flow: register extension metadata once, then verify CN views")
    add_register_args(register_parser)
    activate_parser = subparsers.add_parser("activate", help=argparse.SUPPRESS)
    add_register_args(activate_parser)

    def add_cluster_init_args(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--output", type=Path, default=None, help="output path; defaults to ~/.plugin_ctl/cluster.toml")
        command_parser.add_argument("--name", default="local-opentenbase", help="cluster name written to the config")
        command_parser.add_argument("--backend", choices=["auto", "opentenbase_ctl", "sql"], default="auto", help="cluster discovery backend")
        command_parser.add_argument("--opentenbase-ctl", default=None, help="opentenbase_ctl binary path")
        command_parser.add_argument("--opentenbase-ctl-config", type=Path, default=None, help="opentenbase_ctl config path")
        command_parser.add_argument("--ssh-user", default=DEFAULT_SSH_USER, help="SSH user for physical file distribution")
        command_parser.add_argument("--db-user", default=DEFAULT_DB_USER, help="database user written to node entries")
        command_parser.add_argument("--database", default=DEFAULT_DATABASE, help="database name written to node entries")
        command_parser.add_argument("--ssh-port", type=int, default=DEFAULT_SSH_PORT, help="SSH port written to node entries")
        command_parser.add_argument("--lib-dir", default=DEFAULT_LIB_DIR, help="OpenTenBase library directory")
        command_parser.add_argument("--extension-dir", default=DEFAULT_EXTENSION_DIR, help="OpenTenBase extension SQL/control directory")

    init_parser = subparsers.add_parser("init", help="discover OpenTenBase topology and write the default cluster.toml")
    add_cluster_init_args(init_parser)

    doctor_parser = subparsers.add_parser("doctor", help=argparse.SUPPRESS)
    doctor_parser.add_argument("--container", default="opentenbaseDN1")
    doctor_parser.add_argument("--host", default="127.0.0.1")
    doctor_parser.add_argument("--port", type=int, default=30004)
    doctor_parser.add_argument("--user", default="opentenbase")
    doctor_parser.add_argument("--database", default="postgres")

    dev_parser = subparsers.add_parser("dev", help=argparse.SUPPRESS)
    dev_subparsers = dev_parser.add_subparsers(dest="dev_command", required=True)
    dev_init_parser = dev_subparsers.add_parser("init", help="create a starter plugin skeleton")
    dev_init_parser.add_argument("plugin_id")
    dev_init_parser.add_argument("--dir", type=Path, default=None, help="parent directory for the generated plugin directory")
    dev_init_parser.add_argument("--force", action="store_true", help="overwrite files generated by dev init")

    cluster_parser = subparsers.add_parser("cluster", help=argparse.SUPPRESS)
    cluster_subparsers = cluster_parser.add_subparsers(dest="cluster_command", required=True)
    cluster_subparsers.add_parser("status", help="read-only local Docker/OpenTenBase status")
    cluster_init_parser = cluster_subparsers.add_parser("init", help="discover OpenTenBase topology and write the default cluster.toml")
    add_cluster_init_args(cluster_init_parser)
    cluster_inspect_parser = cluster_subparsers.add_parser("inspect", help="distributed: inspect a cluster.toml topology")
    cluster_inspect_parser.add_argument("-f", "--file", type=Path, help="cluster.toml path; defaults to ./cluster.toml or ~/.plugin_ctl/cluster.toml")
    cluster_inspect_parser.add_argument("--json", action="store_true", help="emit topology as JSON")
    cluster_distribute_parser = cluster_subparsers.add_parser("distribute", help="distributed: dry-run or execute physical payload distribution")
    cluster_distribute_parser.add_argument("--dry-run", action="store_true", help="build a plan only; do not scp or modify remote nodes")
    cluster_distribute_parser.add_argument("-f", "--file", type=Path, help="cluster.toml path; defaults to ./cluster.toml or ~/.plugin_ctl/cluster.toml")
    cluster_distribute_parser.add_argument("plugin_id")
    cluster_distribute_parser.add_argument("--json", action="store_true", help="emit distribution plan/result as JSON")

    plugin_parser = subparsers.add_parser("plugin", help=argparse.SUPPRESS)
    plugin_subparsers = plugin_parser.add_subparsers(dest="plugin_command", required=True)
    plugin_add_parser = plugin_subparsers.add_parser("add", help="discovery: register an external plugin directory or manifest")
    plugin_add_parser.add_argument("plugin_path", type=Path)
    plugin_remove_parser = plugin_subparsers.add_parser("remove", help="discovery: remove a user-registered plugin")
    plugin_remove_parser.add_argument("plugin_id")
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

    plugins_parser = subparsers.add_parser("plugins", help=argparse.SUPPRESS)
    plugins_subparsers = plugins_parser.add_subparsers(dest="plugins_command", required=True)
    plugins_status_parser = plugins_subparsers.add_parser("status", help="governance: show governance status for all plugins")
    plugins_status_parser.add_argument("--json", action="store_true", help="emit plugin governance status as JSON")
    plugins_status_parser.add_argument("--lang", choices=["zh", "en", "both"], default=None, help="human output language")

    command_help = {
        "deploy": "main flow: deploy plugin payload with cluster config; use --dry-run to preview",
        "verify": "lifecycle: verify one plugin package; uses cluster config when available",
        "state": "reporting: show local action state",
        "rollback": "lifecycle: rollback one plugin package; use --dry-run to preview",
        "report": "reporting: show latest action report",
    }
    for name in ["deploy", "verify", "state", "rollback", "report"]:
        cmd = subparsers.add_parser(name, help=command_help[name] if name in {"deploy", "rollback"} else argparse.SUPPRESS)
        if name in {"deploy", "verify", "state", "rollback"}:
            cmd.add_argument("plugin_id", nargs="?")
        if name == "verify":
            cmd.add_argument("--removed", action="store_true", help="verify that plugin objects are absent using removed_probe")
            cmd.add_argument("-f", "--cluster-file", type=Path, help="cluster.toml path; defaults to ./cluster.toml or ~/.plugin_ctl/cluster.toml when present")
            cmd.add_argument("--json", action="store_true", help="with -f, emit distributed verify report as JSON")
        if name == "deploy":
            cmd.add_argument("--dry-run", action="store_true", help="build physical distribution plan only")
            cmd.add_argument("-f", "--cluster-file", type=Path, help="cluster.toml path; defaults to ./cluster.toml or ~/.plugin_ctl/cluster.toml when present")
        if name == "rollback":
            cmd.add_argument("--dry-run", action="store_true", help="show rollback_sql plan instead of executing it")
        if name == "report":
            cmd.add_argument("--json", action="store_true", help="emit latest action report as JSON")

    return parser


def _looks_like_plugin_path(value: str) -> bool:
    path = Path(value).expanduser()
    return path.exists() or "/" in value or "\\" in value or value.endswith((".yml", ".yaml"))


def ensure_plugin_registered(root: Path, plugin_id_or_path: str, *, announce: bool = True) -> tuple[str, bool, Path | None]:
    if "/" not in plugin_id_or_path and "\\" not in plugin_id_or_path and not plugin_id_or_path.endswith((".yml", ".yaml")):
        try:
            Catalog(root=root).load_one(plugin_id_or_path)
            return plugin_id_or_path, False, None
        except ManifestError:
            pass
    if not _looks_like_plugin_path(plugin_id_or_path):
        return plugin_id_or_path, False, None
    manifest, catalog_path = Catalog(root=root).add_user_plugin(Path(plugin_id_or_path))
    if announce:
        print(f"Registered plugin: {manifest.plugin_id}")
        print(f"Manifest: {manifest.path}")
        print(f"Plugin root: {manifest.project_root}")
        print(f"User catalog: {catalog_path}")
    return manifest.plugin_id, True, catalog_path


def _merge_ctl_and_sql_topology(ctl_config: ClusterConfig, sql_config: ClusterConfig) -> ClusterConfig:
    nodes: list[ClusterNode] = []
    for role in ("cn", "dn"):
        ctl_nodes = sorted((node for node in ctl_config.nodes if node.role == role), key=lambda item: item.name)
        sql_nodes = sorted((node for node in sql_config.nodes if node.role == role), key=lambda item: item.name)
        if len(ctl_nodes) != len(sql_nodes):
            return ctl_config
        for ctl_node, sql_node in zip(ctl_nodes, sql_nodes):
            nodes.append(
                ClusterNode(
                    name=ctl_node.name,
                    role=ctl_node.role,
                    host=ctl_node.host,
                    ssh_port=ctl_node.ssh_port,
                    db_port=sql_node.db_port,
                    ssh_user=ctl_node.ssh_user,
                    db_user=sql_node.db_user,
                    database=sql_node.database,
                    lib_dir=ctl_node.lib_dir,
                    extension_dir=ctl_node.extension_dir,
                )
            )
    return ClusterConfig(name=ctl_config.name, nodes=tuple(nodes), backend="opentenbase_ctl")


def cmd_list(root: Path, *, include_builtin: bool = False, builtin_only: bool = False, lang: str | None = None) -> int:
    output_lang = normalize_lang(lang)
    catalog = Catalog(root=root)
    if builtin_only:
        manifests = catalog.load_builtin()
        scope = message("scope_builtin", output_lang)
    elif include_builtin:
        manifests = catalog.load_all()
        scope = message("scope_all", output_lang)
    else:
        manifests = catalog.load_user()
        scope = message("scope_user", output_lang)
    if not manifests:
        print(message("no_plugins_found", output_lang, scope=scope))
        if not include_builtin and not builtin_only:
            print(message("create_one", output_lang))
            print(message("show_builtin", output_lang))
        return 0

    rows = [[m.plugin_id, m.name, m.version, m.payload.get("source_root", "")] for m in manifests]
    print(render_table(["plugin_id", text("name", output_lang), text("version", output_lang), text("source_root", output_lang)], rows))
    return 0


def cmd_list_one(root: Path, plugin_id: str, *, lang: str | None = None) -> int:
    output_lang = normalize_lang(lang)
    cmd_inspect(root, plugin_id)
    records = [record for record in StateStore(root).all() if record.plugin_id == plugin_id]
    if records:
        print(message("recent_actions", output_lang))
        print(
            render_table(
                [
                    "plugin_id",
                    text("action", output_lang),
                    text("ok", output_lang),
                    text("version", output_lang),
                    text("stage", output_lang),
                    text("returncode", output_lang),
                    text("duration_ms", output_lang),
                    text("stdout", output_lang),
                    text("stderr", output_lang),
                    text("timestamp", output_lang),
                    text("detail", output_lang),
                ],
                latest_by_plugin_action(records),
            )
        )
    else:
        print(message("recent_actions_none", output_lang))
    return 0


def cmd_add(root: Path, plugin_path: Path, *, lang: str | None = None) -> int:
    output_lang = normalize_lang(lang)
    manifest, catalog_path = Catalog(root=root).add_user_plugin(plugin_path)
    print(message("registered_plugin", output_lang, plugin_id=manifest.plugin_id))
    print(message("manifest", output_lang, path=manifest.path))
    print(message("plugin_root", output_lang, path=manifest.project_root))
    print(message("user_catalog", output_lang, path=catalog_path))
    print(message("next_list", output_lang))
    return 0


def cmd_remove(root: Path, plugin_id: str, *, lang: str | None = None) -> int:
    output_lang = normalize_lang(lang)
    catalog = Catalog(root=root)
    entry = catalog.user_plugin_entry(plugin_id)
    catalog_path = catalog.remove_user_plugin(plugin_id)
    removed_package_cache = catalog.remove_local_package_cache(plugin_id)
    print(message("removed_user_plugin", output_lang, plugin_id=plugin_id))
    if entry.get("root"):
        print(message("plugin_root", output_lang, path=entry["root"]))
    if entry.get("manifest"):
        print(message("manifest", output_lang, path=entry["manifest"]))
    print(message("re_add", output_lang, path=entry.get("root") or entry.get("manifest")))
    print(message("user_catalog", output_lang, path=catalog_path))
    if removed_package_cache:
        print(message("local_cache_removed", output_lang))
    else:
        print(message("local_cache_not_found", output_lang))
    print(message("database_not_removed", output_lang))
    return 0


def _display_path(path: Path) -> str:
    try:
        relative = path.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        return str(path)
    return f"./{relative.as_posix()}" if str(relative) != "." else "."


def cmd_dev_init(plugin_id: str, *, base_dir: Path | None = None, force: bool = False) -> int:
    result = create_plugin_skeleton(plugin_id, base_dir=base_dir, force=force)
    print(f"Plugin skeleton created: {_display_path(result.target_dir)}")
    print()
    print("Generated files:")
    for rel_path in result.files:
        print(f"  {rel_path.as_posix()}")
    print()
    print("Next steps:")
    plugin_path = _display_path(result.target_dir)
    print(f"  plugin_ctl add {plugin_path}")
    print(f"  plugin_ctl check {plugin_id}")
    print(f"  plugin_ctl deploy {plugin_id}")
    print(f"  plugin_ctl register {plugin_id}")
    print(f"  plugin_ctl verify {plugin_id}")
    print("  plugin_ctl report")
    return 0


def cmd_new(root: Path, plugin_id: str, *, lang: str | None = None) -> int:
    output_lang = normalize_lang(lang)
    result = create_plugin_skeleton(plugin_id)
    manifest, catalog_path = Catalog(root=root).add_user_plugin(result.target_dir)
    print(message("plugin_created", output_lang, plugin_id=manifest.plugin_id))
    print(message("path", output_lang, path=_display_path(result.target_dir)))
    print(message("manifest", output_lang, path=manifest.path))
    print(message("user_catalog", output_lang, path=catalog_path))
    print()
    print(message("next", output_lang))
    print(f"  deploy {manifest.plugin_id}")
    print(f"  register {manifest.plugin_id}")
    print(f"  check {manifest.plugin_id}")
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


def _discover_cluster_for_init(args: argparse.Namespace) -> tuple[ClusterConfig, str, str]:
    if args.backend in {"auto", "opentenbase_ctl"}:
        backend = OpenTenBaseCtlBackend(binary=args.opentenbase_ctl, config_file=args.opentenbase_ctl_config)
        try:
            ctl_config = backend.discover_cluster_config(
                name=args.name if args.name != "local-opentenbase" else None,
                ssh_user=args.ssh_user,
                db_user=args.db_user,
                database=args.database,
                ssh_port=args.ssh_port,
                lib_dir=args.lib_dir,
                extension_dir=args.extension_dir,
            )
            primary = ctl_config.coordinators[0] if ctl_config.coordinators else None
            if primary is not None:
                runtime = OpenTenBaseRuntime(
                    host=primary.host,
                    port=primary.db_port,
                    user=args.db_user,
                    database=args.database,
                    mode="local",
                )
                try:
                    sql_config = discover_cluster_config(
                        runtime,
                        name=ctl_config.name,
                        ssh_user=args.ssh_user,
                        db_user=args.db_user,
                        database=args.database,
                        ssh_port=args.ssh_port,
                        lib_dir=primary.lib_dir,
                        extension_dir=primary.extension_dir,
                    )
                    config = _merge_ctl_and_sql_topology(ctl_config, sql_config)
                    return config, "opentenbase_ctl", "discovered from opentenbase_ctl status; topology verified from pgxc_node"
                except (OSError, ValueError):
                    if args.backend == "opentenbase_ctl":
                        raise
            return ctl_config, "opentenbase_ctl", "discovered from opentenbase_ctl status"
        except OpenTenBaseCtlError:
            if args.backend == "opentenbase_ctl":
                raise

    errors: list[str] = []
    for host, port in [("127.0.0.1", 30004), ("127.0.0.1", 30005), ("127.0.0.1", 30006)]:
        runtime = OpenTenBaseRuntime(host=host, port=port, user=args.db_user, database=args.database, mode="local")
        try:
            config = discover_cluster_config(
                runtime,
                name=args.name,
                ssh_user=args.ssh_user,
                db_user=args.db_user,
                database=args.database,
                ssh_port=args.ssh_port,
                lib_dir=args.lib_dir,
                extension_dir=args.extension_dir,
            )
            return config, "sql", f"discovered from pgxc_node through psql at {host}:{port}"
        except (OSError, ValueError) as exc:
            errors.append(f"{host}:{port}: {exc}")
    raise ValueError("; ".join(errors) or "failed to discover OpenTenBase topology")


def cmd_cluster_init(args: argparse.Namespace) -> int:
    config, backend_name, backend_detail = _discover_cluster_for_init(args)
    target = write_cluster_config(config, args.output or default_cluster_config_path())
    print(f"Cluster config initialized: {target}")
    print(f"Cluster: {config.name}")
    print(f"Backend: {backend_name} ({backend_detail})")
    rows = [
        [
            node.name,
            node.role,
            node.host,
            str(node.db_port),
            node.ssh_user,
            node.db_user,
            node.lib_dir,
            node.extension_dir,
        ]
        for node in config.nodes
    ]
    print(render_table(["name", "role", "host", "db_port", "ssh_user", "db_user", "lib_dir", "extension_dir"], rows))
    print("Review host, ssh_user, lib_dir, and extension_dir before running modifying commands.")
    return 0


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
        "backend": config.backend,
        "coordinators": [_node_json(node) for node in config.coordinators],
        "datanodes": [_node_json(node) for node in config.datanodes],
        "result": "OK",
        "errors": [],
    }


def remote_executor_for_cluster(config: ClusterConfig):
    if config.backend == "opentenbase_ctl":
        return OpenTenBaseCtlRemoteExecutor()
    return ScpSshRemoteExecutor()


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
    print(f"Backend: {config.backend}")
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


def _render_distribution_plan(plan) -> None:
    extension_entries = [
        entry
        for entry in plan.plan
        if entry.file_type in {"extension_control", "sql"}
    ]
    library_entries = [entry for entry in plan.plan if entry.file_type == "shared_library"]
    coordinator_nodes = sorted({entry.node for entry in plan.plan if entry.role == "cn"})
    datanode_nodes = sorted({entry.node for entry in plan.plan if entry.role == "dn"})

    print(f"Deploy plan: {plan.plugin_id}")
    print(f"Plugin: {plan.plugin_id}")
    print(f"Cluster: {plan.cluster}")
    print(f"Coordinator nodes: {len(coordinator_nodes)} ({', '.join(coordinator_nodes) or 'none'})")
    print(f"Datanode nodes: {len(datanode_nodes)} ({', '.join(datanode_nodes) or 'none'})")
    print("Extension files -> extension_dir:")
    _render_plan_group(extension_entries)
    print("Library files -> lib_dir:")
    if library_entries:
        _render_plan_group(library_entries)
    else:
        print("  none (SQL-only plugin)")
    print(
        "Summary: "
        f"extension_copy_items={len(extension_entries)} "
        f"library_copy_items={len(library_entries)} "
        f"errors={len(plan.errors)}"
    )


def _render_plan_group(entries) -> None:
    if not entries:
        print("  none")
        return
    rows = [
        [
            entry.node,
            entry.role,
            entry.file_type,
            "yes" if entry.exists else "no",
            entry.local_path,
            entry.remote_path,
        ]
        for entry in entries
    ]
    print(render_table(["node", "role", "type", "exists", "local_path", "remote_path"], rows))


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
    results = distribute_payload_to_nodes(config, payload_files, remote_executor_for_cluster(config))
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
    cluster_path = find_cluster_config()
    remote_executor = remote_executor_for_cluster(load_cluster_config(cluster_path)) if cluster_path else ScpSshRemoteExecutor()
    report = build_plugin_health_report(
        root,
        plugin_id,
        runtime=OpenTenBaseRuntime(),
        sql_executor=PsqlCoordinatorExecutor(),
        remote_executor=remote_executor,
    )
    if as_json:
        print(json.dumps(health_report_json(report), indent=2, ensure_ascii=False))
    else:
        print(render_health_report(report, normalize_lang(lang)))
    return 1 if report.final_status == "BROKEN" else 0


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
    report = run_distributed_verify(config, manifest, PsqlCoordinatorExecutor(), remote_executor_for_cluster(config))
    if as_json:
        print(json.dumps(distributed_verify_report_json(report), indent=2, ensure_ascii=False))
    else:
        _render_distributed_verify_report(report)
    return 1 if report.errors else 0


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

    _render_distribution_plan(plan)
    print(f"Mode: {mode}")
    print("Activate: skipped")
    print("CREATE EXTENSION: not executed")

    if not execute:
        print("Physical distribution: planned")
        if plan.errors:
            print("Errors:")
            for error in plan.errors:
                print(f"- {error}")
            print("Result: FAILED")
            return 1
        print("Result: OK")
        return 0

    if plan.errors:
        print("Physical distribution: blocked")
        print("Errors:")
        for error in plan.errors:
            print(f"- {error}")
        print("Result: FAILED")
        return 1

    executor = remote_executor_for_cluster(config)
    results = distribute_payload_to_nodes(config, list(physical_payload_files(manifest)), executor)
    metadata_results = sync_plugin_metadata_to_nodes(config, manifest, executor)
    all_results = [*results, *metadata_results]
    print("Physical distribution: executed")
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
        for result in sorted(all_results, key=lambda item: (item.node, item.stage, item.local_path, item.remote_path))
    ]
    if rows:
        print(render_table(["node", "role", "status", "stage", "returncode", "local_sha256", "remote_sha256", "local_path", "remote_path"], rows))
    summary = _distribution_summary(all_results)
    print(
        "Summary: "
        f"total={summary['total']} succeeded={summary['succeeded']} "
        f"failed={summary['failed']} checksum_failed={summary['checksum_failed']}"
    )
    errors = _distribution_errors(all_results)
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


def _extension_available_sql(extension_name: str) -> str:
    return f"SELECT name FROM pg_available_extensions WHERE name = '{extension_name}';"


def _extension_registered_sql(extension_name: str) -> str:
    return f"SELECT extname FROM pg_extension WHERE extname = '{extension_name}';"


def _run_register_precheck(config: ClusterConfig, manifest, executor) -> RegisterPrecheckReport:
    extension_name = extension_name_for(manifest)
    create_sql = create_extension_sql(extension_name)
    primary = config.coordinators[0] if config.coordinators else None
    items: list[RegisterPrecheckItem] = [
        RegisterPrecheckItem("plugin", "OK", f"{manifest.plugin_id} {manifest.version}"),
        RegisterPrecheckItem("extension_name", "OK", extension_name),
    ]
    if primary is None:
        items.append(RegisterPrecheckItem("primary_coordinator", "FAIL", "cluster.toml has no coordinator node"))
        return RegisterPrecheckReport(manifest.plugin_id, extension_name, "", create_sql, False, tuple(items))

    items.append(RegisterPrecheckItem("primary_coordinator", "OK", f"{primary.name} {primary.host}:{primary.db_port}"))
    connect_sql = "SELECT 1;"
    connect = executor.run_sql(primary, connect_sql)
    items.append(
        RegisterPrecheckItem(
            "primary_connection",
            "OK" if connect.returncode == 0 else "FAIL",
            "primary coordinator reachable" if connect.returncode == 0 else (connect.stderr.strip() or connect.stdout.strip() or "connection failed"),
            connect_sql,
        )
    )
    if connect.returncode != 0:
        return RegisterPrecheckReport(manifest.plugin_id, extension_name, primary.name, create_sql, False, tuple(items))

    available_sql = _extension_available_sql(extension_name)
    available = executor.run_sql(primary, available_sql)
    available_names = {line.strip() for line in available.stdout.splitlines() if line.strip()}
    available_ok = available.returncode == 0 and extension_name in available_names
    items.append(
        RegisterPrecheckItem(
            "pg_available_extensions",
            "OK" if available_ok else "FAIL",
            f"{extension_name} is available to CREATE EXTENSION"
            if available_ok
            else (available.stderr.strip() or f"{extension_name} not found in pg_available_extensions"),
            available_sql,
        )
    )
    if not available_ok:
        return RegisterPrecheckReport(manifest.plugin_id, extension_name, primary.name, create_sql, False, tuple(items))

    registered_sql = _extension_registered_sql(extension_name)
    registered = executor.run_sql(primary, registered_sql)
    registered_names = {line.strip() for line in registered.stdout.splitlines() if line.strip()}
    already_registered = registered.returncode == 0 and extension_name in registered_names
    items.append(
        RegisterPrecheckItem(
            "pg_extension",
            "OK" if registered.returncode == 0 else "FAIL",
            "already registered; CREATE EXTENSION will be skipped" if already_registered else "not registered yet",
            registered_sql,
        )
    )
    return RegisterPrecheckReport(manifest.plugin_id, extension_name, primary.name, create_sql, already_registered, tuple(items))


def _register_precheck_json(report: RegisterPrecheckReport) -> dict[str, object]:
    return {
        "plugin_id": report.plugin_id,
        "extension_name": report.extension_name,
        "primary_coordinator": report.primary_coordinator,
        "ok": report.ok,
        "already_registered": report.already_registered,
        "sql": report.sql,
        "items": [
            {
                "name": item.name,
                "status": item.status,
                "detail": item.detail,
                "sql": item.sql,
            }
            for item in report.items
        ],
    }


def _render_register_precheck(report: RegisterPrecheckReport) -> None:
    print(f"Register precheck: {report.plugin_id}")
    print(f"Extension: {report.extension_name}")
    print(f"Primary coordinator: {report.primary_coordinator or 'none'}")
    rows = [[item.status, item.name, item.detail, item.sql] for item in report.items]
    print(render_table(["status", "check", "detail", "sql"], rows))
    if report.already_registered:
        print("CREATE EXTENSION: skipped because pg_extension already contains this extension")
    else:
        print("SQL to execute on primary coordinator only:")
        print(f"  {report.sql}")


def cmd_register(root: Path, plugin_id: str, cluster_file: Path, *, execute: bool = False, as_json: bool = False, deprecated_alias: bool = False) -> int:
    config = load_cluster_config(cluster_file)
    manifest = Catalog(root=root).load_one(plugin_id)
    executor = PsqlCoordinatorExecutor()
    precheck = _run_register_precheck(config, manifest, executor)
    report = None
    if precheck.ok and not precheck.already_registered:
        report = execute_activation(config, manifest, executor) if execute else dry_run_activation_plan(config, manifest)
    if as_json:
        payload = {
            "precheck": _register_precheck_json(precheck),
            "activation": activation_report_json(report) if report else None,
            "errors": [item.detail for item in precheck.items if item.status == "FAIL"],
        }
        if report:
            payload = {**activation_report_json(report), **payload}
        else:
            payload = {
                "cluster": config.name,
                "plugin_id": manifest.plugin_id,
                "extension_name": precheck.extension_name,
                "mode": "skipped" if precheck.already_registered else ("execute" if execute else "dry-run"),
                "physical_distribution": "not_executed",
                "datanodes": "not_connected",
                **payload,
            }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        if deprecated_alias:
            print("Warning: activate is deprecated; use register.")
        _render_register_precheck(precheck)
        if not precheck.ok:
            print("CREATE EXTENSION: blocked by precheck")
            print("Result: FAILED")
            return 1
        if precheck.already_registered:
            print("Result: OK")
            return 0
        if report:
            _render_activation_report(report)
    if not precheck.ok:
        return 1
    if precheck.already_registered:
        return 0
    return 1 if report and report.errors else 0


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


def _rollback_plan_text(manifest) -> str:
    if not manifest.rollback_sql:
        return ""
    try:
        return manifest.rollback_sql.read_text(encoding="utf-8-sig").strip()
    except OSError as exc:
        return f"-- cannot read rollback_sql: {exc}"


def _render_rollback_boundary(manifest) -> None:
    print(f"Rollback plan: {manifest.plugin_id}")
    if manifest.rollback_sql:
        print(f"rollback_sql: {manifest.rollback_sql}")
        sql = _rollback_plan_text(manifest)
        if sql:
            print("SQL to execute:")
            print(sql)
    else:
        print("Warning: manifest has no rollback_sql; rollback is not supported.")
        print("PluginCtl will not guess a DROP EXTENSION or destructive cleanup plan.")
    print("Boundary:")
    print("  rollback only handles database objects declared by rollback_sql.")
    print("  rollback does NOT delete physical files from CN/DN nodes (.control, .sql, .so).")


def cmd_rollback(root: Path, plugin_id: str, *, execute: bool = False) -> int:
    catalog = Catalog(root=root)
    manifest = catalog.load_one(plugin_id)
    runtime = OpenTenBaseRuntime()
    _render_rollback_boundary(manifest)
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
        if args.command == "add":
            return cmd_add(args.root, args.plugin_path, lang=args.lang)
        if args.command == "remove":
            return cmd_remove(args.root, args.plugin_id, lang=args.lang)
        if args.command == "new":
            return cmd_new(args.root, args.plugin_id, lang=args.lang)
        if args.command == "list":
            if args.plugin_id:
                return cmd_list_one(args.root, args.plugin_id, lang=args.lang)
            return cmd_list(args.root, include_builtin=args.all, builtin_only=args.builtin, lang=args.lang)
        if args.command == "inspect":
            return cmd_inspect(args.root, args.plugin_id)
        if args.command == "check":
            return cmd_check(args.root, args.plugin_id_or_path, as_json=args.json, lang=args.lang)
        if args.command == "assess":
            return cmd_assess(args.source_path, as_json=args.json)
        if args.command == "register":
            return cmd_register(args.root, args.plugin_id, require_cluster_config(args.cluster_file), execute=not args.dry_run, as_json=args.json)
        if args.command == "activate":
            return cmd_register(args.root, args.plugin_id, require_cluster_config(args.cluster_file), execute=not args.dry_run, as_json=args.json, deprecated_alias=True)
        if args.command == "init":
            return cmd_cluster_init(args)
        if args.command == "doctor":
            return cmd_doctor(args)
        if args.command == "dev":
            if args.dev_command == "init":
                return cmd_dev_init(args.plugin_id, base_dir=args.dir, force=args.force)
        if args.command == "cluster":
            if args.cluster_command == "status":
                return cmd_cluster_status()
            if args.cluster_command == "init":
                return cmd_cluster_init(args)
            if args.cluster_command == "inspect":
                return cmd_cluster_inspect(require_cluster_config(args.file), as_json=args.json)
            if args.cluster_command == "distribute":
                return cmd_cluster_distribute(args.root, require_cluster_config(args.file), args.plugin_id, dry_run=args.dry_run, execute=not args.dry_run, as_json=args.json)
        if args.command == "plugin":
            if args.plugin_command == "add":
                return cmd_add(args.root, args.plugin_path)
            if args.plugin_command == "remove":
                return cmd_remove(args.root, args.plugin_id)
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
            if args.removed:
                return cmd_verify(args.root, plugin_id, removed=True)
            cluster_file = find_cluster_config(args.cluster_file)
            if cluster_file:
                return cmd_verify_distributed(args.root, plugin_id, cluster_file, as_json=args.json)
            return cmd_verify(args.root, plugin_id, removed=args.removed)
        if args.command == "state":
            return cmd_state(args.root, args.plugin_id)
        if args.command == "report":
            return cmd_report(args.root, as_json=args.json)
        if args.command == "deploy":
            plugin_id = args.plugin_id or "otb_timeseries"
            plugin_id, _, _ = ensure_plugin_registered(args.root, plugin_id)
            return cmd_deploy_physical_distribution(
                args.root,
                plugin_id,
                require_cluster_config(args.cluster_file),
                dry_run=args.dry_run,
                execute=not args.dry_run,
            )
        if args.command == "rollback":
            return cmd_rollback(args.root, args.plugin_id or "otb_timeseries", execute=not args.dry_run)
    except (FileExistsError, FileNotFoundError, ManifestError, ValueError) as exc:
        parser.error(str(exc))

    return 0

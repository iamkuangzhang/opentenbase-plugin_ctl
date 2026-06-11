from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import shlex
import sys
from typing import TextIO


SHELL_BANNER = """OpenTenBase PluginCtl Shell
Type "help" to show commands.
Type "quit" or "exit" to leave.
"""


HELP_TEXT = """Available commands:
  help
  shell
  init
  add <plugin_dir_or_manifest>
  remove <plugin_id>
  list
  inspect <plugin_id>
  check <plugin_id>
  assess <pg_extension_source_path> [--json]
  diagnose <plugin_id>
  deploy <plugin_id> [options]
  register <plugin_id> [options]
  activate <plugin_id> [options]
  verify <plugin_id> [options]
  rollback <plugin_id> [options]
  state [plugin_id]
  report [options]
  doctor

Plugin governance:
  plugin add <plugin_dir_or_manifest>
  plugin remove <plugin_id>
  plugin check <plugin_id>
  plugin status <plugin_id>
  plugin lint <plugin_id>
  plugin plan <plugin_id>
  plugin precheck <plugin_id>
  plugin diagnose <plugin_id>
  plugin roles <plugin_id>
  plugin consistency <plugin_id>
  plugin archive list
  plugin archive inspect <plugin_id>
  plugins status [--json]

Cluster and distributed plugin commands:
  cluster status
  cluster init
  cluster inspect
  cluster distribute <plugin_id> [--dry-run]

  quit
  exit

PluginCtl Shell manages plugin discovery, checks, deployment, registration,
verification, rollback, and reports. "init" only initializes PluginCtl's
cluster.toml from a running OpenTenBase cluster; it does not start, stop,
initialize, or monitor an OpenTenBase cluster.
"""


TOP_LEVEL_COMMANDS = {
    "add",
    "remove",
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

PROGRAM_NAMES = {"plugin_ctl", "opentenbase-pluginctl"}


Dispatcher = Callable[[list[str]], int]
InputFunc = Callable[[str], str]


def translate_shell_command(parts: list[str]) -> list[str] | None:
    if not parts:
        return []
    if parts[0] in PROGRAM_NAMES:
        parts = parts[1:]
        if not parts:
            return []
    command = parts[0]
    if command == "init":
        return ["cluster", "init", *parts[1:]]
    if command == "diagnose":
        return ["plugin", "diagnose", *parts[1:]]
    if command in TOP_LEVEL_COMMANDS:
        return parts
    return None


def _default_dispatcher(argv: list[str]) -> int:
    from .cli import main

    return main(argv)


def run_shell(
    root: Path,
    *,
    dispatcher: Dispatcher | None = None,
    input_func: InputFunc = input,
    output: TextIO | None = None,
) -> int:
    out = output or sys.stdout
    dispatch = dispatcher or _default_dispatcher
    root_args = ["--root", str(root)]

    print(SHELL_BANNER, file=out)
    while True:
        try:
            raw_line = input_func("pluginctl> ")
        except EOFError:
            print("", file=out)
            return 0
        except KeyboardInterrupt:
            print("", file=out)
            return 0

        line = raw_line.strip()
        if not line:
            continue
        if line in {"quit", "exit"}:
            return 0
        if line == "help":
            print(HELP_TEXT, file=out)
            continue
        if line == "shell":
            print("Already in PluginCtl Shell.", file=out)
            continue

        try:
            parts = shlex.split(line)
        except ValueError as exc:
            print(f"Invalid command: {exc}", file=out)
            continue

        argv = translate_shell_command(parts)
        if argv is None:
            print('Unknown command. Type "help" to show commands.', file=out)
            continue
        if not argv:
            continue

        try:
            dispatch([*root_args, *argv])
        except SystemExit as exc:
            if exc.code not in (None, 0):
                print(f"Command exited with status {exc.code}.", file=out)
            continue
        except KeyboardInterrupt:
            print("", file=out)
            continue
        except Exception as exc:
            print(f"Command failed: {exc}", file=out)
            continue

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
  help advanced
  init
  new <plugin_id>
  list [plugin_id]
  list --all
  deploy <plugin_id_or_path>
  register <plugin_id>
  check <plugin_id_or_path>
  rollback <plugin_id> [options]
  quit
  exit

PluginCtl Shell manages plugin discovery, checks, deployment, registration,
rollback, and reports. "init" only initializes PluginCtl's cluster.toml from a
running OpenTenBase cluster; it does not start, stop, initialize, or monitor an
OpenTenBase cluster.
"""


ADVANCED_HELP_TEXT = """Advanced and compatibility commands:
  add <plugin_dir_or_manifest>
  remove <plugin_id>
  inspect <plugin_id>
  assess <pg_extension_source_path> [--json]
  diagnose <plugin_id>
  activate <plugin_id> [options]
  verify <plugin_id> [options]
  state [plugin_id]
  report [options]
  doctor
  dev init <plugin_id> [--dir <target_dir>] [--force]

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
"""


TOP_LEVEL_COMMANDS = {
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


def _needs_confirmation(argv: list[str]) -> bool:
    if not argv:
        return False
    if "--dry-run" in argv or "-h" in argv or "--help" in argv:
        return False
    return argv[0] in {"deploy", "register", "rollback"}


def _confirm(argv: list[str], input_func: InputFunc, out: TextIO) -> bool:
    if not _needs_confirmation(argv):
        return True
    command = argv[0]
    if command == "deploy":
        print("PluginCtl will copy plugin files to OpenTenBase CN/DN nodes.", file=out)
        cancel_message = "Deploy cancelled."
    elif command == "register":
        print("PluginCtl will execute CREATE EXTENSION on the primary coordinator.", file=out)
        cancel_message = "Register cancelled."
    elif command == "rollback":
        print("PluginCtl will execute rollback SQL.", file=out)
        cancel_message = "Rollback cancelled."
    else:
        cancel_message = "Cancelled."
    answer = input_func("Continue? [y/N]: ").strip().lower()
    if answer in {"y", "yes"}:
        return True
    print(cancel_message, file=out)
    return False


def _preview_before_confirm(argv: list[str], root_args: list[str], dispatch: Dispatcher, out: TextIO) -> bool:
    if not _needs_confirmation(argv):
        return True
    preview_argv = [*root_args, *argv, "--dry-run"]
    print("Preview:", file=out)
    try:
        code = dispatch(preview_argv)
    except SystemExit as exc:
        code = int(exc.code or 0)
        if code:
            print(f"Preview exited with status {code}.", file=out)
            return False
    except KeyboardInterrupt:
        print("", file=out)
        return False
    except Exception as exc:
        print(f"Preview failed: {exc}", file=out)
        return False
    if code:
        print(f"Preview exited with status {code}.", file=out)
        return False
    return True


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
        if line == "help advanced":
            print(ADVANCED_HELP_TEXT, file=out)
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
        if not _preview_before_confirm(argv, root_args, dispatch, out):
            continue
        if not _confirm(argv, input_func, out):
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

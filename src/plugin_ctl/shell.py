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
  init
  list
  inspect <plugin_id>
  check <plugin_id>
  diagnose <plugin_id>
  deploy <plugin_id> [options]
  register <plugin_id> [options]
  verify <plugin_id> [options]
  rollback <plugin_id> [options]
  report [options]
  doctor
  quit
  exit

PluginCtl Shell manages plugin discovery, checks, deployment, registration,
verification, rollback, and reports. "init" only initializes PluginCtl's
cluster.toml from a running OpenTenBase cluster; it does not start, stop,
initialize, or monitor an OpenTenBase cluster.
"""


SHELL_COMMANDS = {"list", "inspect", "check", "diagnose", "deploy", "register", "verify", "rollback", "report", "doctor"}


Dispatcher = Callable[[list[str]], int]
InputFunc = Callable[[str], str]


def translate_shell_command(parts: list[str]) -> list[str] | None:
    if not parts:
        return []
    command = parts[0]
    if command == "init":
        return ["cluster", "init", *parts[1:]]
    if command == "diagnose":
        return ["plugin", "diagnose", *parts[1:]]
    if command in SHELL_COMMANDS:
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

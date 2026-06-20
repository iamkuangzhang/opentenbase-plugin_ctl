from __future__ import annotations

import atexit
from collections.abc import Callable
from pathlib import Path
import shlex
import sys
from typing import TextIO

from .i18n import command_help, message, normalize_lang


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


class ShellHistory:
    def __init__(self, history_path: Path | None = None) -> None:
        self.path = history_path or Path.home() / ".plugin_ctl" / "history"
        self.readline = None
        try:
            import readline  # type: ignore[import-not-found]

            self.readline = readline
        except Exception:
            self.readline = None
        self.enabled = self.readline is not None
        self._last_recorded = ""

    def load(self) -> None:
        if not self.enabled or self.readline is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                self.readline.read_history_file(str(self.path))
                length = self.readline.get_current_history_length()
                if length > 0:
                    self._last_recorded = self.readline.get_history_item(length) or ""
            if hasattr(self.readline, "set_auto_history"):
                self.readline.set_auto_history(False)
        except Exception:
            self.enabled = False

    def save(self) -> None:
        if not self.enabled or self.readline is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.readline.write_history_file(str(self.path))
        except Exception:
            pass

    def record(self, line: str) -> None:
        stripped = line.strip()
        if not stripped or stripped == self._last_recorded:
            return
        if not self.enabled or self.readline is None:
            self._last_recorded = stripped
            return
        try:
            self.readline.add_history(stripped)
            self._last_recorded = stripped
        except Exception:
            self.enabled = False


def setup_history(history_path: Path | None = None) -> ShellHistory:
    history = ShellHistory(history_path)
    history.load()
    atexit.register(history.save)
    return history


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
        print(message("deploy_confirm", _confirm.lang), file=out)
        cancel_message = message("deploy_cancelled", _confirm.lang)
    elif command == "register":
        print(message("register_confirm", _confirm.lang), file=out)
        cancel_message = message("register_cancelled", _confirm.lang)
    elif command == "rollback":
        print(message("rollback_confirm", _confirm.lang), file=out)
        cancel_message = message("rollback_cancelled", _confirm.lang)
    else:
        cancel_message = message("cancelled", _confirm.lang)
    answer = input_func(message("continue_prompt", _confirm.lang)).strip().lower()
    if answer in {"y", "yes"}:
        return True
    print(cancel_message, file=out)
    return False


_confirm.lang = "en"  # type: ignore[attr-defined]


def _preview_before_confirm(argv: list[str], root_args: list[str], dispatch: Dispatcher, out: TextIO) -> bool:
    if not _needs_confirmation(argv):
        return True
    preview_argv = [*root_args, *argv, "--dry-run"]
    print(message("preview", _preview_before_confirm.lang), file=out)
    try:
        code = dispatch(preview_argv)
    except SystemExit as exc:
        code = int(exc.code or 0)
        if code:
            print(message("preview_exited", _preview_before_confirm.lang, code=code), file=out)
            return False
    except KeyboardInterrupt:
        print("", file=out)
        return False
    except Exception as exc:
        print(message("preview_failed", _preview_before_confirm.lang, error=exc), file=out)
        return False
    if code:
        print(message("preview_exited", _preview_before_confirm.lang, code=code), file=out)
        return False
    return True


_preview_before_confirm.lang = "en"  # type: ignore[attr-defined]


def _default_dispatcher(argv: list[str]) -> int:
    from .cli import main

    return main(argv)


def run_shell(
    root: Path,
    *,
    dispatcher: Dispatcher | None = None,
    input_func: InputFunc = input,
    output: TextIO | None = None,
    history_path: Path | None = None,
) -> int:
    out = output or sys.stdout
    dispatch = dispatcher or _default_dispatcher
    root_args = ["--root", str(root)]
    lang = "en"
    history = setup_history(history_path)

    print(message("shell_banner", lang), file=out)
    while True:
        _confirm.lang = lang  # type: ignore[attr-defined]
        _preview_before_confirm.lang = lang  # type: ignore[attr-defined]
        try:
            raw_line = input_func("pluginctl> ")
        except EOFError:
            print("", file=out)
            history.save()
            return 0
        except KeyboardInterrupt:
            print("", file=out)
            history.save()
            return 0

        line = raw_line.strip()
        if not line:
            continue
        history.record(line)
        if line.lower() == "cn":
            lang = "zh"
            print(message("language_switched_zh", lang), file=out)
            continue
        if line.lower() == "en":
            lang = "en"
            print(message("language_switched_en", lang), file=out)
            continue
        if line in {"quit", "exit"}:
            history.save()
            return 0
        if line == "help":
            print(message("shell_help", lang), file=out)
            continue
        if line == "help advanced":
            print(message("shell_advanced_help", lang), file=out)
            continue
        if line.startswith("help "):
            command = line.split(maxsplit=1)[1].strip()
            print(f"{command}: {command_help(command, lang)}", file=out)
            continue
        if line == "shell":
            print(message("already_in_shell", lang), file=out)
            continue

        try:
            parts = shlex.split(line)
        except ValueError as exc:
            print(message("invalid_command", lang, error=exc), file=out)
            continue

        argv = translate_shell_command(parts)
        if argv is None:
            print(message("unknown_command", lang), file=out)
            continue
        if not argv:
            continue
        argv = _with_shell_language(argv, lang)
        if not _preview_before_confirm(argv, root_args, dispatch, out):
            continue
        if not _confirm(argv, input_func, out):
            continue

        try:
            dispatch([*root_args, *argv])
        except SystemExit as exc:
            if exc.code not in (None, 0):
                print(message("command_exited", lang, code=exc.code), file=out)
            continue
        except KeyboardInterrupt:
            print("", file=out)
            continue
        except Exception as exc:
            print(message("command_failed", lang, error=exc), file=out)
            continue


def _with_shell_language(argv: list[str], lang: str) -> list[str]:
    if normalize_lang(lang) == "en":
        return argv
    if "--json" in argv or "--lang" in argv:
        return argv
    command = argv[0]
    if command in {"list", "add", "remove", "new", "check"}:
        return [*argv, "--lang", "zh"]
    if command == "plugin" and len(argv) > 1 and argv[1] in {"check", "status", "lint", "plan", "precheck", "diagnose"}:
        return [*argv, "--lang", "zh"]
    if command == "plugins" and len(argv) > 1 and argv[1] == "status":
        return [*argv, "--lang", "zh"]
    return argv

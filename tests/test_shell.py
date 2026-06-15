from __future__ import annotations

import io
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from plugin_ctl.cli import main
from plugin_ctl.shell import run_shell, translate_shell_command


class FakeLocalRuntime:
    container = "fake"
    host = "127.0.0.1"
    port = 30004
    user = "opentenbase"
    database = "postgres"

    def run_sql(self, sql: str) -> subprocess.CompletedProcess[str]:
        if sql == "SELECT 1;":
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="1\n", stderr="")
        if sql == "SELECT version();":
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="OpenTenBase test\n", stderr="")
        if "FROM pgxc_group" in sql:
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="default_group\n", stderr="")
        if "FROM pgxc_shard_map" in sql:
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="16\n", stderr="")
        if "SELECT DISTINCT node_type" in sql:
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="C\n", stderr="")
        if "FROM pgxc_node" in sql:
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="cn001|C|127.0.0.1|30004\n", stderr="")
        return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="", stderr="")

    def run_sql_at(self, host: str, port: int, sql: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="1\n", stderr="")

    def exec(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")


class PluginCtlShellTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def _input(self, lines: list[str]):
        values = iter(lines)

        def inner(prompt: str) -> str:
            return next(values)

        return inner

    def test_no_args_tty_enters_shell(self) -> None:
        with patch("sys.stdin.isatty", return_value=True):
            with patch("plugin_ctl.cli.run_shell", return_value=0) as shell:
                code = main([])

        self.assertEqual(code, 0)
        shell.assert_called_once()

    def test_no_args_non_tty_prints_help_without_entering_shell(self) -> None:
        output = io.StringIO()
        with patch("sys.stdin.isatty", return_value=False):
            with patch("plugin_ctl.cli.run_shell", side_effect=AssertionError("must not enter shell")):
                with redirect_stdout(output):
                    code = main([])

        self.assertEqual(code, 0)
        self.assertIn("usage: plugin_ctl", output.getvalue())

    def test_root_only_tty_enters_shell_with_root(self) -> None:
        with patch("sys.stdin.isatty", return_value=True):
            with patch("plugin_ctl.cli.run_shell", return_value=0) as shell:
                code = main(["--root", str(self.root)])

        self.assertEqual(code, 0)
        shell.assert_called_once_with(self.root)

    def test_root_equals_tty_enters_shell_with_root(self) -> None:
        with patch("sys.stdin.isatty", return_value=True):
            with patch("plugin_ctl.cli.run_shell", return_value=0) as shell:
                code = main([f"--root={self.root}"])

        self.assertEqual(code, 0)
        shell.assert_called_once_with(self.root)

    def test_root_only_non_tty_prints_help_without_entering_shell(self) -> None:
        output = io.StringIO()
        with patch("sys.stdin.isatty", return_value=False):
            with patch("plugin_ctl.cli.run_shell", side_effect=AssertionError("must not enter shell")):
                with redirect_stdout(output):
                    code = main(["--root", str(self.root)])

        self.assertEqual(code, 0)
        self.assertIn("usage: plugin_ctl", output.getvalue())

    def test_explicit_shell_command_enters_shell(self) -> None:
        with patch("plugin_ctl.cli.run_shell", return_value=0) as shell:
            code = main(["--root", str(self.root), "shell"])

        self.assertEqual(code, 0)
        shell.assert_called_once_with(self.root)

    def test_help_quit_exit_empty_and_unknown_commands(self) -> None:
        output = io.StringIO()
        calls: list[list[str]] = []

        code = run_shell(
            self.root,
            dispatcher=lambda argv: calls.append(argv) or 0,
            input_func=self._input(["", "help", "wat", "exit"]),
            output=output,
        )

        self.assertEqual(code, 0)
        text = output.getvalue()
        self.assertIn("OpenTenBase PluginCtl Shell", text)
        self.assertIn("Available commands:", text)
        self.assertIn("new <plugin_id>", text)
        self.assertNotIn("plugin lint", text)
        self.assertIn('Unknown command. Type "help" to show commands.', text)
        self.assertEqual(calls, [])

    def test_quit_exits_shell(self) -> None:
        output = io.StringIO()

        code = run_shell(self.root, dispatcher=lambda argv: 0, input_func=self._input(["quit"]), output=output)

        self.assertEqual(code, 0)

    def test_eof_and_keyboard_interrupt_exit_cleanly(self) -> None:
        for exc in [EOFError, KeyboardInterrupt]:
            output = io.StringIO()

            def raise_input(prompt: str) -> str:
                raise exc()

            code = run_shell(self.root, dispatcher=lambda argv: 0, input_func=raise_input, output=output)

            self.assertEqual(code, 0)
            self.assertIn("OpenTenBase PluginCtl Shell", output.getvalue())

    def test_shell_command_translation(self) -> None:
        self.assertEqual(translate_shell_command(["list"]), ["list"])
        self.assertEqual(translate_shell_command(["list", "demo_plugin"]), ["list", "demo_plugin"])
        self.assertEqual(translate_shell_command(["new", "demo_plugin"]), ["new", "demo_plugin"])
        self.assertEqual(translate_shell_command(["init"]), ["cluster", "init"])
        self.assertEqual(translate_shell_command(["add", "/tmp/demo_plugin"]), ["add", "/tmp/demo_plugin"])
        self.assertEqual(translate_shell_command(["remove", "demo_plugin"]), ["remove", "demo_plugin"])
        self.assertEqual(translate_shell_command(["diagnose", "pluginctl_smoke_plugin"]), ["plugin", "diagnose", "pluginctl_smoke_plugin"])
        self.assertEqual(translate_shell_command(["plugin", "lint", "pluginctl_smoke_plugin"]), ["plugin", "lint", "pluginctl_smoke_plugin"])
        self.assertEqual(translate_shell_command(["plugins", "status", "--json"]), ["plugins", "status", "--json"])
        self.assertEqual(translate_shell_command(["cluster", "inspect"]), ["cluster", "inspect"])
        self.assertEqual(translate_shell_command(["assess", "/tmp/source", "--json"]), ["assess", "/tmp/source", "--json"])
        self.assertEqual(translate_shell_command(["state", "pluginctl_smoke_plugin"]), ["state", "pluginctl_smoke_plugin"])
        self.assertEqual(translate_shell_command(["register", "pluginctl_smoke_plugin"]), ["register", "pluginctl_smoke_plugin"])
        self.assertEqual(translate_shell_command(["plugin_ctl", "list"]), ["list"])
        self.assertIsNone(translate_shell_command(["start", "all"]))

    def test_help_advanced_shows_compatibility_commands(self) -> None:
        output = io.StringIO()

        code = run_shell(
            self.root,
            dispatcher=lambda argv: 0,
            input_func=self._input(["help advanced", "quit"]),
            output=output,
        )

        self.assertEqual(code, 0)
        text = output.getvalue()
        self.assertIn("Advanced and compatibility commands:", text)
        self.assertIn("plugin lint <plugin_id>", text)

    def test_full_cli_commands_are_available_inside_shell(self) -> None:
        calls: list[list[str]] = []
        output = io.StringIO()

        code = run_shell(
            self.root,
            dispatcher=lambda argv: calls.append(argv) or 0,
            input_func=self._input(
                [
                    "plugin lint pluginctl_smoke_plugin",
                    "plugin plan pluginctl_smoke_plugin --json",
                    "plugin precheck pluginctl_smoke_plugin",
                    "plugin roles pluginctl_smoke_plugin",
                    "plugin archive list",
                    "plugins status --json",
                    "cluster inspect",
                    "cluster distribute pluginctl_smoke_plugin --dry-run",
                    "assess /tmp/source --json",
                    "state pluginctl_smoke_plugin",
                    "activate pluginctl_smoke_plugin --dry-run",
                    "quit",
                ]
            ),
            output=output,
        )

        self.assertEqual(code, 0)
        expected = [
            ["--root", str(self.root), "plugin", "lint", "pluginctl_smoke_plugin"],
            ["--root", str(self.root), "plugin", "plan", "pluginctl_smoke_plugin", "--json"],
            ["--root", str(self.root), "plugin", "precheck", "pluginctl_smoke_plugin"],
            ["--root", str(self.root), "plugin", "roles", "pluginctl_smoke_plugin"],
            ["--root", str(self.root), "plugin", "archive", "list"],
            ["--root", str(self.root), "plugins", "status", "--json"],
            ["--root", str(self.root), "cluster", "inspect"],
            ["--root", str(self.root), "cluster", "distribute", "pluginctl_smoke_plugin", "--dry-run"],
            ["--root", str(self.root), "assess", "/tmp/source", "--json"],
            ["--root", str(self.root), "state", "pluginctl_smoke_plugin"],
            ["--root", str(self.root), "activate", "pluginctl_smoke_plugin", "--dry-run"],
        ]
        self.assertEqual(calls, expected)

    def test_shell_command_inside_shell_does_not_recurse(self) -> None:
        output = io.StringIO()
        calls: list[list[str]] = []

        code = run_shell(self.root, dispatcher=lambda argv: calls.append(argv) or 0, input_func=self._input(["shell", "quit"]), output=output)

        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        self.assertIn("Already in PluginCtl Shell.", output.getvalue())

    def test_system_exit_does_not_leave_shell(self) -> None:
        output = io.StringIO()
        calls: list[list[str]] = []

        def dispatch(argv: list[str]) -> int:
            calls.append(argv)
            raise SystemExit(2)

        code = run_shell(self.root, dispatcher=dispatch, input_func=self._input(["list", "quit"]), output=output)

        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertIn("Command exited with status 2.", output.getvalue())

    def test_regular_exception_does_not_leave_shell(self) -> None:
        output = io.StringIO()
        calls: list[list[str]] = []

        def dispatch(argv: list[str]) -> int:
            calls.append(argv)
            if "--dry-run" in argv:
                return 0
            if len([call for call in calls if "--dry-run" not in call]) == 1:
                raise PermissionError("state path is not writable")
            return 0

        code = run_shell(self.root, dispatcher=dispatch, input_func=self._input(["rollback demo", "y", "list", "quit"]), output=output)

        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0], ["--root", str(self.root), "rollback", "demo", "--dry-run"])
        self.assertIn("Command failed: state path is not writable", output.getvalue())

    def test_modifying_shell_commands_confirm_before_dispatch(self) -> None:
        output = io.StringIO()
        calls: list[list[str]] = []

        code = run_shell(
            self.root,
            dispatcher=lambda argv: calls.append(argv) or 0,
            input_func=self._input(["deploy demo", "n", "register demo", "y", "quit"]),
            output=output,
        )

        self.assertEqual(code, 0)
        self.assertEqual(
            calls,
            [
                ["--root", str(self.root), "deploy", "demo", "--dry-run"],
                ["--root", str(self.root), "register", "demo", "--dry-run"],
                ["--root", str(self.root), "register", "demo"],
            ],
        )
        text = output.getvalue()
        self.assertIn("Preview:", text)
        self.assertIn("PluginCtl will copy plugin files", text)
        self.assertIn("Deploy cancelled.", text)
        self.assertIn("PluginCtl will execute CREATE EXTENSION", text)

    def test_list_maps_to_existing_list_command(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            code = run_shell(self.root, dispatcher=main, input_func=self._input(["list", "quit"]), output=output)

        self.assertEqual(code, 0)
        text = output.getvalue()
        self.assertIn("No user plugins found.", text)
        self.assertIn("Show built-in examples with: list --all", text)

    def test_diagnose_maps_to_plugin_diagnose(self) -> None:
        calls: list[list[str]] = []
        output = io.StringIO()

        code = run_shell(
            self.root,
            dispatcher=lambda argv: calls.append(argv) or 0,
            input_func=self._input(["diagnose pluginctl_smoke_plugin", "quit"]),
            output=output,
        )

        self.assertEqual(code, 0)
        self.assertEqual(calls, [["--root", str(self.root), "plugin", "diagnose", "pluginctl_smoke_plugin"]])

    def test_help_flag_does_not_enter_shell(self) -> None:
        output = io.StringIO()
        with patch("plugin_ctl.cli.run_shell", side_effect=AssertionError("must not enter shell")):
            with redirect_stdout(output), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    main(["--help"])

        self.assertEqual(cm.exception.code, 0)
        self.assertIn("usage: plugin_ctl", output.getvalue())

    def test_existing_list_and_check_commands_still_work(self) -> None:
        list_output = io.StringIO()
        with redirect_stdout(list_output):
            list_code = main(["--root", str(self.root), "list"])

        self.assertEqual(list_code, 0)
        self.assertIn("No user plugins found.", list_output.getvalue())

        list_all_output = io.StringIO()
        with redirect_stdout(list_all_output):
            list_all_code = main(["--root", str(self.root), "list", "--all"])

        self.assertEqual(list_all_code, 0)
        self.assertIn("pluginctl_smoke_plugin", list_all_output.getvalue())

        check_output = io.StringIO()
        with patch("plugin_ctl.cli.OpenTenBaseRuntime", return_value=FakeLocalRuntime()):
            with redirect_stdout(check_output):
                check_code = main(["--root", str(self.root), "check", "pluginctl_smoke_plugin"])

        self.assertEqual(check_code, 0)
        self.assertIn("结果: READY", check_output.getvalue())


if __name__ == "__main__":
    unittest.main()

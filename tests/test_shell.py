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
        self.assertEqual(translate_shell_command(["init"]), ["cluster", "init"])
        self.assertEqual(translate_shell_command(["diagnose", "pluginctl_smoke_plugin"]), ["plugin", "diagnose", "pluginctl_smoke_plugin"])
        self.assertEqual(translate_shell_command(["register", "pluginctl_smoke_plugin"]), ["register", "pluginctl_smoke_plugin"])
        self.assertIsNone(translate_shell_command(["start", "all"]))

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

    def test_list_maps_to_existing_list_command(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            code = run_shell(self.root, dispatcher=main, input_func=self._input(["list", "quit"]), output=output)

        self.assertEqual(code, 0)
        self.assertIn("pluginctl_smoke_plugin", output.getvalue())

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
        self.assertIn("pluginctl_smoke_plugin", list_output.getvalue())

        check_output = io.StringIO()
        with patch("plugin_ctl.cli.OpenTenBaseRuntime", return_value=FakeLocalRuntime()):
            with redirect_stdout(check_output):
                check_code = main(["--root", str(self.root), "check", "pluginctl_smoke_plugin"])

        self.assertEqual(check_code, 0)
        self.assertIn("Result: OK", check_output.getvalue())


if __name__ == "__main__":
    unittest.main()

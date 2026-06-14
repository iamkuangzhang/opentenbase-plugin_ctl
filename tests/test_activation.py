from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from plugin_ctl.activation import PsqlCoordinatorExecutor, execute_activation
from plugin_ctl.catalog import Catalog
from plugin_ctl.cli import main
from plugin_ctl.cluster import ClusterConfig, ClusterNode
from plugin_ctl.runtime.opentenbase import RemoteCommandResult


CLUSTER_TOML = """
[cluster]
name = "activation-test"

[[nodes]]
name = "cn001"
role = "cn"
host = "10.0.0.11"
ssh_port = 22
db_port = 30004
ssh_user = "otb"
db_user = "opentenbase"
database = "postgres"
lib_dir = "/opt/otb/lib"
extension_dir = "/opt/otb/share/extension"

[[nodes]]
name = "cn002"
role = "cn"
host = "10.0.0.12"
ssh_port = 22
db_port = 30005
ssh_user = "otb"
db_user = "opentenbase"
database = "postgres"
lib_dir = "/opt/otb/lib"
extension_dir = "/opt/otb/share/extension"

[[nodes]]
name = "dn001"
role = "dn"
host = "10.0.0.21"
ssh_port = 22
db_port = 40004
ssh_user = "otb"
db_user = "opentenbase"
database = "postgres"
lib_dir = "/opt/otb/lib"
extension_dir = "/opt/otb/share/extension"
"""


class FakeCoordinatorExecutor:
    def __init__(
        self,
        *,
        versions: dict[str, str] | None = None,
        available: bool = True,
        registered: bool = False,
        fail_activate_for: str = "",
        fail_query_for: str = "",
    ) -> None:
        self.versions = versions or {"cn001": "0.1.0", "cn002": "0.1.0"}
        self.available = available
        self.registered = registered
        self.fail_activate_for = fail_activate_for
        self.fail_query_for = fail_query_for
        self.calls: list[tuple[str, str]] = []

    def run_sql(self, node: ClusterNode, sql: str) -> RemoteCommandResult:
        self.calls.append((node.name, sql))
        if sql == "SELECT 1;":
            return RemoteCommandResult(node=node.name, argv=("psql",), returncode=0, stdout="1\n", stderr="")
        if "FROM pg_available_extensions" in sql:
            stdout = "pluginctl_smoke_plugin\n" if self.available else ""
            return RemoteCommandResult(node=node.name, argv=("psql",), returncode=0, stdout=stdout, stderr="")
        if "SELECT extname FROM pg_extension" in sql:
            stdout = "pluginctl_smoke_plugin\n" if self.registered else ""
            return RemoteCommandResult(node=node.name, argv=("psql",), returncode=0, stdout=stdout, stderr="")
        if sql.startswith("CREATE EXTENSION"):
            if node.name == self.fail_activate_for:
                return RemoteCommandResult(node=node.name, argv=("psql",), returncode=1, stdout="", stderr="activate failed")
            self.registered = True
            return RemoteCommandResult(node=node.name, argv=("psql",), returncode=0, stdout="CREATE EXTENSION\n", stderr="")
        if node.name == self.fail_query_for:
            return RemoteCommandResult(node=node.name, argv=("psql",), returncode=1, stdout="", stderr="query failed")
        return RemoteCommandResult(node=node.name, argv=("psql",), returncode=0, stdout=self.versions.get(node.name, "") + "\n", stderr="")


class ActivationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.manifest = Catalog(root=self.root).load_one("pluginctl_smoke_plugin")
        self.cluster = ClusterConfig(
            name="activation-test",
            nodes=(
                ClusterNode("cn001", "cn", "10.0.0.11", 22, 30004, "otb", "opentenbase", "postgres", "/opt/otb/lib", "/opt/otb/share/extension"),
                ClusterNode("cn002", "cn", "10.0.0.12", 22, 30005, "otb", "opentenbase", "postgres", "/opt/otb/lib", "/opt/otb/share/extension"),
                ClusterNode("dn001", "dn", "10.0.0.21", 22, 40004, "otb", "opentenbase", "postgres", "/opt/otb/lib", "/opt/otb/share/extension"),
            ),
        )

    def test_execute_activation_succeeds_when_versions_match(self) -> None:
        executor = FakeCoordinatorExecutor()
        report = execute_activation(self.cluster, self.manifest, executor)

        self.assertEqual(report.mode, "execute")
        self.assertEqual(report.datanodes, "not_connected")
        self.assertEqual(report.summary.activated, 1)
        self.assertFalse(report.summary.version_mismatch)
        self.assertEqual(report.errors, ())

    def test_register_stage_runs_create_extension_on_primary_cn_only(self) -> None:
        executor = FakeCoordinatorExecutor()
        execute_activation(self.cluster, self.manifest, executor)

        self.assertEqual(executor.calls[0][0], "cn001")
        self.assertTrue(executor.calls[0][1].startswith("CREATE EXTENSION"))
        create_calls = [call for call in executor.calls if call[1].startswith("CREATE EXTENSION")]
        self.assertEqual(create_calls, [("cn001", "CREATE EXTENSION IF NOT EXISTS pluginctl_smoke_plugin;")])
        version_calls = [call[0] for call in executor.calls if call[1].startswith("SELECT extversion")]
        self.assertEqual(version_calls, ["cn001", "cn002"])

    def test_missing_extension_fails_version_check(self) -> None:
        report = execute_activation(self.cluster, self.manifest, FakeCoordinatorExecutor(versions={"cn001": "0.1.0", "cn002": ""}))

        self.assertEqual(report.summary.missing, 1)
        self.assertTrue(report.errors)
        self.assertEqual(next(item for item in report.versions if item.node == "cn002").status, "missing")

    def test_version_mismatch_fails(self) -> None:
        report = execute_activation(self.cluster, self.manifest, FakeCoordinatorExecutor(versions={"cn001": "0.1.0", "cn002": "0.2.0"}))

        self.assertTrue(report.summary.version_mismatch)
        self.assertTrue(any("version mismatch" in error for error in report.errors))

    def test_registration_failure_is_structured(self) -> None:
        report = execute_activation(self.cluster, self.manifest, FakeCoordinatorExecutor(fail_activate_for="cn001"))

        failed = next(item for item in report.activation if item.node == "cn001")
        self.assertEqual(failed.status, "failed")
        self.assertIn("activate failed", failed.stderr)
        self.assertTrue(report.errors)

    def test_psql_executor_uses_argument_list_without_shell(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok\n", stderr="")
        with patch("subprocess.run", return_value=completed) as run:
            result = PsqlCoordinatorExecutor().run_sql(self.cluster.coordinators[0], "SELECT 1;")

        args, kwargs = run.call_args
        self.assertEqual(
            args[0],
            [
                "psql",
                "-X",
                "-v",
                "ON_ERROR_STOP=1",
                "-h",
                "10.0.0.11",
                "-p",
                "30004",
                "-U",
                "opentenbase",
                "-d",
                "postgres",
                "-Atc",
                "SELECT 1;",
            ],
        )
        self.assertNotIn("shell", kwargs)
        self.assertEqual(result.stdout, "ok\n")


class ActivationCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.tempdir = tempfile.TemporaryDirectory()
        self.cluster_file = Path(self.tempdir.name) / "cluster.toml"
        self.cluster_file.write_text(CLUSTER_TOML, encoding="utf-8")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _run(self, argv: list[str]) -> tuple[int, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, output.getvalue()

    def test_register_dry_run_does_not_create_executor(self) -> None:
        fake = FakeCoordinatorExecutor()
        with patch("plugin_ctl.cli.PsqlCoordinatorExecutor", return_value=fake):
            code, output = self._run(["--root", str(self.root), "register", "pluginctl_smoke_plugin", "-f", str(self.cluster_file), "--dry-run"])

        self.assertEqual(code, 0)
        self.assertIn("Register precheck", output)
        self.assertIn("pg_available_extensions", output)
        self.assertIn("SQL to execute", output)
        self.assertIn("Mode: dry-run", output)
        self.assertIn("Physical distribution: not_executed", output)
        self.assertIn("Datanodes: not_connected", output)
        self.assertIn("CREATE EXTENSION: planned on primary CN only", output)
        self.assertFalse(any(call[1].startswith("CREATE EXTENSION") for call in fake.calls))

    def test_register_defaults_to_execute_once_then_verifies_all_cn(self) -> None:
        fake = FakeCoordinatorExecutor()
        with patch("plugin_ctl.cli.PsqlCoordinatorExecutor", return_value=fake):
            code, output = self._run(["--root", str(self.root), "register", "pluginctl_smoke_plugin", "-f", str(self.cluster_file)])

        self.assertEqual(code, 0)
        self.assertIn("Register precheck", output)
        self.assertIn("Mode: execute", output)
        self.assertIn("CREATE EXTENSION: executed on primary CN only", output)
        self.assertIn("Result: OK", output)
        self.assertEqual(len([call for call in fake.calls if call[1].startswith("CREATE EXTENSION")]), 1)

    def test_register_uses_default_cluster_config_when_file_is_omitted(self) -> None:
        fake = FakeCoordinatorExecutor()
        with patch.dict(os.environ, {"OPENTENBASE_PLUGINCTL_CLUSTER_FILE": str(self.cluster_file)}):
            with patch("plugin_ctl.cli.PsqlCoordinatorExecutor", return_value=fake):
                code, output = self._run(["--root", str(self.root), "register", "pluginctl_smoke_plugin"])

        self.assertEqual(code, 0)
        self.assertIn("CREATE EXTENSION: executed on primary CN only", output)
        self.assertEqual(len([call for call in fake.calls if call[1].startswith("CREATE EXTENSION")]), 1)

    def test_register_rejects_removed_execute_flag(self) -> None:
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                main(["register", "pluginctl_smoke_plugin", "-f", str(self.cluster_file), "--execute"])

    def test_register_json_shape_is_stable(self) -> None:
        with patch("plugin_ctl.cli.PsqlCoordinatorExecutor", return_value=FakeCoordinatorExecutor()):
            code, output = self._run(["--root", str(self.root), "register", "pluginctl_smoke_plugin", "-f", str(self.cluster_file), "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["cluster"], "activation-test")
        self.assertEqual(payload["plugin_id"], "pluginctl_smoke_plugin")
        self.assertEqual(payload["extension_name"], "pluginctl_smoke_plugin")
        self.assertEqual(payload["mode"], "execute")
        self.assertEqual(payload["physical_distribution"], "not_executed")
        self.assertEqual(payload["datanodes"], "not_connected")
        for key in ["activation", "versions", "summary", "errors", "precheck"]:
            self.assertIn(key, payload)

    def test_register_blocks_when_extension_is_not_available(self) -> None:
        fake = FakeCoordinatorExecutor(available=False)
        with patch("plugin_ctl.cli.PsqlCoordinatorExecutor", return_value=fake):
            code, output = self._run(["--root", str(self.root), "register", "pluginctl_smoke_plugin", "-f", str(self.cluster_file)])

        self.assertEqual(code, 1)
        self.assertIn("pg_available_extensions", output)
        self.assertIn("CREATE EXTENSION: blocked by precheck", output)
        self.assertFalse(any(call[1].startswith("CREATE EXTENSION") for call in fake.calls))

    def test_register_skips_when_extension_is_already_registered(self) -> None:
        fake = FakeCoordinatorExecutor(registered=True)
        with patch("plugin_ctl.cli.PsqlCoordinatorExecutor", return_value=fake):
            code, output = self._run(["--root", str(self.root), "register", "pluginctl_smoke_plugin", "-f", str(self.cluster_file)])

        self.assertEqual(code, 0)
        self.assertIn("already registered", output)
        self.assertIn("CREATE EXTENSION: skipped", output)
        self.assertFalse(any(call[1].startswith("CREATE EXTENSION") for call in fake.calls))

    def test_activate_alias_still_works_with_deprecation_notice(self) -> None:
        with patch("plugin_ctl.cli.PsqlCoordinatorExecutor", return_value=FakeCoordinatorExecutor()):
            code, output = self._run(["--root", str(self.root), "activate", "pluginctl_smoke_plugin", "-f", str(self.cluster_file), "--dry-run"])

        self.assertEqual(code, 0)
        self.assertIn("deprecated", output)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from datanexus.activation import PsqlCoordinatorExecutor, execute_activation
from datanexus.catalog import Catalog
from datanexus.cli import main
from datanexus.cluster import ClusterConfig, ClusterNode
from datanexus.runtime.opentenbase import RemoteCommandResult


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
        fail_activate_for: str = "",
        fail_query_for: str = "",
    ) -> None:
        self.versions = versions or {"cn001": "0.1.0", "cn002": "0.1.0"}
        self.fail_activate_for = fail_activate_for
        self.fail_query_for = fail_query_for
        self.calls: list[tuple[str, str]] = []

    def run_sql(self, node: ClusterNode, sql: str) -> RemoteCommandResult:
        self.calls.append((node.name, sql))
        if sql.startswith("CREATE EXTENSION"):
            if node.name == self.fail_activate_for:
                return RemoteCommandResult(node=node.name, argv=("psql",), returncode=1, stdout="", stderr="activate failed")
            return RemoteCommandResult(node=node.name, argv=("psql",), returncode=0, stdout="CREATE EXTENSION\n", stderr="")
        if node.name == self.fail_query_for:
            return RemoteCommandResult(node=node.name, argv=("psql",), returncode=1, stdout="", stderr="query failed")
        return RemoteCommandResult(node=node.name, argv=("psql",), returncode=0, stdout=self.versions.get(node.name, "") + "\n", stderr="")


class ActivationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.manifest = Catalog(root=self.root).load_one("dnx_smoke_plugin")
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
        self.assertEqual(report.summary.activated, 2)
        self.assertFalse(report.summary.version_mismatch)
        self.assertEqual(report.errors, ())

    def test_activation_stage_runs_in_coordinator_order(self) -> None:
        executor = FakeCoordinatorExecutor()
        execute_activation(self.cluster, self.manifest, executor)

        self.assertEqual(executor.calls[0][0], "cn001")
        self.assertEqual(executor.calls[1][0], "cn002")
        self.assertTrue(executor.calls[0][1].startswith("CREATE EXTENSION"))
        self.assertTrue(executor.calls[1][1].startswith("CREATE EXTENSION"))

    def test_missing_extension_fails_version_check(self) -> None:
        report = execute_activation(self.cluster, self.manifest, FakeCoordinatorExecutor(versions={"cn001": "0.1.0", "cn002": ""}))

        self.assertEqual(report.summary.missing, 1)
        self.assertTrue(report.errors)
        self.assertEqual(next(item for item in report.versions if item.node == "cn002").status, "missing")

    def test_version_mismatch_fails(self) -> None:
        report = execute_activation(self.cluster, self.manifest, FakeCoordinatorExecutor(versions={"cn001": "0.1.0", "cn002": "0.2.0"}))

        self.assertTrue(report.summary.version_mismatch)
        self.assertTrue(any("version mismatch" in error for error in report.errors))

    def test_activation_failure_is_structured(self) -> None:
        report = execute_activation(self.cluster, self.manifest, FakeCoordinatorExecutor(fail_activate_for="cn002"))

        failed = next(item for item in report.activation if item.node == "cn002")
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

    def test_activate_defaults_to_dry_run_without_executor(self) -> None:
        with patch("datanexus.cli.PsqlCoordinatorExecutor", side_effect=AssertionError("dry-run must not create psql executor")):
            code, output = self._run(["--root", str(self.root), "activate", "dnx_smoke_plugin", "-f", str(self.cluster_file)])

        self.assertEqual(code, 0)
        self.assertIn("Mode: dry-run", output)
        self.assertIn("Physical distribution: not_executed", output)
        self.assertIn("Datanodes: not_connected", output)
        self.assertIn("CREATE EXTENSION: planned", output)

    def test_activate_execute_uses_executor(self) -> None:
        fake = FakeCoordinatorExecutor()
        with patch("datanexus.cli.PsqlCoordinatorExecutor", return_value=fake):
            code, output = self._run(["--root", str(self.root), "activate", "dnx_smoke_plugin", "-f", str(self.cluster_file), "--execute"])

        self.assertEqual(code, 0)
        self.assertIn("Mode: execute", output)
        self.assertIn("CREATE EXTENSION: executed", output)
        self.assertIn("Result: OK", output)
        self.assertTrue(fake.calls)

    def test_activate_rejects_dry_run_and_execute_together(self) -> None:
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                main(["activate", "dnx_smoke_plugin", "-f", str(self.cluster_file), "--dry-run", "--execute"])

    def test_activate_execute_json_shape_is_stable(self) -> None:
        with patch("datanexus.cli.PsqlCoordinatorExecutor", return_value=FakeCoordinatorExecutor()):
            code, output = self._run(["--root", str(self.root), "activate", "dnx_smoke_plugin", "-f", str(self.cluster_file), "--execute", "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["cluster"], "activation-test")
        self.assertEqual(payload["plugin_id"], "dnx_smoke_plugin")
        self.assertEqual(payload["extension_name"], "dnx_smoke_plugin")
        self.assertEqual(payload["mode"], "execute")
        self.assertEqual(payload["physical_distribution"], "not_executed")
        self.assertEqual(payload["datanodes"], "not_connected")
        for key in ["activation", "versions", "summary", "errors"]:
            self.assertIn(key, payload)


if __name__ == "__main__":
    unittest.main()

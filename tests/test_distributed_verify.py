from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from plugin_ctl.catalog import Catalog
from plugin_ctl.cli import main
from plugin_ctl.cluster import ClusterConfig, ClusterNode
from plugin_ctl.distributed_verify import run_distributed_verify
from plugin_ctl.runtime.opentenbase import RemoteCommandResult


CLUSTER_TOML = """
[cluster]
name = "verify-test"

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


class FakeSqlExecutor:
    def __init__(
        self,
        *,
        versions: dict[str, str] | None = None,
        prepared: dict[str, str] | None = None,
        fail_connect_for: str = "",
    ) -> None:
        self.versions = versions or {"cn001": "0.1.0", "cn002": "0.1.0"}
        self.prepared = prepared or {}
        self.fail_connect_for = fail_connect_for

    def run_sql(self, node: ClusterNode, sql: str) -> RemoteCommandResult:
        if sql == "SELECT 1;":
            if node.name == self.fail_connect_for:
                return RemoteCommandResult(node=node.name, argv=("psql",), returncode=1, stdout="", stderr="connection failed")
            return RemoteCommandResult(node=node.name, argv=("psql",), returncode=0, stdout="1\n", stderr="")
        if "FROM pg_extension" in sql:
            return RemoteCommandResult(node=node.name, argv=("psql",), returncode=0, stdout=self.versions.get(node.name, "") + "\n", stderr="")
        if "FROM pg_prepared_xacts" in sql:
            return RemoteCommandResult(node=node.name, argv=("psql",), returncode=0, stdout=self.prepared.get(node.name, ""), stderr="")
        return RemoteCommandResult(node=node.name, argv=("psql",), returncode=0, stdout="", stderr="")


class FakeRemoteExecutor:
    def __init__(self, root: Path, *, missing_for: str = "", mismatch_for: str = "") -> None:
        self.root = root
        self.missing_for = missing_for
        self.mismatch_for = mismatch_for

    def run(self, node: ClusterNode, argv: list[str]) -> RemoteCommandResult:
        return RemoteCommandResult(node=node.name, argv=tuple(argv), returncode=0, stdout="", stderr="")

    def copy_file(self, node: ClusterNode, local_path: Path, remote_path: str) -> RemoteCommandResult:
        raise AssertionError("distributed verify must not copy files")

    def sha256_file(self, node: ClusterNode, remote_path: str) -> RemoteCommandResult:
        if node.name == self.missing_for:
            return RemoteCommandResult(node=node.name, argv=("sha256sum", remote_path), returncode=1, stdout="", stderr="missing")
        name = Path(remote_path).name
        matches = [path for path in self.root.rglob(name) if path.is_file()]
        digest = sha256(matches[0].read_bytes()).hexdigest() if matches else ""
        if node.name == self.mismatch_for and digest:
            digest = "0" * 64
        return RemoteCommandResult(
            node=node.name,
            argv=("sha256sum", remote_path),
            returncode=0 if digest else 1,
            stdout=f"{digest}  {remote_path}\n" if digest else "",
            stderr="" if digest else "missing",
        )


class DistributedVerifyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.manifest = Catalog(root=self.root).load_one("pluginctl_smoke_plugin")
        self.cluster = ClusterConfig(
            name="verify-test",
            nodes=(
                ClusterNode("cn001", "cn", "10.0.0.11", 22, 30004, "otb", "opentenbase", "postgres", "/opt/otb/lib", "/opt/otb/share/extension"),
                ClusterNode("cn002", "cn", "10.0.0.12", 22, 30005, "otb", "opentenbase", "postgres", "/opt/otb/lib", "/opt/otb/share/extension"),
                ClusterNode("dn001", "dn", "10.0.0.21", 22, 40004, "otb", "opentenbase", "postgres", "/opt/otb/lib", "/opt/otb/share/extension"),
            ),
        )

    def test_distributed_verify_passes_when_all_checks_match(self) -> None:
        report = run_distributed_verify(self.cluster, self.manifest, FakeSqlExecutor(), FakeRemoteExecutor(self.root))

        self.assertFalse(report.errors)
        self.assertTrue(report.summary.extension_consistent)
        self.assertFalse(report.summary.prepared_leak)
        self.assertEqual(report.summary.checksum_failed, 0)

    def test_missing_extension_fails(self) -> None:
        report = run_distributed_verify(
            self.cluster,
            self.manifest,
            FakeSqlExecutor(versions={"cn001": "0.1.0", "cn002": ""}),
            FakeRemoteExecutor(self.root),
        )

        self.assertTrue(report.errors)
        self.assertEqual(next(item for item in report.coordinator_extensions if item.node == "cn002").extension_status, "missing")

    def test_version_mismatch_fails(self) -> None:
        report = run_distributed_verify(
            self.cluster,
            self.manifest,
            FakeSqlExecutor(versions={"cn001": "0.1.0", "cn002": "0.2.0"}),
            FakeRemoteExecutor(self.root),
        )

        self.assertFalse(report.summary.extension_consistent)
        self.assertTrue(any("version mismatch" in error for error in report.errors))

    def test_missing_physical_file_fails(self) -> None:
        report = run_distributed_verify(self.cluster, self.manifest, FakeSqlExecutor(), FakeRemoteExecutor(self.root, missing_for="dn001"))

        self.assertTrue(any(item.file_status == "missing" for item in report.file_checks))
        self.assertTrue(report.errors)

    def test_checksum_mismatch_fails(self) -> None:
        report = run_distributed_verify(self.cluster, self.manifest, FakeSqlExecutor(), FakeRemoteExecutor(self.root, mismatch_for="cn001"))

        self.assertGreater(report.summary.checksum_failed, 0)
        self.assertTrue(report.errors)

    def test_prepared_transaction_leak_fails(self) -> None:
        report = run_distributed_verify(
            self.cluster,
            self.manifest,
            FakeSqlExecutor(prepared={"dn001": "gid1|2026-01-01 00:00:00|opentenbase|postgres\n"}),
            FakeRemoteExecutor(self.root),
        )

        self.assertTrue(report.summary.prepared_leak)
        self.assertTrue(any("prepared transaction residue" in error for error in report.errors))

    def test_dn_connection_failure_fails(self) -> None:
        report = run_distributed_verify(self.cluster, self.manifest, FakeSqlExecutor(fail_connect_for="dn001"), FakeRemoteExecutor(self.root))

        self.assertEqual(next(item for item in report.connectivity if item.node == "dn001").connected_status, "failed")
        self.assertTrue(any("connection failed" in error for error in report.errors))


class DistributedVerifyCliTest(unittest.TestCase):
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

    def test_verify_without_cluster_file_keeps_smoke_verify(self) -> None:
        class Runtime:
            container = "fake"
            host = "127.0.0.1"
            port = 30004
            user = "opentenbase"
            database = "postgres"

            def run_sql(self, sql: str) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="ok\n", stderr="")

        missing_default = str(Path(self.tempdir.name) / "missing.toml")
        with patch.dict(os.environ, {"OPENTENBASE_PLUGINCTL_CLUSTER_FILE": missing_default}):
            with patch("plugin_ctl.cli.OpenTenBaseRuntime", return_value=Runtime()):
                code, output = self._run(["--root", str(self.root), "verify", "pluginctl_smoke_plugin"])

        self.assertEqual(code, 0)
        self.assertIn("smoke verify passed", output)

    def test_verify_with_cluster_file_enters_distributed_verify(self) -> None:
        with patch("plugin_ctl.cli.PsqlCoordinatorExecutor", return_value=FakeSqlExecutor()):
            with patch("plugin_ctl.cli.ScpSshRemoteExecutor", return_value=FakeRemoteExecutor(self.root)):
                code, output = self._run(["--root", str(self.root), "verify", "pluginctl_smoke_plugin", "-f", str(self.cluster_file)])

        self.assertEqual(code, 0)
        self.assertIn("Mode: distributed-verify", output)
        self.assertIn("Coordinator extension check:", output)
        self.assertIn("Prepared transaction scan:", output)
        self.assertIn("Result: OK", output)

    def test_verify_uses_default_cluster_config_when_file_is_omitted(self) -> None:
        with patch.dict(os.environ, {"OPENTENBASE_PLUGINCTL_CLUSTER_FILE": str(self.cluster_file)}):
            with patch("plugin_ctl.cli.PsqlCoordinatorExecutor", return_value=FakeSqlExecutor()):
                with patch("plugin_ctl.cli.ScpSshRemoteExecutor", return_value=FakeRemoteExecutor(self.root)):
                    code, output = self._run(["--root", str(self.root), "verify", "pluginctl_smoke_plugin"])

        self.assertEqual(code, 0)
        self.assertIn("Mode: distributed-verify", output)
        self.assertIn("Result: OK", output)

    def test_verify_json_shape_is_stable(self) -> None:
        with patch("plugin_ctl.cli.PsqlCoordinatorExecutor", return_value=FakeSqlExecutor()):
            with patch("plugin_ctl.cli.ScpSshRemoteExecutor", return_value=FakeRemoteExecutor(self.root)):
                code, output = self._run(["--root", str(self.root), "verify", "pluginctl_smoke_plugin", "-f", str(self.cluster_file), "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["cluster"], "verify-test")
        self.assertEqual(payload["mode"], "distributed-verify")
        self.assertEqual(payload["physical_distribution"], "not_executed")
        self.assertEqual(payload["create_extension"], "not_executed")
        for key in ["coordinator_extensions", "file_checks", "prepared_transactions", "summary", "errors"]:
            self.assertIn(key, payload)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from plugin_ctl.cli import main
from plugin_ctl.cluster import ClusterNode
from plugin_ctl.runtime.opentenbase import RemoteCommandResult


CLUSTER_TOML = """
[cluster]
name = "m3-test"

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


class ClusterCliTest(unittest.TestCase):
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

    def test_cluster_inspect_human_output(self) -> None:
        code, output = self._run(["cluster", "inspect", "-f", str(self.cluster_file)])

        self.assertEqual(code, 0)
        self.assertIn("Cluster: m3-test", output)
        self.assertIn("Coordinators:", output)
        self.assertIn("Datanodes:", output)
        self.assertIn("cn001", output)
        self.assertIn("dn001", output)
        self.assertIn("Result: OK", output)

    def test_cluster_inspect_json_output(self) -> None:
        code, output = self._run(["cluster", "inspect", "-f", str(self.cluster_file), "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["cluster"], "m3-test")
        self.assertEqual(payload["result"], "OK")
        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["coordinators"][0]["name"], "cn001")
        self.assertEqual(payload["datanodes"][0]["role"], "dn")

    def test_cluster_distribute_dry_run_json_uses_manifest_payload_without_scp(self) -> None:
        code, output = self._run(
            [
                "--root",
                str(self.root),
                "cluster",
                "distribute",
                "--dry-run",
                "-f",
                str(self.cluster_file),
                "pluginctl_smoke_plugin",
                "--json",
            ]
        )

        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["cluster"], "m3-test")
        self.assertEqual(payload["mode"], "dry-run")
        self.assertEqual(payload["plugin_id"], "pluginctl_smoke_plugin")
        self.assertEqual(payload["errors"], [])
        self.assertTrue(payload["plan"])
        self.assertIn("coordinators", payload)
        self.assertIn("datanodes", payload)
        self.assertTrue(any(entry["remote_path"].startswith("/opt/otb/share/extension/") for entry in payload["plan"]))

    def test_cluster_distribute_dry_run_human_output(self) -> None:
        code, output = self._run(
            [
                "--root",
                str(self.root),
                "cluster",
                "distribute",
                "--dry-run",
                "-f",
                str(self.cluster_file),
                "pluginctl_smoke_plugin",
            ]
        )

        self.assertEqual(code, 0)
        self.assertIn("Mode: dry-run", output)
        self.assertIn("pluginctl_smoke_plugin", output)
        self.assertIn("install.sql", output)
        self.assertIn("Result: OK", output)

    def test_cluster_distribute_defaults_to_dry_run_without_flag(self) -> None:
        code, output = self._run(
            [
                "--root",
                str(self.root),
                "cluster",
                "distribute",
                "-f",
                str(self.cluster_file),
                "pluginctl_smoke_plugin",
            ]
        )

        self.assertEqual(code, 0)
        self.assertIn("Mode: dry-run", output)

    def test_cluster_distribute_rejects_dry_run_and_execute_together(self) -> None:
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                main(
                    [
                        "--root",
                        str(self.root),
                        "cluster",
                        "distribute",
                        "--dry-run",
                        "--execute",
                        "-f",
                        str(self.cluster_file),
                        "pluginctl_smoke_plugin",
                    ]
                )

    def test_cluster_distribute_execute_uses_real_execute_path_with_fake_executor(self) -> None:
        fake = FakeRemoteExecutor()
        with patch("plugin_ctl.cli.ScpSshRemoteExecutor", return_value=fake):
            code, output = self._run(
                [
                    "--root",
                    str(self.root),
                    "cluster",
                    "distribute",
                    "--execute",
                    "-f",
                    str(self.cluster_file),
                    "pluginctl_smoke_plugin",
                ]
            )

        self.assertEqual(code, 0)
        self.assertIn("Mode: execute", output)
        self.assertIn("Summary:", output)
        self.assertIn("Result: OK", output)
        self.assertTrue(fake.copies)

    def test_cluster_distribute_execute_json_output_is_stable(self) -> None:
        fake = FakeRemoteExecutor()
        with patch("plugin_ctl.cli.ScpSshRemoteExecutor", return_value=fake):
            code, output = self._run(
                [
                    "--root",
                    str(self.root),
                    "cluster",
                    "distribute",
                    "--execute",
                    "-f",
                    str(self.cluster_file),
                    "pluginctl_smoke_plugin",
                    "--json",
                ]
            )

        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["cluster"], "m3-test")
        self.assertEqual(payload["mode"], "execute")
        self.assertEqual(payload["plugin_id"], "pluginctl_smoke_plugin")
        self.assertIn("summary", payload)
        self.assertIn("plan", payload)
        self.assertIn("results", payload)
        self.assertIn("errors", payload)
        self.assertEqual(payload["errors"], [])
        self.assertTrue(payload["results"])
        first = payload["results"][0]
        for key in ["node", "role", "status", "local_sha256", "remote_sha256", "checksum_ok"]:
            self.assertIn(key, first)

    def test_cluster_distribute_execute_json_reports_checksum_failure(self) -> None:
        fake = FakeRemoteExecutor(mismatch_checksum_for="dn001")
        with patch("plugin_ctl.cli.ScpSshRemoteExecutor", return_value=fake):
            code, output = self._run(
                [
                    "--root",
                    str(self.root),
                    "cluster",
                    "distribute",
                    "--execute",
                    "-f",
                    str(self.cluster_file),
                    "pluginctl_smoke_plugin",
                    "--json",
                ]
            )

        self.assertEqual(code, 1)
        payload = json.loads(output)
        self.assertGreater(payload["summary"]["checksum_failed"], 0)
        self.assertTrue(payload["errors"])

    def test_cluster_distribute_dry_run_reports_missing_payload_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            (root / "src" / "plugin_ctl").mkdir(parents=True)
            (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
            manifest_dir = root / "catalog" / "plugins"
            manifest_dir.mkdir(parents=True)
            (manifest_dir / "broken.yml").write_text(
                """
plugin_id: broken
name: Broken
version: 0.1.0
description: Missing payload sample.
database: OpenTenBase
targets:
  cn: true
  dn: true
distributed:
  required_roles:
    - coordinator
payload:
  source_root: payload
  install_sql: payload/missing.sql
  verify_sql: payload/missing_verify.sql
  smoke_sql: payload/missing_verify.sql
  installed_probe: SELECT 1;
""",
                encoding="utf-8",
            )

            code, output = self._run(
                [
                    "--root",
                    str(root),
                    "cluster",
                    "distribute",
                    "--dry-run",
                    "-f",
                    str(self.cluster_file),
                    "broken",
                    "--json",
                ]
            )

        self.assertEqual(code, 1)
        payload = json.loads(output)
        self.assertEqual(payload["mode"], "dry-run")
        self.assertTrue(any("payload file missing" in error for error in payload["errors"]))

class FakeRemoteExecutor:
    def __init__(self, *, mismatch_checksum_for: str = "") -> None:
        self.mismatch_checksum_for = mismatch_checksum_for
        self.copies: list[tuple[str, str, str]] = []
        self.remote_hashes: dict[tuple[str, str], str] = {}

    def run(self, node: ClusterNode, argv: list[str]) -> RemoteCommandResult:
        return RemoteCommandResult(node=node.name, argv=tuple(argv), returncode=0, stdout="", stderr="")

    def copy_file(self, node: ClusterNode, local_path: Path, remote_path: str) -> RemoteCommandResult:
        self.copies.append((node.name, str(local_path), remote_path))
        self.remote_hashes[(node.name, remote_path)] = sha256(local_path.read_bytes()).hexdigest()
        return RemoteCommandResult(node=node.name, argv=("scp",), returncode=0, stdout="", stderr="")

    def sha256_file(self, node: ClusterNode, remote_path: str) -> RemoteCommandResult:
        digest = self.remote_hashes[(node.name, remote_path)]
        if node.name == self.mismatch_checksum_for:
            digest = "0" * 64
        return RemoteCommandResult(
            node=node.name,
            argv=("sha256sum", remote_path),
            returncode=0,
            stdout=f"{digest}  {remote_path}\n",
            stderr="",
        )


if __name__ == "__main__":
    unittest.main()

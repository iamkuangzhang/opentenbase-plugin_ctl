from __future__ import annotations

import io
import json
import os
import subprocess
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
name = "main-flow"

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


class FakeRemoteExecutor:
    def __init__(self) -> None:
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
        return RemoteCommandResult(
            node=node.name,
            argv=("sha256sum", remote_path),
            returncode=0,
            stdout=f"{digest}  {remote_path}\n",
            stderr="",
        )


class MainFlowCliTest(unittest.TestCase):
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

    def test_check_aggregates_lint_plan_precheck_and_diagnose(self) -> None:
        with patch("plugin_ctl.cli.OpenTenBaseRuntime", return_value=FakeLocalRuntime()):
            code, output = self._run(["--root", str(self.root), "check", "pluginctl_smoke_plugin"])

        self.assertEqual(code, 0)
        self.assertIn("== lint ==", output)
        self.assertIn("== plan ==", output)
        self.assertIn("== precheck ==", output)
        self.assertIn("== diagnose ==", output)
        self.assertIn("Result: OK", output)

    def test_check_json_has_stable_keys(self) -> None:
        with patch("plugin_ctl.cli.OpenTenBaseRuntime", return_value=FakeLocalRuntime()):
            code, output = self._run(["--root", str(self.root), "check", "pluginctl_smoke_plugin", "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["plugin_id"], "pluginctl_smoke_plugin")
        self.assertTrue(payload["ok"])
        for key in ["lint", "plan", "precheck", "diagnose", "errors"]:
            self.assertIn(key, payload)

    def test_check_path_auto_adds_plugin_without_polluting_json(self) -> None:
        catalog_file = Path(self.tempdir.name) / "catalog.json"
        plugin_parent = Path(self.tempdir.name) / "plugins"
        plugin_dir = plugin_parent / "path_check_plugin"
        with patch.dict(os.environ, {"PLUGIN_CTL_CATALOG_FILE": str(catalog_file)}):
            self.assertEqual(
                self._run(["--root", str(self.root), "dev", "init", "path_check_plugin", "--dir", str(plugin_parent)])[0],
                0,
            )
            with patch("plugin_ctl.cli.OpenTenBaseRuntime", return_value=FakeLocalRuntime()):
                code, output = self._run(["--root", str(self.root), "check", str(plugin_dir), "--json"])

            self.assertEqual(code, 0)
            payload = json.loads(output)
            self.assertEqual(payload["plugin_id"], "path_check_plugin")
            self.assertTrue(payload["ok"])

    def test_check_returns_nonzero_for_blocking_lint_failure(self) -> None:
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
description: Missing files.
database: OpenTenBase
targets:
  cn: true
payload:
  source_root: payload
  install_sql: payload/install.sql
  verify_sql: payload/verify.sql
  smoke_sql: payload/verify.sql
  installed_probe: SELECT 1;
""",
                encoding="utf-8",
            )
            with patch("plugin_ctl.cli.OpenTenBaseRuntime", return_value=FakeLocalRuntime()):
                code, output = self._run(["--root", str(root), "check", "broken", "--json"])

        self.assertEqual(code, 1)
        payload = json.loads(output)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["errors"])

    def test_deploy_with_cluster_file_dry_run_previews_physical_distribution(self) -> None:
        with patch("plugin_ctl.cli.ScpSshRemoteExecutor", side_effect=AssertionError("dry-run must not create executor")):
            code, output = self._run(
                ["--root", str(self.root), "deploy", "pluginctl_smoke_plugin", "-f", str(self.cluster_file), "--dry-run"]
            )

        self.assertEqual(code, 0)
        self.assertIn("Mode: dry-run", output)
        self.assertIn("Activate: skipped", output)
        self.assertIn("CREATE EXTENSION: not executed", output)
        self.assertIn("Result: OK", output)

    def test_deploy_with_cluster_file_defaults_to_physical_distribution(self) -> None:
        fake = FakeRemoteExecutor()
        with patch("plugin_ctl.cli.ScpSshRemoteExecutor", return_value=fake):
            code, output = self._run(
                ["--root", str(self.root), "deploy", "pluginctl_smoke_plugin", "-f", str(self.cluster_file)]
            )

        self.assertEqual(code, 0)
        self.assertTrue(fake.copies)
        self.assertIn("Mode: execute", output)
        self.assertIn("Physical distribution: executed", output)
        self.assertIn("Activate: skipped", output)
        self.assertIn("CREATE EXTENSION: not executed", output)
        self.assertIn("Result: OK", output)

    def test_deploy_path_auto_adds_then_distributes(self) -> None:
        catalog_file = Path(self.tempdir.name) / "catalog.json"
        plugin_parent = Path(self.tempdir.name) / "plugins"
        plugin_dir = plugin_parent / "path_deploy_plugin"
        fake = FakeRemoteExecutor()

        with patch.dict(os.environ, {"PLUGIN_CTL_CATALOG_FILE": str(catalog_file)}):
            self.assertEqual(
                self._run(["--root", str(self.root), "dev", "init", "path_deploy_plugin", "--dir", str(plugin_parent)])[0],
                0,
            )
            with patch("plugin_ctl.cli.ScpSshRemoteExecutor", return_value=fake):
                code, output = self._run(["--root", str(self.root), "deploy", str(plugin_dir), "-f", str(self.cluster_file)])

            self.assertEqual(code, 0)
            self.assertTrue(fake.copies)
            self.assertIn("Registered plugin: path_deploy_plugin", output)
            self.assertIn("Plugin: path_deploy_plugin", output)
            self.assertIn("Result: OK", output)

    def test_deploy_uses_default_cluster_config_when_file_is_omitted(self) -> None:
        fake = FakeRemoteExecutor()
        with patch.dict(os.environ, {"OPENTENBASE_PLUGINCTL_CLUSTER_FILE": str(self.cluster_file)}):
            with patch("plugin_ctl.cli.ScpSshRemoteExecutor", return_value=fake):
                code, output = self._run(["--root", str(self.root), "deploy", "pluginctl_smoke_plugin"])

        self.assertEqual(code, 0)
        self.assertTrue(fake.copies)
        self.assertIn("Mode: execute", output)
        self.assertIn("Physical distribution: executed", output)

    def test_deploy_requires_cluster_config_for_execution(self) -> None:
        missing_default = str(Path(self.tempdir.name) / "missing.toml")
        with patch.dict(os.environ, {"OPENTENBASE_PLUGINCTL_CLUSTER_FILE": missing_default}):
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    main(["--root", str(self.root), "deploy", "pluginctl_smoke_plugin"])

    def test_deploy_requires_cluster_config_even_for_preview(self) -> None:
        missing_default = str(Path(self.tempdir.name) / "missing.toml")
        with patch.dict(os.environ, {"OPENTENBASE_PLUGINCTL_CLUSTER_FILE": missing_default}):
            with patch("plugin_ctl.cli.OpenTenBaseRuntime", side_effect=AssertionError("deploy must not use local SQL runtime")):
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        main(["--root", str(self.root), "deploy", "pluginctl_smoke_plugin"])

    def test_deploy_rejects_removed_execute_flag(self) -> None:
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                main(
                    [
                        "--root",
                        str(self.root),
                        "deploy",
                        "pluginctl_smoke_plugin",
                        "-f",
                        str(self.cluster_file),
                        "--execute",
                    ]
                )


if __name__ == "__main__":
    unittest.main()

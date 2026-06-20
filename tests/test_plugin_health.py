from __future__ import annotations

from hashlib import sha256
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plugin_ctl.activation import CoordinatorSqlResult
from plugin_ctl.catalog import Catalog
from plugin_ctl.cluster import ClusterNode
from plugin_ctl.plugin_health import build_plugin_health_report, health_report_json
from plugin_ctl.runtime.opentenbase import RemoteCommandResult
from plugin_ctl.state_store import StateStore


CLUSTER_TOML = """
[cluster]
name = "health-test"

[[nodes]]
name = "cn001"
role = "cn"
host = "127.0.0.1"
ssh_port = 22
db_port = 30004
ssh_user = "opentenbase"
db_user = "opentenbase"
database = "postgres"
lib_dir = "/opt/otb/lib"
extension_dir = "/opt/otb/share/extension"

[[nodes]]
name = "dn001"
role = "dn"
host = "127.0.0.1"
ssh_port = 22
db_port = 20008
ssh_user = "opentenbase"
db_user = "opentenbase"
database = "postgres"
lib_dir = "/opt/otb/lib"
extension_dir = "/opt/otb/share/extension"
"""


class FakeRuntime:
    container = "fake"
    host = "127.0.0.1"
    port = 30004
    user = "opentenbase"
    database = "postgres"

    def __init__(self, *, removed: bool = False) -> None:
        self.removed = removed

    def run_sql(self, sql: str) -> subprocess.CompletedProcess[str]:
        if "removed" in sql:
            return subprocess.CompletedProcess(["psql"], 0, "removed\n" if self.removed else "present\n", "")
        return subprocess.CompletedProcess(["psql"], 0, "ok\n", "")

    def exec(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(args), 0, "", "")


class FakeSqlExecutor:
    def __init__(self, *, installed: bool = False) -> None:
        self.installed = installed

    def run_sql(self, node: ClusterNode, sql: str) -> CoordinatorSqlResult:
        if sql.strip() == "SELECT 1;":
            return CoordinatorSqlResult(node.name, sql, 0, "1\n", "")
        if "pg_extension" in sql:
            return CoordinatorSqlResult(node.name, sql, 0, "0.1.0\n" if self.installed else "", "")
        if "pg_prepared_xacts" in sql:
            return CoordinatorSqlResult(node.name, sql, 0, "", "")
        return CoordinatorSqlResult(node.name, sql, 0, "", "")


class FakeRemoteExecutor:
    def __init__(self, plugin_dir: Path, *, missing: bool = False) -> None:
        self.plugin_dir = plugin_dir
        self.missing = missing

    def run(self, node: ClusterNode, argv: list[str]) -> RemoteCommandResult:
        return RemoteCommandResult(node.name, tuple(argv), 0, "", "")

    def copy_file(self, node: ClusterNode, local_path: Path, remote_path: str) -> RemoteCommandResult:
        return RemoteCommandResult(node.name, ("scp",), 0, "", "")

    def sha256_file(self, node: ClusterNode, remote_path: str) -> RemoteCommandResult:
        if self.missing:
            return RemoteCommandResult(node.name, ("sha256sum", remote_path), 1, "", "missing")
        matches = list(self.plugin_dir.rglob(Path(remote_path).name))
        digest = sha256(matches[0].read_bytes()).hexdigest() if matches else ""
        return RemoteCommandResult(node.name, ("sha256sum", remote_path), 0 if digest else 1, f"{digest}  {remote_path}\n" if digest else "", "")


def write_extension_plugin(parent: Path, plugin_id: str = "health_demo", *, control_version: str = "0.1.0", rollback: bool = True) -> Path:
    plugin_dir = parent / plugin_id
    sql_dir = plugin_dir / "sql"
    sql_dir.mkdir(parents=True)
    (plugin_dir / f"{plugin_id}.control").write_text(
        f"comment = '{plugin_id}'\ndefault_version = '{control_version}'\nrelocatable = true\n",
        encoding="utf-8",
    )
    (sql_dir / f"{plugin_id}--0.1.0.sql").write_text(f"CREATE SCHEMA IF NOT EXISTS {plugin_id};\n", encoding="utf-8")
    (sql_dir / "verify.sql").write_text("SELECT 'ok';\n", encoding="utf-8")
    if rollback:
        (sql_dir / "rollback.sql").write_text(f"DROP SCHEMA IF EXISTS {plugin_id} CASCADE;\n", encoding="utf-8")
    rollback_line = "  rollback_sql: sql/rollback.sql\n" if rollback else ""
    (plugin_dir / "manifest.yml").write_text(
        f"""
plugin_id: {plugin_id}
name: Health Demo
version: 0.1.0
description: Health check test plugin.
extension: {plugin_id}
database: OpenTenBase
targets:
  cn: true
  dn: true
distributed:
  required_roles:
    - coordinator
  probe_strategy: coordinator
payload:
  source_root: .
  extension_name: {plugin_id}
  install_sql: sql/{plugin_id}--0.1.0.sql
  verify_sql: sql/verify.sql
  smoke_sql: sql/verify.sql
{rollback_line}  installed_probe: SELECT extversion FROM pg_extension WHERE extname = '{plugin_id}';
  removed_probe: SELECT 'removed';
""",
        encoding="utf-8",
    )
    return plugin_dir


class PluginHealthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tempdir.name)
        self.catalog_file = self.tmp / "catalog.json"
        self.state_file = self.tmp / "state.json"
        self.archive_file = self.tmp / "archive.json"
        self.env = {
            "PLUGIN_CTL_CATALOG_FILE": str(self.catalog_file),
            "PLUGIN_CTL_STATE_FILE": str(self.state_file),
            "PLUGIN_CTL_ARCHIVE_FILE": str(self.archive_file),
            "OPENTENBASE_PLUGINCTL_CLUSTER_FILE": str(self.tmp / "missing-cluster.toml"),
        }

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def build_report(self, target: str, *, installed: bool = False, removed: bool = False, remote_missing: bool = False):
        plugin_dir = self.tmp / "health_demo"
        return build_plugin_health_report(
            self.tmp,
            target,
            runtime=FakeRuntime(removed=removed),
            sql_executor=FakeSqlExecutor(installed=installed),
            remote_executor=FakeRemoteExecutor(plugin_dir, missing=remote_missing),
        )

    def test_input_directory_manifest_and_catalog_id(self) -> None:
        plugin_dir = write_extension_plugin(self.tmp)
        with patch.dict(os.environ, self.env):
            by_dir = self.build_report(str(plugin_dir))
            by_manifest = self.build_report(str(plugin_dir / "manifest.yml"))
            Catalog(root=self.tmp).add_user_plugin(plugin_dir)
            by_id = self.build_report("health_demo")

        self.assertEqual(by_dir.final_status, "NEW")
        self.assertEqual(by_manifest.plugin_id, "health_demo")
        self.assertEqual(by_id.final_status, "READY")

    def test_no_cluster_config_skips_distributed_checks(self) -> None:
        plugin_dir = write_extension_plugin(self.tmp)
        with patch.dict(os.environ, self.env):
            Catalog(root=self.tmp).add_user_plugin(plugin_dir)
            report = self.build_report("health_demo")

        payload = health_report_json(report)
        self.assertEqual(payload["final_status"], "READY")
        self.assertTrue(any(item["name"] == "cluster.toml" and item["status"] == "SKIP" for item in payload["sections"][3]["items"]))

    def test_cluster_summary_and_remote_file_checks_are_merged(self) -> None:
        plugin_dir = write_extension_plugin(self.tmp)
        cluster_file = self.tmp / "cluster.toml"
        cluster_file.write_text(CLUSTER_TOML, encoding="utf-8")
        env = {**self.env, "OPENTENBASE_PLUGINCTL_CLUSTER_FILE": str(cluster_file)}
        with patch.dict(os.environ, env):
            Catalog(root=self.tmp).add_user_plugin(plugin_dir)
            report = self.build_report("health_demo", installed=False)

        payload = health_report_json(report)
        self.assertEqual(payload["final_status"], "DEPLOYED")
        self.assertTrue(any("CN=1, DN=1" in item["detail"] for item in payload["sections"][3]["items"]))
        self.assertTrue(any(item["name"] == "remote_files" and item["status"] == "OK" for item in payload["sections"][4]["items"]))

    def test_registered_plugin_runs_verify_sql(self) -> None:
        plugin_dir = write_extension_plugin(self.tmp)
        cluster_file = self.tmp / "cluster.toml"
        cluster_file.write_text(CLUSTER_TOML, encoding="utf-8")
        env = {**self.env, "OPENTENBASE_PLUGINCTL_CLUSTER_FILE": str(cluster_file)}
        with patch.dict(os.environ, env):
            Catalog(root=self.tmp).add_user_plugin(plugin_dir)
            report = self.build_report("health_demo", installed=True)

        self.assertEqual(report.final_status, "REGISTERED")
        payload = health_report_json(report)
        self.assertTrue(any(item["name"] == "verify_sql" and item["status"] == "OK" for item in payload["sections"][5]["items"]))

    def test_successful_rollback_and_removed_probe_reports_removed(self) -> None:
        plugin_dir = write_extension_plugin(self.tmp)
        with patch.dict(os.environ, self.env):
            Catalog(root=self.tmp).add_user_plugin(plugin_dir)
            StateStore(self.tmp).append("health_demo", "rollback", True, "rollback passed")
            report = self.build_report("health_demo", removed=True)

        self.assertEqual(report.final_status, "REMOVED")

    def test_deployed_files_override_old_removed_state(self) -> None:
        plugin_dir = write_extension_plugin(self.tmp)
        cluster_file = self.tmp / "cluster.toml"
        cluster_file.write_text(CLUSTER_TOML, encoding="utf-8")
        env = {**self.env, "OPENTENBASE_PLUGINCTL_CLUSTER_FILE": str(cluster_file)}
        with patch.dict(os.environ, env):
            Catalog(root=self.tmp).add_user_plugin(plugin_dir)
            StateStore(self.tmp).append("health_demo", "rollback", True, "rollback passed")
            report = self.build_report("health_demo", installed=False, removed=True)

        self.assertEqual(report.final_status, "DEPLOYED")

    def test_control_version_mismatch_is_broken(self) -> None:
        plugin_dir = write_extension_plugin(self.tmp, control_version="9.9.9")
        with patch.dict(os.environ, self.env):
            Catalog(root=self.tmp).add_user_plugin(plugin_dir)
            report = self.build_report("health_demo")

        self.assertEqual(report.final_status, "BROKEN")
        self.assertFalse(health_report_json(report)["ok"])

    def test_missing_rollback_is_warning_not_failure(self) -> None:
        plugin_dir = write_extension_plugin(self.tmp, rollback=False)
        with patch.dict(os.environ, self.env):
            Catalog(root=self.tmp).add_user_plugin(plugin_dir)
            report = self.build_report("health_demo")

        self.assertEqual(report.final_status, "READY")
        self.assertTrue(any("rollback_sql" in warning for warning in health_report_json(report)["warnings"]))


if __name__ == "__main__":
    unittest.main()

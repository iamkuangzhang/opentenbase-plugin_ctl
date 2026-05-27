from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from plugin_ctl.cli import cmd_plugin_status
from plugin_ctl.manifest import PluginManifest
from plugin_ctl.plugin_governance import governance_status, governance_status_json, plugin_checks
from plugin_ctl.state_store import StateStore


class GovernanceRuntime:
    def __init__(self, probe_results: dict[str, subprocess.CompletedProcess[str]] | None = None) -> None:
        self.probe_results = probe_results or {}

    def run_sql(self, sql: str) -> subprocess.CompletedProcess[str]:
        if "SELECT DISTINCT node_type" in sql:
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="C\nD\n", stderr="")
        if "FROM pgxc_node" in sql:
            return subprocess.CompletedProcess(
                args=["psql"],
                returncode=0,
                stdout="cn001|C|127.0.0.1|30004\ndn001|D|127.0.0.1|40004\n",
                stderr="",
            )
        return self.probe_results.get(
            sql,
            subprocess.CompletedProcess(args=["psql"], returncode=1, stdout="", stderr="probe failed"),
        )

    def run_sql_at(self, host: str, port: int, sql: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="1\n", stderr="")


def make_manifest(root: Path, *, plugin_id: str, installed_probe: str | None, distributed: dict | None) -> PluginManifest:
    manifest_path = root / "platform" / "catalog" / "plugins" / f"{plugin_id}.yml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("", encoding="utf-8")

    install_sql = root / "platform" / "payload" / plugin_id / "install.sql"
    verify_sql = root / "platform" / "payload" / plugin_id / "verify.sql"
    rollback_sql = root / "platform" / "payload" / plugin_id / "rollback.sql"
    rollback_sql.parent.mkdir(parents=True, exist_ok=True)
    install_sql.write_text("SELECT 1;", encoding="utf-8")
    verify_sql.write_text("SELECT 1;", encoding="utf-8")
    rollback_sql.write_text("SELECT 1;", encoding="utf-8")

    payload = {
        "source_root": f"payload/{plugin_id}",
        "install_sql": f"payload/{plugin_id}/install.sql",
        "verify_sql": f"payload/{plugin_id}/verify.sql",
        "smoke_sql": f"payload/{plugin_id}/verify.sql",
        "rollback_sql": f"payload/{plugin_id}/rollback.sql",
        "removed_probe": "SELECT 'removed';",
    }
    if installed_probe:
        payload["installed_probe"] = installed_probe

    return PluginManifest(
        plugin_id=plugin_id,
        name=plugin_id,
        version="1.0.0",
        description="test plugin",
        database="OpenTenBase",
        targets={"cn": True, "dn": True},
        payload=payload,
        distributed=distributed or {},
        path=manifest_path,
    )


class PluginGovernanceTest(unittest.TestCase):
    def test_plugin_check_ready_when_manifest_probe_and_distributed_are_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = make_manifest(
                root,
                plugin_id="ready_plugin",
                installed_probe="SELECT ready.version();",
                distributed={"required_roles": ["coordinator"], "probe_strategy": "coordinator"},
            )
            runtime = GovernanceRuntime(
                {"SELECT ready.version();": subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="1.0.0\n", stderr="")}
            )

            checks = plugin_checks(root, runtime, manifest)

            self.assertFalse([check for check in checks if check.status == "fail"])
            self.assertEqual(next(check for check in checks if check.check == "installed_state").detail, "installed: 1.0.0")
            self.assertEqual(next(check for check in checks if check.check == "can_verify").status, "pass")

    def test_missing_distributed_is_warning_not_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = make_manifest(root, plugin_id="legacy_plugin", installed_probe="SELECT legacy.version();", distributed=None)
            runtime = GovernanceRuntime(
                {"SELECT legacy.version();": subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="1.0.0\n", stderr="")}
            )

            checks = plugin_checks(root, runtime, manifest)
            distributed_check = next(check for check in checks if check.check == "distributed")

            self.assertEqual(distributed_check.status, "warn")
            self.assertFalse([check for check in checks if check.status == "fail"])

    def test_installed_probe_failure_reports_not_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = make_manifest(
                root,
                plugin_id="absent_plugin",
                installed_probe="SELECT absent.version();",
                distributed={"required_roles": ["coordinator"], "probe_strategy": "coordinator"},
            )
            runtime = GovernanceRuntime()

            checks = plugin_checks(root, runtime, manifest)

            self.assertIn("not_installed", next(check for check in checks if check.check == "installed_state").detail)
            self.assertEqual(next(check for check in checks if check.check == "can_verify").status, "warn")

    def test_missing_installed_probe_is_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = make_manifest(
                root,
                plugin_id="unknown_plugin",
                installed_probe=None,
                distributed={"required_roles": ["coordinator"], "probe_strategy": "coordinator"},
            )
            runtime = GovernanceRuntime()

            checks = plugin_checks(root, runtime, manifest)

            self.assertEqual(next(check for check in checks if check.check == "installed_probe").status, "warn")
            self.assertIn("unknown", next(check for check in checks if check.check == "installed_state").detail)

    def test_plugins_status_aggregates_lifecycle_state_and_json_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ready = make_manifest(
                root,
                plugin_id="ready_plugin",
                installed_probe="SELECT ready.version();",
                distributed={"required_roles": ["coordinator"], "probe_strategy": "coordinator"},
            )
            legacy = make_manifest(root, plugin_id="legacy_plugin", installed_probe=None, distributed=None)
            StateStore(root).append("ready_plugin", "deploy", True, "deploy ok")
            runtime = GovernanceRuntime(
                {"SELECT ready.version();": subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="1.0.0\n", stderr="")}
            )

            statuses = [governance_status(root, runtime, ready), governance_status(root, runtime, legacy)]
            payload = governance_status_json(statuses)

            self.assertEqual(payload[0]["plugin_id"], "ready_plugin")
            self.assertEqual(payload[0]["installed_state"], "installed")
            self.assertEqual(payload[0]["distributed_ready"], "yes")
            self.assertEqual(payload[1]["plugin_id"], "legacy_plugin")
            self.assertEqual(payload[1]["distributed_ready"], "warning")
            self.assertIn("last_deploy", payload[0])
            self.assertIn("notes", payload[1])

    def test_plugin_status_can_render_bilingual_human_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = make_manifest(
                root,
                plugin_id="ready_plugin",
                installed_probe="SELECT ready.version();",
                distributed={"required_roles": ["coordinator"], "probe_strategy": "coordinator"},
            )
            manifest_dir = root / "platform" / "catalog" / "plugins"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            (manifest_dir / "ready_plugin.yml").write_text(
                "\n".join(
                    [
                        "plugin_id: ready_plugin",
                        "name: Ready Plugin",
                        "version: 1.0.0",
                        "description: Ready plugin",
                        "database: OpenTenBase",
                        "targets:",
                        "  cn: true",
                        "  dn: true",
                        "distributed:",
                        "  required_roles:",
                        "    - coordinator",
                        "  probe_strategy: coordinator",
                        "payload:",
                        "  source_root: payload/ready_plugin",
                        "  install_sql: payload/ready_plugin/install.sql",
                        "  verify_sql: payload/ready_plugin/verify.sql",
                        "  rollback_sql: payload/ready_plugin/rollback.sql",
                        "  installed_probe: SELECT ready.version();",
                    ]
                ),
                encoding="utf-8",
            )
            runtime = GovernanceRuntime(
                {"SELECT ready.version();": subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="1.0.0\n", stderr="")}
            )

            with patch("plugin_ctl.cli.OpenTenBaseRuntime", return_value=runtime), patch("builtins.print") as mocked_print:
                result = cmd_plugin_status(root / "platform", "ready_plugin", lang="both")

            self.assertEqual(result, 0)
            output = mocked_print.call_args.args[0]
            self.assertIn("插件 / Plugin", output)
            self.assertIn("已安装 / installed", output)


if __name__ == "__main__":
    unittest.main()

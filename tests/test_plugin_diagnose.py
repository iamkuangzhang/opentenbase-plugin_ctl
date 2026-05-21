from pathlib import Path
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from datanexus.cli import cmd_plugin_diagnose, cmd_plugins_status
from datanexus.manifest import load_manifest
from datanexus.plugin_diagnose import diagnose_plugin, diagnosis_json


class DiagnoseRuntime:
    def __init__(
        self,
        *,
        probe_results: dict[str, subprocess.CompletedProcess[str]] | None = None,
        connection_ok: bool = True,
        roles_stdout: str = "C\nD\n",
        nodes_stdout: str = "cn001|C|127.0.0.1|30004\ndn001|D|127.0.0.1|40004\n",
        remote_tmp_ok: bool = True,
    ) -> None:
        self.probe_results = probe_results or {}
        self.connection_ok = connection_ok
        self.roles_stdout = roles_stdout
        self.nodes_stdout = nodes_stdout
        self.remote_tmp_ok = remote_tmp_ok

    def run_sql(self, sql: str) -> subprocess.CompletedProcess[str]:
        if sql == "SELECT 1;":
            return subprocess.CompletedProcess(args=["psql"], returncode=0 if self.connection_ok else 1, stdout="1\n" if self.connection_ok else "", stderr="" if self.connection_ok else "down")
        if sql == "SELECT version();":
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="OpenTenBase test\n", stderr="")
        if "SELECT DISTINCT node_type" in sql:
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout=self.roles_stdout, stderr="")
        if "FROM pgxc_node" in sql:
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout=self.nodes_stdout, stderr="")
        return self.probe_results.get(sql, subprocess.CompletedProcess(args=["psql"], returncode=1, stdout="", stderr="probe failed"))

    def run_sql_at(self, host: str, port: int, sql: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="1\n", stderr="")

    def exec(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=["docker", "exec", *args], returncode=0 if self.remote_tmp_ok else 1, stdout="", stderr="" if self.remote_tmp_ok else "not writable")


def write_manifest(
    platform_root: Path,
    plugin_id: str,
    *,
    installed_probe: str,
    include_distributed: bool = True,
    include_removed_probe: bool = True,
    include_rollback: bool = True,
    create_install_sql: bool = True,
) -> Path:
    manifest_dir = platform_root / "examples" / "plugins" / plugin_id
    payload_dir = platform_root / "payload" / plugin_id / "sql"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    payload_dir.mkdir(parents=True, exist_ok=True)
    if create_install_sql:
        (payload_dir / "install.sql").write_text("SELECT 1;", encoding="utf-8")
    (payload_dir / "verify.sql").write_text("SELECT 1;", encoding="utf-8")
    if include_rollback:
        (payload_dir / "rollback.sql").write_text("SELECT 1;", encoding="utf-8")

    lines = [
        f"plugin_id: {plugin_id}",
        "name: Diagnose Plugin",
        "version: 0.1.0",
        "description: diagnose fixture",
        "database: OpenTenBase",
        "targets:",
        "  cn: true",
        "  dn: true",
    ]
    if include_distributed:
        lines.extend(
            [
                "distributed:",
                "  required_roles:",
                "    - coordinator",
                "  probe_strategy: coordinator",
            ]
        )
    lines.extend(
        [
            "payload:",
            f"  source_root: payload/{plugin_id}",
            f"  install_sql: payload/{plugin_id}/sql/install.sql",
            f"  verify_sql: payload/{plugin_id}/sql/verify.sql",
            f"  smoke_sql: payload/{plugin_id}/sql/verify.sql",
            f"  installed_probe: {installed_probe}",
        ]
    )
    if include_rollback:
        lines.append(f"  rollback_sql: payload/{plugin_id}/sql/rollback.sql")
    if include_removed_probe:
        lines.append("  removed_probe: SELECT 'removed';")

    manifest_path = manifest_dir / "manifest.yml"
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest_path


class PluginDiagnoseTest(unittest.TestCase):
    def test_diagnose_installed_plugin_recommends_verify(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "platform"
            manifest = load_manifest(write_manifest(root, "installed_plugin", installed_probe="SELECT installed_plugin.version();"))
            runtime = DiagnoseRuntime(
                probe_results={"SELECT installed_plugin.version();": subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="1.0.0\n", stderr="")},
            )

            diagnosis = diagnose_plugin(root, runtime, manifest)

            self.assertTrue(diagnosis.package_ok)
            self.assertTrue(diagnosis.env_ready)
            self.assertEqual(diagnosis.installed_state, "installed")
            self.assertEqual(diagnosis.next_action, "verify")

    def test_diagnose_not_installed_plugin_recommends_deploy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "platform"
            manifest = load_manifest(write_manifest(root, "fresh_plugin", installed_probe="SELECT fresh_plugin.version();"))
            runtime = DiagnoseRuntime(
                probe_results={"SELECT fresh_plugin.version();": subprocess.CompletedProcess(args=["psql"], returncode=1, stdout="", stderr="missing")},
            )

            diagnosis = diagnose_plugin(root, runtime, manifest)

            self.assertEqual(diagnosis.installed_state, "not_installed")
            self.assertEqual(diagnosis.next_action, "deploy")

    def test_diagnose_lint_failure_recommends_fix_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "platform"
            manifest = load_manifest(write_manifest(root, "broken_plugin", installed_probe="SELECT broken_plugin.version();", create_install_sql=False))
            runtime = DiagnoseRuntime(
                probe_results={"SELECT broken_plugin.version();": subprocess.CompletedProcess(args=["psql"], returncode=1, stdout="", stderr="missing")},
            )

            diagnosis = diagnose_plugin(root, runtime, manifest)

            self.assertFalse(diagnosis.package_ok)
            self.assertEqual(diagnosis.next_action, "fix_manifest")

    def test_diagnose_precheck_failure_recommends_fix_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "platform"
            manifest = load_manifest(write_manifest(root, "env_plugin", installed_probe="SELECT env_plugin.version();"))
            runtime = DiagnoseRuntime(
                connection_ok=False,
                probe_results={"SELECT env_plugin.version();": subprocess.CompletedProcess(args=["psql"], returncode=1, stdout="", stderr="missing")},
            )

            diagnosis = diagnose_plugin(root, runtime, manifest)

            self.assertFalse(diagnosis.env_ready)
            self.assertEqual(diagnosis.next_action, "fix_environment")

    def test_diagnose_json_shape_contains_aggregation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "platform"
            manifest = load_manifest(write_manifest(root, "json_plugin", installed_probe="SELECT json_plugin.version();"))
            runtime = DiagnoseRuntime(
                probe_results={"SELECT json_plugin.version();": subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="1.0.0\n", stderr="")},
            )

            payload = diagnosis_json(diagnose_plugin(root, runtime, manifest))

            self.assertIn("lint", payload)
            self.assertIn("plan", payload)
            self.assertIn("precheck", payload)
            self.assertIn("package_ok", payload)
            self.assertIn("conclusion", payload)

    def test_cmd_plugin_diagnose_json_prints_machine_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "platform"
            manifest = load_manifest(write_manifest(root, "cmd_plugin", installed_probe="SELECT cmd_plugin.version();"))
            runtime = DiagnoseRuntime(
                probe_results={"SELECT cmd_plugin.version();": subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="1.0.0\n", stderr="")},
            )

            with patch("datanexus.cli.OpenTenBaseRuntime", return_value=runtime), patch("builtins.print") as mocked_print:
                result = cmd_plugin_diagnose(root, "cmd_plugin", as_json=True)

            self.assertEqual(result, 0)
            payload = json.loads(mocked_print.call_args.args[0])
            self.assertEqual(payload["plugin_id"], "cmd_plugin")
            self.assertIn("package_ok", payload)
            self.assertIn("next_action", payload)

    def test_cmd_plugins_status_json_is_concise(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "platform"
            write_manifest(root, "ready_plugin", installed_probe="SELECT ready_plugin.version();")
            write_manifest(root, "fresh_plugin", installed_probe="SELECT fresh_plugin.version();")
            runtime = DiagnoseRuntime(
                probe_results={
                    "SELECT ready_plugin.version();": subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="1.0.0\n", stderr=""),
                    "SELECT fresh_plugin.version();": subprocess.CompletedProcess(args=["psql"], returncode=1, stdout="", stderr="missing"),
                }
            )

            with patch("datanexus.cli.OpenTenBaseRuntime", return_value=runtime), patch("builtins.print") as mocked_print:
                result = cmd_plugins_status(root, as_json=True)

            self.assertEqual(result, 0)
            payload = json.loads(mocked_print.call_args.args[0])
            self.assertEqual(payload[0]["plugin_id"], "fresh_plugin")
            self.assertIn("package_ok", payload[0])
            self.assertIn("env_ready", payload[0])
            self.assertIn("installed_state", payload[0])
            self.assertIn("next_action", payload[0])
            self.assertIn("risk", payload[0])


if __name__ == "__main__":
    unittest.main()

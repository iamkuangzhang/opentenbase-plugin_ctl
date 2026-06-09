from pathlib import Path
import subprocess
import tempfile
import unittest

from plugin_ctl.manifest import load_manifest
from plugin_ctl.plugin_package import (
    lint_items_json,
    lint_manifest_path,
    plugin_precheck,
    plugin_plan,
    plugin_plan_json,
    precheck_items_json,
)


class ProbeRuntime:
    def __init__(self, *, returncode: int = 0, stdout: str = "1.0.0\n", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.sql_calls: list[str] = []

    def run_sql(self, sql: str) -> subprocess.CompletedProcess[str]:
        self.sql_calls.append(sql)
        return subprocess.CompletedProcess(args=["psql"], returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)


class PrecheckRuntime:
    def __init__(
        self,
        *,
        connection_ok: bool = True,
        roles_stdout: str = "C\nD\n",
        installed_returncode: int = 1,
        installed_stdout: str = "",
        installed_stderr: str = "missing",
        remote_tmp_ok: bool = True,
        default_group_stdout: str = "default_group\n",
        sharding_map_stdout: str = "16\n",
    ) -> None:
        self.connection_ok = connection_ok
        self.roles_stdout = roles_stdout
        self.installed_returncode = installed_returncode
        self.installed_stdout = installed_stdout
        self.installed_stderr = installed_stderr
        self.remote_tmp_ok = remote_tmp_ok
        self.default_group_stdout = default_group_stdout
        self.sharding_map_stdout = sharding_map_stdout
        self.sql_calls: list[str] = []
        self.exec_calls: list[tuple[str, ...]] = []

    def run_sql(self, sql: str) -> subprocess.CompletedProcess[str]:
        self.sql_calls.append(sql)
        if sql == "SELECT 1;":
            return subprocess.CompletedProcess(args=["psql"], returncode=0 if self.connection_ok else 1, stdout="1\n" if self.connection_ok else "", stderr="" if self.connection_ok else "down")
        if sql == "SELECT version();":
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="OpenTenBase test\n", stderr="")
        if "FROM pgxc_group" in sql:
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout=self.default_group_stdout, stderr="")
        if "FROM pgxc_shard_map" in sql:
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout=self.sharding_map_stdout, stderr="")
        if "SELECT DISTINCT node_type" in sql:
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout=self.roles_stdout, stderr="")
        if "FROM pgxc_node" in sql:
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="cn001|C|127.0.0.1|30004\ndn001|D|127.0.0.1|40004\n", stderr="")
        return subprocess.CompletedProcess(
            args=["psql"],
            returncode=self.installed_returncode,
            stdout=self.installed_stdout,
            stderr=self.installed_stderr,
        )

    def run_sql_at(self, host: str, port: int, sql: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="1\n", stderr="")

    def exec(self, *args: str) -> subprocess.CompletedProcess[str]:
        self.exec_calls.append(args)
        return subprocess.CompletedProcess(args=["docker", "exec", *args], returncode=0 if self.remote_tmp_ok else 1, stdout="", stderr="" if self.remote_tmp_ok else "not writable")


def write_plugin(
    platform_root: Path,
    plugin_id: str = "lint_plugin",
    *,
    include_distributed: bool = True,
    include_rollback: bool = True,
    include_removed_probe: bool = True,
    include_installed_probe: bool = True,
    create_files: bool = True,
    install_sql: str = "CREATE SCHEMA IF NOT EXISTS lint_plugin;",
) -> Path:
    manifest_dir = platform_root / "examples" / "plugins" / plugin_id
    payload_dir = platform_root / "payload" / plugin_id
    manifest_dir.mkdir(parents=True, exist_ok=True)
    if create_files:
        (payload_dir / "sql").mkdir(parents=True, exist_ok=True)
        (payload_dir / "sql" / "install.sql").write_text(install_sql, encoding="utf-8")
        (payload_dir / "sql" / "verify.sql").write_text("SELECT 1;", encoding="utf-8")
        (payload_dir / "sql" / "rollback.sql").write_text("DROP SCHEMA IF EXISTS lint_plugin;", encoding="utf-8")

    lines = [
        f"plugin_id: {plugin_id}",
        "name: Lint Plugin",
        "version: 0.1.0",
        "description: Test plugin",
        "database: OpenTenBase",
        "targets:",
        "  cn: true",
        "  dn: false",
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
        ]
    )
    if include_rollback:
        lines.append(f"  rollback_sql: payload/{plugin_id}/sql/rollback.sql")
    if include_installed_probe:
        lines.append("  installed_probe: SELECT lint_plugin.version();")
    if include_removed_probe:
        lines.append("  removed_probe: SELECT 'removed';")

    manifest_path = manifest_dir / "manifest.yml"
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest_path


class PluginPackageLintTest(unittest.TestCase):
    def test_lint_complete_manifest_passes_without_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = write_plugin(Path(tmpdir) / "platform")

            items = lint_manifest_path(manifest_path)

            self.assertFalse([item for item in items if item.status == "fail"])
            self.assertIn({"plugin_id": "lint_plugin", "check": "distributed.required_roles", "status": "pass", "detail": "coordinator"}, lint_items_json(items))

    def test_lint_missing_top_level_field_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "platform" / "examples" / "plugins" / "bad_plugin" / "manifest.yml"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(
                "\n".join(
                    [
                        "plugin_id: bad_plugin",
                        "name: Bad Plugin",
                        "version: 0.1.0",
                        "database: OpenTenBase",
                        "targets:",
                        "  cn: true",
                        "payload: {}",
                    ]
                ),
                encoding="utf-8",
            )

            items = lint_manifest_path(manifest_path)

            self.assertEqual(next(item for item in items if item.check == "field:description").status, "fail")

    def test_lint_missing_payload_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = write_plugin(Path(tmpdir) / "platform", create_files=False)

            items = lint_manifest_path(manifest_path)

            self.assertEqual(next(item for item in items if item.check == "install_sql").status, "fail")
            self.assertEqual(next(item for item in items if item.check == "source_root").status, "fail")

    def test_lint_missing_distributed_and_rollback_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = write_plugin(Path(tmpdir) / "platform", include_distributed=False, include_rollback=False)

            items = lint_manifest_path(manifest_path)

            self.assertEqual(next(item for item in items if item.check == "distributed").status, "warn")
            self.assertEqual(next(item for item in items if item.check == "rollback_sql").status, "warn")

    def test_lint_requires_build_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = write_plugin(Path(tmpdir) / "platform")
            manifest_path.write_text(manifest_path.read_text(encoding="utf-8") + "  requires_build: true\n", encoding="utf-8")

            items = lint_manifest_path(manifest_path)

            self.assertEqual(next(item for item in items if item.check == "payload:requires_build").status, "warn")


class PluginPackagePlanTest(unittest.TestCase):
    def test_plan_installed_plugin_skips_deploy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = load_manifest(write_plugin(Path(tmpdir) / "platform"))
            runtime = ProbeRuntime(returncode=0, stdout="0.1.0\n")

            plan = plugin_plan(runtime, manifest)

            self.assertEqual(plan.installed_state, "installed")
            self.assertIn("skip deploy", plan.deploy_plan)
            self.assertEqual(runtime.sql_calls, ["SELECT lint_plugin.version();"])

    def test_plan_not_installed_plugin_copies_payload_and_runs_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = load_manifest(write_plugin(Path(tmpdir) / "platform"))
            runtime = ProbeRuntime(returncode=1, stdout="", stderr="missing")

            plan = plugin_plan(runtime, manifest)
            payload = plugin_plan_json(plan)

            self.assertEqual(payload["installed_state"], "not_installed")
            self.assertIn("copy", payload["deploy_plan"])
            self.assertIn("install.sql", payload["deploy_plan"])
            self.assertIn("coordinator", payload["target_roles"])

    def test_plan_missing_probe_is_unknown_and_does_not_execute_other_sql(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = load_manifest(write_plugin(Path(tmpdir) / "platform", include_installed_probe=False))
            runtime = ProbeRuntime()

            plan = plugin_plan(runtime, manifest)

            self.assertEqual(plan.installed_state, "unknown")
            self.assertIn("missing installed_probe", plan.risks)
            self.assertEqual(runtime.sql_calls, [])

    def test_plan_missing_rollback_reports_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = load_manifest(write_plugin(Path(tmpdir) / "platform", include_rollback=False))

            plan = plugin_plan(ProbeRuntime(returncode=1, stderr="missing"), manifest)

            self.assertIn("unsupported", plan.rollback_plan)
            self.assertIn("rollback unsupported", plan.risks)

    def test_plan_requires_build_reports_risk(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = write_plugin(Path(tmpdir) / "platform")
            manifest_path.write_text(manifest_path.read_text(encoding="utf-8") + "  requires_build: true\n", encoding="utf-8")
            manifest = load_manifest(manifest_path)

            plan = plugin_plan(ProbeRuntime(returncode=1, stderr="missing"), manifest)

            self.assertIn("native build required before deploy", plan.risks)

    def test_plan_real_manifests_have_expected_governance_shape(self) -> None:
        platform_root = Path(__file__).resolve().parents[1]
        smoke = load_manifest(platform_root / "examples" / "plugins" / "pluginctl_smoke_plugin" / "manifest.yml")
        otb = load_manifest(platform_root / "catalog" / "plugins" / "otb_timeseries.yml")

        smoke_plan = plugin_plan(ProbeRuntime(returncode=1, stderr="missing"), smoke)
        otb_plan = plugin_plan(ProbeRuntime(returncode=0, stdout="1.0.0\n"), otb)

        self.assertEqual(smoke_plan.plugin_id, "pluginctl_smoke_plugin")
        self.assertIn("rollback.sql", smoke_plan.rollback_plan)
        self.assertEqual(otb_plan.installed_state, "installed")
        self.assertIn("rollback unsupported", otb_plan.risks)
        self.assertIn("chunk distribution warning is tracked separately", otb_plan.risks)


class PluginPackagePrecheckTest(unittest.TestCase):
    def test_precheck_passes_read_only_deploy_prerequisites(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            platform_root = Path(tmpdir) / "platform"
            manifest = load_manifest(write_plugin(platform_root))
            runtime = PrecheckRuntime()

            items = plugin_precheck(platform_root, runtime, manifest)
            payload = precheck_items_json(items)

            self.assertFalse([item for item in items if item.status == "fail"])
            self.assertIn({"plugin_id": "lint_plugin", "check": "runtime:connection", "status": "pass", "detail": "1"}, payload)
            self.assertIn({"plugin_id": "lint_plugin", "check": "runtime:default_node_group", "status": "pass", "detail": "default_group"}, payload)
            self.assertIn({"plugin_id": "lint_plugin", "check": "runtime:sharding_map", "status": "pass", "detail": "16 shard map rows for default group"}, payload)
            self.assertIn("SELECT lint_plugin.version();", runtime.sql_calls)
            self.assertEqual(runtime.exec_calls, [("bash", "-lc", "test -w /tmp")])

    def test_precheck_missing_default_group_fails_for_table_creating_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            platform_root = Path(tmpdir) / "platform"
            manifest = load_manifest(write_plugin(platform_root, install_sql="CREATE TABLE lint_plugin.t(id int);"))
            runtime = PrecheckRuntime(default_group_stdout="")

            items = plugin_precheck(platform_root, runtime, manifest)

            default_group = next(item for item in items if item.check == "runtime:default_node_group")
            self.assertEqual(default_group.status, "fail")
            self.assertIn("CREATE DEFAULT NODE GROUP", default_group.detail)

    def test_precheck_missing_sharding_map_fails_for_table_creating_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            platform_root = Path(tmpdir) / "platform"
            manifest = load_manifest(write_plugin(platform_root, install_sql="CREATE TABLE lint_plugin.t(id int);"))
            runtime = PrecheckRuntime(sharding_map_stdout="0\n")

            items = plugin_precheck(platform_root, runtime, manifest)

            sharding_map = next(item for item in items if item.check == "runtime:sharding_map")
            self.assertEqual(sharding_map.status, "fail")
            self.assertEqual(sharding_map.detail, "0 shard map rows for default group")

    def test_precheck_missing_sharding_map_warns_for_non_table_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            platform_root = Path(tmpdir) / "platform"
            manifest = load_manifest(write_plugin(platform_root))
            runtime = PrecheckRuntime(default_group_stdout="", sharding_map_stdout="0\n")

            items = plugin_precheck(platform_root, runtime, manifest)

            self.assertEqual(next(item for item in items if item.check == "runtime:default_node_group").status, "warn")
            self.assertEqual(next(item for item in items if item.check == "runtime:sharding_map").status, "warn")

    def test_precheck_connection_failure_stops_runtime_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            platform_root = Path(tmpdir) / "platform"
            manifest = load_manifest(write_plugin(platform_root))
            runtime = PrecheckRuntime(connection_ok=False)

            items = plugin_precheck(platform_root, runtime, manifest)

            self.assertEqual(next(item for item in items if item.check == "runtime:connection").status, "fail")
            self.assertNotIn("SELECT version();", runtime.sql_calls)
            self.assertEqual(runtime.exec_calls, [])

    def test_precheck_missing_required_role_fails_for_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            platform_root = Path(tmpdir) / "platform"
            manifest = load_manifest(write_plugin(platform_root))
            runtime = PrecheckRuntime(roles_stdout="D\n")

            items = plugin_precheck(platform_root, runtime, manifest)

            role_check = next(item for item in items if item.check == "distributed:required_roles")
            self.assertEqual(role_check.status, "fail")
            self.assertIn("coordinator", role_check.detail)

    def test_precheck_remote_tmp_failure_fails_without_copying_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            platform_root = Path(tmpdir) / "platform"
            manifest = load_manifest(write_plugin(platform_root))
            runtime = PrecheckRuntime(remote_tmp_ok=False)

            items = plugin_precheck(platform_root, runtime, manifest)

            tmp_check = next(item for item in items if item.check == "runtime:remote_tmp_writable")
            self.assertEqual(tmp_check.status, "fail")
            self.assertIn("not writable", tmp_check.detail)


if __name__ == "__main__":
    unittest.main()

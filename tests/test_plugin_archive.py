from pathlib import Path
import subprocess
import tempfile
import unittest

from plugin_ctl.manifest import load_manifest
from plugin_ctl.plugin_archive import ArchiveStore, archive_record_json, build_archive_record, manifest_checksum
from plugin_ctl.plugin_consistency import consistency_check, consistency_items_json
from plugin_ctl.plugin_diagnose import diagnose_plugin
from plugin_ctl.plugin_roles import manifest_roles, role_hooks, role_hooks_json, role_steps, role_steps_json
from plugin_ctl.state_store import StateStore


class Runtime:
    def __init__(self, *, installed: bool = True, roles: str = "C\nD\n") -> None:
        self.installed = installed
        self.roles = roles

    def run_sql(self, sql: str) -> subprocess.CompletedProcess[str]:
        if sql == "SELECT 1;":
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="1\n", stderr="")
        if sql == "SELECT version();":
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="OpenTenBase test\n", stderr="")
        if "SELECT DISTINCT node_type" in sql:
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout=self.roles, stderr="")
        if "FROM pgxc_node" in sql:
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="cn001|C|127.0.0.1|30004\ndn001|D|127.0.0.1|40004\n", stderr="")
        if self.installed:
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="0.1.0\n", stderr="")
        return subprocess.CompletedProcess(args=["psql"], returncode=1, stdout="", stderr="missing")

    def run_sql_at(self, host: str, port: int, sql: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="1\n", stderr="")

    def exec(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=["docker", "exec", *args], returncode=0, stdout="", stderr="")


def write_manifest(root: Path, *, distributed: bool = True, hooks: bool = False) -> Path:
    manifest_dir = root / "examples" / "plugins" / "archive_plugin"
    payload_dir = root / "payload" / "archive_plugin" / "sql"
    hook_dir = root / "payload" / "archive_plugin" / "hooks"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    payload_dir.mkdir(parents=True, exist_ok=True)
    hook_dir.mkdir(parents=True, exist_ok=True)
    for name in ["install.sql", "verify.sql", "rollback.sql"]:
        (payload_dir / name).write_text("SELECT 1;", encoding="utf-8")
    (hook_dir / "preinstall.sql").write_text("SELECT 'preinstall';", encoding="utf-8")
    lines = [
        "plugin_id: archive_plugin",
        "name: Archive Plugin",
        "version: 0.1.0",
        "description: archive fixture",
        "database: OpenTenBase",
        "targets:",
        "  cn: true",
        "  dn: true",
    ]
    if distributed:
        lines.extend(
            [
                "distributed:",
                "  required_roles:",
                "    - coordinator",
                "    - datanode",
                "  probe_strategy: coordinator",
            ]
        )
    if hooks:
        lines.extend(
            [
                "hooks:",
                "  preinstall:",
                "    coordinator:",
                "      - payload/archive_plugin/hooks/preinstall.sql",
            ]
        )
    lines.extend(
        [
            "payload:",
            "  source_root: payload/archive_plugin",
            "  install_sql: payload/archive_plugin/sql/install.sql",
            "  verify_sql: payload/archive_plugin/sql/verify.sql",
            "  smoke_sql: payload/archive_plugin/sql/verify.sql",
            "  rollback_sql: payload/archive_plugin/sql/rollback.sql",
            "  installed_probe: SELECT archive_plugin.version();",
            "  removed_probe: SELECT 'removed';",
        ]
    )
    path = manifest_dir / "manifest.yml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class PluginArchiveTest(unittest.TestCase):
    def test_archive_record_persists_package_state_and_latest_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = load_manifest(write_manifest(root))
            StateStore(root).append(
                "archive_plugin",
                "deploy",
                True,
                "deployed",
                {"version": "0.1.0", "cluster": "test", "container": "cn", "remote_root": "/tmp/plugin_ctl/archive_plugin_test"},
            )
            diagnosis = diagnose_plugin(root, Runtime(installed=True), manifest)

            record = ArchiveStore(root).upsert(build_archive_record(root, manifest, diagnosis))
            loaded = ArchiveStore(root).get("archive_plugin")

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.plugin_id, "archive_plugin")  # type: ignore[union-attr]
            self.assertEqual(loaded.status, "installed")  # type: ignore[union-attr]
            self.assertEqual(loaded.target_roles, ["coordinator", "datanode"])  # type: ignore[union-attr]
            self.assertIn("deploy", loaded.latest_actions)  # type: ignore[union-attr]
            self.assertEqual(archive_record_json(record)["runtime_metadata"]["container"], "cn")
            self.assertEqual(archive_record_json(record)["manifest"]["kind"], "bundled_package")
            self.assertTrue(archive_record_json(record)["package_state"]["payload_complete"])
            self.assertIn("source_root", archive_record_json(record)["payload"])

    def test_manifest_checksum_changes_when_payload_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = load_manifest(write_manifest(root))
            before = manifest_checksum(manifest)
            manifest.install_sql.write_text("SELECT 2;", encoding="utf-8")

            self.assertNotEqual(before, manifest_checksum(manifest))

    def test_role_mapping_uses_distributed_or_targets_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = load_manifest(write_manifest(root, distributed=True))
            legacy = load_manifest(write_manifest(root, distributed=False))

            self.assertEqual(manifest_roles(manifest), ["coordinator", "datanode"])
            self.assertEqual(manifest_roles(legacy), ["coordinator", "datanode"])
            self.assertIn({"role": "coordinator", "step": "install_sql", "detail": str(manifest.install_sql)}, role_steps_json(role_steps(manifest)))

    def test_role_hooks_are_mapped_by_lifecycle_and_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = load_manifest(write_manifest(root, hooks=True))

            hooks = role_hooks(manifest)

            self.assertEqual(role_hooks_json(hooks), [{"hook": "preinstall", "role": "coordinator", "detail": "payload/archive_plugin/hooks/preinstall.sql", "exists": True}])
            self.assertIn({"role": "coordinator", "step": "hook:preinstall", "detail": "payload/archive_plugin/hooks/preinstall.sql"}, role_steps_json(role_steps(manifest)))

    def test_consistency_warns_without_archive_and_passes_with_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = load_manifest(write_manifest(root))
            runtime = Runtime(installed=True)

            missing = consistency_check(root, runtime, manifest)
            self.assertEqual(next(item for item in missing if item.check == "archive:record").status, "warn")

            diagnosis = diagnose_plugin(root, runtime, manifest)
            ArchiveStore(root).upsert(build_archive_record(root, manifest, diagnosis))
            checks = consistency_check(root, runtime, manifest)
            payload = consistency_items_json(checks)

            self.assertIn({"plugin_id": "archive_plugin", "check": "archive:record", "status": "pass", "detail": "status=installed, version=0.1.0"}, payload)
            self.assertEqual(next(item for item in checks if item.check == "archive_vs_runtime").status, "pass")

    def test_consistency_warns_when_archive_and_runtime_disagree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = load_manifest(write_manifest(root))
            ArchiveStore(root).upsert(build_archive_record(root, manifest, diagnose_plugin(root, Runtime(installed=True), manifest)))

            checks = consistency_check(root, Runtime(installed=False), manifest)

            self.assertEqual(next(item for item in checks if item.check == "archive_vs_runtime").status, "warn")

    def test_consistency_checks_archived_remote_payload_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = load_manifest(write_manifest(root))
            StateStore(root).append(
                "archive_plugin",
                "deploy",
                True,
                "deployed",
                {"version": "0.1.0", "remote_root": "/tmp/plugin_ctl/archive_plugin_test"},
            )
            ArchiveStore(root).upsert(build_archive_record(root, manifest, diagnose_plugin(root, Runtime(installed=True), manifest)))

            checks = consistency_check(root, Runtime(installed=True), manifest)

            self.assertEqual(next(item for item in checks if item.check == "role_remote_payload:coordinator").status, "pass")
            self.assertEqual(next(item for item in checks if item.check == "role_remote_payload:datanode").status, "pass")

    def test_consistency_surfaces_package_file_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = load_manifest(write_manifest(root))
            manifest.install_sql.unlink()

            checks = consistency_check(root, Runtime(installed=True), manifest)

            install_check = next(item for item in checks if item.check == "package:install_sql")
            self.assertEqual(install_check.status, "fail")


if __name__ == "__main__":
    unittest.main()

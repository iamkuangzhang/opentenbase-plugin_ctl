from pathlib import Path
import subprocess
import tempfile
import unittest

from datanexus.catalog import Catalog
from datanexus.manifest import PluginManifest
from datanexus.rollback import rollback_plugin


class DummyRuntime:
    pass


class RecordingRuntime:
    def __init__(self, *, rollback_returncode: int = 0) -> None:
        self.rollback_returncode = rollback_returncode
        self.sql_calls: list[str] = []

    def run_sql(self, sql: str) -> subprocess.CompletedProcess[str]:
        self.sql_calls.append(sql)
        if sql == "SELECT 1;":
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="1\n", stderr="")
        return subprocess.CompletedProcess(
            args=["psql"],
            returncode=self.rollback_returncode,
            stdout="rollback ok" if self.rollback_returncode == 0 else "",
            stderr="rollback failed" if self.rollback_returncode else "",
        )


class RollbackTest(unittest.TestCase):
    def manifest_with_rollback(self, root: Path, rollback_sql: Path) -> PluginManifest:
        manifest_path = root / "platform" / "catalog" / "plugins" / "sample.yml"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text("", encoding="utf-8")
        return PluginManifest(
            plugin_id="sample_plugin",
            name="Sample Plugin",
            version="1.0.0",
            description="Rollback test fixture",
            database="OpenTenBase",
            targets={"cn": True, "dn": True},
            payload={
                "source_root": "src/sample_plugin",
                "install_sql": "src/sample_plugin/install.sql",
                "verify_sql": "tests/sample.sql",
                "rollback_sql": str(rollback_sql.relative_to(root)),
            },
            path=manifest_path,
        )

    def test_rollback_requires_manifest_script(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = Catalog(root=root).load_one("otb_timeseries")
        result = rollback_plugin(DummyRuntime(), manifest)  # type: ignore[arg-type]
        self.assertFalse(result.ok)
        self.assertEqual(result.returncode, 2)
        self.assertIn("rollback_sql", result.detail)

    def test_rollback_with_script_defaults_to_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            rollback_sql = root / "rollback.sql"
            rollback_sql.write_text("SELECT 'planned rollback';", encoding="utf-8")
            manifest = self.manifest_with_rollback(root, rollback_sql)
            runtime = RecordingRuntime()

            result = rollback_plugin(runtime, manifest)

            self.assertTrue(result.ok)
            self.assertEqual(result.returncode, 0)
            self.assertIn("rollback plan ready", result.detail)
            self.assertEqual(result.stdout, "SELECT 'planned rollback';")
            self.assertEqual(runtime.sql_calls, [])
            self.assertEqual(result.metadata["execute"], False)
            self.assertEqual(result.metadata["dry_run"], True)

    def test_rollback_execute_runs_sql_and_returns_success_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            rollback_sql = root / "rollback.sql"
            rollback_sql.write_text("SELECT 'execute rollback';", encoding="utf-8")
            manifest = self.manifest_with_rollback(root, rollback_sql)
            runtime = RecordingRuntime()

            result = rollback_plugin(runtime, manifest, execute=True)

            self.assertTrue(result.ok)
            self.assertEqual(result.detail, "rollback passed")
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "rollback ok")
            self.assertEqual(runtime.sql_calls, ["SELECT 1;", "SELECT 'execute rollback';"])
            self.assertEqual(result.metadata["execute"], True)

    def test_rollback_execute_returns_failure_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            rollback_sql = root / "rollback.sql"
            rollback_sql.write_text("SELECT 'execute rollback';", encoding="utf-8")
            manifest = self.manifest_with_rollback(root, rollback_sql)
            runtime = RecordingRuntime(rollback_returncode=1)

            result = rollback_plugin(runtime, manifest, execute=True)

            self.assertFalse(result.ok)
            self.assertEqual(result.detail, "rollback failed")
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr, "rollback failed")
            self.assertEqual(runtime.sql_calls, ["SELECT 1;", "SELECT 'execute rollback';"])
            self.assertEqual(result.metadata["execute"], True)


if __name__ == "__main__":
    unittest.main()

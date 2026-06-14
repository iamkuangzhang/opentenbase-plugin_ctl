from pathlib import Path
import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from plugin_ctl.catalog import Catalog
from plugin_ctl.cli import main
from plugin_ctl.manifest import PluginManifest
from plugin_ctl.rollback import rollback_plugin


class DummyRuntime:
    pass


class RecordingRuntime:
    container = "fake"
    host = "127.0.0.1"
    port = 30004
    user = "opentenbase"
    database = "postgres"

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

    def exec(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")


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
                "rollback_sql": str(rollback_sql.relative_to(root / "platform")),
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
            rollback_sql = root / "platform" / "rollback.sql"
            rollback_sql.parent.mkdir(parents=True, exist_ok=True)
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
            rollback_sql = root / "platform" / "rollback.sql"
            rollback_sql.parent.mkdir(parents=True, exist_ok=True)
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
            rollback_sql = root / "platform" / "rollback.sql"
            rollback_sql.parent.mkdir(parents=True, exist_ok=True)
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


class RollbackCliTest(unittest.TestCase):
    def _write_manifest(self, root: Path, *, include_rollback: bool = True) -> None:
        payload = root / "catalog" / "payload" / "sample"
        payload.mkdir(parents=True)
        (payload / "install.sql").write_text("SELECT 1;\n", encoding="utf-8")
        (payload / "verify.sql").write_text("SELECT 1;\n", encoding="utf-8")
        if include_rollback:
            (payload / "rollback.sql").write_text("SELECT 'rollback';\n", encoding="utf-8")
        manifest = root / "catalog" / "plugins" / "sample.yml"
        manifest.parent.mkdir(parents=True)
        rollback_line = "  rollback_sql: catalog/payload/sample/rollback.sql\n" if include_rollback else ""
        manifest.write_text(
            f"""
plugin_id: sample_plugin
name: Sample Plugin
version: 1.0.0
description: sample
database: OpenTenBase
targets:
  cn: true
payload:
  source_root: catalog/payload/sample
  install_sql: catalog/payload/sample/install.sql
  verify_sql: catalog/payload/sample/verify.sql
  smoke_sql: catalog/payload/sample/verify.sql
{rollback_line}  installed_probe: SELECT 1;
""",
            encoding="utf-8",
        )

    def _run(self, argv: list[str]) -> tuple[int, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, output.getvalue()

    def test_rollback_dry_run_outputs_boundary_and_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_manifest(root)
            with patch("plugin_ctl.cli.OpenTenBaseRuntime", return_value=RecordingRuntime()):
                code, output = self._run(["--root", str(root), "rollback", "sample_plugin", "--dry-run"])

        self.assertEqual(code, 0)
        self.assertIn("Rollback plan: sample_plugin", output)
        self.assertIn("SQL to execute:", output)
        self.assertIn("SELECT 'rollback';", output)
        self.assertIn("rollback does NOT delete physical files from CN/DN nodes", output)

    def test_rollback_missing_script_outputs_safe_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_manifest(root, include_rollback=False)
            with patch("plugin_ctl.cli.OpenTenBaseRuntime", return_value=RecordingRuntime()):
                code, output = self._run(["--root", str(root), "rollback", "sample_plugin", "--dry-run"])

        self.assertEqual(code, 2)
        self.assertIn("Warning: manifest has no rollback_sql", output)
        self.assertIn("will not guess a DROP EXTENSION", output)
        self.assertIn("rollback does NOT delete physical files from CN/DN nodes", output)


if __name__ == "__main__":
    unittest.main()

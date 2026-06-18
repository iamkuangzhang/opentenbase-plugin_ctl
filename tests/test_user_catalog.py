from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from plugin_ctl.catalog import Catalog
from plugin_ctl.cli import main


def write_external_plugin(root: Path, plugin_id: str = "external_demo_plugin") -> Path:
    plugin_dir = root / plugin_id
    sql_dir = plugin_dir / "payload" / "sql"
    sql_dir.mkdir(parents=True)
    (sql_dir / "install.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (sql_dir / "verify.sql").write_text("SELECT 'ok';\n", encoding="utf-8")
    (sql_dir / "rollback.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (plugin_dir / "manifest.yml").write_text(
        "\n".join(
            [
                f"plugin_id: {plugin_id}",
                "name: External Demo Plugin",
                "version: 0.1.0",
                "description: External plugin registered by path.",
                "database: OpenTenBase",
                "targets:",
                "  cn: true",
                "  dn: false",
                "distributed:",
                "  required_roles:",
                "    - coordinator",
                "  probe_strategy: coordinator",
                "payload:",
                "  source_root: payload",
                "  install_sql: payload/sql/install.sql",
                "  verify_sql: payload/sql/verify.sql",
                "  smoke_sql: payload/sql/verify.sql",
                "  rollback_sql: payload/sql/rollback.sql",
                "  installed_probe: SELECT 1;",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return plugin_dir


class UserCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def run_silent(self, argv: list[str]) -> int:
        with redirect_stdout(io.StringIO()):
            return main(argv)

    def test_add_registers_external_plugin_without_copying_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            plugin_dir = write_external_plugin(tmp)
            catalog_file = tmp / "home" / "catalog.json"
            env = {"PLUGIN_CTL_CATALOG_FILE": str(catalog_file)}

            with patch.dict(os.environ, env):
                output = io.StringIO()
                with redirect_stdout(output):
                    code = main(["--root", str(self.root), "add", str(plugin_dir)])

                self.assertEqual(code, 0)
                self.assertIn("Registered plugin: external_demo_plugin", output.getvalue())
                manifest = Catalog(root=self.root).load_one("external_demo_plugin")
                self.assertEqual(manifest.project_root, plugin_dir)
                self.assertEqual(manifest.source_root, plugin_dir / "payload")
                entry = Catalog(root=self.root).user_plugin_entry("external_demo_plugin")
                self.assertEqual(entry["root"], str(plugin_dir.resolve()))

    def test_added_plugin_is_visible_to_list_inspect_and_lint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            plugin_dir = write_external_plugin(tmp)
            catalog_file = tmp / "home" / "catalog.json"
            env = {"PLUGIN_CTL_CATALOG_FILE": str(catalog_file)}

            with patch.dict(os.environ, env):
                self.assertEqual(self.run_silent(["--root", str(self.root), "add", str(plugin_dir)]), 0)

                list_output = io.StringIO()
                with redirect_stdout(list_output):
                    list_code = main(["--root", str(self.root), "list"])
                self.assertEqual(list_code, 0)
                self.assertIn("external_demo_plugin", list_output.getvalue())

                inspect_output = io.StringIO()
                with redirect_stdout(inspect_output):
                    inspect_code = main(["--root", str(self.root), "inspect", "external_demo_plugin"])
                self.assertEqual(inspect_code, 0)
                self.assertIn("External Demo Plugin", inspect_output.getvalue())

                lint_output = io.StringIO()
                with redirect_stdout(lint_output):
                    lint_code = main(["--root", str(self.root), "plugin", "lint", "external_demo_plugin"])
                self.assertEqual(lint_code, 0)
                self.assertIn("external_demo_plugin", lint_output.getvalue())

    def test_remove_only_removes_user_registered_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            plugin_dir = write_external_plugin(tmp)
            catalog_file = tmp / "home" / "catalog.json"
            env = {"PLUGIN_CTL_CATALOG_FILE": str(catalog_file)}

            with patch.dict(os.environ, env):
                self.assertEqual(self.run_silent(["--root", str(self.root), "add", str(plugin_dir)]), 0)
                remove_output = io.StringIO()
                with redirect_stdout(remove_output):
                    remove_code = main(["--root", str(self.root), "remove", "external_demo_plugin"])
                self.assertEqual(remove_code, 0)
                self.assertIn(f"Plugin root: {plugin_dir.resolve()}", remove_output.getvalue())
                self.assertIn(f"Manifest: {(plugin_dir / 'manifest.yml').resolve()}", remove_output.getvalue())
                self.assertIn(f"Re-add: plugin_ctl add {plugin_dir.resolve()}", remove_output.getvalue())
                self.assertIn("Database objects and distributed extension files were not removed.", remove_output.getvalue())
                with self.assertRaises(Exception):
                    Catalog(root=self.root).load_one("external_demo_plugin")

    def test_remove_clears_local_package_metadata_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            plugin_dir = write_external_plugin(tmp, plugin_id="cached_demo")
            catalog_file = tmp / "home" / "catalog.json"
            package_dir = tmp / "home" / "packages" / "cached_demo"
            package_dir.mkdir(parents=True)
            (package_dir / "manifest.yml").write_text((plugin_dir / "manifest.yml").read_text(encoding="utf-8"), encoding="utf-8")
            env = {"PLUGIN_CTL_CATALOG_FILE": str(catalog_file)}

            with patch.dict(os.environ, env):
                self.assertEqual(self.run_silent(["--root", str(self.root), "add", str(plugin_dir)]), 0)
                self.assertTrue(package_dir.exists())

                remove_output = io.StringIO()
                with redirect_stdout(remove_output):
                    remove_code = main(["--root", str(self.root), "remove", "cached_demo"])

                self.assertEqual(remove_code, 0)
                self.assertIn("Local package metadata cache: removed", remove_output.getvalue())
                self.assertFalse(package_dir.exists())
                list_output = io.StringIO()
                with redirect_stdout(list_output):
                    list_code = main(["--root", str(self.root), "list"])
                self.assertEqual(list_code, 0)
                self.assertNotIn("cached_demo", list_output.getvalue())

    def test_list_reads_deployed_package_manifests_without_catalog_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            package_dir = tmp / "home" / "packages" / "deployed_demo"
            package_dir.mkdir(parents=True)
            (package_dir / "manifest.yml").write_text(
                "\n".join(
                    [
                        "plugin_id: deployed_demo",
                        "name: Deployed Demo Plugin",
                        "version: 0.1.0",
                        "description: Deployed demo plugin.",
                        "database: OpenTenBase",
                        "targets:",
                        "  cn: true",
                        "payload:",
                        "  source_root: .",
                        "install_sql: SELECT 1;",
                        "verify_sql: SELECT 1;",
                        "rollback_sql: SELECT 1;",
                        "installed_probe: SELECT 1;",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            catalog_file = tmp / "home" / "catalog.json"
            env = {"PLUGIN_CTL_CATALOG_FILE": str(catalog_file)}

            with patch.dict(os.environ, env):
                list_output = io.StringIO()
                with redirect_stdout(list_output):
                    list_code = main(["--root", str(self.root), "list"])

                self.assertEqual(list_code, 0)
                self.assertIn("deployed_demo", list_output.getvalue())

    def test_list_deduplicates_catalog_and_deployed_package_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            plugin_dir = write_external_plugin(tmp, plugin_id="duplicate_demo")
            package_dir = tmp / "home" / "packages" / "duplicate_demo"
            package_dir.mkdir(parents=True)
            (package_dir / "manifest.yml").write_text((plugin_dir / "manifest.yml").read_text(encoding="utf-8"), encoding="utf-8")
            catalog_file = tmp / "home" / "catalog.json"
            env = {"PLUGIN_CTL_CATALOG_FILE": str(catalog_file)}

            with patch.dict(os.environ, env):
                self.assertEqual(self.run_silent(["--root", str(self.root), "add", str(plugin_dir)]), 0)
                list_output = io.StringIO()
                with redirect_stdout(list_output):
                    list_code = main(["--root", str(self.root), "list"])

                self.assertEqual(list_code, 0)
                self.assertEqual(list_output.getvalue().count("duplicate_demo"), 1)


if __name__ == "__main__":
    unittest.main()

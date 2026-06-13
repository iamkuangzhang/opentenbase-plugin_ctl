from __future__ import annotations

import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from plugin_ctl.catalog import Catalog
from plugin_ctl.cli import main
from plugin_ctl.dev_init import generated_relative_paths


class FakeRuntime:
    container = "fake"
    host = "127.0.0.1"
    port = 30004
    user = "opentenbase"
    database = "postgres"

    def run_sql(self, sql: str) -> subprocess.CompletedProcess[str]:
        if sql == "SELECT 1;":
            return subprocess.CompletedProcess(["psql"], 0, "1\n", "")
        if sql == "SELECT version();":
            return subprocess.CompletedProcess(["psql"], 0, "OpenTenBase test\n", "")
        if "FROM pgxc_group" in sql:
            return subprocess.CompletedProcess(["psql"], 0, "default_group\n", "")
        if "FROM pgxc_shard_map" in sql:
            return subprocess.CompletedProcess(["psql"], 0, "16\n", "")
        if "SELECT DISTINCT node_type" in sql:
            return subprocess.CompletedProcess(["psql"], 0, "C\nD\n", "")
        if "FROM pgxc_node" in sql:
            return subprocess.CompletedProcess(["psql"], 0, "cn001|C|127.0.0.1|30004\ndn001|D|127.0.0.1|20008\n", "")
        if "pg_extension" in sql:
            return subprocess.CompletedProcess(["psql"], 0, "", "")
        return subprocess.CompletedProcess(["psql"], 0, "", "")

    def run_sql_at(self, host: str, port: int, sql: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["psql"], 0, "1\n", "")

    def exec(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(args), 0, "", "")


class DevInitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def run_cli(self, argv: list[str]) -> tuple[int, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, output.getvalue()

    def run_silent(self, argv: list[str]) -> int:
        return self.run_cli(argv)[0]

    def test_dev_init_generates_plugin_directory_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            code, output = self.run_cli(["--root", str(self.root), "dev", "init", "my_plugin", "--dir", tmpdir])

            plugin_dir = Path(tmpdir) / "my_plugin"
            self.assertEqual(code, 0)
            self.assertIn("Plugin skeleton created:", output)
            for rel_path in generated_relative_paths("my_plugin"):
                self.assertTrue((plugin_dir / rel_path).exists(), rel_path)

    def test_generated_files_use_requested_plugin_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(self.run_silent(["--root", str(self.root), "dev", "init", "otb_vector", "--dir", tmpdir]), 0)
            plugin_dir = Path(tmpdir) / "otb_vector"

            for rel_path in generated_relative_paths("otb_vector"):
                if rel_path.name == ".pluginctlignore":
                    continue
                text = (plugin_dir / rel_path).read_text(encoding="utf-8")
                self.assertIn("otb_vector", text)
                self.assertNotIn("my_plugin", text)

    def test_invalid_plugin_id_reports_friendly_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            error = io.StringIO()
            with redirect_stderr(error):
                with self.assertRaises(SystemExit):
                    main(["--root", str(self.root), "dev", "init", "MyPlugin", "--dir", tmpdir])

            text = error.getvalue()
            self.assertIn("Invalid plugin_id: MyPlugin", text)
            self.assertIn("plugin_id must match: ^[a-z][a-z0-9_]*$", text)

    def test_existing_directory_requires_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "my_plugin"
            plugin_dir.mkdir()
            error = io.StringIO()
            with redirect_stderr(error):
                with self.assertRaises(SystemExit):
                    main(["--root", str(self.root), "dev", "init", "my_plugin", "--dir", tmpdir])

            self.assertIn("target directory already exists", error.getvalue())

    def test_force_overwrites_generated_files_without_deleting_other_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "my_plugin"
            self.assertEqual(self.run_silent(["--root", str(self.root), "dev", "init", "my_plugin", "--dir", tmpdir]), 0)
            extra = plugin_dir / "notes.txt"
            extra.write_text("keep me\n", encoding="utf-8")
            (plugin_dir / "README.md").write_text("old\n", encoding="utf-8")

            self.assertEqual(self.run_silent(["--root", str(self.root), "dev", "init", "my_plugin", "--dir", tmpdir, "--force"]), 0)

            self.assertEqual(extra.read_text(encoding="utf-8"), "keep me\n")
            self.assertIn("# my_plugin", (plugin_dir / "README.md").read_text(encoding="utf-8"))

    def test_generated_manifest_can_be_added_inspected_linted_and_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            catalog_file = tmp / "home" / "catalog.json"
            plugin_dir = tmp / "plugins" / "my_plugin"
            env = {"PLUGIN_CTL_CATALOG_FILE": str(catalog_file)}

            with patch.dict(os.environ, env):
                self.assertEqual(self.run_silent(["--root", str(self.root), "dev", "init", "my_plugin", "--dir", str(tmp / "plugins")]), 0)
                self.assertEqual(self.run_silent(["--root", str(self.root), "add", str(plugin_dir)]), 0)
                manifest = Catalog(root=self.root).load_one("my_plugin")
                self.assertEqual(manifest.plugin_id, "my_plugin")
                self.assertEqual(manifest.project_root, plugin_dir)

                inspect_code, inspect_output = self.run_cli(["--root", str(self.root), "inspect", "my_plugin"])
                self.assertEqual(inspect_code, 0)
                self.assertIn("my_plugin Plugin", inspect_output)

                lint_code, lint_output = self.run_cli(["--root", str(self.root), "plugin", "lint", "my_plugin"])
                self.assertEqual(lint_code, 0)
                self.assertIn("distributed.required_roles", lint_output)

                with patch("plugin_ctl.cli.OpenTenBaseRuntime", return_value=FakeRuntime()):
                    check_code, check_output = self.run_cli(["--root", str(self.root), "check", "my_plugin"])
                self.assertEqual(check_code, 0)
                self.assertIn("结果: READY", check_output)

    def test_new_generates_plugin_and_adds_to_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            catalog_file = tmp / "home" / "catalog.json"
            env = {"PLUGIN_CTL_CATALOG_FILE": str(catalog_file)}
            old_cwd = Path.cwd()

            try:
                os.chdir(tmp)
                with patch.dict(os.environ, env):
                    code, output = self.run_cli(["--root", str(self.root), "new", "my_plugin"])

                    self.assertEqual(code, 0)
                    self.assertIn("Plugin created and added: my_plugin", output)
                    self.assertTrue((tmp / "my_plugin" / "manifest.yml").exists())
                    manifest = Catalog(root=self.root).load_one("my_plugin")
                    self.assertEqual(manifest.plugin_id, "my_plugin")
                    self.assertEqual(manifest.project_root, tmp / "my_plugin")
            finally:
                os.chdir(old_cwd)

    def test_list_plugin_id_shows_details_and_recent_actions(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--root", str(self.root), "list", "pluginctl_smoke_plugin"])

        self.assertEqual(code, 0)
        text = output.getvalue()
        self.assertIn('"plugin_id": "pluginctl_smoke_plugin"', text)
        self.assertIn("Recent actions:", text)

    def test_shell_maps_dev_init(self) -> None:
        from plugin_ctl.shell import translate_shell_command

        self.assertEqual(translate_shell_command(["new", "my_plugin"]), ["new", "my_plugin"])
        self.assertEqual(translate_shell_command(["dev", "init", "my_plugin"]), ["dev", "init", "my_plugin"])
        self.assertEqual(
            translate_shell_command(["dev", "init", "my_plugin", "--dir", "./plugins", "--force"]),
            ["dev", "init", "my_plugin", "--dir", "./plugins", "--force"],
        )


if __name__ == "__main__":
    unittest.main()

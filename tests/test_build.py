from __future__ import annotations

import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from plugin_ctl.catalog import Catalog
from plugin_ctl.cli import main
from plugin_ctl.dev_init import generated_relative_paths
from plugin_ctl.manifest import load_manifest


class FakeRuntime:
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
        return subprocess.CompletedProcess(["psql"], 0, "", "")

    def exec(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(args), 0, "", "")


class BuildCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def run_cli(self, argv: list[str]) -> tuple[int, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, output.getvalue()

    def test_new_default_and_sql_generate_sql_only_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            with patch.dict(os.environ, {"PLUGIN_CTL_CATALOG_FILE": str(tmp / "catalog.json")}):
                old = Path.cwd()
                try:
                    os.chdir(tmp)
                    self.assertEqual(self.run_cli(["--root", str(self.root), "new", "hello"])[0], 0)
                    self.assertEqual(self.run_cli(["--root", str(self.root), "new", "-sql", "hello_sql"])[0], 0)
                finally:
                    os.chdir(old)
                for name in ["hello", "hello_sql"]:
                    manifest = load_manifest(tmp / name / "manifest.yml")
                    self.assertEqual(manifest.plugin_type, "sql")
                    for rel_path in generated_relative_paths(name):
                        self.assertTrue((tmp / name / rel_path).exists(), rel_path)

    def test_new_c_generates_c_template_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            with patch.dict(os.environ, {"PLUGIN_CTL_CATALOG_FILE": str(tmp / "catalog.json")}):
                old = Path.cwd()
                try:
                    os.chdir(tmp)
                    code, output = self.run_cli(["--root", str(self.root), "new", "-c", "hello"])
                finally:
                    os.chdir(old)

            self.assertEqual(code, 0)
            self.assertIn("Plugin created and added: hello", output)
            for rel_path in generated_relative_paths("hello", "c"):
                self.assertTrue((tmp / "hello" / rel_path).exists(), rel_path)
            manifest = load_manifest(tmp / "hello" / "manifest.yml")
            self.assertEqual(manifest.plugin_type, "c")
            self.assertEqual(manifest.source_root, tmp / "hello")
            self.assertEqual(manifest.install_sql, tmp / "hello" / "sql" / "hello--0.1.0.sql")
            self.assertEqual(manifest.build["system"], "pgxs")
            self.assertIn("hello.so", manifest.library_files)
            self.assertIn("module_pathname = '$libdir/hello'", (tmp / "hello" / "hello.control").read_text(encoding="utf-8"))
            makefile = (tmp / "hello" / "Makefile").read_text(encoding="utf-8")
            self.assertIn("MODULE_big = hello", makefile)
            self.assertIn("OBJS = src/hello.o", makefile)
            sql = (tmp / "hello" / "sql" / "hello--0.1.0.sql").read_text(encoding="utf-8")
            self.assertIn("AS 'MODULE_PATHNAME', 'hello'", sql)
            self.assertIn("LANGUAGE C", sql)
            source = (tmp / "hello" / "src" / "hello.c").read_text(encoding="utf-8")
            self.assertIn("PG_MODULE_MAGIC;", source)
            self.assertIn("PG_FUNCTION_INFO_V1(hello);", source)
            self.assertIn("Datum\nhello(PG_FUNCTION_ARGS)", source)

    def test_sql_only_build_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            with patch.dict(os.environ, {"PLUGIN_CTL_CATALOG_FILE": str(tmp / "catalog.json")}):
                old = Path.cwd()
                try:
                    os.chdir(tmp)
                    self.assertEqual(self.run_cli(["--root", str(self.root), "new", "hello"])[0], 0)
                finally:
                    os.chdir(old)
                code, output = self.run_cli(["--root", str(self.root), "build", "hello"])

            self.assertEqual(code, 0)
            self.assertIn("Plugin hello is SQL-only and does not require compilation.", output)

    def test_c_plugin_without_so_is_build_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            with patch.dict(os.environ, {"PLUGIN_CTL_CATALOG_FILE": str(tmp / "catalog.json")}):
                old = Path.cwd()
                try:
                    os.chdir(tmp)
                    self.assertEqual(self.run_cli(["--root", str(self.root), "new", "-c", "hello"])[0], 0)
                finally:
                    os.chdir(old)
                with patch("plugin_ctl.cli.OpenTenBaseRuntime", return_value=FakeRuntime()):
                    code, output = self.run_cli(["--root", str(self.root), "check", "hello"])

            self.assertEqual(code, 0)
            self.assertIn("Result: BUILD_REQUIRED", output)
            self.assertIn("run build hello", output)
            self.assertNotIn("hello.so, hello.so", output)

    def test_c_plugin_without_so_stays_build_required_with_cluster_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            cluster_file = tmp / "cluster.toml"
            cluster_file.write_text(
                """
[cluster]
name = "test"

[[nodes]]
name = "cn001"
role = "cn"
host = "127.0.0.1"
ssh_port = 22
db_port = 30004
ssh_user = "opentenbase"
db_user = "opentenbase"
database = "postgres"
lib_dir = "/tmp/lib"
extension_dir = "/tmp/share/extension"

[[nodes]]
name = "dn001"
role = "dn"
host = "127.0.0.1"
ssh_port = 22
db_port = 20008
ssh_user = "opentenbase"
db_user = "opentenbase"
database = "postgres"
lib_dir = "/tmp/lib"
extension_dir = "/tmp/share/extension"
""",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"PLUGIN_CTL_CATALOG_FILE": str(tmp / "catalog.json"), "OPENTENBASE_PLUGINCTL_CLUSTER_FILE": str(cluster_file)}):
                old = Path.cwd()
                try:
                    os.chdir(tmp)
                    self.assertEqual(self.run_cli(["--root", str(self.root), "new", "-c", "hello"])[0], 0)
                finally:
                    os.chdir(old)
                with patch("plugin_ctl.cli.OpenTenBaseRuntime", return_value=FakeRuntime()):
                    code, output = self.run_cli(["--root", str(self.root), "check", "hello"])

            self.assertEqual(code, 0)
            self.assertIn("[BUILD_REQUIRED] distribution_plan", output)
            self.assertIn("Result: BUILD_REQUIRED", output)

    def test_build_success_makes_c_plugin_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_pg_config = tmp / "pg_config"
            fake_pg_config.write_text("fake\n", encoding="utf-8")
            with patch.dict(os.environ, {"PLUGIN_CTL_CATALOG_FILE": str(tmp / "catalog.json")}):
                old = Path.cwd()
                try:
                    os.chdir(tmp)
                    self.assertEqual(self.run_cli(["--root", str(self.root), "new", "-c", "hello"])[0], 0)
                finally:
                    os.chdir(old)

                def fake_run(argv, **kwargs):
                    if argv[0] == str(fake_pg_config) and argv[1] == "--pgxs":
                        return subprocess.CompletedProcess(argv, 0, "/fake/pgxs.mk\n", "")
                    if argv[0] == "make" and len(argv) == 2:
                        (tmp / "hello" / "hello.so").write_text("so\n", encoding="utf-8")
                    return subprocess.CompletedProcess(argv, 0, "ok\n", "")

                manifest = tmp / "hello" / "manifest.yml"
                text = manifest.read_text(encoding="utf-8").replace("pg_config: auto", f"pg_config: {fake_pg_config.as_posix()}")
                manifest.write_text(text, encoding="utf-8")

                with patch("plugin_ctl.build.subprocess.run", side_effect=fake_run), patch("plugin_ctl.build.shutil.which", return_value="make"):
                    code, output = self.run_cli(["--root", str(self.root), "build", "hello"])
                with patch("plugin_ctl.cli.OpenTenBaseRuntime", return_value=FakeRuntime()):
                    check_code, check_output = self.run_cli(["--root", str(self.root), "check", "hello"])

            self.assertEqual(code, 0)
            self.assertIn("Build completed for hello.", output)
            self.assertEqual(check_code, 0)
            self.assertIn("Result: READY", check_output)

    def test_build_failure_reports_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_pg_config = tmp / "pg_config"
            fake_pg_config.write_text("fake\n", encoding="utf-8")
            with patch.dict(os.environ, {"PLUGIN_CTL_CATALOG_FILE": str(tmp / "catalog.json")}):
                old = Path.cwd()
                try:
                    os.chdir(tmp)
                    self.assertEqual(self.run_cli(["--root", str(self.root), "new", "-c", "hello"])[0], 0)
                finally:
                    os.chdir(old)
                manifest = tmp / "hello" / "manifest.yml"
                manifest.write_text(manifest.read_text(encoding="utf-8").replace("pg_config: auto", f"pg_config: {fake_pg_config.as_posix()}"), encoding="utf-8")

                def fake_run(argv, **kwargs):
                    if argv[0] == str(fake_pg_config):
                        return subprocess.CompletedProcess(argv, 0, "/fake/pgxs.mk\n", "")
                    if argv[0] == "make" and len(argv) == 2:
                        return subprocess.CompletedProcess(argv, 2, "", "compile failed\n")
                    return subprocess.CompletedProcess(argv, 0, "clean\n", "")

                with patch("plugin_ctl.build.subprocess.run", side_effect=fake_run), patch("plugin_ctl.build.shutil.which", return_value="make"):
                    code, output = self.run_cli(["--root", str(self.root), "build", "hello"])

            self.assertEqual(code, 2)
            self.assertIn("compile failed", output)
            self.assertIn("Build failed for hello", output)

    def test_deploy_blocks_when_c_so_is_missing(self) -> None:
        cluster_file = Path(self.root) / "tests" / "_missing_cluster.toml"
        cluster_file.write_text(
            """
[cluster]
name = "test"

[[nodes]]
name = "cn001"
role = "cn"
host = "127.0.0.1"
ssh_port = 22
db_port = 30004
ssh_user = "opentenbase"
db_user = "opentenbase"
database = "postgres"
lib_dir = "/tmp/lib"
extension_dir = "/tmp/share/extension"

[[nodes]]
name = "dn001"
role = "dn"
host = "127.0.0.1"
ssh_port = 22
db_port = 20008
ssh_user = "opentenbase"
db_user = "opentenbase"
database = "postgres"
lib_dir = "/tmp/lib"
extension_dir = "/tmp/share/extension"
""",
            encoding="utf-8",
        )
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir)
                with patch.dict(os.environ, {"PLUGIN_CTL_CATALOG_FILE": str(tmp / "catalog.json")}):
                    old = Path.cwd()
                    try:
                        os.chdir(tmp)
                        self.assertEqual(self.run_cli(["--root", str(self.root), "new", "-c", "hello"])[0], 0)
                    finally:
                        os.chdir(old)
                    code, output = self.run_cli(["--root", str(self.root), "deploy", "hello", "-f", str(cluster_file), "--dry-run"])
                    zh_code, zh_output = self.run_cli(["--root", str(self.root), "deploy", "hello", "-f", str(cluster_file), "--dry-run", "--lang", "zh"])

            self.assertEqual(code, 1)
            self.assertIn("Build artifact missing: hello.so", output)
            self.assertIn("Run 'build hello' before deployment.", output)
            self.assertEqual(zh_code, 1)
            self.assertIn("缺少编译产物：hello.so", zh_output)
            self.assertIn("build hello", zh_output)
        finally:
            cluster_file.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

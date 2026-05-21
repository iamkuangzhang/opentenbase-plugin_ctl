from pathlib import Path
import subprocess
import unittest
from typing import Any

from datanexus.catalog import Catalog
from datanexus.deploy import deploy_sql_payload


class UnreachableRuntime:
    def run_sql(self, sql: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=["psql"], returncode=1, stdout="", stderr="connection refused")


class RecordingRuntime:
    def __init__(
        self,
        *,
        installed_stdout: str = "",
        copy_returncode: int = 0,
        install_returncode: int = 0,
    ) -> None:
        self.installed_stdout = installed_stdout
        self.copy_returncode = copy_returncode
        self.install_returncode = install_returncode
        self.sql_calls: list[str] = []
        self.exec_calls: list[tuple[str, ...]] = []
        self.copy_calls: list[tuple[Path, str]] = []
        self.sql_file_calls: list[str] = []

    def run_sql(self, sql: str) -> subprocess.CompletedProcess[str]:
        self.sql_calls.append(sql)
        if sql == "SELECT 1;":
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="1\n", stderr="")
        return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout=self.installed_stdout, stderr="")

    def exec(self, *args: str) -> subprocess.CompletedProcess[str]:
        self.exec_calls.append(args)
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")

    def copy_to_container(self, source: Path, remote_dir: str) -> subprocess.CompletedProcess[str]:
        self.copy_calls.append((source, remote_dir))
        return subprocess.CompletedProcess(
            args=["docker", "cp"],
            returncode=self.copy_returncode,
            stdout="",
            stderr="copy failed" if self.copy_returncode else "",
        )

    def run_sql_file(self, remote_path: str) -> subprocess.CompletedProcess[str]:
        self.sql_file_calls.append(remote_path)
        return subprocess.CompletedProcess(
            args=["psql", "-f", remote_path],
            returncode=self.install_returncode,
            stdout="installed" if self.install_returncode == 0 else "",
            stderr="install failed" if self.install_returncode else "",
        )


class DeployTest(unittest.TestCase):
    def load_manifest(self) -> Any:
        root = Path(__file__).resolve().parents[1]
        return Catalog(root=root).load_one("otb_timeseries")

    def load_smoke_manifest(self) -> Any:
        root = Path(__file__).resolve().parents[1]
        return Catalog(root=root).load_one("dnx_smoke_plugin")

    def test_deploy_stops_when_runtime_unreachable(self) -> None:
        manifest = self.load_manifest()
        result = deploy_sql_payload(UnreachableRuntime(), manifest)  # type: ignore[arg-type]
        self.assertFalse(result.ok)
        self.assertIn("connection refused", result.detail)

    def test_deploy_skips_when_installed_probe_returns_version(self) -> None:
        manifest = self.load_manifest()
        runtime = RecordingRuntime(installed_stdout="1.0.0\n")
        result = deploy_sql_payload(runtime, manifest)  # type: ignore[arg-type]

        self.assertTrue(result.ok)
        self.assertEqual(result.detail, "already deployed: 1.0.0")
        self.assertEqual(runtime.sql_calls, ["SELECT 1;", "SELECT otb_ts.version();"])
        self.assertEqual(runtime.exec_calls, [])
        self.assertEqual(runtime.copy_calls, [])
        self.assertEqual(runtime.sql_file_calls, [])

    def test_deploy_copies_payload_and_runs_install_sql_when_not_installed(self) -> None:
        manifest = self.load_manifest()
        runtime = RecordingRuntime()
        result = deploy_sql_payload(runtime, manifest)  # type: ignore[arg-type]

        self.assertTrue(result.ok)
        self.assertEqual(result.detail, "deploy sql payload passed")
        self.assertEqual(runtime.sql_calls, ["SELECT 1;", "SELECT otb_ts.version();"])
        self.assertEqual(len(runtime.exec_calls), 1)
        self.assertEqual(len(runtime.copy_calls), 1)
        self.assertEqual(runtime.copy_calls[0][0], manifest.source_root)
        self.assertEqual(len(runtime.sql_file_calls), 1)
        self.assertTrue(runtime.sql_file_calls[0].endswith("/otb_timeseries/core/sql/otb_timeseries--1.0.sql"))

    def test_smoke_plugin_deploy_copies_payload_and_runs_install_sql_when_not_installed(self) -> None:
        manifest = self.load_smoke_manifest()
        runtime = RecordingRuntime()
        result = deploy_sql_payload(runtime, manifest)  # type: ignore[arg-type]

        self.assertTrue(result.ok)
        self.assertEqual(result.metadata["stage"], "install")
        self.assertEqual(runtime.sql_calls, ["SELECT 1;", "SELECT dnx_smoke_plugin.version();"])
        self.assertEqual(len(runtime.exec_calls), 1)
        self.assertEqual(len(runtime.copy_calls), 1)
        self.assertEqual(runtime.copy_calls[0][0], manifest.source_root)
        self.assertEqual(len(runtime.sql_file_calls), 1)
        self.assertTrue(runtime.sql_file_calls[0].endswith("/payload/sql/install.sql"))

    def test_deploy_reports_copy_failure(self) -> None:
        manifest = self.load_manifest()
        runtime = RecordingRuntime(copy_returncode=1)
        result = deploy_sql_payload(runtime, manifest)  # type: ignore[arg-type]

        self.assertFalse(result.ok)
        self.assertEqual(result.detail, "copy failed")
        self.assertEqual(runtime.sql_file_calls, [])

    def test_deploy_reports_install_sql_failure(self) -> None:
        manifest = self.load_manifest()
        runtime = RecordingRuntime(install_returncode=1)
        result = deploy_sql_payload(runtime, manifest)  # type: ignore[arg-type]

        self.assertFalse(result.ok)
        self.assertEqual(result.detail, "install failed")
        self.assertEqual(len(runtime.exec_calls), 1)
        self.assertEqual(len(runtime.copy_calls), 1)
        self.assertEqual(len(runtime.sql_file_calls), 1)


if __name__ == "__main__":
    unittest.main()

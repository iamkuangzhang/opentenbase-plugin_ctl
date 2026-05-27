import subprocess
import unittest
from pathlib import Path

from plugin_ctl.catalog import Catalog
from plugin_ctl.verify import run_removed_verify, run_smoke_verify


class RemovedProbeRuntime:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.sql_calls: list[str] = []

    def run_sql(self, sql: str) -> subprocess.CompletedProcess[str]:
        self.sql_calls.append(sql)
        return subprocess.CompletedProcess(
            args=["psql"],
            returncode=self.returncode,
            stdout=self.stdout,
            stderr="" if self.returncode == 0 else "probe failed",
        )


class SmokeRuntime(RemovedProbeRuntime):
    pass


class VerifyTest(unittest.TestCase):
    def load_smoke_manifest(self):
        root = Path(__file__).resolve().parents[1]
        return Catalog(root=root).load_one("pluginctl_smoke_plugin")

    def test_removed_verify_passes_when_probe_returns_removed(self) -> None:
        manifest = self.load_smoke_manifest()
        runtime = RemovedProbeRuntime("removed\n")
        result = run_removed_verify(runtime, manifest)  # type: ignore[arg-type]

        self.assertTrue(result.ok)
        self.assertEqual(result.detail, "removed verify passed")
        self.assertEqual(result.metadata["stage"], "removed")
        self.assertEqual(len(runtime.sql_calls), 1)

    def test_removed_verify_fails_when_probe_returns_present(self) -> None:
        manifest = self.load_smoke_manifest()
        runtime = RemovedProbeRuntime("present\n")
        result = run_removed_verify(runtime, manifest)  # type: ignore[arg-type]

        self.assertFalse(result.ok)
        self.assertEqual(result.detail, "present")
        self.assertEqual(result.returncode, 1)

    def test_smoke_verify_enforces_expected_stdout(self) -> None:
        manifest = self.load_smoke_manifest()
        runtime = SmokeRuntime("invalid\n")
        result = run_smoke_verify(runtime, manifest, manifest.smoke_sql)  # type: ignore[arg-type]

        self.assertFalse(result.ok)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.detail, "invalid")


if __name__ == "__main__":
    unittest.main()

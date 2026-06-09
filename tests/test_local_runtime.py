from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plugin_ctl.runtime.opentenbase import OpenTenBaseRuntime


class LocalRuntimeTest(unittest.TestCase):
    def test_local_copy_supports_payload_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "payload"
            source.mkdir()
            (source / "install.sql").write_text("select 1;\n", encoding="utf-8")

            runtime = OpenTenBaseRuntime(mode="local")
            result = runtime.copy_to_container(source, str(root / "remote"))

            self.assertEqual(result.returncode, 0)
            self.assertEqual((root / "remote" / "payload" / "install.sql").read_text(encoding="utf-8"), "select 1;\n")

    @patch("plugin_ctl.runtime.opentenbase.subprocess.run")
    def test_local_run_sql_does_not_call_docker(self, run) -> None:
        run.return_value.returncode = 0
        run.return_value.stdout = "1\n"
        run.return_value.stderr = ""

        runtime = OpenTenBaseRuntime(mode="local")
        runtime.run_sql("SELECT 1;")

        argv = run.call_args.args[0]
        self.assertNotIn("docker", argv)
        self.assertIn("-c", argv)
        self.assertIn("SELECT 1;", argv)


if __name__ == "__main__":
    unittest.main()

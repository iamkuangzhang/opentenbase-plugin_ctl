from pathlib import Path
import io
import unittest
from contextlib import redirect_stdout

from plugin_ctl.cli import build_parser, main


class CliProductTest(unittest.TestCase):
    def test_root_help_names_command_groups(self) -> None:
        help_text = build_parser().format_help()

        self.assertIn("usage: plugin_ctl", help_text)

        for group in ["discovery", "governance", "lifecycle", "archive", "distributed", "reporting", "runtime"]:
            self.assertIn(group, help_text)

    def test_pyproject_exposes_product_console_script(self) -> None:
        root = Path(__file__).resolve().parents[1]
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('name = "opentenbase-plugin_ctl"', pyproject)
        self.assertIn('dynamic = ["version"]', pyproject)
        self.assertIn('version = { attr = "plugin_ctl.__version__" }', pyproject)
        self.assertIn('requires-python = ">=3.11"', pyproject)
        self.assertIn('plugin_ctl = "plugin_ctl.cli:main"', pyproject)
        self.assertNotIn("opentenbase-" + "pluginctl", pyproject)
        self.assertNotIn("opentenbase_" + "plugin_ctl", pyproject)

    def test_version_output_is_1_0_0(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as cm:
            main(["--version"])

        self.assertEqual(cm.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), "plugin_ctl 1.0.0")


if __name__ == "__main__":
    unittest.main()

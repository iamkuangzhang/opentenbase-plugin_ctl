from pathlib import Path
import unittest

from plugin_ctl.cli import build_parser


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
        self.assertIn('requires-python = ">=3.11"', pyproject)
        self.assertIn('plugin_ctl = "plugin_ctl.cli:main"', pyproject)
        self.assertIn('opentenbase-pluginctl = "plugin_ctl.cli:main"', pyproject)
        self.assertIn('opentenbase-plugin_ctl = "plugin_ctl.cli:main"', pyproject)


if __name__ == "__main__":
    unittest.main()

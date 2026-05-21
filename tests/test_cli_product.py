from pathlib import Path
import unittest

from datanexus.cli import build_parser


class CliProductTest(unittest.TestCase):
    def test_root_help_names_command_groups(self) -> None:
        help_text = build_parser().format_help()

        for group in ["discovery", "governance", "lifecycle", "archive", "distributed", "reporting", "runtime"]:
            self.assertIn(group, help_text)

    def test_pyproject_exposes_product_console_script(self) -> None:
        root = Path(__file__).resolve().parents[1]
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('name = "opentenbase-pluginctl"', pyproject)
        self.assertIn('opentenbase-pluginctl = "datanexus.cli:main"', pyproject)
        self.assertIn('datanexus = "datanexus.cli:main"', pyproject)


if __name__ == "__main__":
    unittest.main()

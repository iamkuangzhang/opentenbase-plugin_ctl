from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from plugin_ctl.cli import main
from plugin_ctl.source_assess import assess_source


class SourceAssessTest(unittest.TestCase):
    def test_assess_warns_for_c_function_without_shippable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "demo.control").write_text("default_version = '1.0'\n", encoding="utf-8")
            (root / "demo--1.0.sql").write_text(
                "CREATE FUNCTION demo_add(int, int) RETURNS int AS 'MODULE_PATHNAME' LANGUAGE C IMMUTABLE;\n",
                encoding="utf-8",
            )

            items = assess_source(root)

            shippable = next(item for item in items if item.check == "c_function_shippable")
            self.assertEqual(shippable.status, "warn")
            self.assertIn("SHIPPABLE", shippable.detail)

    def test_assess_passes_for_explicit_shippable_function(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "demo.control").write_text("default_version = '1.0'\n", encoding="utf-8")
            (root / "demo--1.0.sql").write_text(
                "CREATE FUNCTION demo_add(int, int) RETURNS int AS 'MODULE_PATHNAME' LANGUAGE C IMMUTABLE SHIPPABLE;\n",
                encoding="utf-8",
            )

            items = assess_source(root)

            self.assertEqual(next(item for item in items if item.check == "c_function_shippable").status, "pass")

    def test_assess_fails_for_c_side_dynamic_table_ddl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "demo.control").write_text("default_version = '1.0'\n", encoding="utf-8")
            (root / "demo.c").write_text('void f(void) { SPI_execute("CREATE TABLE x(id int)", false, 0); }\n', encoding="utf-8")

            items = assess_source(root)

            ddl = next(item for item in items if item.check == "c_dynamic_table_ddl")
            self.assertEqual(ddl.status, "fail")
            self.assertEqual(ddl.path, "demo.c")

    def test_assess_missing_control_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            items = assess_source(Path(tmpdir))

            self.assertEqual(next(item for item in items if item.check == "control_file").status, "fail")


class SourceAssessCliTest(unittest.TestCase):
    def test_assess_json_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "demo.control").write_text("default_version = '1.0'\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["assess", str(root), "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertIn("source_path", payload)
        self.assertIn("items", payload)
        self.assertTrue(payload["items"])


if __name__ == "__main__":
    unittest.main()

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugin_ctl.cli import cmd_report
from plugin_ctl.state_store import StateStore


class ReportTest(unittest.TestCase):
    def test_report_keeps_latest_record_per_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root)
            store.append("otb_timeseries", "deploy", True, "old deploy")
            store.append("otb_timeseries", "verify", True, "verify ok")
            store.append("otb_timeseries", "deploy", True, "new deploy")

            with patch("builtins.print") as mocked_print:
                result = cmd_report(root)

            self.assertEqual(result, 0)
            output = "\n".join(str(call.args[0]) for call in mocked_print.call_args_list)
            self.assertIn("new deploy", output)
            self.assertIn("verify ok", output)
            self.assertNotIn("old deploy", output)

    def test_report_json_contains_governance_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = StateStore(root)
            store.append(
                "pluginctl_smoke_plugin",
                "deploy",
                True,
                "deploy sql payload passed",
                {
                    "version": "0.1.0",
                    "stage": "install",
                    "returncode": 0,
                    "duration_ms": 12,
                },
            )

            with patch("builtins.print") as mocked_print:
                result = cmd_report(root, as_json=True)

            self.assertEqual(result, 0)
            payload = json.loads(mocked_print.call_args.args[0])
            self.assertEqual(payload[0]["plugin_id"], "pluginctl_smoke_plugin")
            self.assertEqual(payload[0]["action"], "deploy")
            self.assertTrue(payload[0]["ok"])
            self.assertEqual(payload[0]["version"], "0.1.0")
            self.assertEqual(payload[0]["stage"], "install")
            self.assertEqual(payload[0]["returncode"], 0)
            self.assertEqual(payload[0]["duration_ms"], 12)
            self.assertEqual(payload[0]["detail"], "deploy sql payload passed")
            self.assertIn("timestamp", payload[0])


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import tempfile
import unittest

from datanexus.state_store import StateStore


class StateStoreTest(unittest.TestCase):
    def test_append_and_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(Path(tmpdir))
            record = store.append("otb_timeseries", "verify", True, "ok", {"returncode": 0})
            latest = store.latest("otb_timeseries")
            self.assertIsNotNone(latest)
            self.assertEqual(latest.plugin_id, record.plugin_id)
            self.assertEqual(latest.action, "verify")
            self.assertTrue(latest.ok)


if __name__ == "__main__":
    unittest.main()

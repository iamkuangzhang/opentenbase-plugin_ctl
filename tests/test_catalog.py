from pathlib import Path
import unittest

from datanexus.catalog import Catalog


class CatalogTest(unittest.TestCase):
    def test_load_timeseries_manifest(self) -> None:
        root = Path(__file__).resolve().parents[1]
        catalog = Catalog(root=root)
        manifest = catalog.load_one("otb_timeseries")
        self.assertEqual(manifest.plugin_id, "otb_timeseries")
        self.assertEqual(manifest.name, "OpenTenBase TimeSeries")
        self.assertTrue(manifest.targets["dn"])

    def test_load_smoke_plugin_manifest_from_examples(self) -> None:
        root = Path(__file__).resolve().parents[1]
        catalog = Catalog(root=root)
        manifest = catalog.load_one("dnx_smoke_plugin")
        self.assertEqual(manifest.plugin_id, "dnx_smoke_plugin")
        self.assertEqual(manifest.source_root, root / "examples" / "plugins" / "dnx_smoke_plugin" / "payload")
        self.assertTrue(manifest.install_sql.exists())
        self.assertTrue(manifest.verify_sql.exists())
        self.assertIsNotNone(manifest.rollback_sql)

    def test_load_legacy_plugin_manifests(self) -> None:
        root = Path(__file__).resolve().parents[1]
        catalog = Catalog(root=root)
        plugin_ids = {manifest.plugin_id for manifest in catalog.load_all()}

        self.assertTrue(
            {
                "otb_age",
                "otb_analytics",
                "otb_fulltext",
                "otb_health",
                "otb_routing",
                "otb_scheduler",
                "otb_snapshot",
                "otb_timeseries",
            }.issubset(plugin_ids)
        )


if __name__ == "__main__":
    unittest.main()

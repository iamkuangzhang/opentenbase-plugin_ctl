import unittest

from datanexus.i18n import normalize_lang, text, value


class I18nTest(unittest.TestCase):
    def test_labels_support_zh_en_and_both(self) -> None:
        self.assertEqual(text("plugin", "zh"), "插件")
        self.assertEqual(text("plugin", "en"), "Plugin")
        self.assertEqual(text("plugin", "both"), "插件 / Plugin")

    def test_values_support_zh_en_and_both(self) -> None:
        self.assertEqual(value("installed", "zh"), "已安装")
        self.assertEqual(value("installed", "en"), "installed")
        self.assertEqual(value("installed", "both"), "已安装 / installed")

    def test_unknown_lang_falls_back_to_zh(self) -> None:
        self.assertEqual(normalize_lang("bad"), "zh")


if __name__ == "__main__":
    unittest.main()

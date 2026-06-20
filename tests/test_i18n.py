import unittest

from plugin_ctl.i18n import normalize_lang, resource_keys, text, value


class I18nTest(unittest.TestCase):
    def test_labels_support_zh_en_and_both(self) -> None:
        self.assertEqual(text("plugin", "zh"), "插件")
        self.assertEqual(text("plugin", "en"), "Plugin")
        self.assertEqual(text("plugin", "both"), "插件 / Plugin")

    def test_values_support_zh_en_and_both(self) -> None:
        self.assertEqual(value("installed", "zh"), "已安装")
        self.assertEqual(value("installed", "en"), "installed")
        self.assertEqual(value("installed", "both"), "已安装 / installed")

    def test_unknown_lang_falls_back_to_en(self) -> None:
        self.assertEqual(normalize_lang("bad"), "en")

    def test_default_lang_is_en(self) -> None:
        self.assertEqual(normalize_lang(None), "en")

    def test_resource_keys_match(self) -> None:
        for section in ["LABELS", "VALUES", "MESSAGES", "COMMAND_HELP"]:
            keys = resource_keys(section)
            self.assertEqual(keys["en"], keys["zh"])


if __name__ == "__main__":
    unittest.main()

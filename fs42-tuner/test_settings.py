"""Tests for settings.py. Run: python3 test_settings.py"""
import json
import os
import shutil
import tempfile
import unittest

import settings


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "settings.json")

    def tearDown(self):
        shutil.rmtree(self.dir)

    # the settings file itself, through one of its settings (the keeper's)
    def test_other_settings_in_the_file_are_kept(self):
        with open(self.path, "w") as f:
            json.dump({"something": {"else": 1}}, f)
        settings.set_keeper({"days_ahead": 10}, self.path)
        self.assertEqual(json.load(open(self.path))["something"], {"else": 1})

    def test_a_broken_or_odd_file_never_raises(self):
        for text in ("{not json", "[1,2]", '{"keeper": 5}', '{"keeper": {"enabled": "maybe", "days_ahead": 300}}'):
            with open(self.path, "w") as f:
                f.write(text)
            k = settings.get_keeper({}, self.path)
            self.assertEqual((k["enabled"], k["days_ahead"]), (True, 7), text)

    def test_the_file_is_readable_and_editable_from_the_host(self):
        settings.set_keeper({"enabled": True}, self.path)
        self.assertEqual(os.stat(self.path).st_mode & 0o666, 0o666)
        self.assertEqual([n for n in os.listdir(self.dir) if n.startswith(".settings-")], [])   # no temp left


class CaptionLanguage(unittest.TestCase):
    def test_english_by_default_and_a_language_is_kept(self):
        path = os.path.join(tempfile.mkdtemp(), "settings.json")
        self.assertEqual(settings.get_captions(path), {"language": "en"})
        self.assertEqual(settings.set_captions({"language": " JA "}, path), {"language": "ja"})
        self.assertEqual(settings.get_captions(path), {"language": "ja"})
        for bad in ("english", "", None, 5):
            with self.assertRaises(settings.SettingsError):
                settings.set_captions({"language": bad}, path)


if __name__ == "__main__":
    unittest.main()

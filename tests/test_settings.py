"""The small config file: where it lives, what it stores, how it fails."""
import json
import os
import tempfile
import unittest
from unittest import mock

from jellyfin_bangumi_ids import settings


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"JBMID_CONFIG_DIR": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_roundtrip(self):
        settings.save({"archive": "/data/bangumi/archive", "url": "http://jf:8096"})
        data = settings.load()
        self.assertEqual(data["archive"], "/data/bangumi/archive")
        self.assertEqual(data["url"], "http://jf:8096")
        self.assertEqual(settings.config_path(),
                         os.path.join(self.tmp.name, "config.json"))

    def test_unknown_keys_are_ignored(self):
        settings.save({"api_key": "secret", "archive": "/a"})
        raw = json.load(open(settings.config_path(), encoding="utf-8"))
        self.assertNotIn("api_key", raw)
        self.assertNotIn("api_key", settings.load())

    def test_unset_removes_one_key(self):
        settings.save({"archive": "/a", "url": "http://x"})
        settings.unset("archive")
        self.assertNotIn("archive", settings.load())
        self.assertEqual(settings.load()["url"], "http://x")

    def test_broken_file_is_ignored(self):
        with open(settings.config_path(), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.assertEqual(settings.load(), {})
        settings.save({"archive": "/a"})
        self.assertEqual(settings.load()["archive"], "/a")

    def test_blank_values_are_dropped(self):
        settings.save({"archive": "   "})
        self.assertNotIn("archive", settings.load())

    @unittest.skipIf(os.name == "nt", "posix permissions")
    def test_file_is_private(self):
        settings.save({"archive": "/a"})
        mode = os.stat(settings.config_path()).st_mode & 0o777
        self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()

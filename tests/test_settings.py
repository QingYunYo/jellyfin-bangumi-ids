"""The small config file: where it lives, what it stores, how it fails."""
import io
import json

FAKE_KEY = "0f9e8d7c6b5a4938271605f4e3d2c1b0"
import os
import tempfile
import unittest
from contextlib import redirect_stderr
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

    def test_ipv4_flag_roundtrip(self):
        settings.save({"ipv4": "on"})
        self.assertEqual(settings.load()["ipv4"], "on")
        settings.save({"ipv4": "off"})
        self.assertEqual(settings.load()["ipv4"], "off")

    def test_roundtrip(self):
        settings.save({"archive": "/data/bangumi/archive", "url": "http://jf:8096"})
        data = settings.load()
        self.assertEqual(data["archive"], "/data/bangumi/archive")
        self.assertEqual(data["url"], "http://jf:8096")
        self.assertEqual(settings.config_path(),
                         os.path.join(self.tmp.name, "config.json"))

    def test_unknown_keys_are_ignored(self):
        settings.save({"bogus": "x", "archive": "/a"})
        raw = json.load(open(settings.config_path(), encoding="utf-8"))
        self.assertNotIn("bogus", raw)
        self.assertNotIn("bogus", settings.load())

    def test_api_key_is_stored_and_masked(self):
        key = FAKE_KEY
        settings.save({"api_key": key})
        self.assertEqual(settings.load()["api_key"], key)
        shown = settings.mask(settings.load()["api_key"])
        self.assertNotIn(key[4:-4], shown)
        self.assertTrue(shown.startswith(key[:4]))
        self.assertEqual(settings.mask("short"), "*****")
        self.assertEqual(settings.mask(""), "")

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


class BrokenFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"JBMID_CONFIG_DIR": self.tmp.name})
        self.env.start()
        settings.LAST_ERROR[:] = []

    def tearDown(self):
        settings.LAST_ERROR[:] = []
        self.env.stop()
        self.tmp.cleanup()

    def test_broken_json_is_reported_not_swallowed(self):
        with open(settings.config_path(), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            data = settings.load()
        self.assertEqual(data, {})
        self.assertTrue(settings.LAST_ERROR)
        self.assertIn("config", stderr.getvalue())

    def test_save_keeps_the_broken_file_as_dot_bad(self):
        with open(settings.config_path(), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        with redirect_stderr(io.StringIO()):
            settings.save({"url": "http://jf:8096"})
        self.assertTrue(os.path.exists(settings.config_path() + ".bad"))
        self.assertEqual(settings.load()["url"], "http://jf:8096")

    def test_unset_on_a_missing_file_creates_nothing(self):
        settings.unset("archive")
        self.assertFalse(os.path.exists(settings.config_path()))

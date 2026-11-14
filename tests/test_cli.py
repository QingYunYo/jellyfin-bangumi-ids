"""Top-level CLI behaviour: exit codes and messages that must not vanish."""
import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from jellyfin_bangumi_ids import cli


class MissingKeyTest(unittest.TestCase):
    def test_missing_key_is_reported_and_exits_1(self):
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"JF_API_KEY": ""}), redirect_stderr(buf):
            code = cli.main(["scan", "--limit", "1"])
        self.assertEqual(code, 1)
        self.assertIn("missing API key", buf.getvalue())

    def test_bare_invocation_prints_help_and_exits_0(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main([])
        self.assertEqual(code, 0)
        self.assertIn("usage", out.getvalue().lower())

    def test_argument_errors_keep_exit_2(self):
        with redirect_stderr(io.StringIO()):
            code = cli.main(["scan", "--no-such-flag"])
        self.assertEqual(code, 2)


class StoredKeyTest(unittest.TestCase):
    """The key can come from the config file, so nothing has to be exported."""

    def setUp(self):
        import tempfile
        from jellyfin_bangumi_ids import settings
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"JBMID_CONFIG_DIR": self.tmp.name,
                                                "JF_API_KEY": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.tmp.cleanup)
        settings.save({"url": "http://jf.example:8096", "api_key": "from-file"})
        self.args = mock.Mock(api_key=None)

    def test_key_falls_back_to_the_config_file(self):
        self.assertEqual(cli.api_key(self.args), "from-file")
        self.assertEqual(self.args.api_key, "from-file")

    def test_flag_wins_over_the_file(self):
        self.args.api_key = "from-flag"
        self.assertEqual(cli.api_key(self.args), "from-flag")

    def test_url_comes_from_the_file(self):
        args = mock.Mock(url=None)
        self.assertEqual(cli.server_url(args), "http://jf.example:8096")

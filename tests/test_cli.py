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


class BareEntryTest(unittest.TestCase):
    def test_top_level_flags_reach_the_menu(self):
        args = cli.build_parser().parse_args(["--write", "--yes", "--lang", "en"])
        self.assertIsNone(getattr(args, "func", None))
        ns = cli._wizard_args(args)
        self.assertTrue(ns.write)
        self.assertTrue(ns.yes)
        self.assertEqual(ns.lang, "en")
        self.assertEqual(ns.timeout, 20.0)


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


class LanguageFlagTest(unittest.TestCase):
    """--lang is a preference at the top level, not a one-shot on the wizard."""

    def setUp(self):
        import tempfile
        from jellyfin_bangumi_ids import settings
        self.settings = settings
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = mock.patch.dict(os.environ, {"JBMID_CONFIG_DIR": self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_top_level_flag_parses_before_the_subcommand(self):
        args = cli.build_parser().parse_args(["--lang", "zh", "config"])
        self.assertEqual(args.lang, "zh")

    def test_top_level_flag_is_stored(self):
        with mock.patch.object(cli, "cmd_doctor", return_value=0), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["--lang", "en", "doctor"]), 0)
        self.assertEqual(self.settings.load()["lang"], "en")


class StoredIpv4Test(unittest.TestCase):
    def test_stored_flag_forces_ipv4(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        calls = []
        args = mock.Mock(ipv4=False, timeout=20.0, url="http://jf:8096", api_key="k")
        with mock.patch.dict(os.environ, {"JBMID_CONFIG_DIR": tmp.name}), \
                mock.patch.object(cli, "force_ipv4", lambda: calls.append(1)):
            cli.settings.save({"ipv4": "on"})
            cli.clients(args)
        self.assertEqual(calls, [1])

    def test_absent_flag_leaves_ipv4_alone(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        calls = []
        args = mock.Mock(ipv4=False, timeout=20.0, url="http://jf:8096", api_key="k")
        with mock.patch.dict(os.environ, {"JBMID_CONFIG_DIR": tmp.name}), \
                mock.patch.object(cli, "force_ipv4", lambda: calls.append(1)):
            cli.clients(args)
        self.assertEqual(calls, [])

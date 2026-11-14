"""The interactive wizard: menus, previews, and the promise that nothing writes unasked."""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from jellyfin_bangumi_ids import settings, wizard
from jellyfin_bangumi_ids.wizard import Session


class FakeJf:
    def libraries(self):
        return {"动漫": "lib-1"}

    def all_series(self, library_name=None):
        return [{"Id": "s1", "Name": "凉宫春日的忧郁"}]

    def get(self, path, params=None):
        return {"Version": "12.4.0"}


def session(tmp, archive="/data/bangumi/archive", yes=False, write=False):
    sess = Session(FakeJf(), mock.MagicMock(), archive, {"Version": "12.4.0"}, yes, write)
    sess.backup_dir = os.path.join(tmp, "backups")
    return sess


def args(**kw):
    base = {"url": None, "api_key": "k", "ipv4": False, "timeout": 5.0, "archive": None,
            "archive_root": None, "search_archive": False, "no_archive": False,
            "verbose": False, "lang": None, "yes": False, "write": False}
    base.update(kw)
    return mock.Mock(**base)


def run_output(fn, *a):
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn(*a)
    return buf.getvalue()


class InputTest(unittest.TestCase):
    def test_confirm_defaults_to_no(self):
        with mock.patch("builtins.input", return_value=""):
            self.assertFalse(wizard._confirm("write?"))

    def test_confirm_accepts_yes(self):
        for answer in ("y", "yes", "是"):
            with mock.patch("builtins.input", return_value=answer):
                self.assertTrue(wizard._confirm("write?"))

    def test_eof_has_its_own_exit_code(self):
        with mock.patch("builtins.input", side_effect=EOFError):
            with self.assertRaises(SystemExit) as ctx:
                wizard._ask("q")
        self.assertEqual(ctx.exception.code, wizard.EOF_CODE)

    def test_choose_back_adds_a_zero_row(self):
        with mock.patch("builtins.input", return_value="0"):
            with self.assertRaises(wizard._Back):
                wizard._choose("pick", [("a", "A"), ("b", "B")], back="返回")

    def test_ask_back_returns_none_on_enter(self):
        with mock.patch("builtins.input", return_value=""):
            with self.assertRaises(wizard._Back):
                wizard._ask_back("dir")

    def test_limit_accepts_a_for_all(self):
        with mock.patch("builtins.input", return_value="a"):
            self.assertIsNone(wizard._limit())

    def test_limit_enter_goes_back(self):
        with mock.patch("builtins.input", return_value=""):
            with self.assertRaises(wizard._Back):
                wizard._limit()

    def test_choose_reprompts(self):
        with mock.patch("builtins.input", side_effect=["9", "2"]):
            got = wizard._choose("pick", [("a", "A"), ("b", "B")])
        self.assertEqual(got, "b")


class NonTtyTest(unittest.TestCase):
    def test_refuses_without_yes(self):
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            self.assertEqual(wizard.run(args(lang=None)), 2)

    def test_yes_mode_takes_defaults_and_exits(self):
        sess = session(tempfile.mkdtemp(), yes=True)
        with mock.patch.object(sys.stdin, "isatty", return_value=False), \
                mock.patch.object(wizard, "_open", return_value=sess), \
                mock.patch.object(wizard, "_ask", return_value="0"), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(wizard.run(args(yes=True, lang="en")), 0)


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sess = session(self.tmp)
        wizard._LANG[0] = "en"
        self.libs = mock.patch.object(wizard, "_choose", return_value="")
        self.libs.start()

    def tearDown(self):
        self.libs.stop()
        wizard._LANG[0] = "zh"

    def test_verify_uses_the_archive_when_present(self):
        with mock.patch.object(wizard, "run_verify_offline",
                               return_value={"counts": {"ids": 10, "dup": 0}}) as offline:
            out = run_output(wizard._flow_verify, self.sess)
        self.assertTrue(offline.called)
        self.assertIn("ids", out)

    def test_verify_falls_back_online(self):
        self.sess.archive = None
        with mock.patch.object(wizard, "run_verify", return_value={"counts": {"ids": 1}}) as online:
            run_output(wizard._flow_verify, self.sess)
        self.assertTrue(online.called)

    def test_episodes_without_changes_does_not_ask(self):
        report = {"summary": {"series_ok": 1, "series_review": 0, "episodes_to_write": 0}}
        with mock.patch.object(wizard, "run_scan", return_value=report), \
                mock.patch.object(wizard, "apply_report") as apply, \
                mock.patch.object(wizard, "_ask", return_value="a"), \
                mock.patch.object(wizard, "_confirm") as confirm:
            out = run_output(wizard._flow_episodes, self.sess)
        self.assertFalse(apply.called)
        self.assertFalse(confirm.called)
        self.assertIn("nothing", out)

    def test_episodes_declined_writes_nothing(self):
        report = {"summary": {"series_ok": 1, "series_review": 0, "episodes_to_write": 3}}
        with mock.patch.object(wizard, "run_scan", return_value=report), \
                mock.patch.object(wizard, "apply_report") as apply, \
                mock.patch.object(wizard, "_ask", return_value="a"), \
                mock.patch.object(wizard, "_confirm", return_value=False):
            out = run_output(wizard._flow_episodes, self.sess)
        self.assertFalse(apply.called)
        self.assertIn("cancelled", out)

    def test_episodes_accepted_applies_with_backup(self):
        report = {"summary": {"series_ok": 1, "series_review": 0, "episodes_to_write": 3}}

        def write_backup(*_args, **_kw):
            with open(_kw["backup_path"], "w", encoding="utf-8") as fh:
                fh.write("[]")

        with mock.patch.object(wizard, "run_scan", return_value=report), \
                mock.patch.object(wizard, "apply_report", side_effect=write_backup) as apply, \
                mock.patch.object(wizard, "_ask", return_value="a"), \
                mock.patch.object(wizard, "_confirm", return_value=True):
            out = run_output(wizard._flow_episodes, self.sess)
        self.assertTrue(apply.called)
        self.assertIn("episodes-", apply.call_args.kwargs["backup_path"])
        self.assertIn("rollback", out)

    def test_seasons_preview_then_write(self):
        with mock.patch.object(wizard, "run_seasons",
                               side_effect=[{"planned": 2}, {"planned": 2}]) as seasons, \
                mock.patch.object(wizard, "_confirm", return_value=True):
            run_output(wizard._flow_seasons, self.sess)
        self.assertEqual(seasons.call_count, 2)
        self.assertTrue(seasons.call_args.kwargs["dry_run"] is False)

    def test_seasons_nothing_planned(self):
        with mock.patch.object(wizard, "run_seasons", return_value={"planned": 0}) as seasons, \
                mock.patch.object(wizard, "_confirm") as confirm:
            out = run_output(wizard._flow_seasons, self.sess)
        self.assertEqual(seasons.call_count, 1)
        self.assertFalse(confirm.called)
        self.assertIn("nothing", out)

    def test_specials_apply_after_confirm(self):
        report = {"summary": {"specials_matched": 2, "specials_cleared": 0, "episodes_to_write": 2}}
        with mock.patch.object(wizard, "run_specials", return_value=report), \
                mock.patch.object(wizard, "apply_report") as apply, \
                mock.patch.object(wizard, "_ask", return_value="a"), \
                mock.patch.object(wizard, "_confirm", return_value=True):
            run_output(wizard._flow_specials, self.sess)
        self.assertTrue(apply.called)

    def test_sync_preview_is_dry_by_default(self):
        with mock.patch.object(wizard, "run_sync", return_value={"exit": 0, "steps": []}) as sync, \
                mock.patch.object(wizard, "_ask", return_value="a"), \
                mock.patch.object(wizard, "_confirm", return_value=False):
            run_output(wizard._flow_sync, self.sess)
        self.assertTrue(sync.call_args.kwargs["dry_run"])

    def test_sync_writes_when_confirmed(self):
        with mock.patch.object(wizard, "run_sync", return_value={"exit": 0, "steps": []}) as sync, \
                mock.patch.object(wizard, "_ask", return_value="a"), \
                mock.patch.object(wizard, "_confirm", return_value=True):
            run_output(wizard._flow_sync, self.sess)
        self.assertFalse(sync.call_args.kwargs["dry_run"])

    def test_rollback_without_backups(self):
        out = run_output(wizard._flow_rollback, self.sess)
        self.assertIn("no backup", out)

    def test_rollback_previews_then_restores(self):
        os.makedirs(self.sess.backup_dir)
        path = os.path.join(self.sess.backup_dir, "ids-1.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[]")
        with mock.patch.object(wizard, "rollback") as roll, \
                mock.patch.object(wizard, "_ask", return_value="1"), \
                mock.patch.object(wizard, "_confirm", return_value=True):
            run_output(wizard._flow_rollback, self.sess)
        self.assertEqual(roll.call_count, 2)
        self.assertTrue(roll.call_args_list[0].kwargs["dry_run"])
        self.assertFalse(roll.call_args_list[1].kwargs.get("dry_run", False))

    def test_bulk_change_needs_the_count_typed(self):
        report = {"summary": {"series_ok": 1, "series_review": 0, "episodes_to_write": 120}}

        def write_backup(*_args, **_kw):
            with open(_kw["backup_path"], "w", encoding="utf-8") as fh:
                fh.write("[]")

        with mock.patch.object(wizard, "run_scan", return_value=report), \
                mock.patch.object(wizard, "apply_report", side_effect=write_backup) as apply, \
                mock.patch.object(wizard, "_ask", return_value="120"), \
                mock.patch.object(wizard, "_confirm", return_value=True):
            out = run_output(wizard._flow_episodes, self.sess)
        self.assertTrue(apply.called)
        self.assertIn("rollback", out)

    def test_bulk_change_wrong_count_writes_nothing(self):
        report = {"summary": {"series_ok": 1, "series_review": 0, "episodes_to_write": 120}}
        with mock.patch.object(wizard, "run_scan", return_value=report), \
                mock.patch.object(wizard, "apply_report") as apply, \
                mock.patch.object(wizard, "_ask", return_value="12"), \
                mock.patch.object(wizard, "_confirm", return_value=True):
            out = run_output(wizard._flow_episodes, self.sess)
        self.assertFalse(apply.called)
        self.assertIn("cancelled", out)

    def test_write_flag_flips_the_default_of_the_write_prompt(self):
        sess = self.sess
        sess.write_default = True
        with mock.patch.object(wizard, "_confirm", return_value=True) as confirm:
            self.assertTrue(sess.confirm("write?"))
        self.assertEqual(confirm.call_args.kwargs.get("default"), True)

    def test_yes_beats_write_flag(self):
        sess = self.sess
        sess.write_default = True
        sess.assume_yes = True
        self.assertFalse(sess.confirm("write?"))

    def test_backup_filter_ignores_reports(self):
        with open(os.path.join(self.tmp, "a-backup.json"), "w", encoding="utf-8") as fh:
            fh.write('[{"item_id": "x", "new": "1"}]')
        with open(os.path.join(self.tmp, "scan-report.json"), "w", encoding="utf-8") as fh:
            fh.write('{"summary": {}}')
        self.assertTrue(wizard._is_backup(os.path.join(self.tmp, "a-backup.json")))
        self.assertFalse(wizard._is_backup(os.path.join(self.tmp, "scan-report.json")))

    def test_config_unset(self):
        with mock.patch.dict(os.environ, {"JBMID_CONFIG_DIR": self.tmp}):
            settings.save({"archive": "/a"})
            with mock.patch.object(wizard, "_choose",
                                   side_effect=["unset", "archive", wizard._Back]):
                run_output(wizard._flow_config, self.sess)
            self.assertNotIn("archive", settings.load())

    def test_english_menu(self):
        wizard._LANG[0] = "en"
        try:
            out = run_output(wizard._menu)
        finally:
            wizard._LANG[0] = "zh"
        self.assertIn("check", out)
        self.assertIn("exit", out)


class ArchiveTest(unittest.TestCase):
    def test_skips_to_online(self):
        with mock.patch.object(wizard, "find_archive", return_value=None), \
                mock.patch.object(wizard, "_choose", return_value="skip"):
            self.assertIsNone(wizard._archive(args(), FakeJf()))

    def test_saves_the_chosen_path(self):
        tmp = tempfile.mkdtemp()
        found = os.path.join(tmp, "archive")
        with mock.patch.dict(os.environ, {"JBMID_CONFIG_DIR": tmp}), \
                mock.patch.object(wizard, "find_archive", side_effect=[None, found]), \
                mock.patch.object(wizard, "_choose", return_value="path"), \
                mock.patch.object(wizard, "_ask", return_value="/typed/path"), \
                mock.patch.object(wizard, "_confirm", return_value=True):
            self.assertEqual(wizard._archive(args(), FakeJf()), found)
            self.assertEqual(settings.load()["archive"], found)


if __name__ == "__main__":
    unittest.main()


class RegressionTest(unittest.TestCase):
    """The four promises the review found broken: back, --yes, counters, gates."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sess = session(self.tmp.name)
        wizard._LANG[0] = "en"
        wizard._NONINTERACTIVE[0] = False
        settings.LAST_ERROR[:] = []

    def tearDown(self):
        wizard._LANG[0] = "zh"
        wizard._NONINTERACTIVE[0] = False
        self.tmp.cleanup()

    def _args(self, **kw):
        base = {"url": None, "api_key": "k", "timeout": 5, "archive": None,
                "archive_root": None, "search_archive": False, "no_archive": False,
                "yes": False, "write": False, "lang": None, "ipv4": False}
        base.update(kw)
        return mock.Mock(**base)

    def test_back_on_the_archive_screen_means_online(self):
        with mock.patch.object(wizard, "find_archive", return_value=None), \
                mock.patch.object(wizard, "archive_hint", return_value=""), \
                mock.patch.object(wizard, "_choose", side_effect=wizard._Back), \
                redirect_stdout(io.StringIO()):
            self.assertIsNone(wizard._archive(self._args(), self.sess.jf))

    def test_back_on_the_first_screen_is_not_a_crash(self):
        tty = mock.Mock()
        tty.isatty.return_value = True
        with mock.patch.object(wizard.sys, "stdin", tty), \
                mock.patch.object(wizard, "_open", side_effect=wizard._Back), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(wizard.run(self._args()), 0)

    def test_yes_without_a_key_never_calls_getpass(self):
        wizard._NONINTERACTIVE[0] = True
        with mock.patch.object(wizard.getpass, "getpass", side_effect=AssertionError), \
                redirect_stdout(io.StringIO()):
            self.assertIsNone(wizard._open(self._args(api_key="")))

    def test_verify_prints_the_real_counters(self):
        report = {"checked": 10, "unknown": 1, "duplicate": 0, "low_similarity": 3,
                  "disorder": 2, "foreign_subject": 0,
                  "season_rows": [{"a": 1}], "span_rows": []}
        with mock.patch.object(wizard, "_choose", return_value=""), \
                mock.patch.object(wizard, "run_verify_offline", return_value=report):
            out = run_output(wizard._flow_verify, self.sess)
        self.assertIn("low-sim", out)
        self.assertIn("season-ids", out)
        self.assertIn("1", out)

    def test_limit_rejects_letters_instead_of_meaning_all(self):
        with mock.patch("builtins.input", side_effect=["x", "7"]), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(wizard._limit(), 7)

    def test_write_flag_does_not_pre_answer_clearing_specials(self):
        self.sess.write_default = True
        report = {"summary": {"specials_matched": 0, "specials_cleared": 0,
                              "episodes_to_write": 0}}
        with mock.patch.object(wizard, "run_specials", return_value=report) as spec, \
                mock.patch.object(wizard, "_confirm", return_value=False) as confirm, \
                mock.patch.object(wizard, "_choose", return_value=""), \
                mock.patch.object(wizard, "_ask", return_value="a"), \
                redirect_stdout(io.StringIO()):
            wizard._flow_specials(self.sess)
        self.assertEqual(confirm.call_args.kwargs.get("default"), False)
        self.assertFalse(spec.call_args.kwargs["clear_borrowed"])

    def test_sync_does_not_ask_to_write_when_the_preview_failed(self):
        preview = {"exit": 1, "steps": [{"step": "scan", "ok": False, "error": "boom"}],
                   "backups": []}
        with mock.patch.object(wizard, "run_sync", return_value=preview) as sync, \
                mock.patch.object(wizard, "_confirm") as confirm, \
                mock.patch.object(wizard, "_choose", return_value=""), \
                mock.patch.object(wizard, "_ask", return_value="a"), \
                redirect_stdout(io.StringIO()):
            wizard._flow_sync(self.sess)
        self.assertEqual(sync.call_count, 1)
        self.assertFalse(confirm.called)


class PlannedCountTest(unittest.TestCase):
    """A sync preview must count season rewrites too, not just episode writes."""

    def test_counts_stats_and_seasons(self):
        preview = {"steps": [
            {"step": "apply", "stats": {"written": 5}},
            {"step": "anchor", "seasons": {"issues": [{"a": 1}, {"b": 2}, {"c": 3}]}},
            {"step": "special", "stats": {"written": 2}},
        ]}
        self.assertEqual(wizard._planned_count(preview), 10)

    def test_missing_keys_count_as_zero(self):
        self.assertEqual(wizard._planned_count({"steps": [{"step": "scan", "ok": True}]}), 0)


class BackupDirTest(unittest.TestCase):
    """--backup-dir / --out-dir must land where the operator asked."""

    def test_backup_and_out_dir_override_the_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            sess = Session(FakeJf(), mock.MagicMock(), None, {"Version": "12"},
                           False, False,
                           backup_dir=os.path.join(tmp, "b"), out_dir=os.path.join(tmp, "o"))
            backup = sess.backup_path("episodes")
            report = sess.report_path("scan")
        self.assertEqual(os.path.dirname(backup), os.path.join(tmp, "b"))
        self.assertEqual(os.path.dirname(report), os.path.join(tmp, "o"))

    def test_default_is_local_backups_under_the_working_directory(self):
        sess = Session(FakeJf(), mock.MagicMock(), None, {"Version": "12"}, False, False)
        self.assertEqual(sess.backup_dir, os.path.join(os.getcwd(), "_local", "backups"))
        self.assertEqual(sess.out_dir, sess.backup_dir)


class FirstRunTest(unittest.TestCase):
    """First contact: URL + key + save, and the key can be kept out of the file."""

    def setUp(self):
        import tempfile
        from jellyfin_bangumi_ids import settings
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"JBMID_CONFIG_DIR": self.tmp.name,
                                                "JF_API_KEY": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.tmp.cleanup)
        self.settings = settings

    def _run(self, save_key=True):
        args = mock.Mock(timeout=5.0, no_save_key=not save_key, url=None, api_key=None)
        args.hide_key = True
        with mock.patch.object(wizard, "_ask", return_value="http://jf:8096"), \
                mock.patch.object(wizard, "probe_url", return_value={"Version": "12.4.0"}), \
                mock.patch.object(wizard.getpass, "getpass", return_value="k-123"), \
                mock.patch.object(wizard.Jellyfin, "ping",
                                  return_value={"version": "12.4.0", "users": 2,
                                                "libraries": 8}), \
                mock.patch.object(wizard, "_confirm", return_value=True):
            return wizard._first_run(args, "http://127.0.0.1:8096", "")

    def test_saves_url_and_key(self):
        url, key = self._run()
        self.assertEqual(url, "http://jf:8096")
        self.assertEqual(key, "k-123")
        self.assertEqual(self.settings.load()["url"], "http://jf:8096")
        self.assertEqual(self.settings.load()["api_key"], "k-123")

    def test_no_save_key_keeps_it_out(self):
        self._run(save_key=False)
        self.assertEqual(self.settings.load()["url"], "http://jf:8096")
        self.assertNotIn("api_key", self.settings.load())


class InputRulesTest(unittest.TestCase):
    """The rules the first-run experience depends on."""

    def test_url_gets_http_when_the_scheme_is_missing(self):
        self.assertEqual(wizard.normalize_url("192.168.1.10:8096"),
                         "http://192.168.1.10:8096")
        self.assertEqual(wizard.normalize_url(" http://jf:8096/ "), "http://jf:8096")
        self.assertEqual(wizard.normalize_url("https://jf"), "https://jf")
        self.assertEqual(wizard.normalize_url(""), "")

    def test_key_is_cleaned_but_not_rewritten(self):
        self.assertEqual(wizard.clean_key("  'abc'  "), ("abc", True))
        self.assertEqual(wizard.clean_key("Bearer abc"), ("abc", True))
        self.assertEqual(wizard.clean_key("abc"), ("abc", False))

    def test_full_width_characters_are_rejected_not_converted(self):
        with mock.patch("builtins.input", side_effect=["１９２", "192"]), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(wizard._read_line("q: ", ascii_only=True), "192")
        self.assertIn("全角", out.getvalue())

    def test_connection_errors_point_at_the_right_field(self):
        self.assertEqual(wizard.classify_conn(Exception("unknown url type: 192.168.1.2")), "url")
        self.assertEqual(wizard.classify_conn(Exception("HTTP 401")), "key")
        self.assertEqual(wizard.classify_conn(Exception("boom")), "other")
        self.assertIn("http://", wizard.explain_conn(Exception("unknown url type: x")))

    def test_yes_no_bracket_names_the_action_and_the_default(self):
        seen = {}

        def fake_input(prompt):
            seen["prompt"] = prompt
            return ""

        with mock.patch("builtins.input", side_effect=fake_input):
            wizard._confirm("重试？", default=True, actions="Y=重新输入地址，n=放弃")
        self.assertIn("Y=重新输入地址", seen["prompt"])
        self.assertIn("回车默认Y", seen["prompt"])

    def test_a_failed_save_says_so(self):
        with mock.patch.object(wizard.settings, "save", side_effect=OSError(13, "denied")), \
                redirect_stdout(io.StringIO()) as out:
            self.assertFalse(wizard.save_settings({"url": "http://x"}))
        self.assertIn("没保存", out.getvalue())


class LanguageTest(unittest.TestCase):
    """Menu language: --lang wins, then JBMID_LANG, then the POSIX locale."""

    def setUp(self):
        self.saved = dict(os.environ)
        for name in ("JBMID_LANG", "LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
            os.environ.pop(name, None)
        wizard._LANG[0] = "zh"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved)
        wizard._LANG[0] = "zh"

    def test_unset_locale_stays_chinese(self):
        self.assertEqual(wizard.detect_lang(), "zh")

    def test_english_locale_switches(self):
        os.environ["LANG"] = "en_US.UTF-8"
        self.assertEqual(wizard.detect_lang(), "en")

    def test_chinese_locale_stays(self):
        os.environ["LANG"] = "zh_CN.UTF-8"
        self.assertEqual(wizard.detect_lang(), "zh")

    def test_c_locale_is_not_english(self):
        os.environ["LANG"] = "C"
        self.assertEqual(wizard.detect_lang(), "zh")

    def test_jbmid_lang_wins_over_lang(self):
        os.environ["LANG"] = "en_US.UTF-8"
        os.environ["JBMID_LANG"] = "zh"
        self.assertEqual(wizard.detect_lang(), "zh")

    def test_explicit_lang_overrides_environment(self):
        os.environ["LANG"] = "en_US.UTF-8"
        wizard.set_lang("zh")
        self.assertEqual(wizard.language(), "zh")
        wizard.set_lang("en")
        self.assertEqual(wizard.language(), "en")

    def test_menu_label_follows_language(self):
        wizard.set_lang("en")
        self.assertEqual(wizard.t("retry"), "Try again?")
        wizard.set_lang("zh")
        self.assertEqual(wizard.t("retry"), "重试？")

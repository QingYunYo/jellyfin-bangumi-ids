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
                mock.patch.object(wizard, "_ask", return_value="0"):
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
                mock.patch.object(wizard, "_ask", return_value=""), \
                mock.patch.object(wizard, "_confirm") as confirm:
            out = run_output(wizard._flow_episodes, self.sess)
        self.assertFalse(apply.called)
        self.assertFalse(confirm.called)
        self.assertIn("nothing", out)

    def test_episodes_declined_writes_nothing(self):
        report = {"summary": {"series_ok": 1, "series_review": 0, "episodes_to_write": 3}}
        with mock.patch.object(wizard, "run_scan", return_value=report), \
                mock.patch.object(wizard, "apply_report") as apply, \
                mock.patch.object(wizard, "_ask", return_value=""), \
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
                mock.patch.object(wizard, "_ask", return_value=""), \
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
                mock.patch.object(wizard, "_ask", return_value=""), \
                mock.patch.object(wizard, "_confirm", return_value=True):
            run_output(wizard._flow_specials, self.sess)
        self.assertTrue(apply.called)

    def test_sync_preview_is_dry_by_default(self):
        with mock.patch.object(wizard, "run_sync", return_value={"exit": 0, "steps": []}) as sync, \
                mock.patch.object(wizard, "_ask", return_value=""), \
                mock.patch.object(wizard, "_confirm", return_value=False):
            run_output(wizard._flow_sync, self.sess)
        self.assertTrue(sync.call_args.kwargs["dry_run"])

    def test_sync_writes_when_confirmed(self):
        with mock.patch.object(wizard, "run_sync", return_value={"exit": 0, "steps": []}) as sync, \
                mock.patch.object(wizard, "_ask", return_value=""), \
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
            with mock.patch.object(wizard, "_choose", side_effect=["unset", "archive"]):
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

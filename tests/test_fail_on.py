"""--fail-on turns report counters into an exit code for scripts and CI."""
import argparse
import unittest
from unittest import mock

from jellyfin_bangumi_ids import cli
from jellyfin_bangumi_ids.verify import fail_on_breaches

REPORT = {
    "checked": 10,
    "unknown": 0,
    "duplicate": 2,
    "low_similarity": 3,
    "foreign_subject": 0,
    "disorder": 1,
    "anchor_rows": [],
    "season_rows": [{"season": 1}],
    "span_rows": [],
    "duplicate_series": [],
    "rows": [{"series": "A", "error": "boom"}, {"series": "A"}, {"series": "B"}],
    "by_series": [],
}


class FailOnBreachesTest(unittest.TestCase):
    def test_none_and_absent_disable_the_gate(self):
        self.assertEqual(fail_on_breaches(REPORT, None), [])
        self.assertEqual(fail_on_breaches(REPORT, ""), [])
        self.assertEqual(fail_on_breaches(REPORT, "none"), [])
        self.assertEqual(fail_on_breaches(REPORT, "none,low-sim"), [])

    def test_counts_above_zero_are_reported_in_order(self):
        self.assertEqual(fail_on_breaches(REPORT, "low-sim,dup"), [("low-sim", 3), ("dup", 2)])
        self.assertEqual(fail_on_breaches(REPORT, "foreign"), [])
        self.assertEqual(fail_on_breaches(REPORT, "disorder"), [("disorder", 1)])

    def test_rows_and_error_rows_are_counted(self):
        self.assertEqual(fail_on_breaches(REPORT, "season-ids"), [("season-ids", 1)])
        self.assertEqual(fail_on_breaches(REPORT, "errors"), [("errors", 1)])
        self.assertEqual(fail_on_breaches(REPORT, "anchors"), [])

    def test_aliases_and_underscores(self):
        self.assertEqual(fail_on_breaches(REPORT, "low_similarity"), [("low-similarity", 3)])
        self.assertEqual(fail_on_breaches(REPORT, "duplicate"), [("duplicate", 2)])
        self.assertEqual(fail_on_breaches(REPORT, "season-spans"), [])

    def test_unknown_key_is_refused_instead_of_passing(self):
        with self.assertRaises(SystemExit) as err:
            fail_on_breaches(REPORT, "low-sim,low-simm")
        self.assertIn("unknown --fail-on item 'low-simm'", str(err.exception))
        self.assertIn("low-sim", str(err.exception))


class ExitCodeTest(unittest.TestCase):
    def args(self, fail_on=None, by_series=False):
        return argparse.Namespace(library=None, limit=None, threshold=0.45,
                                  out="jbmid-check.json", series_id=None,
                                  by_series=by_series, fail_on=fail_on, no_archive=True,
                                  archive=None, verbose=False, url=None, api_key=None,
                                  ipv4=False, timeout=20.0)

    def run_verify(self, report, **kwargs):
        with mock.patch.object(cli, "clients", return_value=(mock.Mock(), mock.Mock())), \
                mock.patch.object(cli, "data_source", return_value=None), \
                mock.patch.object(cli, "run_verify", return_value=report):
            return cli.cmd_verify(self.args(**kwargs))

    def test_clean_report_exits_zero(self):
        report = {"checked": 3, "low_similarity": 0, "rows": [], "by_series": []}
        self.assertEqual(self.run_verify(report, fail_on="low-sim"), 0)

    def test_breach_exits_one(self):
        report = {"checked": 3, "low_similarity": 2, "rows": [], "by_series": []}
        self.assertEqual(self.run_verify(report, fail_on="low-sim"), 1)

    def test_fail_on_none_overrides_a_dirty_report(self):
        report = {"checked": 3, "low_similarity": 2, "rows": [], "by_series": []}
        self.assertEqual(self.run_verify(report, fail_on="none"), 0)

    def test_no_checked_id_still_exits_one(self):
        report = {"checked": 0, "low_similarity": 0, "rows": [], "by_series": []}
        self.assertEqual(self.run_verify(report), 1)

    def test_by_series_prints_the_aggregate(self):
        report = {"checked": 3, "low_similarity": 1,
                  "rows": [{"series": "A", "item_id": "e1"}],
                  "by_series": [{"series": "A", "episodes": 3, "total": 1,
                                 "low_similarity": 1, "duplicate": 0, "disorder": 0,
                                 "foreign_subject": 0, "unknown_id": 0, "coverage": 0.6667}]}
        with mock.patch("builtins.print") as out:
            self.assertEqual(self.run_verify(report, by_series=True), 0)
        printed = " ".join(str(call) for call in out.call_args_list)
        self.assertIn("cover", printed)
        self.assertIn("A", printed)
        self.assertIn("67%", printed)


if __name__ == "__main__":
    unittest.main()

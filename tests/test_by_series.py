"""verify --by-series: the findings grouped per show, worst first."""
import contextlib
import io
import json
import os
import tempfile
import unittest

from jellyfin_bangumi_ids.cli import print_by_series
from jellyfin_bangumi_ids.verify import by_series, run_verify_offline


def ep(item_id, name, pid=None):
    row = {"Id": item_id, "Name": name, "IndexNumber": 1, "ParentIndexNumber": 1,
           "ProviderIds": {}}
    if pid:
        row["ProviderIds"]["Bangumi"] = str(pid)
    return row


class FakeJf:
    def __init__(self, series, episodes):
        self._series = series
        self._episodes = episodes

    def all_series(self, library_name=None, limit=None):
        return list(self._series)

    def episodes(self, series_id):
        return list(self._episodes.get(series_id, []))


def write_archive(directory, subjects, episodes):
    with open(os.path.join(directory, "subject.jsonlines"), "w", encoding="utf-8") as fh:
        for row in subjects:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(os.path.join(directory, "episode.jsonlines"), "w", encoding="utf-8") as fh:
        for row in episodes:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


class BySeriesTest(unittest.TestCase):
    def report(self):
        return {"rows": [
            {"series": "A", "item_id": "a1", "kind": "low_similarity"},
            {"series": "A", "item_id": "a2", "kind": "low_similarity"},
            {"series": "A", "item_id": "a3", "kind": "low_similarity"},
            {"series": "A", "item_id": "a4", "kind": "disorder"},
            {"series": "A", "item_id": "a5", "error": "boom"},
            {"series": "B", "item_id": "b1", "kind": "low_similarity"},
        ]}

    def test_counts_and_coverage_per_series(self):
        rows = by_series(self.report(), checked={"A": 6, "B": 4})
        self.assertEqual([r["series"] for r in rows], ["A", "B"])
        first, second = rows
        self.assertEqual(first["episodes"], 6)
        self.assertEqual(first["total"], 5)
        self.assertEqual(first["low_similarity"], 3)
        self.assertEqual(first["disorder"], 1)
        self.assertEqual(first["errors"], 1)
        self.assertEqual(first["coverage"], round(1 / 6.0, 4))
        self.assertEqual(second["episodes"], 4)
        self.assertEqual(second["total"], 1)
        self.assertEqual(second["coverage"], 0.75)

    def test_unknown_kind_falls_back_to_low_similarity(self):
        rows = by_series({"rows": [{"series": "A", "item_id": "a1"}]}, checked={"A": 2})
        self.assertEqual(rows[0]["low_similarity"], 1)

    def test_duplicates_are_added_per_series(self):
        rows = by_series({"rows": []}, checked={"A": 4}, duplicates={"A": 2})
        self.assertEqual(rows[0]["duplicate"], 2)
        self.assertEqual(rows[0]["total"], 2)

    def test_series_without_checked_episodes_do_not_divide_by_zero(self):
        rows = by_series({"rows": [{"series": "A", "item_id": "x"}]})
        self.assertEqual(rows[0]["episodes"], 0)
        self.assertEqual(rows[0]["coverage"], 0.0)

    def test_sorted_by_findings_then_episode_count(self):
        report = {"rows": [{"series": "small", "item_id": "s1"},
                           {"series": "big", "item_id": "b1"},
                           {"series": "big", "item_id": "b2"}]}
        rows = by_series(report, checked={"small": 2, "big": 10})
        self.assertEqual([r["series"] for r in rows], ["big", "small"])


class OfflineReportTest(unittest.TestCase):
    def build(self, d):
        write_archive(
            d,
            [{"id": 100, "name": "Series", "name_cn": "剧名", "type": 2, "eps": 2}],
            [{"id": 1, "subject_id": 100, "sort": 1, "type": 0, "name": "a", "name_cn": "第一话"},
             {"id": 2, "subject_id": 100, "sort": 2, "type": 0, "name": "b", "name_cn": "第二话"}])
        jf = FakeJf([{"Id": "s1", "Name": "剧名", "OriginalTitle": "Series",
                      "ProviderIds": {"Bangumi": "100"}}],
                    {"s1": [ep("e1", "第一话", 1), ep("e2", "完全不同的标题", 2)]})
        return jf

    def test_report_carries_the_by_series_block(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "check.json")
            report = run_verify_offline(self.build(d), d, out=out)
            with open(out, encoding="utf-8") as fh:
                saved = json.load(fh)
        self.assertIn("by_series", saved)
        rows = report["by_series"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["series"], "剧名")
        self.assertEqual(rows[0]["episodes"], 2)
        self.assertEqual(rows[0]["low_similarity"], 1)
        self.assertEqual(rows[0]["total"], 1)
        self.assertEqual(rows[0]["coverage"], 0.5)


class PrintTest(unittest.TestCase):
    def test_prints_a_header_and_at_most_twenty_rows(self):
        rows = [{"series": "剧%02d" % i, "episodes": 12, "total": 25 - i,
                 "low_similarity": 25 - i, "duplicate": 0, "disorder": 0,
                 "foreign_subject": 0, "unknown_id": 0, "coverage": 0.8333}
                for i in range(25)]
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            print_by_series(rows)
        lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(lines), 21)
        self.assertIn("cover", lines[0])
        self.assertIn("low", lines[0])
        self.assertIn("剧00", lines[1])
        self.assertIn("83%", lines[1])
        self.assertEqual(len(rows), 25)           # the caller's list is untouched

    def test_empty_report_says_nothing_was_flagged(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            print_by_series([])
        self.assertIn("nothing flagged", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()

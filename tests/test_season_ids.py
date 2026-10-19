"""Tests for season-level Bangumi id voting (the plugin reports 在看 with these)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from collections import Counter

from jellyfin_bangumi_ids.anchor import run_seasons
from jellyfin_bangumi_ids.scan import season_id_issues


def season(index, item_id, pid=None, name=None):
    ids = {"Bangumi": str(pid)} if pid is not None else {}
    return {"Id": item_id, "IndexNumber": index, "Name": name or "第 %d 季" % index,
            "ProviderIds": ids}


def episode(item_id, eid):
    return {"Id": item_id, "ProviderIds": {"Bangumi": str(eid)}}


class FakeJellyfin:
    def __init__(self, seasons, episodes, series=None):
        self._seasons = seasons
        self._episodes = episodes
        self._series = series or [{"Id": "s1", "Name": "某动画", "ProviderIds": {}}]
        self.writes = []

    def seasons(self, series_id):
        return self._seasons

    def season_episodes(self, season_id):
        return self._episodes.get(season_id, [])

    def find_series(self, name, library_name=None):
        return self._series[0]

    def all_series(self, library_name=None, limit=None):
        return list(self._series)

    def set_provider_id(self, item_id, provider, value):
        self.writes.append((item_id, provider, value))
        return {"ok": True, "before": None, "after": str(value), "collateral": {}}


class FakeBangumi:
    def __init__(self, mapping):
        self.mapping = mapping

    def episode(self, eid):
        return {"subject_id": self.mapping[int(eid)]}


class SeasonIssueTest(unittest.TestCase):
    def test_matching_season_is_not_reported(self):
        issues = season_id_issues([season(1, "se1", 100)], {1: Counter({100: 5})})
        self.assertEqual(issues, [])

    def test_shifted_season_is_reported_with_votes(self):
        issues = season_id_issues([season(3, "se3", 373247)], {3: Counter({501963: 4, 373247: 1})})
        self.assertEqual(len(issues), 1)
        row = issues[0]
        self.assertEqual((row["season"], row["current"], row["expected"]), (3, "373247", 501963))
        self.assertEqual((row["count"], row["total"]), (4, 5))
        self.assertEqual(row["votes"], {501963: 4, 373247: 1})

    def test_missing_season_id_counts_as_mismatch(self):
        issues = season_id_issues([season(1, "se1", None)], {1: Counter({100: 2})})
        self.assertEqual(issues[0]["current"], None)

    def test_specials_and_empty_votes_are_ignored(self):
        seasons = [season(0, "sp", 999), season(2, "se2", 200)]
        self.assertEqual(season_id_issues(seasons, {0: Counter({100: 3})}), [])
        self.assertEqual(season_id_issues(seasons, {2: Counter()}), [])


class RunSeasonsTest(unittest.TestCase):
    def build(self, confident=True):
        seasons = [season(1, "se1", 200), season(2, "se2", 300)]
        eps = {"se1": [episode("e1", 1), episode("e2", 2)],
               "se2": [episode("e3", 3), episode("e4", 4)]}
        mapping = {1: 100, 2: 100, 3: 400, 4: 400}
        return FakeJellyfin(seasons, eps), FakeBangumi(mapping)

    def test_dry_run_reports_without_writing(self):
        jf, bgm = self.build()
        out = run_seasons(jf, bgm, name="某动画", dry_run=True)
        self.assertEqual(len(out["issues"]), 2)
        self.assertEqual(out["fixed"], 0)
        self.assertEqual(jf.writes, [])

    def test_writes_confident_seasons(self):
        jf, bgm = self.build()
        out = run_seasons(jf, bgm, name="某动画")
        self.assertEqual(out["fixed"], 2)
        self.assertEqual(jf.writes, [("se1", "Bangumi", 100), ("se2", "Bangumi", 400)])

    def test_low_confidence_needs_force(self):
        seasons = [season(1, "se1", 200)]
        eps = {"se1": [episode("e1", 1), episode("e2", 2)]}
        jf = FakeJellyfin(seasons, eps)
        bgm = FakeBangumi({1: 300, 2: 400})
        out = run_seasons(jf, bgm, name="某动画")
        self.assertEqual(out["fixed"], 0)
        self.assertFalse(out["issues"][0]["confident"])
        out = run_seasons(jf, bgm, name="某动画", force=True)
        self.assertEqual(out["fixed"], 1)

    def test_backup_is_written(self):
        jf, bgm = self.build()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "backup.json")
            run_seasons(jf, bgm, name="某动画", backup_path=path)
            rows = json.load(open(path))
        self.assertEqual([r["season"] for r in rows], [1, 2])
        self.assertEqual(rows[0]["kind"], "season")
        self.assertEqual(rows[0]["old"], "200")
        self.assertEqual(rows[0]["new"], 100)

    def test_all_series_walks_the_library(self):
        seasons = [season(1, "se1", 200)]
        eps = {"se1": [episode("e1", 1)]}
        series = [{"Id": "s1", "Name": "A", "ProviderIds": {}},
                  {"Id": "s2", "Name": "B", "ProviderIds": {}}]
        jf = FakeJellyfin(seasons, eps, series)
        out = run_seasons(jf, FakeBangumi({1: 100}), all_series=True)
        self.assertEqual(out["series"], 2)


if __name__ == "__main__":
    unittest.main()

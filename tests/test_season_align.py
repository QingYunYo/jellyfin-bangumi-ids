"""Season-level alignment: a library may split a franchise its own way."""
import unittest
from unittest.mock import patch

from jellyfin_bangumi_ids.auto import scan_auto
from jellyfin_bangumi_ids.match import align, align_scores
from jellyfin_bangumi_ids.scan import OK, REVIEW, scan_series
from jellyfin_bangumi_ids.season_align import plan_segments


def bgm_ep(eid, name):
    return {"id": eid, "name": name, "name_cn": name, "sort": eid}


def bgm_eps(first, count, pattern="第%d话"):
    return [bgm_ep(first + i, pattern % (i + 1)) for i in range(count)]


def local_ep(item_id, name, season=1, index=1, pid=None):
    out = {"Id": item_id, "Name": name, "IndexNumber": index, "ParentIndexNumber": season}
    if pid is not None:
        out["ProviderIds"] = {"Bangumi": str(pid)}
    return out


def local_season(first, count, pattern, season=1, pids=None):
    return [local_ep("e%d-%d" % (season, i), pattern % (i + 1), season, i + 1,
                     None if pids is None else pids[i])
            for i in range(count)]


class FakeBgm:
    """Network-free Bangumi stand-in with explicit chains."""

    def __init__(self, subjects, chains=None, names=None, results=None):
        self.subjects = subjects          # {subject_id: [episode dicts]}
        self.chains = chains or []        # [[subject ids]] in airing order
        self.names = names or {}
        self.results = results or {}

    def subject(self, sid):
        title = self.names.get(sid) or "T"
        return {"id": sid, "name_cn": title, "name": title}

    def relations(self, sid):
        return []

    def chain(self, sid):
        for chain in self.chains:
            if sid in chain:
                return list(chain)
        return [sid]

    def episode_list(self, sid):
        return list(self.subjects.get(sid, []))

    def episodes(self, sid, ep_type=0):
        return []

    def search(self, keyword, limit=10):
        return list(self.results.get(keyword, []))


class FakeJf:
    def __init__(self, item, seasons):
        self.series = item
        self._seasons = seasons          # [(season_no, [episode dicts])]

    def all_series(self, library_name=None, limit=None):
        return [self.series]

    def seasons(self, series_id):
        return [{"Id": "s%d" % no, "IndexNumber": no} for no, _ in self._seasons]

    def season_episodes(self, season_id):
        number = int(season_id[1:])
        for season_no, episodes in self._seasons:
            if season_no == number:
                return list(episodes)
        return []

    def set_provider_id(self, item_id, provider, value):
        return {"ok": True, "before": None, "after": str(value), "collateral": {}}


def show(name="T", sid="sid1", pid=None):
    out = {"Id": sid, "Name": name, "ProviderIds": {}}
    if pid:
        out["ProviderIds"]["Bangumi"] = str(pid)
    return out


class AlignScoresTest(unittest.TestCase):
    def test_matrix_form_matches_name_form(self):
        names = ["白夜", "觉悟", "完全不同"]
        pool = [bgm_ep(1, "白夜"), bgm_ep(2, "觉悟"), bgm_ep(3, "别的")]
        from jellyfin_bangumi_ids.match import episode_similarity
        scores = [[episode_similarity(n, ep) for ep in pool] for n in names]
        self.assertEqual(align_scores(scores), align(names, pool))

    def test_empty_matrix(self):
        self.assertEqual(align_scores([]), [])


class PlanTest(unittest.TestCase):
    """``plan_segments`` alone: which subjects does each local season claim?"""

    def ubw_like(self):
        prequel = [bgm_ep(1000 + i, "零之战 第%d话" % (i + 1)) for i in range(25)]
        first = [bgm_ep(2000, "序章")] + [bgm_ep(2001 + i, "正传 第%d话" % (i + 1))
                                          for i in range(12)]
        second = [bgm_ep(3000 + i, "终章 第%d话" % (i + 1)) for i in range(13)]
        bgm = FakeBgm({10639: prequel, 95225: first, 109386: second},
                      chains=[[10639, 95225, 109386]])
        groups = [local_season(0, 12, "正传 第%d话"), local_season(0, 13, "终章 第%d话", season=2)]
        return bgm, groups

    def test_two_seasons_claim_two_of_three_subjects(self):
        bgm, groups = self.ubw_like()
        plan = plan_segments(groups, [10639, 95225, 109386], bgm)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.spans, [[95225], [109386]])
        self.assertEqual([len(pairs) for _, _, pairs in plan.segments], [12, 13])

    def test_movie_between_seasons_is_skipped(self):
        bgm = FakeBgm({37685: bgm_eps(100, 22, "第一季 第%d话"),
                       77625: bgm_eps(200, 11, "第二季 第%d话"),
                       83067: [bgm_ep(300, "剧场版")],
                       277105: bgm_eps(400, 8, "第三季 第%d话")},
                      chains=[[37685, 77625, 83067, 277105]])
        groups = [local_season(0, 22, "第一季 第%d话"),
                  local_season(0, 11, "第二季 第%d话", season=2),
                  local_season(0, 8, "第三季 第%d话", season=3)]
        plan = plan_segments(groups, [37685, 77625, 83067, 277105], bgm)
        self.assertEqual(plan.spans, [[37685], [77625], [277105]])

    def test_stored_ids_match_a_season_missing_one_episode(self):
        """Rick and Morty S5: names are useless, the stored ids know the hole."""
        pool = bgm_eps(500, 10, "Rick %d")
        kept = [500, 501, 502, 503, 504, 506, 507, 508, 509]   # episode 506 is missing
        bgm = FakeBgm({93377: bgm_eps(400, 10, "S1 %d"), 331936: pool},
                      chains=[[93377, 331936]])
        groups = [local_season(0, 10, "S1 %d"),
                  local_season(0, 9, "完全不同的名字 %d", season=2, pids=kept)]
        plan = plan_segments(groups, [93377, 331936], bgm)
        self.assertEqual(plan.spans, [[93377], [331936]])
        self.assertEqual(plan.segments[1][2], [(i, i if i < 5 else i + 1) for i in range(9)])

    def test_no_evidence_returns_none(self):
        bgm = FakeBgm({1: bgm_eps(100, 5, "甲 %d"), 2: bgm_eps(200, 5, "乙 %d")},
                      chains=[[1, 2]])
        groups = [local_season(0, 4, "毫无关系 %d"), local_season(0, 6, "也毫无关系 %d", season=2)]
        self.assertIsNone(plan_segments(groups, [1, 2], bgm))

    def test_two_seasons_on_one_subject_are_rejected(self):
        bgm = FakeBgm({1: bgm_eps(100, 3, "甲 %d"), 2: bgm_eps(200, 1, "乙 %d")},
                      chains=[[1, 2]])
        ids = [100, 101, 102]
        groups = [local_season(0, 3, "甲 %d", pids=ids),
                  local_season(0, 3, "甲 %d", season=2, pids=ids)]
        self.assertIsNone(plan_segments(groups, [1, 2], bgm))

    def test_single_season_is_not_planned(self):
        bgm = FakeBgm({1: bgm_eps(100, 3, "甲 %d"), 2: bgm_eps(200, 3, "乙 %d")},
                      chains=[[1, 2]])
        self.assertIsNone(plan_segments([local_season(0, 3, "甲 %d")], [1, 2], bgm))


class ScanSeasonMapTest(unittest.TestCase):
    """``scan_series`` uses the plan only when the flat pool would fail."""

    def ubw_like(self):
        prequel = [bgm_ep(1000 + i, "零之战 第%d话" % (i + 1)) for i in range(25)]
        first = [bgm_ep(2000, "序章")] + [bgm_ep(2001 + i, "正传 第%d话" % (i + 1))
                                          for i in range(12)]
        second = [bgm_ep(3000 + i, "终章 第%d话" % (i + 1)) for i in range(13)]
        bgm = FakeBgm({10639: prequel, 95225: first, 109386: second},
                      chains=[[10639, 95225, 109386]])
        jf = FakeJf(show(pid=95225), [(1, local_season(0, 12, "正传 第%d话")),
                                      (2, local_season(0, 13, "终章 第%d话", season=2))])
        return jf, bgm

    def test_flat_pool_would_mismatch(self):
        jf, bgm = self.ubw_like()
        entry = scan_series(jf, bgm, jf.series)
        self.assertEqual(entry["status"], OK)
        self.assertEqual(entry["chain"], [10639, 95225, 109386])
        self.assertEqual(len(entry["episodes"]), 25)
        self.assertEqual([e["bgm_id"] for e in entry["episodes"][:3]],
                         ["2001", "2002", "2003"])
        self.assertEqual(entry["episodes"][-1]["bgm_id"], "3012")
        self.assertTrue(any(note.startswith("season map") for note in entry["notes"]))

    def test_failed_plan_keeps_the_flat_review(self):
        bgm = FakeBgm({1: bgm_eps(100, 5, "甲 %d"), 2: bgm_eps(200, 5, "乙 %d"),
                       3: bgm_eps(300, 5, "丙 %d")},
                      chains=[[1, 2, 3]], names={1: "T", 2: "T", 3: "T"})
        jf = FakeJf(show(pid=1), [(1, local_season(0, 4, "毫无关系 %d")),
                                 (2, local_season(0, 3, "也毫无关系 %d", season=2))])
        entry = scan_series(jf, bgm, jf.series)
        self.assertEqual(entry["status"], REVIEW)
        self.assertIn("size mismatch", entry["reason"])
        self.assertEqual(entry["coverage"], 0.0)
        self.assertFalse(any(note.startswith("season map") for note in entry["notes"]))

    def test_single_season_still_uses_the_flat_pool(self):
        bgm = FakeBgm({1: bgm_eps(100, 5, "甲 %d"), 2: bgm_eps(200, 5, "乙 %d")},
                      chains=[[1, 2]], names={1: "T", 2: "T"})
        jf = FakeJf(show(pid=1), [(1, local_season(0, 3, "甲 %d"))])
        entry = scan_series(jf, bgm, jf.series)
        self.assertEqual(entry["status"], REVIEW)
        self.assertIn("size mismatch", entry["reason"])


class AutoSeasonMapTest(unittest.TestCase):
    def setUp(self):
        quiet = patch("jellyfin_bangumi_ids.auto.log")
        quiet.start()
        self.addCleanup(quiet.stop)

    def test_auto_uses_the_season_map(self):
        pool = bgm_eps(500, 10, "Rick %d")
        kept = [500, 501, 502, 503, 504, 506, 507, 508, 509]
        bgm = FakeBgm({93377: bgm_eps(400, 10, "S1 %d"), 331936: pool},
                      chains=[[93377, 331936]],
                      results={"T": [{"id": 93377, "name": "T", "name_cn": "T"}]})
        jf = FakeJf(show(), [(1, local_season(0, 10, "S1 %d")),
                             (2, local_season(0, 9, "完全不同 %d", season=2, pids=kept))])
        entry = scan_auto(jf, bgm)[0]
        self.assertEqual(entry["status"], OK)
        self.assertEqual(entry["method"], "season-map")
        self.assertEqual([e["bgm_id"] for e in entry["episodes"][-2:]], ["508", "509"])
        self.assertEqual(len(entry["episodes"]), 19)
        self.assertIn("331936", entry["reason"])

    def test_auto_trusts_a_stored_anchor_when_the_title_is_not_findable(self):
        pool = bgm_eps(500, 10, "Rick %d")
        kept = [500, 501, 502, 503, 504, 506, 507, 508, 509]
        bgm = FakeBgm({93377: bgm_eps(400, 10, "S1 %d"), 331936: pool},
                      chains=[[93377, 331936]], results={})
        jf = FakeJf(show(pid=93377), [(1, local_season(0, 10, "S1 %d")),
                                      (2, local_season(0, 9, "完全不同 %d", season=2, pids=kept))])
        entry = scan_auto(jf, bgm)[0]
        self.assertEqual(entry["status"], OK)
        self.assertEqual(entry["subject"], 93377)
        self.assertEqual(len(entry["episodes"]), 19)

    def test_auto_prefers_a_plan_that_covers_every_episode(self):
        bgm = FakeBgm({1: bgm_eps(100, 3, "零 %d"), 2: bgm_eps(200, 3, "甲 %d"),
                       3: bgm_eps(300, 3, "乙 %d")},
                      chains=[[1, 2, 3]],
                      results={"T": [{"id": 2, "name": "T", "name_cn": "T"}]})
        untranslated = local_season(0, 3, "甲 %d", pids=[200, 201, 202])
        untranslated[2] = local_ep("e1-2", "对不上的翻译", 1, 3, 202)
        jf = FakeJf(show(), [(1, untranslated), (2, local_season(0, 3, "乙 %d", season=2))])
        entry = scan_auto(jf, bgm)[0]
        self.assertEqual(entry["method"], "season-map")
        self.assertEqual(len(entry["episodes"]), 6)
        self.assertEqual(entry["episodes"][2]["bgm_id"], "202")

    def test_auto_ignores_an_order_only_plan(self):
        bgm = FakeBgm({1: bgm_eps(100, 4, "甲 %d"), 2: bgm_eps(200, 4, "乙 %d")},
                      chains=[[1, 2]],
                      results={"T": [{"id": 1, "name": "T", "name_cn": "T"}]})
        jf = FakeJf(show(), [(1, local_season(0, 4, "毫无关系 %d")),
                             (2, local_season(0, 4, "也毫无关系 %d", season=2))])
        entry = scan_auto(jf, bgm)[0]
        self.assertEqual(entry["status"], REVIEW)
        self.assertNotEqual(entry["method"], "season-map")


if __name__ == "__main__":
    unittest.main()

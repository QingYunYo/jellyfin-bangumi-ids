"""Season-level stored ids split the alignment (Cyberpunk: two subjects, one show)."""
import unittest

from jellyfin_bangumi_ids.scan import scan_series


def subject(sid, name, names, start):
    return {"id": sid, "name": name, "name_cn": name,
            "episodes": [{"id": start + i, "name": names % (i + 1)} for i in range(10)]}


class FakeBgm:
    """Two subjects related by 相同世界观: ``chain`` never links them."""

    def __init__(self, subjects, chains=None):
        self._subjects = subjects
        self._chains = chains or {}

    def subject(self, sid):
        return self._subjects[int(sid)]

    def chain(self, sid):
        return list(self._chains.get(int(sid), [int(sid)]))

    def episode_list(self, sid):
        return [{"id": e["id"], "name": e["name"], "subject_id": int(sid), "sort": i + 1}
                for i, e in enumerate(self._subjects[int(sid)]["episodes"])]

    def episodes(self, sid, ep_type=0):
        return []

    def episode(self, eid):
        return {"id": int(eid), "subject_id": 0, "name": ""}

    def search(self, keyword, limit=10):
        return []


class FakeJf:
    def __init__(self, series, seasons):
        self._series = series
        # (index, season item id, season Bangumi id, [(item id, name)])
        self._seasons = seasons

    def seasons(self, series_id):
        return [{"Id": sid, "IndexNumber": index,
                 "ProviderIds": {"Bangumi": str(pid)} if pid else {}}
                for index, sid, pid, _eps in self._seasons]

    def season_episodes(self, season_id):
        for index, sid, _pid, eps in self._seasons:
            if sid == season_id:
                return [{"Id": item, "Name": name, "IndexNumber": n + 1,
                         "ParentIndexNumber": index, "ProviderIds": {}}
                        for n, (item, name) in enumerate(eps)]
        return []

    def episodes(self, series_id):
        return [ep for season in self.seasons(series_id)
                for ep in self.season_episodes(season["Id"])]

    def set_provider_id(self, item_id, provider, value):
        return {"ok": True, "before": None, "after": value, "collateral": []}


def cyberpunk_jf(season_one_id=309311, season_two_id=513878, series_pid=309311):
    first = [("s1e%d" % i, "第%d话" % i) for i in range(1, 11)]
    second = [("s2e%d" % i, "第二季第%d话" % i) for i in range(1, 11)]
    series = {"Id": "jf1", "Name": "赛博朋克：边缘行者",
              "ProviderIds": {"Bangumi": str(series_pid)} if series_pid else {}}
    return FakeJf(series, [(1, "se1", season_one_id, first),
                           (2, "se2", season_two_id, second)])


class SeasonOwnedSegmentsTest(unittest.TestCase):
    def setUp(self):
        self.bgm = FakeBgm({309311: subject(309311, "赛博朋克 边缘行者", "第%d话", 5000),
                            513878: subject(513878, "赛博朋克 边缘行者 第二季",
                                            "第二季第%d话", 6000)},
                           chains={309311: [309311], 513878: [513878]})

    def scan(self, jf, bgm=None):
        return scan_series(jf, bgm or self.bgm, jf._series)

    def test_each_season_aligns_on_its_own_stored_id(self):
        entry = self.scan(cyberpunk_jf())
        self.assertEqual(entry["status"], "ok", entry["reason"])
        self.assertEqual(entry["coverage"], 1.0)
        self.assertEqual(entry["chain"], [309311])
        self.assertEqual({e["subject"] for e in entry["episodes"]}, {309311, 513878})
        ids = [e["bgm_id"] for e in entry["episodes"]]
        self.assertEqual(len(ids), 20)
        self.assertEqual(len(set(ids)), 20)
        self.assertTrue(any("keeps its own subject 513878" in n for n in entry["notes"]))

    def test_implausible_season_id_is_not_trusted(self):
        bgm = FakeBgm({309311: subject(309311, "赛博朋克 边缘行者", "第%d话", 5000),
                       999999: subject(999999, "完全无关的动画", "别的第%d话", 7000)})
        # S1 has no stored id, so only the series id anchors the chain; the S2 id
        # belongs to an unrelated subject and must not create a segment of its own.
        jf = cyberpunk_jf(season_one_id=None, season_two_id=999999)
        entry = scan_series(jf, bgm, jf._series)
        self.assertEqual(entry["status"], "review")
        self.assertIn("size mismatch", entry["reason"])
        self.assertEqual({e["subject"] for e in entry["episodes"]}, {309311})

    def test_season_id_with_the_wrong_episode_count_is_not_trusted(self):
        big = subject(513878, "赛博朋克 边缘行者 第二季", "第二季第%d话", 6000)
        big["episodes"] += [{"id": 9000 + i, "name": "extra%d" % i} for i in range(20)]
        bgm = FakeBgm({309311: subject(309311, "赛博朋克 边缘行者", "第%d话", 5000),
                       513878: big})
        entry = self.scan(cyberpunk_jf(season_one_id=None), bgm)
        self.assertEqual(entry["status"], "review")
        self.assertFalse(any("keeps its own subject 513878" in n for n in entry["notes"]))

    def test_overlapping_subjects_are_reported_as_duplicates(self):
        same = subject(513878, "赛博朋克 边缘行者 第二季", "第%d话", 5000)
        bgm = FakeBgm({309311: subject(309311, "赛博朋克 边缘行者", "第%d话", 5000),
                       513878: same})
        entry = self.scan(cyberpunk_jf(), bgm)
        self.assertEqual(entry["status"], "review")
        self.assertIn("duplicate Bangumi episode ids", entry["reason"])

    def test_missing_first_season_id_falls_back_to_the_series_id_chain(self):
        jf = cyberpunk_jf(season_one_id=None)
        entry = self.scan(jf)
        self.assertEqual(entry["status"], "ok", entry["reason"])
        self.assertEqual(entry["anchor"], 309311)
        self.assertEqual(entry["anchor_how"], "series-id")
        self.assertEqual(entry["chain"], [309311])
        ids = [e["bgm_id"] for e in entry["episodes"]]
        self.assertEqual(len(ids), 20)
        self.assertEqual(len(set(ids)), 20)
        self.assertTrue(any("chain from series id 309311" in n for n in entry["notes"]))


if __name__ == "__main__":
    unittest.main()

import json
import os
import tempfile
import unittest

from jellyfin_bangumi_ids.scan import (REVIEW, OK, apply_report, pick_anchor, rollback, scan_series,
                                       scan_specials)


class FakeBgm:
    """Network-free Bangumi stand-in."""

    def __init__(self, subjects, specials=None, names=None, results=None):
        self.subjects = subjects          # {subject_id: [episode dicts]}
        self.specials = specials or {}    # {subject_id: [type=1 episode dicts]}
        self.names = names or {}          # {subject_id: title}
        self.results = results or {}      # {keyword: [search hit dicts]}
        self.links = {1671: [1672]}       # subject -> sequels

    def subject(self, sid):
        return {"id": sid, "name_cn": self.names.get(sid) or "T", "name": self.names.get(sid) or "T"}

    def relations(self, sid):
        return [{"id": n, "type": 2, "relation": "续集"} for n in self.links.get(sid, [])]

    def chain(self, sid):
        order, cur = [sid], sid
        while self.links.get(cur):
            cur = self.links[cur][0]
            order.append(cur)
        return order

    def episodes(self, sid, ep_type=0):
        if ep_type:
            return list(self.specials.get(sid, []))
        return self.subjects.get(sid, [])

    def episode_list(self, sid):
        return list(self.subjects.get(sid, []))

    def search(self, keyword, limit=10):
        return list(self.results.get(keyword, []))


class FakeJf:
    def __init__(self, series, seasons):
        self.series = series
        self._seasons = seasons          # [(season_no, [(item_id, name)])]
        self._items = {i: n for _, eps in seasons for i, n in eps}
        self.writes = []

    def seasons(self, series_id):
        return [{"Id": "s%d" % no, "IndexNumber": no} for no, _ in self._seasons]

    def season_episodes(self, season_id):
        no = int(season_id[1:])
        for n, eps in self._seasons:
            if n == no:
                return [{"Id": i, "Name": name, "IndexNumber": k + 1, "ParentIndexNumber": n}
                        for k, (i, name) in enumerate(eps)]
        return []

    def set_provider_id(self, item_id, provider, value):
        self.writes.append((item_id, value))
        return {"ok": True, "before": None, "after": str(value), "collateral": {}}

    def item(self, item_id):
        return {"Id": item_id, "ProviderIds": {}}


def series(name="T", sid="sid1", pid=None):
    out = {"Id": sid, "Name": name, "ProviderIds": {}}
    if pid:
        out["ProviderIds"]["Bangumi"] = str(pid)
    return out


class ScanTest(unittest.TestCase):
    def test_equal_counts_use_sequence(self):
        jf = FakeJf(series(pid=1671), [(1, [("a", "一"), ("b", "二")])])
        bgm = FakeBgm({1671: [{"id": 1, "name_cn": "一", "sort": 1},
                              {"id": 2, "name_cn": "二", "sort": 2}]})
        entry = scan_series(jf, bgm, jf.series)
        self.assertEqual(entry["status"], OK)
        self.assertEqual([e["bgm_id"] for e in entry["episodes"]], ["1", "2"])

    def test_mismatch_goes_to_review(self):
        jf = FakeJf(series(pid=1671), [(1, [("a", "完全不同"), ("b", "也完全不同")])])
        bgm = FakeBgm({1671: [{"id": 9, "name_cn": "一", "sort": 1}]})
        entry = scan_series(jf, bgm, jf.series)
        self.assertEqual(entry["status"], REVIEW)

    def test_missing_anchor_is_reviewed(self):
        jf = FakeJf(series(), [(1, [("a", "一")])])
        entry = scan_series(jf, FakeBgm({}), jf.series, allow_search=False)
        self.assertEqual(entry["status"], REVIEW)
        self.assertIn("anchor", entry["reason"])

    def test_apply_and_rollback(self):
        jf = FakeJf(series(pid=1671), [(1, [("a", "一")])])
        report = {"series": [{"series": "T", "status": OK, "episodes": [
            {"item_id": "a", "season": 1, "index": 1, "name": "一", "bgm_id": "42"}]}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "backup.json")
            apply_report(jf, report, backup_path=path)
            self.assertEqual(jf.writes, [("a", "42")])
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)[0]["new"], "42")
            rollback(jf, path)
            self.assertEqual(jf.writes[-1], ("a", None))


class AnchorTest(unittest.TestCase):
    """A stored id is only trusted when the subject actually carries this show's title."""

    def test_implausible_series_id_is_ignored(self):
        bad = {"Id": "s1", "Name": "物语系列", "OriginalTitle": "化物語",
               "ProviderIds": {"Bangumi": "2098"}}
        bgm = FakeBgm({1671: [{"id": 11, "sort": 1, "name_cn": "黑仪·蟹 其一"}]},
                      names={2098: "源氏物語千年紀 Genji", 1671: "化物語"},
                      results={"化物語": [{"id": 1671, "name": "化物語", "name_cn": "化物语"}]})
        jf = FakeJf(bad, [(1, [("a", "黑仪·蟹 其一")])])
        entry = scan_series(jf, bgm, jf.series)
        self.assertEqual(entry["anchor"], 1671)
        self.assertEqual(entry["anchor_how"], "search")
        self.assertTrue(any("ignored implausible" in n for n in entry["notes"]))
        self.assertEqual(entry["status"], OK)

    def test_original_title_rescues_anchor(self):
        show = {"Id": "s2", "Name": "迷途之子!!!!!", "OriginalTitle": "BanG Dream! It's MyGO!!!!!",
                "ProviderIds": {}}
        bgm = FakeBgm({428735: [{"id": 1211350, "sort": 1, "name_cn": "羽丘的怪女孩"}]},
                      names={428735: "BanG Dream! It's MyGO!!!!!"},
                      results={"BanG Dream! It's MyGO!!!!!": [
                          {"id": 428735, "name": "BanG Dream! It's MyGO!!!!!", "name_cn": ""}]})
        jf = FakeJf(show, [(1, [("a", "羽丘的不可思议女孩")])])
        entry = scan_series(jf, bgm, jf.series)
        self.assertEqual(entry["anchor"], 428735)
        self.assertEqual(entry["anchor_how"], "search")

    def test_wrong_id_without_search_stays_review(self):
        bad = {"Id": "s3", "Name": "物语系列", "ProviderIds": {"Bangumi": "2098"}}
        bgm = FakeBgm({}, names={2098: "源氏物語千年紀 Genji"})
        jf = FakeJf(bad, [(1, [("a", "黑仪·蟹 其一")])])
        entry = scan_series(jf, bgm, jf.series, allow_search=False)
        self.assertEqual(entry["status"], REVIEW)
        self.assertIn("anchor", entry["reason"])


if __name__ == "__main__":
    unittest.main()


class SpecialsTest(unittest.TestCase):
    def _series(self):
        return {"Id": "series1", "Name": "测试番", "ProviderIds": {"Bangumi": "1671"}}

    def test_specials_match_by_name(self):
        bgm = FakeBgm({1671: [{"id": 1, "sort": 1, "name_cn": "第一集"}]},
                      specials={1671: [{"id": 900, "sort": 1, "name_cn": "番外篇 艾莉丝的哥布林讨伐"},
                                       {"id": 901, "sort": 2, "name_cn": "特别篇 守墓人与猫与魔术师"}]},
                      names={1671: "测试番"})
        jf = FakeJf(self._series(), [
            (0, [("sp1", "番外篇「艾莉丝的哥布林讨伐」")]),
            (1, [("e1", "第一集")]),
        ])
        entry = scan_specials(jf, bgm, self._series())
        self.assertEqual(entry["status"], OK)
        self.assertEqual(entry["matched"], 1)
        self.assertEqual(entry["episodes"][0]["bgm_id"], "900")

    def test_no_specials_on_bangumi_goes_to_review(self):
        bgm = FakeBgm({1671: [{"id": 1, "sort": 1, "name_cn": "第一集"}]}, names={1671: "测试番"})
        jf = FakeJf(self._series(), [(0, [("sp1", "番外篇 艾莉丝的哥布林讨伐")])])
        entry = scan_specials(jf, bgm, self._series())
        self.assertEqual(entry["status"], REVIEW)
        self.assertEqual(entry["to_write"], 0)

    def test_unmatched_special_is_not_written(self):
        bgm = FakeBgm({1671: []}, specials={1671: [{"id": 900, "sort": 1, "name_cn": "完全无关的东西"}]},
                      names={1671: "测试番"})
        jf = FakeJf(self._series(), [(0, [("sp1", "番外篇 艾莉丝的哥布林讨伐")])])
        entry = scan_specials(jf, bgm, self._series())
        self.assertEqual(entry["status"], REVIEW)
        self.assertEqual(entry["to_write"], 0)


class ChainTrimTest(unittest.TestCase):
    """One franchise, several subjects: align against the part this library actually holds."""

    def _episodes(self, base, count):
        return [{"id": base + i, "sort": i + 1, "name_cn": "第%d话" % (i + 1)} for i in range(count)]

    def test_sequel_subject_is_trimmed_when_counts_match(self):
        show = {"Id": "s1", "Name": "T", "OriginalTitle": "T", "ProviderIds": {"Bangumi": "100"}}
        bgm = FakeBgm({100: self._episodes(1000, 13), 200: self._episodes(2000, 13)},
                      names={100: "T", 200: "T 续作"})
        bgm.links = {100: [200], 200: []}
        jf = FakeJf(show, [(1, [("e%d" % i, "第%d话" % i) for i in range(1, 14)])])
        entry = scan_series(jf, bgm, jf.series)
        self.assertEqual(entry["chain"], [100])
        self.assertEqual(entry["status"], OK)
        self.assertTrue(any("chain trimmed" in n for n in entry["notes"]))

    def test_prequel_is_not_used_to_match_a_shorter_library(self):
        show = {"Id": "s2", "Name": "T", "OriginalTitle": "T", "ProviderIds": {"Bangumi": "200"}}
        bgm = FakeBgm({100: self._episodes(1000, 25), 200: self._episodes(2000, 13)},
                      names={100: "T 前传", 200: "T"})
        bgm.chain = lambda sid: [100, 200]   # prequel first, anchor second
        jf = FakeJf(show, [(1, [("e%d" % i, "第%d话" % i) for i in range(1, 26)])])
        entry = scan_series(jf, bgm, jf.series)
        self.assertEqual(entry["chain"], [100, 200])
        self.assertEqual(entry["status"], REVIEW)


class ProviderIdsFakeJf:
    """FakeJf that also carries ProviderIds, so anchors can be read back."""

    def __init__(self, series, seasons):
        self.series = series
        self._seasons = seasons          # [(season_no, subject_id, [(item_id, name, bangumi)])]
        self.writes = []

    def seasons(self, series_id):
        return [{"Id": "s%d" % no, "IndexNumber": no,
                 "ProviderIds": {"Bangumi": str(sid)} if sid else {}}
                for no, sid, _ in self._seasons]

    def season_episodes(self, season_id):
        no = int(season_id[1:])
        for n, _sid, eps in self._seasons:
            if n == no:
                return [{"Id": i, "Name": name, "IndexNumber": k + 1, "ParentIndexNumber": n,
                         "ProviderIds": {"Bangumi": str(bgm)} if bgm else {}}
                        for k, (i, name, bgm) in enumerate(eps)]
        return []

    def set_provider_id(self, item_id, provider, value):
        self.writes.append((item_id, value))
        return {"ok": True, "before": None, "after": value, "collateral": {}}

    def item(self, item_id):
        return {"Id": item_id, "ProviderIds": {}}


class EpisodeParentAnchorTest(unittest.TestCase):
    def test_stale_season_id_yields_to_episode_parent(self):
        show = {"Id": "haruhi", "Name": "凉宫春日的忧郁", "ProviderIds": {"Bangumi": "1372"}}
        jf = ProviderIdsFakeJf(show, [
            (1, 1372, [("e1", "朝比奈实玖瑠的冒险", 5000), ("e2", "凉宫春日的忧郁 I", 5001)]),
        ])

        class Bgm:
            def subject(self, sid):
                return {"id": sid, "name": "凉宫春日的忧郁" if sid == 1606 else "小凉宫春日的忧郁"}

            def episode(self, eid):
                return {"id": eid, "subject_id": 1606}

            def search(self, keyword, limit=10):
                return []

        sid, how, _ = pick_anchor(Bgm(), jf, show)
        self.assertEqual((sid, how), (1606, "episode-parent"))


class PreserveOrderTest(unittest.TestCase):
    def test_broadcast_order_ids_are_not_rewritten(self):
        show = {"Id": "s", "Name": "凉宫春日的忧郁", "ProviderIds": {"Bangumi": "1606"}}
        bgm = FakeBgm({1606: [{"id": 5000, "sort": 1, "name_cn": "第一话"},
                              {"id": 5001, "sort": 2, "name_cn": "第二话"}]},
                      names={1606: "凉宫春日的忧郁"})
        jf = ProviderIdsFakeJf(show, [
            (1, 1606, [("e1", "朝比奈实玖瑠的冒险", 5001), ("e2", "凉宫春日的忧郁 I", 5000)]),
        ])
        entry = scan_series(jf, bgm, jf.series)
        self.assertEqual(entry["status"], OK)
        self.assertEqual(entry["to_write"], 0)
        self.assertTrue(any("kept 2 existing ids" in n for n in entry["notes"]))


class BorrowedSpecialTest(unittest.TestCase):
    def test_borrowed_special_id_is_cleared(self):
        show = {"Id": "s", "Name": "测试番", "ProviderIds": {"Bangumi": "1671"}}
        bgm = FakeBgm({1671: [{"id": 500, "sort": 1, "name_cn": "第一集"}]},
                      specials={1671: [{"id": 900, "sort": 1, "name_cn": "完全无关"}]},
                      names={1671: "测试番"})
        bgm.episode = lambda eid: {"id": eid, "name_cn": "完全无关"}
        jf = ProviderIdsFakeJf(show, [
            (0, None, [("sp", "番外篇 某物", 500)]),
            (1, 1671, [("e1", "第一集", 500)]),
        ])
        entry = scan_specials(jf, bgm, show, clear_borrowed=True)
        self.assertEqual(entry["status"], OK)
        clear = [e for e in entry["episodes"] if e.get("clear")]
        self.assertEqual(len(clear), 1)
        self.assertIsNone(clear[0]["bgm_id"])
        apply_report(jf, {"series": [entry]})
        self.assertIn(("sp", None), jf.writes)

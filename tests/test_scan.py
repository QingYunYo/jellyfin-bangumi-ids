import json
import os
import tempfile
import unittest

from jellyfin_bangumi_ids.scan import REVIEW, OK, apply_report, rollback, scan_series


class FakeBgm:
    """Network-free Bangumi stand-in."""

    def __init__(self, subjects):
        self.subjects = subjects          # {subject_id: [episode dicts]}
        self.links = {1671: [1672]}       # subject -> sequels

    def subject(self, sid):
        return {"id": sid, "name_cn": "S%d" % sid}

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
            return []
        return self.subjects.get(sid, [])

    def episode_list(self, sid):
        return list(self.subjects.get(sid, []))

    def search(self, keyword, limit=10):
        return []


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


if __name__ == "__main__":
    unittest.main()

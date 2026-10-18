import unittest

from jellyfin_bangumi_ids.anchor import derive_anchor
from jellyfin_bangumi_ids.scan import pick_anchor


class FakeBgm:
    """Just enough of the Bangumi client for anchor resolution."""

    def __init__(self, names, parents=None):
        self.names = names              # {subject_id: title}
        self.parents = parents or {}    # {episode_id: subject_id}

    def subject(self, sid):
        title = self.names.get(sid) or "T"
        return {"id": sid, "name": title, "name_cn": title}

    def episode(self, eid):
        return {"id": eid, "subject_id": self.parents[eid]}

    def episode_list(self, sid):
        return []

    def search(self, keyword, limit=10):
        return []


class FakeJf:
    """A series whose seasons and episodes carry (or do not carry) Bangumi ids."""

    def __init__(self, series_pid=None, season_pid=None, episode_pids=None):
        self._series_pid = series_pid
        self._season_pid = season_pid
        self._episode_pids = episode_pids or []

    def seasons(self, series_id):
        out = [{"Id": "s1", "IndexNumber": 1}]
        if self._season_pid:
            out[0]["ProviderIds"] = {"Bangumi": str(self._season_pid)}
        return out

    def season_episodes(self, season_id):
        out = []
        for i, pid in enumerate(self._episode_pids):
            ep = {"Id": "e%d" % i, "Name": "第 %d 集" % (i + 1),
                  "IndexNumber": i + 1, "ParentIndexNumber": 1}
            if pid:
                ep["ProviderIds"] = {"Bangumi": str(pid)}
            out.append(ep)
        return out


def series(pid=None, name="T"):
    out = {"Id": "sid1", "Name": name, "ProviderIds": {}}
    if pid:
        out["ProviderIds"]["Bangumi"] = str(pid)
    return out


class PickAnchorOrderTest(unittest.TestCase):
    def test_season_vote_beats_a_plausible_series_id(self):
        # Both ids carry a plausible title, so the guard lets both through; the
        # season vote wins because a series-level id is one field a bad match can
        # poison, while every season is scraped separately.
        bgm = FakeBgm({2098: "T", 1671: "T"})
        jf = FakeJf(series_pid=2098, season_pid=1671)
        sid, how, _notes = pick_anchor(bgm, jf, series(pid=2098))
        self.assertEqual((sid, how), (1671, "season-id"))

    def test_episode_parent_beats_both(self):
        bgm = FakeBgm({2098: "T", 1671: "T", 1606: "T"}, parents={101: 1606, 102: 1606})
        jf = FakeJf(series_pid=2098, season_pid=1671, episode_pids=[101, 102])
        sid, how, _notes = pick_anchor(bgm, jf, series(pid=2098))
        self.assertEqual((sid, how), (1606, "episode-parent"))

    def test_a_wrong_series_id_is_never_consulted(self):
        # The 物语系列 shape: the series id points at an unrelated show while the
        # seasons carry the right one.  The season vote answers before the series
        # id is even looked at, so the wrong value cannot win.
        bgm = FakeBgm({2098: "源氏物語千年紀 Genji", 1671: "T"})
        jf = FakeJf(series_pid=2098, season_pid=1671)
        sid, how, _notes = pick_anchor(bgm, jf, series(pid=2098))
        self.assertEqual((sid, how), (1671, "season-id"))


class DeriveAnchorTest(unittest.TestCase):
    def test_episode_parent_first(self):
        bgm = FakeBgm({2098: "T", 1671: "T", 1606: "T"}, parents={101: 1606})
        jf = FakeJf(series_pid=2098, season_pid=1671, episode_pids=[101])
        self.assertEqual(derive_anchor(bgm, jf, series(pid=2098)), (1606, "episode-parent"))

    def test_season_vote_before_series_id(self):
        bgm = FakeBgm({2098: "T", 1671: "T"})
        jf = FakeJf(series_pid=2098, season_pid=1671)
        self.assertEqual(derive_anchor(bgm, jf, series(pid=2098)), (1671, "season-id"))


if __name__ == "__main__":
    unittest.main()

"""--series-id selects a library entry by its exact Jellyfin item id."""
import unittest

from jellyfin_bangumi_ids.cli import build_parser
from jellyfin_bangumi_ids.jellyfin import Jellyfin, select_series
from jellyfin_bangumi_ids.scan import run_scan


class PickJf:
    def __init__(self, by_id, listed=None):
        self.by_id = by_id
        self.listed = listed if listed is not None else list(by_id.values())
        self.asked = []

    def series_by_id(self, item_id):
        self.asked.append(str(item_id))
        if str(item_id) not in self.by_id:
            raise SystemExit("series not found: item %s" % item_id)
        return self.by_id[str(item_id)]

    def all_series(self, library_name=None, limit=None):
        raise AssertionError("all_series must not be used when --series-id is given")


class SelectSeriesTest(unittest.TestCase):
    def test_ids_win_over_the_library_scan(self):
        jf = PickJf({"a": {"Id": "a", "Name": "one"}, "b": {"Id": "b", "Name": "two"}})
        got = select_series(jf, ["b", "a"])
        self.assertEqual([s["Id"] for s in got], ["b", "a"])
        self.assertEqual(jf.asked, ["b", "a"])

    def test_limit_applies_to_the_selected_ids(self):
        jf = PickJf({"a": {"Id": "a"}, "b": {"Id": "b"}})
        self.assertEqual([s["Id"] for s in select_series(jf, ["a", "b"], limit=1)], ["a"])

    def test_without_ids_the_library_scan_runs(self):
        class Library(PickJf):
            def all_series(self, library_name=None, limit=None):
                return [{"Id": "x"}]
        self.assertEqual([s["Id"] for s in select_series(Library({}))], ["x"])


class SeriesByIdTest(unittest.TestCase):
    class Item(Jellyfin):
        def __init__(self, dto):
            super().__init__("http://127.0.0.1:8096", "key")
            self.dto = dto

        def item(self, item_id):
            return self.dto

    def test_returns_the_series_dto(self):
        dto = {"Id": "abc", "Type": "Series", "Name": "剧"}
        self.assertEqual(self.Item(dto).series_by_id("abc")["Name"], "剧")

    def test_rejects_a_non_series_item(self):
        with self.assertRaises(SystemExit) as err:
            self.Item({"Id": "abc", "Type": "Movie"}).series_by_id("abc")
        self.assertIn("is not a series", str(err.exception))

    def test_rejects_a_missing_item(self):
        with self.assertRaises(SystemExit) as err:
            self.Item({}).series_by_id("abc")
        self.assertIn("series not found", str(err.exception))


class FakeJf:
    """Two library entries that share a name -- the case --series-id exists for."""

    def __init__(self):
        self._series = [
            {"Id": "tv", "Name": "同名剧", "ProviderIds": {"Bangumi": "100"}},
            {"Id": "movie", "Name": "同名剧", "ProviderIds": {"Bangumi": "100"}},
        ]
        self.scanned = []

    def series_by_id(self, item_id):
        self.scanned.append(str(item_id))
        for series in self._series:
            if series["Id"] == str(item_id):
                return series
        raise SystemExit("series not found: item %s" % item_id)

    def all_series(self, library_name=None, limit=None):
        return list(self._series)

    def find_series(self, name, library_name=None):
        raise SystemExit("ambiguous series name %r (2 matches)" % name)

    def seasons(self, series_id):
        return [{"Id": "se-" + series_id, "IndexNumber": 1, "ProviderIds": {}}]

    def season_episodes(self, season_id):
        return [{"Id": "e-" + season_id, "Name": "第一话", "IndexNumber": 1,
                 "ParentIndexNumber": 1, "ProviderIds": {}}]

    def episodes(self, series_id):
        return self.season_episodes("se-" + series_id)


class FakeBgm:
    def subject(self, sid):
        return {"id": int(sid), "name": "同名剧", "name_cn": "同名剧", "eps": 1}

    def chain(self, sid):
        return [int(sid)]

    def episode_list(self, sid):
        return [{"id": 11, "name": "第一话", "subject_id": int(sid), "sort": 1}]

    def episodes(self, sid, ep_type=0):
        return []

    def episode(self, eid):
        return {"id": int(eid), "subject_id": 100, "name": "第一话"}

    def search(self, keyword, limit=10):
        return []


class ScanSeriesIdTest(unittest.TestCase):
    def test_scan_uses_the_item_id_and_never_the_ambiguous_name(self):
        jf = FakeJf()
        report = run_scan(jf, FakeBgm(), series_ids=["movie"], out=self.path())
        self.assertEqual(jf.scanned, ["movie"])
        self.assertEqual([e["series_id"] for e in report["series"]], ["movie"])
        self.assertEqual(report["series"][0]["status"], "ok")
        self.assertEqual(report["summary"]["episodes_to_write"], 1)

    def path(self):
        import os
        import tempfile
        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        self.addCleanup(os.unlink, path)
        return path


class ParserTest(unittest.TestCase):
    def parse(self, *argv):
        return build_parser().parse_args(list(argv))

    def test_scan_accepts_several_ids(self):
        args = self.parse("scan", "--series-id", "a", "--series-id", "b")
        self.assertEqual(args.series_id, ["a", "b"])

    def test_every_series_aware_command_takes_an_id(self):
        for command in ("special", "auto", "verify"):
            self.assertEqual(self.parse(command, "--series-id", "x").series_id, ["x"])
        for command in ("anchor", "season"):
            argv = [command, "--series-id", "x"]
            if command == "season":
                argv += ["--map", "map.json"]
            self.assertEqual(self.parse(*argv).series_id, "x")

    def test_sync_takes_ids_too(self):
        args = self.parse("sync", "--series-id", "a", "--series-id", "b")
        self.assertEqual(args.series_id, ["a", "b"])


if __name__ == "__main__":
    unittest.main()

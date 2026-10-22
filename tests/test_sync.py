"""sync runs the documented repair order and stops at the first failure."""
import contextlib
import io
import json
import os
import tempfile
import unittest

from jellyfin_bangumi_ids.sync import run_sync


class FakeJf:
    def __init__(self, series_pid="100", fail_writes=()):
        self.series = {"Id": "s1", "Name": "剧", "ProviderIds": {}}
        if series_pid:
            self.series["ProviderIds"]["Bangumi"] = series_pid
        self.season_ids = {}
        self.stored = {}
        self.writes = []
        self.fail_writes = set(fail_writes)

    def all_series(self, library_name=None, limit=None):
        return [dict(self.series)]

    def series_by_id(self, item_id):
        return dict(self.series)

    def find_series(self, name, library_name=None):
        return dict(self.series)

    def seasons(self, series_id):
        ids = dict(self.season_ids)
        return [{"Id": "se1", "IndexNumber": 1, "ProviderIds": ids}]

    def season_episodes(self, season_id):
        out = []
        for index, (item_id, name) in enumerate((("e1", "第一话"), ("e2", "第二话")), 1):
            ids = {}
            if item_id in self.stored:
                ids["Bangumi"] = self.stored[item_id]
            out.append({"Id": item_id, "Name": name, "IndexNumber": index,
                        "ParentIndexNumber": 1, "ProviderIds": ids})
        return out

    def episodes(self, series_id):
        return self.season_episodes("se1")

    def item(self, item_id):
        ids = {}
        if item_id in self.stored:
            ids["Bangumi"] = self.stored[item_id]
        kind = "Season" if item_id == "se1" else "Episode"
        return {"Id": item_id, "Type": kind, "ProviderIds": ids}

    def set_provider_id(self, item_id, provider, value):
        before = self.stored.get(item_id) if item_id != "se1" else self.season_ids.get(item_id)
        if item_id in self.fail_writes:
            return {"ok": False, "before": before, "after": str(value), "collateral": []}
        target = self.season_ids if item_id == "se1" else self.stored
        if value is None:
            target.pop(item_id, None)
        else:
            target[item_id] = str(value)
        self.writes.append((item_id, value))
        return {"ok": True, "before": before, "after": str(value), "collateral": []}

    def refresh_item(self, item_id, replace_all=True):
        return {}


class FakeBgm:
    def __init__(self, names=("第一话", "第二话")):
        self.names = list(names)

    def subject(self, sid):
        return {"id": int(sid), "name": "剧", "name_cn": "剧", "eps": len(self.names)}

    def chain(self, sid):
        return [int(sid)]

    def episode_list(self, sid):
        return [{"id": 11 + i, "name": name, "subject_id": 100, "sort": i + 1}
                for i, name in enumerate(self.names)]

    def episode(self, eid):
        index = int(eid) - 11
        name = self.names[index] if 0 <= index < len(self.names) else "?"
        return {"id": int(eid), "subject_id": 100, "name": name, "name_cn": name}

    def episodes(self, sid, ep_type=0):
        return []

    def search(self, keyword, limit=10):
        return []


def run(jf, bgm, **kwargs):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = run_sync(jf, bgm, **kwargs)
    lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
    return result, lines


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "out")
        self.backup = os.path.join(self.tmp.name, "backup")
        self.common = dict(out_dir=self.out, backup_dir=self.backup)

    def read(self, name, folder=None):
        with open(os.path.join(folder or self.out, name), encoding="utf-8") as fh:
            return json.load(fh)

    def test_dry_run_prints_every_step_and_writes_nothing(self):
        jf = FakeJf()
        result, lines = run(jf, FakeBgm(), dry_run=True, **self.common)
        self.assertEqual(result["exit"], 0)
        self.assertEqual(result["failed_step"], None)
        self.assertEqual(jf.writes, [])
        self.assertEqual(jf.stored, {})
        self.assertEqual(len(lines), 5)
        self.assertTrue(all(line.startswith("[") for line in lines))
        self.assertIn("would write 2 episodes", lines[1])
        self.assertIn("would be written", lines[2])
        self.assertEqual(sorted(os.listdir(self.out)),
                         ["jbmid-check.json", "jbmid-report.json", "jbmid-specials.json"])
        self.assertIn("no id stored yet", lines[4])
        self.assertFalse(os.path.exists(self.backup) and os.listdir(self.backup))

    def test_real_run_writes_episodes_season_ids_and_backups(self):
        jf = FakeJf()
        result, lines = run(jf, FakeBgm(), **self.common)
        self.assertEqual(result["exit"], 0, lines)
        self.assertEqual(jf.stored, {"e1": "11", "e2": "12"})
        self.assertEqual(jf.season_ids, {"se1": "100"})
        self.assertEqual([step["step"] for step in result["steps"]],
                         ["scan", "apply", "anchor", "special", "verify"])
        self.assertEqual(self.read("jbmid-report.json")["summary"]["episodes_to_write"], 2)
        self.assertEqual(self.read("jbmid-check.json")["checked"], 2)
        self.assertEqual(self.read("jbmid-check.json")["low_similarity"], 0)
        backups = sorted(os.listdir(self.backup))
        self.assertEqual(backups, ["jbmid-anchor-backup.json", "jbmid-backup.json"])

    def test_stop_on_review_halts_after_scan(self):
        jf = FakeJf(series_pid=None)
        result, lines = run(jf, FakeBgm(), stop_on_review=True, **self.common)
        self.assertEqual(result["exit"], 1)
        self.assertEqual(result["failed_step"], "scan")
        self.assertEqual(len(result["steps"]), 1)
        self.assertEqual(jf.writes, [])
        self.assertEqual(len(lines), 1)
        self.assertIn("FAILED", lines[0])
        self.assertIn("need review", lines[0])

    def test_failed_write_stops_the_run(self):
        jf = FakeJf(fail_writes=("e2",))
        result, lines = run(jf, FakeBgm(), **self.common)
        self.assertEqual(result["exit"], 1)
        self.assertEqual(result["failed_step"], "apply")
        self.assertEqual([step["step"] for step in result["steps"]],
                         ["scan", "apply"])
        self.assertEqual(len(lines), 2)
        self.assertIn("FAILED", lines[1])
        self.assertEqual(jf.season_ids, {})

    def archive(self, names):
        folder = os.path.join(self.tmp.name, "archive")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "subject.jsonlines"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": 100, "name": "剧", "name_cn": "剧", "type": 2,
                                 "eps": 2}, ensure_ascii=False) + "\n")
        with open(os.path.join(folder, "episode.jsonlines"), "w", encoding="utf-8") as fh:
            for index, name in enumerate(names, 1):
                fh.write(json.dumps({"id": 10 + index, "subject_id": 100, "sort": index,
                                     "type": 0, "name": name, "name_cn": name},
                                    ensure_ascii=False) + "\n")
        return folder

    def test_fail_on_counter_exits_one_at_verify(self):
        jf = FakeJf()
        archive = self.archive(["别的名字", "又是别的"])
        result, lines = run(jf, FakeBgm(), archive=archive, fail_on="low-sim", **self.common)
        self.assertEqual(result["exit"], 1)
        self.assertEqual(result["failed_step"], "verify")
        self.assertEqual(len(result["steps"]), 5)
        self.assertIn("FAILED", lines[-1])
        self.assertIn("low-sim=2", lines[-1])
        self.assertEqual(jf.stored, {"e1": "11", "e2": "12"})

    def test_fail_on_none_accepts_the_same_report(self):
        jf = FakeJf()
        archive = self.archive(["别的名字", "又是别的"])
        result, lines = run(jf, FakeBgm(), archive=archive, fail_on="none", **self.common)
        self.assertEqual(result["exit"], 0)
        self.assertEqual(len(lines), 5)
        self.assertEqual(self.read("jbmid-check.json")["low_similarity"], 2)


if __name__ == "__main__":
    unittest.main()

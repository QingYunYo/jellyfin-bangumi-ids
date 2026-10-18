import json
import os
import tempfile
import unittest

from jellyfin_bangumi_ids import archive
from jellyfin_bangumi_ids.verify import run_verify_offline


class FakeJf:
    def __init__(self, series, episodes):
        self._series = series            # [{Id, Name, OriginalTitle, ProviderIds}]
        self._episodes = episodes        # {series_id: [{Id, Name, IndexNumber, ProviderIds}]}

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


def ep(item_id, name, pid=None):
    row = {"Id": item_id, "Name": name, "IndexNumber": 1, "ParentIndexNumber": 1,
           "ProviderIds": {}}
    if pid:
        row["ProviderIds"]["Bangumi"] = str(pid)
    return row


class ArchiveReaderTest(unittest.TestCase):
    def test_collect_keeps_only_wanted(self):
        with tempfile.TemporaryDirectory() as d:
            write_archive(d, [{"id": 1, "name": "n", "name_cn": "名"}],
                          [{"id": 10, "subject_id": 1, "sort": 1, "type": 0,
                            "name": "a", "name_cn": "甲"},
                           {"id": 11, "subject_id": 1, "sort": 2, "type": 0,
                            "name": "b", "name_cn": "乙"}])
            rows = archive.collect_episodes(os.path.join(d, "episode.jsonlines"), {10})
            self.assertEqual(list(rows), [10])
            self.assertEqual(rows[10]["name_cn"], "甲")
            subs = archive.collect_subjects(os.path.join(d, "subject.jsonlines"), {1})
            self.assertEqual(subs[1]["name_cn"], "名")

    def test_numeric_strings_are_coerced(self):
        with tempfile.TemporaryDirectory() as d:
            write_archive(d, [{"id": "1", "name": "n"}],
                          [{"id": "10", "subject_id": "1", "sort": "1",
                            "type": "0", "name": "a", "name_cn": "甲"}])
            rows = archive.collect_episodes(os.path.join(d, "episode.jsonlines"), {10})
            self.assertEqual(rows[10]["subject_id"], 1)


class OfflineVerifyTest(unittest.TestCase):
    def build(self, d):
        write_archive(
            d,
            [{"id": 100, "name": "Series", "name_cn": "剧名", "type": 2, "eps": 3},
             {"id": 200, "name": "Other", "name_cn": "别的剧", "type": 2, "eps": 1}],
            [{"id": 1, "subject_id": 100, "sort": 1, "type": 0, "name": "a", "name_cn": "第一话"},
             {"id": 2, "subject_id": 100, "sort": 2, "type": 0, "name": "b", "name_cn": "第二话"},
             {"id": 3, "subject_id": 200, "sort": 1, "type": 0, "name": "c", "name_cn": "另一话"}])
        jf = FakeJf([{"Id": "s1", "Name": "剧名", "OriginalTitle": "Series",
                      "ProviderIds": {"Bangumi": "100"}}],
                    {"s1": [ep("e1", "第一话", 1), ep("e2", "第二话", 2),
                            ep("e3", "完全不同的标题", 3), ep("e4", "第一话", 1),
                            ep("e5", "第二话", 999)]})
        return jf

    def test_reports_every_problem_class(self):
        with tempfile.TemporaryDirectory() as d:
            jf = self.build(d)
            out = os.path.join(d, "check.json")
            report = run_verify_offline(jf, d, out=out)
            self.assertEqual(report["checked"], 5)
            self.assertEqual(report["unknown"], 1)        # 999 not in archive
            self.assertEqual(report["duplicate"], 1)      # id 1 used twice
            self.assertEqual(report["low_similarity"], 1) # "完全不同的标题"
            self.assertEqual(report["foreign_subject"], 1)  # id 3 -> subject 200
            self.assertEqual(report["disorder"], 1)       # id 1 comes back after id 2
            self.assertEqual(report["anchor_rows"], [])
            kinds = sorted({r["kind"] for r in report["rows"]})
            self.assertEqual(kinds, ["disorder", "foreign_subject", "low_similarity",
                                     "unknown_id"])
            self.assertTrue(os.path.isfile(out))

    def test_filename_noise_does_not_count_as_low_similarity(self):
        with tempfile.TemporaryDirectory() as d:
            write_archive(d, [{"id": 100, "name": "S", "name_cn": "剧名", "type": 2}],
                          [{"id": 1, "subject_id": 100, "sort": 1, "type": 0,
                            "name": "a", "name_cn": "欢迎来到鸟白岛"}])
            jf = FakeJf([{"Id": "s1", "Name": "剧名", "OriginalTitle": "S",
                          "ProviderIds": {"Bangumi": "100"}}],
                        {"s1": [ep("e1", "S01E01 - [CASO&DMG] 欢迎来到鸟白岛", 1)]})
            report = run_verify_offline(jf, d, out=os.path.join(d, "c.json"))
            self.assertEqual(report["low_similarity"], 0)

    def test_anchor_mismatch_is_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            write_archive(d, [{"id": 9, "name": "Genji", "name_cn": "源氏物语", "type": 2},
                              {"id": 77, "name": "Bakemonogatari", "name_cn": "化物语", "type": 2}],
                          [{"id": 1, "subject_id": 77, "sort": 1, "type": 0,
                            "name": "a", "name_cn": "一"}])
            jf = FakeJf([{"Id": "s1", "Name": "物语系列", "OriginalTitle": "Monogatari",
                          "ProviderIds": {"Bangumi": "9"}}],
                        {"s1": [ep("e1", "一", 1)]})
            report = run_verify_offline(jf, d, out=os.path.join(d, "c.json"))
            self.assertEqual(len(report["anchor_rows"]), 1)
            self.assertEqual(report["anchor_rows"][0]["kind"], "anchor_unused")
            self.assertEqual(report["anchor_rows"][0]["used"], [77])


if __name__ == "__main__":
    unittest.main()

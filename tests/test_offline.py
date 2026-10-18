"""Offline archive backend: index build, serving, and API fallback."""
import json
import os
import tempfile
import unittest

from jellyfin_bangumi_ids.offline import ArchiveIndex, OfflineBangumi, find_archive


def write_archive(path, subjects, episodes):
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "subject.jsonlines"), "w", encoding="utf-8") as fh:
        for row in subjects:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(os.path.join(path, "episode.jsonlines"), "w", encoding="utf-8") as fh:
        for row in episodes:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


SUBJECTS = [
    {"id": 1606, "type": 2, "name": "涼宮ハルヒの憂鬱", "name_cn": "凉宫春日的忧郁", "date": "2006-04-03"},
    {"id": 95225, "type": 2, "name": "Fate/stay night [UBW]", "name_cn": "命运之夜 无限剑制", "date": "2014-10-05"},
]
EPISODES = [
    {"id": 1, "subject_id": 1606, "sort": 1, "type": 0, "name": "朝比奈ミクルの冒険 Episode00", "name_cn": "朝比奈实玖瑠的冒险 Episode00"},
    {"id": 2, "subject_id": 1606, "sort": 2, "type": 0, "name": "涼宮ハルヒの憂鬱 I", "name_cn": "凉宫春日的忧郁 I"},
    {"id": 3, "subject_id": 1606, "sort": 3, "type": 1, "name": "SP 映像特典", "name_cn": "SP 映像特典"},
    {"id": 4, "subject_id": 95225, "sort": 1, "type": 0, "name": "", "name_cn": ""},
]


class FakeApi:
    def __init__(self):
        self.calls = []

    def subject(self, sid):
        self.calls.append(("subject", sid))
        return {"id": sid, "name": "api-%d" % sid}

    def relations(self, sid):
        self.calls.append(("relations", sid))
        return [{"id": 2, "type": 2, "relation": "续集", "name": "next"}]

    def search(self, keyword, limit=10):
        self.calls.append(("search", keyword))
        return [{"id": 42, "name": keyword}]

    def episodes(self, sid, ep_type=0):
        self.calls.append(("episodes", sid))
        return [{"id": 99, "name": "api ep", "sort": 1}]

    def episode(self, eid):
        self.calls.append(("episode", eid))
        return {"id": eid, "name": "api-%d" % eid}


class ArchiveTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = os.path.join(self.tmp, "archive")
        write_archive(self.dir, SUBJECTS, EPISODES)
        self.cache = os.path.join(self.tmp, "cache")
        os.environ["JBMID_CACHE"] = self.cache
        self.index = ArchiveIndex(self.dir, cache_dir=self.cache, verbose=False)

    def tearDown(self):
        os.environ.pop("JBMID_CACHE", None)

    def test_index_serves_subjects_and_episodes(self):
        self.assertEqual(self.index.subject(1606)["name_cn"], "凉宫春日的忧郁")
        self.assertIsNone(self.index.subject(424242))
        self.assertTrue(self.index.has_subject(95225))
        main = self.index.episodes(1606, 0)
        self.assertEqual([e["id"] for e in main], [1, 2])
        self.assertEqual([e["id"] for e in self.index.episodes(1606, 1)], [3])
        self.assertEqual(self.index.episode(4)["subject_id"], 95225)
        self.assertIsNone(self.index.episode(424242))

    def test_index_is_reused(self):
        self.index.counts()          # first query builds the index
        first = self.index.db_path
        again = ArchiveIndex(self.dir, cache_dir=self.cache, verbose=False)
        self.assertEqual(first, again.db_path)
        self.assertTrue(os.path.exists(first))
        # a rebuilt index counts the same rows
        self.assertEqual(again.counts()["subjects"], 2)
        self.assertEqual(again.counts()["episodes"], 4)

    def test_offline_client_prefers_archive(self):
        api = FakeApi()
        bgm = OfflineBangumi(self.index, api)
        self.assertEqual(bgm.subject(1606)["name_cn"], "凉宫春日的忧郁")
        self.assertEqual([e["id"] for e in bgm.episode_list(1606)], [1, 2])
        self.assertEqual(bgm.episode(2)["name"], "涼宮ハルヒの憂鬱 I")
        self.assertEqual(api.calls, [])
        self.assertEqual(bgm.api_hits, 0)

    def test_offline_client_falls_back_for_unknown(self):
        api = FakeApi()
        bgm = OfflineBangumi(self.index, api)
        self.assertEqual(bgm.subject(424242)["name"], "api-424242")
        self.assertEqual(bgm.episodes(424242), [{"id": 99, "name": "api ep", "sort": 1}])
        self.assertEqual(bgm.episode(424242)["name"], "api-424242")
        self.assertIn(("subject", 424242), api.calls)

    def test_relations_and_search_are_cached(self):
        api = FakeApi()
        bgm = OfflineBangumi(self.index, api)
        self.assertEqual(bgm.relations(1606)[0]["relation"], "续集")
        self.assertEqual(bgm.search("凉宫")[0]["id"], 42)
        self.assertEqual(len(api.calls), 2)
        # second access comes from the index, the API is not asked again
        bgm.relations(1606)
        bgm.search("凉宫")
        self.assertEqual(len(api.calls), 2)
        self.assertEqual(bgm.api_hits, 2)

    def test_find_archive_prefers_explicit_and_env(self):
        self.assertEqual(find_archive(None, self.dir), os.path.abspath(self.dir))
        self.assertIsNone(find_archive(None, os.path.join(self.tmp, "nope")))
        os.environ["JBMID_ARCHIVE"] = self.dir
        try:
            self.assertEqual(find_archive(None), os.path.abspath(self.dir))
        finally:
            os.environ.pop("JBMID_ARCHIVE", None)
        self.assertIsNone(find_archive(None))

    def test_find_archive_reads_jellyfin_data_path(self):
        root = os.path.join(self.tmp, "jf")
        nested = os.path.join(root, "data", "bangumi", "archive")
        write_archive(nested, SUBJECTS, EPISODES)

        class Jf:
            def get(self, path, params=None):
                return {"InternalMetadataPath": os.path.join(root, "metadata"),
                        "DataPath": root}

        self.assertEqual(find_archive(Jf()), os.path.abspath(nested))

        class JfNone(Jf):
            def get(self, path, params=None):
                return {}

        self.assertIsNone(find_archive(JfNone()))

if __name__ == "__main__":
    unittest.main()

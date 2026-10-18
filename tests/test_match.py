import unittest

from jellyfin_bangumi_ids.match import (align, episode_similarity, fill_gaps, is_special,
                                        name_match, similarity, variants)


def ep(name_cn, ep_id=1):
    return {"id": ep_id, "name_cn": name_cn, "name": name_cn}


class MatchTest(unittest.TestCase):
    def test_normalize_drops_punctuation(self):
        self.assertEqual(similarity("Re:Zero", "re zero"), 1.0)

    def test_variants_finds_title_after_dash(self):
        self.assertIn("白夜", variants("进击的巨人 - S03E18 - 白夜"))

    def test_variants_strips_group_and_marker(self):
        self.assertIn("白夜", variants("S01E18 - [SAIO-Raws] 白夜"))

    def test_episode_similarity_uses_variants(self):
        self.assertGreaterEqual(episode_similarity("进击的巨人 - S03E18 - 白夜", ep("白夜")), 0.99)

    def test_special_detection(self):
        self.assertTrue(is_special("OVA 番外篇"))
        self.assertTrue(is_special("总集篇"))
        self.assertFalse(is_special("第3话 觉悟"))

    def test_align_is_monotonic_and_skips_noise(self):
        local = ["A", "B", "C"]
        pool = [ep("A", 10), ep("X", 11), ep("B", 12), ep("C", 13)]
        self.assertEqual(align(local, pool), [(0, 0), (1, 2), (2, 3)])

    def test_fill_gaps_pairs_equal_runs(self):
        self.assertEqual(fill_gaps([(0, 0), (3, 3)], 4, 4), [(0, 0), (1, 1), (2, 2), (3, 3)])

    def test_fill_gaps_keeps_unequal_runs(self):
        self.assertEqual(fill_gaps([(0, 0), (2, 3)], 4, 4), [(0, 0), (2, 3)])

    def test_name_match_guard(self):
        self.assertTrue(name_match("无职转生", "无职转生～到了异世界就拿出真本事～"))
        self.assertFalse(name_match("Andor", "安德烈和威利的冒险"))


if __name__ == "__main__":
    unittest.main()

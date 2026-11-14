import unittest

from jellyfin_bangumi_ids.match import (align, episode_similarity, fill_gaps, fill_unnamed,
                                        is_special, name_match, normalize, similarity, variants)


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


class NormalizeTest(unittest.TestCase):
    def test_kana_survives(self):
        # pure-katakana titles used to normalise to "" and score 0 against everything
        self.assertEqual(normalize("ダンダダン"), "ダンダダン")
        self.assertEqual(similarity("ダンダダン", "ダンダダン"), 1.0)
        self.assertGreater(similarity("よふかしのうた", "よふかしのうた"), 0.9)

    def test_fullwidth_folds_to_ascii(self):
        self.assertEqual(normalize("８６―エイティシックス―"), "86エイティシックス")
        self.assertEqual(normalize("ＦＡＴＥ／ＺＥＲＯ"), "fatezero")

    def test_latin_and_cjk_still_work(self):
        self.assertEqual(normalize("86-不存在的战区-"), "86不存在的战区")
        self.assertTrue(name_match("命运之夜 前传", "Fate/Zero") is False)


class FillUnnamedTest(unittest.TestCase):
    """A show that just started airing: Bangumi created the ids but not the titles."""

    def local(self):
        return [{"Name": n} for n in ("FX是什么？", "我上杠杆了所以没问题", "不止损，不行……？",
                                      "没有浮亏简直太棒了", "做多？做空？", "留意经济指标",
                                      "我不要被强制平仓啊")]

    def pool(self):
        rows = [{"id": 1741638, "name_cn": "FX⋯是什么？", "sort": 1},
                {"id": 1741639, "name_cn": "有槓杆就没问题", "sort": 2}]
        rows += [{"id": 1741638 + k, "name_cn": "", "name": "", "sort": k}
                 for k in range(3, 13)]
        return rows

    def test_fills_the_untitled_tail_after_a_named_pair(self):
        pairs, filled = fill_unnamed([(0, 0), (1, 1)], self.local(), self.pool())
        self.assertEqual(filled, 5)
        self.assertEqual(pairs, [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6)])

    def test_refuses_when_the_block_holds_titles(self):
        pool = self.pool()
        pool[3]["name_cn"] = "有名字"
        _, filled = fill_unnamed([(0, 0), (1, 1)], self.local(), pool)
        self.assertEqual(filled, 0)

    def test_refuses_without_a_preceding_named_pair(self):
        _, filled = fill_unnamed([], self.local()[2:], self.pool()[2:])
        self.assertEqual(filled, 0)

    def test_refuses_when_the_pool_run_is_shorter(self):
        _, filled = fill_unnamed([(0, 0), (1, 1)], self.local(), self.pool()[:5])
        self.assertEqual(filled, 0)

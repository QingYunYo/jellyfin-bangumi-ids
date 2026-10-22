"""`apply --refresh`: after an id is rewritten, ask Jellyfin to refresh that item."""
import unittest

from jellyfin_bangumi_ids.scan import OK, apply_report


class RefreshJf:
    def __init__(self, current, fail_on=()):
        self.current = dict(current)          # item_id -> existing Bangumi id
        self.refreshed = []
        self.fail_on = set(fail_on)

    def item(self, item_id):
        value = self.current.get(item_id)
        return {"Id": item_id,
                "ProviderIds": {"Bangumi": value} if value else {}}

    def set_provider_id(self, item_id, provider, value):
        before = self.current.get(item_id)
        self.current[item_id] = value
        return {"ok": True, "before": before, "after": value, "collateral": {}}

    def refresh_item(self, item_id, replace_all=True):
        if item_id in self.fail_on:
            raise RuntimeError("boom")
        self.refreshed.append(item_id)
        return {"ok": True}


def report(entries):
    return {"series": [{"series": "T", "status": OK,
                        "episodes": [{"item_id": i, "season": 1, "index": n,
                                      "name": "ep", "bgm_id": b}
                                     for n, (i, b) in enumerate(entries, 1)]}]}


class RefreshAfterApplyTest(unittest.TestCase):
    def test_refreshes_only_items_that_changed(self):
        jf = RefreshJf({"a": "1", "b": "2", "c": "3"})
        apply_report(jf, report([("a", "10"), ("b", "2"), ("c", "30")]), refresh=True)
        self.assertEqual(jf.refreshed, ["a", "c"])

    def test_no_refresh_without_the_flag(self):
        jf = RefreshJf({"a": "1"})
        apply_report(jf, report([("a", "10")]))
        self.assertEqual(jf.refreshed, [])

    def test_no_refresh_on_dry_run(self):
        jf = RefreshJf({"a": "1"})
        apply_report(jf, report([("a", "10")]), dry_run=True, refresh=True)
        self.assertEqual(jf.refreshed, [])

    def test_failed_refresh_does_not_stop_the_rest(self):
        jf = RefreshJf({"a": "1", "b": "2"}, fail_on={"a"})
        backup = apply_report(jf, report([("a", "10"), ("b", "20")]), refresh=True)
        self.assertEqual(jf.refreshed, ["b"])
        self.assertEqual(len(backup), 2)

    def test_nothing_to_write_means_nothing_to_refresh(self):
        jf = RefreshJf({"a": "1"})
        apply_report(jf, report([("a", "1")]), refresh=True)
        self.assertEqual(jf.refreshed, [])


if __name__ == "__main__":
    unittest.main()

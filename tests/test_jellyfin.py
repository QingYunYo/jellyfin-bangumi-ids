import unittest

from jellyfin_bangumi_ids.jellyfin import Jellyfin


class _Stub(Jellyfin):
    """Jellyfin client with only the library table stubbed in (no network)."""

    def __init__(self, libs):
        self._libs = dict(libs)

    def libraries(self):
        return dict(self._libs)


class LibraryResolutionTest(unittest.TestCase):
    def setUp(self):
        self.jf = _Stub({"Anime": "a", "Movies": "m", "Concerts": "c"})

    def test_exact_name(self):
        self.assertEqual(self.jf.library_id("Anime"), "a")

    def test_case_insensitive(self):
        self.assertEqual(self.jf.library_id("anime"), "a")
        self.assertEqual(self.jf.library_id("MOVIES"), "m")
        self.assertEqual(self.jf.library_id("  concerts  "), "c")

    def test_unambiguous_substring(self):
        self.assertEqual(self.jf.library_id("movie"), "m")

    def test_ambiguous_substring_lists_candidates(self):
        with self.assertRaises(SystemExit) as ctx:
            self.jf.library_id("o")  # "movies" and "concerts"
        self.assertIn("ambiguous library", str(ctx.exception))

    def test_unknown_library_lists_available(self):
        with self.assertRaises(SystemExit) as ctx:
            self.jf.library_id("Animee")
        message = str(ctx.exception)
        self.assertIn("unknown library: Animee", message)
        self.assertIn("available:", message)
        self.assertIn("Concerts", message)


if __name__ == "__main__":
    unittest.main()

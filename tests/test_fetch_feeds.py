import importlib.machinery
import importlib.util
import json
import pathlib
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "bin" / "fetch-feeds"
loader = importlib.machinery.SourceFileLoader("fetch_feeds", str(SCRIPT))
spec = importlib.util.spec_from_loader("fetch_feeds", loader)
ff = importlib.util.module_from_spec(spec)
loader.exec_module(ff)


class ParseDateTest(unittest.TestCase):
    def test_dates_are_utc_seconds_for_js(self):
        self.assertEqual(ff.parse_date("Tue, 01 Jan 2024 12:00:00 GMT"), "2024-01-01T12:00:00+00:00")
        self.assertEqual(ff.parse_date("2024-01-01T14:00:00.123456+02:00"), "2024-01-01T12:00:00+00:00")
        self.assertEqual(ff.parse_date("2024-01-01T12:00:00.5Z"), "2024-01-01T12:00:00+00:00")

    def test_naive_and_bad_dates(self):
        self.assertEqual(ff.parse_date("2024-01-01T12:00:00"), "2024-01-01T12:00:00+00:00")
        self.assertEqual(ff.parse_date("not a date"), "")
        self.assertEqual(ff.parse_date(""), "")


class CacheFallbackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.original = (ff.CACHE, ff.fetch)
        self.addCleanup(self._restore)
        ff.CACHE = pathlib.Path(self.tmp.name) / "cache.json"

    def _restore(self):
        ff.CACHE, ff.fetch = self.original

    def test_failed_feed_keeps_cached_items(self):
        feeds = [{"name": "A", "url": "https://a.test/rss"}]
        item = {"title": "Hello", "url": "https://a.test/1", "published": ""}

        ff.fetch = lambda f: {"name": f["name"], "items": [item], "error": None}
        ff.run(feeds)

        ff.fetch = lambda f: {"name": f["name"], "items": [], "error": "timed out"}
        results = ff.run(feeds)

        self.assertEqual(results[0]["items"], [item])
        self.assertEqual(results[0]["error"], "timed out")
        self.assertEqual(ff.load_cache(), [{"name": "A", "items": [item]}])

    def test_cached_mode_reads_saved_cache(self):
        ff.save_cache([{"name": "A", "items": []}])
        self.assertEqual(ff.load_cache(), [{"name": "A", "items": []}])

    def test_bad_cache_is_ignored(self):
        ff.CACHE.write_text(json.dumps({"not": "a list"}))
        self.assertEqual(ff.load_cache(), [])
        ff.CACHE.write_text("not json")
        self.assertEqual(ff.load_cache(), [])


if __name__ == "__main__":
    unittest.main()

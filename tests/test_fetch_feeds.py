import importlib.machinery
import importlib.util
import json
import pathlib
import tempfile
import unittest
import unittest.mock

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


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = pathlib.Path(self.tmp.name)
        self.original = (ff.CACHE, ff.SEEN, ff.CONFIG, ff.fetch)
        self.addCleanup(self._restore)
        ff.CACHE = base / "cache.json"
        ff.SEEN = base / "seen.json"
        ff.CONFIG = base / "feeds.json"

    def _restore(self):
        ff.CACHE, ff.SEEN, ff.CONFIG, ff.fetch = self.original


class CacheFallbackTest(FilesTest):
    def test_failed_feed_keeps_cached_items(self):
        feeds = [{"name": "A", "url": "https://a.test/rss"}]
        item = {"title": "Hello", "url": "https://a.test/1", "published": ""}

        ff.fetch = lambda f, *_: {"name": f["name"], "items": [item], "error": None}
        ff.run(feeds)

        ff.fetch = lambda f, *_: {"name": f["name"], "items": [], "error": "timed out"}
        results = ff.run(feeds)

        self.assertEqual(results[0]["items"], [item])
        self.assertEqual(results[0]["error"], "timed out")
        self.assertEqual(ff.load_cache(), [{"name": "A", "url": "https://a.test/rss", "items": [item]}])

    def test_cached_mode_reads_saved_cache(self):
        ff.save_cache([{"name": "A", "items": []}])
        self.assertEqual(ff.load_cache(), [{"name": "A", "items": []}])

    def test_bad_cache_is_ignored(self):
        ff.CACHE.write_text(json.dumps({"not": "a list"}))
        self.assertEqual(ff.load_cache(), [])
        ff.CACHE.write_text("not json")
        self.assertEqual(ff.load_cache(), [])


class LimitTest(unittest.TestCase):
    def test_limit_is_read_and_clamped(self):
        self.assertEqual(ff.parse_limit(["--limit", "5"]), 5)
        self.assertEqual(ff.parse_limit(["--limit", "999"]), ff.MAX_LIMIT)
        self.assertEqual(ff.parse_limit(["--limit", "0"]), 1)
        self.assertEqual(ff.parse_limit(["--limit", "x"]), ff.LIMIT)
        self.assertEqual(ff.parse_limit([]), ff.LIMIT)


class ReadStateTest(FilesTest):
    def test_mark_read_dedupes_skips_bad_urls_and_caps(self):
        ff.mark_read(["https://a.test/1", "https://a.test/1", "javascript:x", "https://a.test/2"])
        ff.mark_read(["https://a.test/2", "https://a.test/3"])
        self.assertEqual(ff.load_seen(), ["https://a.test/1", "https://a.test/2", "https://a.test/3"])

        with unittest.mock.patch.object(ff, "MAX_SEEN", 2):
            ff.mark_read(["https://a.test/4"])
        self.assertEqual(ff.load_seen(), ["https://a.test/3", "https://a.test/4"])


class FeedEditTest(FilesTest):
    def test_add_creates_file_from_defaults_and_keeps_them(self):
        self.assertTrue(ff.add_feed("https://b.test/rss")["ok"])
        names = [f["name"] for f in json.loads(ff.CONFIG.read_text())]
        self.assertEqual(names, ["Hacker News", "Omarchy News", "b.test"])

    def test_add_rejects_duplicates_and_non_http(self):
        ff.add_feed("https://b.test/rss")
        self.assertFalse(ff.add_feed("https://b.test/rss")["ok"])
        self.assertFalse(ff.add_feed("file:///etc/passwd")["ok"])

    def test_remove_keeps_entries_it_does_not_own(self):
        ff.CONFIG.write_text(json.dumps([
            {"name": "A", "url": "https://a.test/rss"},
            {"name": "", "url": "https://bad.test"},
            {"name": "B", "url": "https://b.test/rss"},
        ]))
        self.assertTrue(ff.remove_feed("https://a.test/rss")["ok"])
        self.assertEqual(json.loads(ff.CONFIG.read_text()), [
            {"name": "", "url": "https://bad.test"},
            {"name": "B", "url": "https://b.test/rss"},
        ])

    def test_remove_refuses_last_valid_feed(self):
        ff.CONFIG.write_text(json.dumps([{"name": "A", "url": "https://a.test/rss"}]))
        self.assertFalse(ff.remove_feed("https://a.test/rss")["ok"])
        self.assertEqual(ff.load_feeds(), [{"name": "A", "url": "https://a.test/rss"}])

    def test_broken_config_is_never_overwritten(self):
        ff.CONFIG.write_text("{ not json, but my notes")
        self.assertFalse(ff.add_feed("https://b.test/rss")["ok"])
        self.assertFalse(ff.remove_feed("https://b.test/rss")["ok"])
        self.assertEqual(ff.CONFIG.read_text(), "{ not json, but my notes")


if __name__ == "__main__":
    unittest.main()

import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
import sys
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
        self.assertEqual(ff.load_cache(), [{"name": "A", "url": "https://a.test/rss", "items": [item], "disabled": False}])

    def test_fallback_matches_by_url_not_name(self):
        item = {"title": "Old", "url": "https://a.test/1", "published": ""}
        ff.save_cache([{"name": "A", "url": "https://a.test/rss", "items": [item]}])

        ff.fetch = lambda f, *_: {"name": f["name"], "items": [], "error": "timed out"}
        renamed = ff.run([{"name": "Renamed", "url": "https://a.test/rss"}])
        other = ff.run([{"name": "A", "url": "https://b.test/rss"}])

        self.assertEqual(renamed[0]["items"], [item])
        self.assertEqual(other[0]["items"], [])

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


class FeedOptionsTest(FilesTest):
    def test_limit_and_enabled_are_read_with_safe_defaults(self):
        self.assertEqual(ff.valid_feed({"name": "A", "url": "https://a.test", "limit": 999})["limit"], ff.MAX_LIMIT)
        self.assertEqual(ff.valid_feed({"name": "A", "url": "https://a.test", "limit": "5"})["limit"], None)
        self.assertEqual(ff.valid_feed({"name": "A", "url": "https://a.test", "limit": True})["limit"], None)
        self.assertTrue(ff.valid_feed({"name": "A", "url": "https://a.test"})["enabled"])
        self.assertFalse(ff.valid_feed({"name": "A", "url": "https://a.test", "enabled": False})["enabled"])

    def test_disabled_feed_is_not_fetched_and_per_feed_limit_is_used(self):
        seen = []
        ff.fetch = lambda f, limit: seen.append((f["name"], limit)) or {"name": f["name"], "items": [], "error": None}
        results = ff.run([
            {"name": "On", "url": "https://a.test/rss", "enabled": True, "limit": 3},
            {"name": "Off", "url": "https://b.test/rss", "enabled": False, "limit": None},
            {"name": "Plain", "url": "https://c.test/rss"},
        ], limit=15)
        self.assertEqual(seen, [("On", 3), ("Plain", 15)])
        self.assertEqual(results[1], {"name": "Off", "items": [], "error": None, "disabled": True, "url": "https://b.test/rss"})

    def test_toggle_disables_and_enables_and_keeps_one_enabled(self):
        ff.CONFIG.write_text(json.dumps([
            {"name": "A", "url": "https://a.test/rss"},
            {"name": "B", "url": "https://b.test/rss"},
        ]))
        self.assertTrue(ff.toggle_feed("https://a.test/rss")["ok"])
        self.assertFalse(ff.toggle_feed("https://b.test/rss")["ok"])
        self.assertEqual([f.get("enabled", True) for f in json.loads(ff.CONFIG.read_text())], [False, True])
        self.assertTrue(ff.toggle_feed("https://a.test/rss")["ok"])
        self.assertEqual([f.get("enabled", True) for f in json.loads(ff.CONFIG.read_text())], [True, True])

    def test_remove_refuses_when_only_disabled_feeds_would_remain(self):
        ff.CONFIG.write_text(json.dumps([
            {"name": "A", "url": "https://a.test/rss"},
            {"name": "B", "url": "https://b.test/rss", "enabled": False},
        ]))
        self.assertFalse(ff.remove_feed("https://a.test/rss")["ok"])


class ReadStateTest(FilesTest):
    def test_mark_read_dedupes_skips_bad_urls_and_caps(self):
        ff.mark_read(["https://a.test/1", "https://a.test/1", "javascript:x", "https://a.test/2"])
        ff.mark_read(["https://a.test/2", "https://a.test/3"])
        self.assertEqual(ff.load_seen(), ["https://a.test/1", "https://a.test/2", "https://a.test/3"])

        with unittest.mock.patch.object(ff, "MAX_SEEN", 2):
            ff.mark_read(["https://a.test/4"])
        self.assertEqual(ff.load_seen(), ["https://a.test/3", "https://a.test/4"])

    def test_reread_headline_is_kept_over_older_reads(self):
        ff.mark_read(["https://a.test/1", "https://a.test/2"])
        ff.mark_read(["https://a.test/1"])
        with unittest.mock.patch.object(ff, "MAX_SEEN", 2):
            ff.mark_read(["https://a.test/3"])
        self.assertEqual(ff.load_seen(), ["https://a.test/1", "https://a.test/3"])

    def test_unmark_removes_only_given_urls(self):
        ff.mark_read(["https://a.test/1", "https://a.test/2"])
        ff.unmark_read(["https://a.test/1", "https://a.test/9"])
        self.assertEqual(ff.load_seen(), ["https://a.test/2"])

    def test_read_state_is_private(self):
        old = os.umask(0o022)
        self.addCleanup(os.umask, old)
        ff.SEEN = pathlib.Path(self.tmp.name) / "new" / "seen.json"
        ff.mark_read(["https://a.test/1"])
        self.assertEqual(ff.SEEN.stat().st_mode & 0o777, 0o600)
        self.assertEqual(ff.SEEN.parent.stat().st_mode & 0o777, 0o700)

    def test_startup_read_tightens_old_files(self):
        ff.CACHE.write_text("[]")
        ff.SEEN.write_text('["https://a.test/1"]')
        os.chmod(ff.CACHE, 0o644)
        os.chmod(ff.SEEN, 0o644)
        os.chmod(self.tmp.name, 0o755)
        with unittest.mock.patch.object(sys, "argv", ["fetch-feeds", "--seen"]), unittest.mock.patch("sys.stdout"):
            ff.main()
        self.assertEqual(ff.SEEN.stat().st_mode & 0o777, 0o600)
        self.assertEqual(ff.CACHE.stat().st_mode & 0o777, 0o600)
        self.assertEqual(pathlib.Path(self.tmp.name).stat().st_mode & 0o777, 0o700)


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
        self.assertEqual(ff.load_feeds()[0], [{"name": "A", "url": "https://a.test/rss", "enabled": True, "limit": None}])

    def test_broken_config_is_never_overwritten(self):
        ff.CONFIG.write_text("{ not json, but my notes")
        self.assertFalse(ff.add_feed("https://b.test/rss")["ok"])
        self.assertFalse(ff.remove_feed("https://b.test/rss")["ok"])
        self.assertEqual(ff.CONFIG.read_text(), "{ not json, but my notes")

    def test_all_invalid_entries_are_kept_when_adding(self):
        ff.CONFIG.write_text(json.dumps([{"name": "", "url": "https://bad.test"}, "my notes"]))
        self.assertTrue(ff.add_feed("https://b.test/rss")["ok"])
        self.assertEqual(json.loads(ff.CONFIG.read_text()), [
            {"name": "", "url": "https://bad.test"},
            "my notes",
            {"name": "b.test", "url": "https://b.test/rss"},
        ])

    def test_broken_config_falls_back_to_defaults_with_error(self):
        ff.CONFIG.write_text("{ not json")
        feeds, error = ff.load_feeds()
        self.assertEqual(feeds, ff.DEFAULT)
        self.assertEqual(error, "feeds.json is not valid JSON")

    def test_run_reports_broken_config_as_a_failed_entry(self):
        ff.CONFIG.write_text("{ not json")
        ff.fetch = lambda f, *_: {"name": f["name"], "items": [], "error": None}
        buf = io.BytesIO()
        stdout = io.TextIOWrapper(buf, encoding="utf-8")
        with unittest.mock.patch.object(sys, "argv", ["fetch-feeds"]), unittest.mock.patch.object(sys, "stdout", stdout):
            ff.main()
        out = json.loads(buf.getvalue())
        self.assertEqual(out[0]["error"], "feeds.json is not valid JSON")
        self.assertEqual([r["name"] for r in out[1:]], ["Hacker News", "Omarchy News"])


if __name__ == "__main__":
    unittest.main()

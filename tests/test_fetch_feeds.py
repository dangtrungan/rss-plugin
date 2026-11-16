import importlib.machinery
import email.message
import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile
import time
import unittest
import unittest.mock
import urllib.error

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "bin" / "fetch-feeds"
loader = importlib.machinery.SourceFileLoader("fetch_feeds", str(SCRIPT))
spec = importlib.util.spec_from_loader("fetch_feeds", loader)
ff = importlib.util.module_from_spec(spec)
loader.exec_module(ff)


FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


class FixtureTest(unittest.TestCase):
    def load(self, name):
        return ff.parse((FIXTURES / name).read_bytes())

    def test_messy_rss(self):
        self.assertEqual(self.load("messy_rss.xml"), [
            {"title": "Named zone date", "url": "https://example.test/a?id=1", "published": "2024-01-01T12:00:00+00:00"},
            {"title": "No date at all", "url": "https://example.test/b", "published": ""},
            {"title": "ISO fallback date", "url": "https://example.test/c", "published": "2024-01-02T10:00:00+00:00"},
            {"title": "Garbage date", "url": "https://example.test/d", "published": ""},
        ])

    def test_messy_atom(self):
        self.assertEqual(self.load("messy_atom.xml"), [
            {"title": "Two links", "url": "https://example.test/first", "published": "2024-03-01T13:30:00+00:00"},
            {"title": "Published only", "url": "https://example.test/p", "published": "2024-03-02T09:00:00+00:00"},
        ])

    def test_messy_json_feed(self):
        self.assertEqual(self.load("messy_jsonfeed.json"), [
            {"title": "With date", "url": "https://example.test/j1", "published": "2024-04-01T12:00:00+00:00"},
            {"title": "External link", "url": "https://example.test/j2", "published": ""},
            {"title": "Date is a number", "url": "https://example.test/j3", "published": ""},
            {"title": "Missing date", "url": "https://example.test/j4", "published": ""},
        ])

    def test_doctype_is_rejected_before_parsing(self):
        with self.assertRaisesRegex(ValueError, "DTD"):
            ff.parse(b'<!DOCTYPE rss [<!ENTITY a "b">]><rss><channel/></rss>')

    def test_json_feed_with_bad_items_has_no_items(self):
        self.assertEqual(ff.parse(b'{"items": 5}'), [])
        self.assertEqual(ff.parse(b'{"items": [1, "x", null]}'), [])


class ReadBodyTest(unittest.TestCase):
    class Chunks:
        def __init__(self, *chunks):
            self.chunks = list(chunks)

        def read(self, n):
            return self.chunks.pop(0) if self.chunks else b""

    def test_reads_whole_body(self):
        self.assertEqual(ff.read_body(self.Chunks(b"ab", b"cd"), time.monotonic() + 5), b"abcd")

    def test_expired_deadline_stops_a_slow_download(self):
        with self.assertRaisesRegex(TimeoutError, "timed out"):
            ff.read_body(self.Chunks(b"ab"), time.monotonic() - 1)

    def test_body_over_cap_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "2 MB"):
            ff.read_body(self.Chunks(b"x" * (ff.MAX_BYTES + 1)), time.monotonic() + 5)


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
        cached = ff.load_cache()[0]
        self.assertEqual(cached["items"], [item])
        self.assertIsNotNone(cached["failing_since"])
        self.assertIsNotNone(cached["last_ok"])

    def test_staleness_tracks_last_success_and_first_failure(self):
        ok = {"name": "A", "items": [], "error": None}
        bad = {"name": "A", "items": [], "error": "timed out"}
        feeds = [{"name": "A", "url": "https://a.test/rss"}]
        ff.fetch = lambda f, *_: dict(ok)
        last_ok = ff.run(feeds)[0]["last_ok"]
        ff.fetch = lambda f, *_: dict(bad)
        first = ff.run(feeds)[0]
        self.assertEqual(first["last_ok"], last_ok)
        self.assertIsNotNone(first["failing_since"])
        with unittest.mock.patch.object(ff, "utc_iso", return_value="2030-01-01T00:00:00+00:00"):
            again = ff.run(feeds)[0]
        self.assertEqual(again["failing_since"], first["failing_since"])
        ff.fetch = lambda f, *_: dict(ok)
        self.assertIsNone(ff.run(feeds)[0]["failing_since"])

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
        ff.fetch = lambda f, limit, *_: seen.append((f["name"], limit)) or {"name": f["name"], "items": [], "error": None}
        results = ff.run([
            {"name": "On", "url": "https://a.test/rss", "enabled": True, "limit": 3},
            {"name": "Off", "url": "https://b.test/rss", "enabled": False, "limit": None},
            {"name": "Plain", "url": "https://c.test/rss"},
        ], limit=15)
        self.assertEqual(seen, [("On", 3), ("Plain", 15)])
        self.assertEqual(results[1], {"name": "Off", "items": [], "error": None, "disabled": True, "url": "https://b.test/rss", "last_ok": None, "failing_since": None})

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


class ConditionalTest(FilesTest):
    url = "https://a.test/rss"

    def _run_with(self, respond):
        calls = []

        def fake_urlopen(req, timeout):
            calls.append(req)
            return respond()

        with unittest.mock.patch.object(ff.urllib.request, "urlopen", fake_urlopen):
            results = ff.run([{"name": "A", "url": self.url}])
        return results, calls[0]

    def test_304_reuses_cached_items_and_sends_validators(self):
        item = {"title": "Old", "url": "https://a.test/1", "published": ""}
        ff.save_cache([{"name": "A", "url": self.url, "items": [item], "etag": '"v1"', "modified": "Mon, 01 Jan 2024 00:00:00 GMT"}])

        def not_modified():
            raise urllib.error.HTTPError(self.url, 304, "Not Modified", {}, None)

        results, req = self._run_with(not_modified)
        self.assertEqual(req.get_header("If-none-match"), '"v1"')
        self.assertEqual(req.get_header("If-modified-since"), "Mon, 01 Jan 2024 00:00:00 GMT")
        self.assertEqual(results[0]["items"], [item])
        self.assertIsNone(results[0]["error"])
        self.assertEqual(ff.load_cache()[0]["etag"], '"v1"')

    def test_200_stores_new_validators(self):
        headers = email.message.Message()
        headers["ETag"] = '"v2"'
        headers["Last-Modified"] = "Tue, 02 Jan 2024 00:00:00 GMT"
        body = b'<rss><channel><item><title>New</title><link>https://a.test/2</link></item></channel></rss>'

        def ok():
            response = io.BytesIO(body)
            response.headers = headers
            return response

        results, req = self._run_with(ok)
        self.assertIsNone(req.get_header("If-none-match"))
        self.assertEqual(results[0]["items"][0]["title"], "New")
        cached = ff.load_cache()[0]
        self.assertEqual((cached["etag"], cached["modified"]), ('"v2"', "Tue, 02 Jan 2024 00:00:00 GMT"))


class CanonicalTest(FilesTest):
    def test_tracking_parameters_are_removed(self):
        self.assertEqual(ff.canonical("https://a.test/p?utm_source=x&id=7&fbclid=y&gclid=z"), "https://a.test/p?id=7")
        self.assertEqual(ff.canonical("https://a.test/p?utm_medium=x"), "https://a.test/p")
        self.assertEqual(ff.canonical("https://a.test/p"), "https://a.test/p")

    def test_old_read_state_with_tracking_matches_new_urls(self):
        ff.SEEN.write_text(json.dumps(["https://a.test/1?utm_source=rss"]))
        self.assertEqual(ff.load_seen(), ["https://a.test/1"])
        ff.mark_read(["https://a.test/2?utm_source=rss"])
        ff.unmark_read(["https://a.test/1?utm_source=rss"])
        self.assertEqual(ff.load_seen(), ["https://a.test/2"])

    def test_same_story_across_feeds_is_shown_once(self):
        item_a = {"title": "Story", "url": "https://a.test/s", "published": ""}
        results = [
            {"name": "A", "items": [item_a, dict(item_a)]},
            {"name": "B", "items": [dict(item_a, title="Same")]},
        ]
        ff.dedupe(results)
        self.assertEqual([len(r["items"]) for r in results], [1, 0])


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

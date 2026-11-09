from __future__ import annotations

import os
import time
import unittest

import alfred
from clipdb import Clip, Hit


def make_hit(item="host 10.0.0.1 up", match="10.0.0.1", extra=0, app="Slack", ts=0.0, rowid=7):
    return Hit(Clip(rowid, item, ts, app), match, extra)


class FormatDateTests(unittest.TestCase):
    def setUp(self):
        self._tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()

    def tearDown(self):
        if self._tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._tz
        time.tzset()

    def test_cocoa_epoch(self):
        self.assertEqual(alfred.format_date(0), "2001-01-01 00:00")

    def test_fractional_ts(self):
        self.assertEqual(alfred.format_date(60.9), "2001-01-01 00:01")

    def test_real_range_ts(self):
        # 2026-11-08 14:02:00 UTC = 1794146520 unix
        self.assertEqual(alfred.format_date(1794146520 - 978307200), "2026-11-08 14:02")

    def test_explicit_tz_offset(self):
        self.assertEqual(alfred.format_date(0, tz=timezone_plus(2)), "2001-01-01 02:00")


def timezone_plus(hours):
    from datetime import timedelta, timezone
    return timezone(timedelta(hours=hours))


class ToItemsTests(unittest.TestCase):
    def setUp(self):
        self._tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()

    def tearDown(self):
        if self._tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._tz
        time.tzset()

    def test_top_level(self):
        out = alfred.to_items([make_hit()], "regex")
        self.assertIs(out["skipknowledge"], True)
        self.assertEqual(len(out["items"]), 1)

    def test_empty_hits(self):
        self.assertEqual(alfred.to_items([], "regex")["items"], [])

    def test_item_schema(self):
        item = alfred.to_items([make_hit()], "regex")["items"][0]
        self.assertEqual(item["uid"], "7")
        self.assertEqual(item["title"], "10.0.0.1")
        self.assertEqual(item["arg"], "host 10.0.0.1 up")
        self.assertIs(item["valid"], True)
        self.assertEqual(item["text"], {"copy": "host 10.0.0.1 up", "largetype": "host 10.0.0.1 up"})
        self.assertEqual(item["mods"]["cmd"], {"arg": "10.0.0.1", "subtitle": "Paste matched part only"})
        self.assertEqual(
            item["mods"]["alt"], {"arg": "host 10.0.0.1 up", "subtitle": "Copy full clip (no paste)"}
        )

    def test_title_single_line_and_truncated(self):
        long = "a" * 300
        item = alfred.to_items([make_hit(match="x\n  y\tz")], "text")["items"][0]
        self.assertEqual(item["title"], "x y z")
        item = alfred.to_items([make_hit(match=long)], "text")["items"][0]
        self.assertEqual(len(item["title"]), 120)

    def test_title_falls_back_to_clip_when_match_blank(self):
        item = alfred.to_items([make_hit(item="whole clip", match="")], "text")["items"][0]
        self.assertEqual(item["title"], "whole clip")

    def test_subtitle_parts(self):
        sub = alfred.to_items([make_hit(extra=2)], "regex")["items"][0]["subtitle"]
        self.assertEqual(sub, "🧠 regex · Slack · 2001-01-01 00:00 · +2 more · host 10.0.0.1 up")

    def test_subtitle_no_more_when_zero(self):
        sub = alfred.to_items([make_hit(extra=0)], "regex")["items"][0]["subtitle"]
        self.assertNotIn("more", sub)

    def test_subtitle_text_marker(self):
        sub = alfred.to_items([make_hit()], "text")["items"][0]["subtitle"]
        self.assertTrue(sub.startswith("🔤 text"))

    def test_subtitle_empty_app_omitted(self):
        sub = alfred.to_items([make_hit(app="")], "regex")["items"][0]["subtitle"]
        self.assertEqual(sub, "🧠 regex · 2001-01-01 00:00 · host 10.0.0.1 up")

    def test_null_or_bad_ts_does_not_raise(self):
        for ts in (None, "junk"):
            sub = alfred.to_items([make_hit(ts=ts)], "regex")["items"][0]["subtitle"]
            self.assertEqual(sub, "🧠 regex · Slack · host 10.0.0.1 up")

    def test_cmd_arg_falls_back_to_full_clip_when_match_empty(self):
        item = alfred.to_items([make_hit(item="whole clip", match="")], "text")["items"][0]
        self.assertEqual(item["mods"]["cmd"]["arg"], "whole clip")

    def test_preview_collapsed_and_capped(self):
        hit = make_hit(item="a\n\n  b " + "c" * 200)
        sub = alfred.to_items([hit], "regex")["items"][0]["subtitle"]
        preview = sub.split(" · ")[-1]
        self.assertTrue(preview.startswith("a b c"))
        self.assertEqual(len(preview), 80)

    def test_unique_uids(self):
        items = alfred.to_items([make_hit(rowid=1), make_hit(rowid=2)], "regex")["items"]
        self.assertEqual([i["uid"] for i in items], ["1", "2"])


class MessageItemTests(unittest.TestCase):
    def test_invalid_item(self):
        self.assertEqual(
            alfred.message_item("No clips match 'x'", "try again"),
            {"title": "No clips match 'x'", "subtitle": "try again", "valid": False},
        )

    def test_default_subtitle(self):
        self.assertEqual(alfred.message_item("t")["subtitle"], "")


if __name__ == "__main__":
    unittest.main()

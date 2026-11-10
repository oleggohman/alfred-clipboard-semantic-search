from __future__ import annotations

import os
import tempfile
import time
import unittest

import alfred
from clipdb import Clip, Hit


def make_hit(item="host 10.0.0.1 up", match="10.0.0.1", extra=0, app="Slack", ts=0.0, rowid=7, apppath=""):
    return Hit(Clip(rowid, item, ts, app, apppath), match, extra)


NOW = 1794146520.0  # unix seconds
NOW_COCOA = NOW - alfred.COCOA_EPOCH


class FormatAgeTests(unittest.TestCase):
    def age(self, delta):
        return alfred.format_age(NOW_COCOA - delta, now=NOW)

    def test_recent_is_just_now(self):
        self.assertEqual(self.age(30), "just now")

    def test_future_is_just_now(self):
        self.assertEqual(self.age(-500), "just now")

    def test_minutes(self):
        self.assertEqual(self.age(5 * 60), "5m ago")

    def test_hours(self):
        self.assertEqual(self.age(2 * 3600), "2h ago")

    def test_days(self):
        self.assertEqual(self.age(3 * 86400), "3d ago")

    def test_seven_days_is_date(self):
        expected = time.strftime("%Y-%m-%d", time.localtime(NOW - 7 * 86400))
        self.assertEqual(self.age(7 * 86400), expected)

    def test_invalid_ts(self):
        for ts in (None, "junk"):
            self.assertEqual(alfred.format_age(ts, now=NOW), "")

    def test_default_now(self):
        self.assertEqual(alfred.format_age(time.time() - alfred.COCOA_EPOCH), "just now")


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
        self.assertEqual(item["arg"], "10.0.0.1")
        self.assertIs(item["valid"], True)
        self.assertEqual(item["text"], {"copy": "host 10.0.0.1 up", "largetype": "host 10.0.0.1 up"})
        self.assertEqual(item["mods"], {"cmd": {"arg": "host 10.0.0.1 up", "subtitle": "Copy whole clip"}})

    def test_arg_falls_back_to_clip_when_match_blank(self):
        item = alfred.to_items([make_hit(item="whole clip", match="  ")], "text")["items"][0]
        self.assertEqual(item["arg"], "whole clip")

    def test_icon_when_app_path_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = alfred.to_items([make_hit(apppath=tmp)], "regex")["items"][0]
        self.assertEqual(item["icon"], {"type": "fileicon", "path": tmp})

    def test_no_icon_when_app_path_empty_or_missing(self):
        for path in ("", os.path.join(tempfile.gettempdir(), "no-such-app-xyz.app")):
            item = alfred.to_items([make_hit(apppath=path)], "regex")["items"][0]
            self.assertNotIn("icon", item)

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
        sub = alfred.to_items([make_hit(extra=2, ts=NOW_COCOA - 3 * 86400)], "regex", now=NOW)["items"][0]["subtitle"]
        self.assertEqual(sub, "3d ago · +2 more · host 10.0.0.1 up")

    def test_subtitle_no_more_when_zero(self):
        sub = alfred.to_items([make_hit(extra=0)], "regex")["items"][0]["subtitle"]
        self.assertNotIn("more", sub)

    def test_subtitle_text_marker(self):
        sub = alfred.to_items([make_hit(ts=NOW_COCOA - 300)], "text", now=NOW)["items"][0]["subtitle"]
        self.assertEqual(sub, "🔤 text · 5m ago · host 10.0.0.1 up")

    def test_subtitle_has_no_app_name(self):
        sub = alfred.to_items([make_hit(app="Slack")], "regex")["items"][0]["subtitle"]
        self.assertNotIn("Slack", sub)

    def test_preview_omitted_when_title_starts_with_it(self):
        sub = alfred.to_items([make_hit(item="10.0.0.1", match="10.0.0.1", ts=NOW_COCOA - 300)], "regex", now=NOW)[
            "items"
        ][0]["subtitle"]
        self.assertEqual(sub, "5m ago")

    def test_preview_omitted_for_long_single_line_clip(self):
        hit = make_hit(item="a" * 200, match="")
        sub = alfred.to_items([hit], "regex", now=NOW)["items"][0]["subtitle"]
        self.assertNotIn("a" * 10, sub)

    def test_preview_kept_when_different(self):
        sub = alfred.to_items([make_hit(ts=NOW_COCOA - 300)], "regex", now=NOW)["items"][0]["subtitle"]
        self.assertTrue(sub.endswith("host 10.0.0.1 up"))

    def test_null_or_bad_ts_does_not_raise(self):
        for ts in (None, "junk"):
            sub = alfred.to_items([make_hit(ts=ts)], "regex", now=NOW)["items"][0]["subtitle"]
            self.assertEqual(sub, "host 10.0.0.1 up")

    def test_preview_collapsed_and_capped(self):
        hit = make_hit(item="a\n\n  b " + "c" * 200, match="zzz")
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

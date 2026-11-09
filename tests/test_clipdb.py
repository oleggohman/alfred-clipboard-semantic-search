from __future__ import annotations

import os
import re
import signal
import sqlite3
import tempfile
import time
import unittest

import clipdb
from clipdb import Clip

SCHEMA = (
    "CREATE TABLE clipboard (item text, ts decimal, app text, apppath text, "
    "dataType integer, dataHash text)"
)


def make_db(rows):
    """rows: (item, ts, app, dataType) tuples; item may be a SQL expression marker."""
    fd, path = tempfile.mkstemp(suffix=".alfdb")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(SCHEMA)
    for item, ts, app, dtype in rows:
        conn.execute(
            "INSERT INTO clipboard (item, ts, app, apppath, dataType, dataHash) VALUES (?,?,?,?,?,?)",
            (item, ts, app, "", dtype, "h"),
        )
    conn.commit()
    conn.close()
    return path


def clips(*items):
    return [Clip(i + 1, t, float(100 - i), "App") for i, t in enumerate(items)]


class LoadClipsTests(unittest.TestCase):
    def tearDown(self):
        for p in getattr(self, "paths", []):
            os.unlink(p)

    def db(self, rows):
        path = make_db(rows)
        self.paths = getattr(self, "paths", []) + [path]
        return path

    def test_only_text_newest_first(self):
        path = self.db([("old", 1, "A", 0), ("img", 5, "A", 1), ("new", 9, "B", 0)])
        got = clipdb.load_clips(path)
        self.assertEqual([c.item for c in got], ["new", "old"])
        self.assertEqual(got[0].app, "B")
        self.assertEqual(got[0].ts, 9)

    def test_null_item_skipped_null_app_empty(self):
        path = self.db([(None, 2, "A", 0), ("x", 1, None, 0)])
        got = clipdb.load_clips(path)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].app, "")

    def test_invalid_utf8_replaced(self):
        path = self.db([("x", 1, "A", 0)])
        conn = sqlite3.connect(path)
        conn.execute("UPDATE clipboard SET item = CAST(x'fffe41' AS TEXT)")
        conn.commit()
        conn.close()
        got = clipdb.load_clips(path)
        self.assertEqual(len(got), 1)
        self.assertIn("�", got[0].item)
        self.assertTrue(got[0].item.endswith("A"))

    def test_read_only(self):
        path = self.db([("x", 1, "A", 0)])
        conn = clipdb._connect(path)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("DELETE FROM clipboard")
        conn.close()

    def test_missing_db(self):
        with self.assertRaises(clipdb.ClipDBError):
            clipdb.load_clips("/nonexistent/dir/clipboard.alfdb")

    def test_corrupt_db(self):
        fd, path = tempfile.mkstemp()
        os.write(fd, b"not a sqlite file" * 100)
        os.close(fd)
        self.paths = [path]
        with self.assertRaises(clipdb.ClipDBError):
            clipdb.load_clips(path)

    def test_path_with_special_chars(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "a b#c?.alfdb")
        src = make_db([("x", 1, "A", 0)])
        os.rename(src, path)
        self.paths = [path]
        self.assertEqual(len(clipdb.load_clips(path)), 1)


class RegexSearchTests(unittest.TestCase):
    IP = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")

    def test_hits_and_match(self):
        cs = clips("host 10.0.0.1 up", "nothing", "a 192.168.1.5")
        res = clipdb.regex_search(cs, self.IP)
        self.assertEqual([h.match for h in res.hits], ["10.0.0.1", "192.168.1.5"])
        self.assertEqual(res.scanned, 3)
        self.assertEqual(res.matched_total, 2)
        self.assertFalse(res.timed_out)

    def test_extra_count(self):
        res = clipdb.regex_search(clips("1.1.1.1 2.2.2.2 3.3.3.3"), self.IP)
        self.assertEqual(res.hits[0].match, "1.1.1.1")
        self.assertEqual(res.hits[0].extra, 2)

    def test_extra_capped(self):
        res = clipdb.regex_search(clips(" ".join(["1.1.1.1"] * 200)), self.IP)
        self.assertEqual(res.hits[0].extra, 99)

    def test_zero_length_only_no_hit(self):
        res = clipdb.regex_search(clips("abc"), re.compile(r"x*"))
        self.assertEqual(res.hits, [])
        self.assertEqual(res.matched_total, 0)

    def test_zero_length_then_real_match(self):
        res = clipdb.regex_search(clips("abc"), re.compile(r"b*"))
        self.assertEqual(res.hits[0].match, "b")

    def test_no_hits(self):
        res = clipdb.regex_search(clips("a", "b"), self.IP)
        self.assertEqual(res.hits, [])
        self.assertEqual(res.scanned, 2)

    def test_limit_matched_total_counts_all(self):
        res = clipdb.regex_search(clips(*["1.2.3.4"] * 10), self.IP, limit=3)
        self.assertEqual(len(res.hits), 3)
        self.assertEqual(res.matched_total, 10)
        self.assertEqual(res.scanned, 10)

    def test_char_cap(self):
        text = "x" * 20000 + " 1.2.3.4"
        res = clipdb.regex_search(clips(text), self.IP)
        self.assertEqual(res.hits, [])
        text = "x" * 19990 + " 1.2.3.4"
        res = clipdb.regex_search(clips(text), self.IP)
        self.assertEqual(len(res.hits), 1)

    def test_redos_times_out(self):
        pat = re.compile(r"(a+)+b")
        start = time.monotonic()
        res = clipdb.regex_search(clips("a" * 30), pat, budget=0.3)
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertTrue(res.timed_out)

    def test_redos_keeps_partial_hits(self):
        pat = re.compile(r"(a+)+b|zz")
        res = clipdb.regex_search(clips("zz", "a" * 30), pat, budget=0.3)
        self.assertTrue(res.timed_out)
        self.assertEqual([h.match for h in res.hits], ["zz"])

    def test_handler_restored(self):
        def sentinel(signum, frame):
            pass

        prev = signal.signal(signal.SIGALRM, sentinel)
        try:
            clipdb.regex_search(clips("a" * 30), re.compile(r"(a+)+b"), budget=0.3)
            clipdb.regex_search(clips("ok"), self.IP, budget=0.3)
            self.assertIs(signal.getsignal(signal.SIGALRM), sentinel)
        finally:
            signal.signal(signal.SIGALRM, prev)

    def test_no_stray_alarm(self):
        pat = re.compile(r"(a+)+b")
        clipdb.regex_search(clips("a" * 30), pat, budget=0.3)
        clipdb.regex_search(clips("a" * 30), pat, budget=0.3)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)
        time.sleep(0.5)  # a stray alarm would kill the process here
        self.assertTrue(True)

    def test_no_stray_alarm_on_fast_search(self):
        clipdb.regex_search(clips("1.1.1.1"), self.IP, budget=0.3)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)


class TextSearchTests(unittest.TestCase):
    def test_all_words_and(self):
        cs = clips("foo bar", "foo only", "bar only")
        got = clipdb.text_search(cs, "foo bar")
        self.assertEqual([h.clip.item for h in got], ["foo bar"])

    def test_case_insensitive(self):
        got = clipdb.text_search(clips("Hello World"), "HELLO world")
        self.assertEqual(len(got), 1)

    def test_match_is_first_line_with_first_word(self):
        got = clipdb.text_search(clips("first\n  second foo line  \nthird bar"), "foo bar")
        self.assertEqual(got[0].match, "second foo line")
        self.assertEqual(got[0].extra, 0)

    def test_limit(self):
        got = clipdb.text_search(clips(*["foo"] * 10), "foo", limit=4)
        self.assertEqual(len(got), 4)

    def test_empty_query(self):
        self.assertEqual(clipdb.text_search(clips("foo"), ""), [])
        self.assertEqual(clipdb.text_search(clips("foo"), "   "), [])

    def test_no_match(self):
        self.assertEqual(clipdb.text_search(clips("foo"), "zzz"), [])


if __name__ == "__main__":
    unittest.main()

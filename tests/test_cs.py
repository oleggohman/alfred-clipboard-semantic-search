from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import cs
import regexgen
from tests.test_clipdb import make_db


class FakeGen:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, query):
        self.calls.append(query)
        return self.result


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cache = regexgen.Cache(os.path.join(self.tmp, "c", "regex_cache.json"))
        self.dbs = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        for p in self.dbs:
            os.unlink(p)

    def db(self, texts):
        rows = [(t, 1000.0 - i, "App", 0) for i, t in enumerate(texts)]
        path = make_db(rows)
        self.dbs.append(path)
        return path

    def run_cs(self, query, texts, gen):
        return cs.run(query, db_path=self.db(texts), cache=self.cache, generator=gen)

    def titles(self, out):
        return [i["title"] for i in out["items"]]

    def test_regex_path_caches_after_search(self):
        gen = FakeGen(r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+")
        out = self.run_cs("ip", ["host 10.0.0.1 up", "nothing", "also 1.2.3.4"], gen)
        self.assertEqual(sorted(self.titles(out)), ["1.2.3.4", "10.0.0.1"])
        self.assertIn("regex", out["items"][0]["subtitle"])
        self.assertEqual(self.cache.get("ip"), gen.result)

    def test_cache_hit_skips_generator(self):
        self.cache.put("ip", r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+")
        gen = FakeGen(None)
        out = self.run_cs("IP", ["a 10.0.0.1"], gen)
        self.assertEqual(gen.calls, [])
        self.assertEqual(self.titles(out), ["10.0.0.1"])

    def test_generator_none_text_mode(self):
        out = self.run_cs("hello", ["say hello", "bye"], FakeGen(None))
        self.assertEqual(len(out["items"]), 1)
        self.assertIn("text", out["items"][0]["subtitle"])

    def test_invalid_regex_text_mode_not_cached(self):
        out = self.run_cs("foo", ["foo bar"], FakeGen("(unclosed"))
        self.assertIn("text", out["items"][0]["subtitle"])
        self.assertIsNone(self.cache.get("foo"))

    def test_zero_hits_text_mode_not_cached(self):
        out = self.run_cs("foo", ["foo bar"], FakeGen("[0-9]{9}"))
        self.assertIn("text", out["items"][0]["subtitle"])
        self.assertIsNone(self.cache.get("foo"))

    def test_cached_regex_zero_hits_deleted(self):
        self.cache.put("foo", "[0-9]{9}")
        out = self.run_cs("foo", ["foo bar"], FakeGen(None))
        self.assertIn("text", out["items"][0]["subtitle"])
        self.assertIsNone(self.cache.get("foo"))

    def test_catch_all_text_mode_not_cached(self):
        texts = ["x%d widget" % i for i in range(25)]
        out = self.run_cs("widget", texts, FakeGen("x[0-9]+"))
        self.assertIn("text", out["items"][0]["subtitle"])
        self.assertIsNone(self.cache.get("widget"))

    def test_cached_catch_all_deleted(self):
        self.cache.put("widget", "x[0-9]+")
        texts = ["x%d widget" % i for i in range(25)]
        self.run_cs("widget", texts, FakeGen(None))
        self.assertIsNone(self.cache.get("widget"))

    def test_small_corpus_not_catch_all(self):
        out = self.run_cs("n", ["a1", "b2"], FakeGen("[0-9]"))
        self.assertIn("regex", out["items"][0]["subtitle"])
        self.assertEqual(self.cache.get("n"), "[0-9]")

    def _timeout(self, hits):
        res = cs.clipdb.SearchResult(hits, 5, len(hits), True)
        return mock.patch.object(cs.clipdb, "regex_search", return_value=res)

    def test_timeout_zero_hits_text_mode(self):
        self.cache.put("foo", "[0-9]{3}")
        with self._timeout([]):
            out = self.run_cs("foo", ["foo bar"], FakeGen(None))
        self.assertIn("text", out["items"][0]["subtitle"])
        self.assertIsNone(self.cache.get("foo"))

    def test_timeout_with_hits_partial_not_cached(self):
        path = self.db(["a 123"])
        clip = cs.clipdb.load_clips(path)[0]
        hit = cs.clipdb.Hit(clip, "123", 0)
        with self._timeout([hit]):
            out = cs.run("foo", db_path=path, cache=self.cache, generator=FakeGen("[0-9]{3}"))
        self.assertEqual(self.titles(out), ["123"])
        self.assertIn("regex", out["items"][0]["subtitle"])
        self.assertIsNone(self.cache.get("foo"))

    def test_timeout_with_hits_deletes_cached(self):
        self.cache.put("foo", "[0-9]{3}")
        path = self.db(["a 123"])
        clip = cs.clipdb.load_clips(path)[0]
        with self._timeout([cs.clipdb.Hit(clip, "123", 0)]):
            cs.run("foo", db_path=path, cache=self.cache, generator=FakeGen(None))
        self.assertIsNone(self.cache.get("foo"))

    def test_text_mode_no_hits_message(self):
        out = self.run_cs("zzqq", ["abc"], FakeGen(None))
        self.assertEqual(len(out["items"]), 1)
        self.assertFalse(out["items"][0]["valid"])
        self.assertIn("No clips match 'zzqq'", out["items"][0]["title"])

    def test_db_error_item(self):
        out = cs.run("ip", db_path=os.path.join(self.tmp, "missing.db"), cache=self.cache, generator=FakeGen(None))
        self.assertEqual(len(out["items"]), 1)
        self.assertFalse(out["items"][0]["valid"])

    def test_empty_query_hint(self):
        for q in ("", "   "):
            out = self.run_cs(q, ["abc"], FakeGen(None))
            self.assertEqual(len(out["items"]), 1)
            self.assertFalse(out["items"][0]["valid"])


class MainTests(unittest.TestCase):
    def call_main(self, argv):
        buf = io.StringIO()
        with mock.patch("sys.argv", argv), contextlib.redirect_stdout(buf):
            rc = cs.main()
        return rc, buf.getvalue()

    def test_unexpected_exception_prints_error_item(self):
        with mock.patch.object(cs, "run", side_effect=RuntimeError("boom")):
            rc, out = self.call_main(["cs.py", "ip"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertFalse(data["items"][0]["valid"])

    def test_missing_argument(self):
        with mock.patch.object(cs, "run", side_effect=lambda q, **k: {"items": [{"title": q}]}):
            rc, out = self.call_main(["cs.py"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["items"][0]["title"], "")

    def test_success_prints_run_result(self):
        with mock.patch.object(cs, "run", return_value={"items": []}) as run:
            rc, out = self.call_main(["cs.py", "ip"])
        self.assertEqual(json.loads(out), {"items": []})
        self.assertEqual(run.call_args[0][0], "ip")


if __name__ == "__main__":
    unittest.main()

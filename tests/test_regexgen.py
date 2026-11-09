from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import regexgen

IP_RE = r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"


class PromptTests(unittest.TestCase):
    def test_backslash_b_literal(self):
        self.assertIn("\\b", regexgen.PROMPT)

    def test_no_backspace_char(self):
        self.assertNotIn("\x08", regexgen.PROMPT)

    def test_examples_present(self):
        for ex in (
            r"request: phone number -> \+?[0-9][0-9 ()-]{7,}[0-9]",
            r"request: hex color -> #[0-9a-fA-F]{6}\b",
            r"request: git command -> \bgit (clone|commit|push|pull|checkout|status|log)\b",
            r"request: date -> [0-9]{4}-[0-9]{2}-[0-9]{2}",
        ):
            self.assertIn(ex, regexgen.PROMPT)


class ParseTests(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(regexgen.parse_fm_output(IP_RE), IP_RE)

    def test_backticks(self):
        self.assertEqual(regexgen.parse_fm_output("`%s`" % IP_RE), IP_RE)

    def test_fence(self):
        self.assertEqual(regexgen.parse_fm_output("```regex\n%s\n```" % IP_RE), IP_RE)

    def test_plain_fence(self):
        self.assertEqual(regexgen.parse_fm_output("```\n%s\n```\n" % IP_RE), IP_RE)

    def test_prefix_echo(self):
        self.assertEqual(regexgen.parse_fm_output("request: ip -> %s" % IP_RE), IP_RE)

    def test_ansi(self):
        self.assertEqual(regexgen.parse_fm_output("\x1b[1;32m%s\x1b[0m" % IP_RE), IP_RE)

    def test_leading_blank_lines(self):
        self.assertEqual(regexgen.parse_fm_output("\n\n  \n%s\n" % IP_RE), IP_RE)

    def test_slash_delimiters(self):
        self.assertEqual(regexgen.parse_fm_output("/%s/" % IP_RE), IP_RE)

    def test_empty(self):
        self.assertEqual(regexgen.parse_fm_output(""), "")
        self.assertEqual(regexgen.parse_fm_output("```\n```"), "")


class ValidateTests(unittest.TestCase):
    def test_valid_ip(self):
        pat = regexgen.validate(IP_RE)
        self.assertIsNotNone(pat)
        self.assertTrue(pat.search("host 10.0.0.1 up"))

    def test_rejected(self):
        for bad in ("(unclosed", ".*", "a?", r"\b", r"(?=\d)", r"\S+", r"\w+", ".", "", "a" * 501):
            self.assertIsNone(regexgen.validate(bad), bad)

    def test_valid_others(self):
        for ok in (r"[0-9]{4}-[0-9]{2}-[0-9]{2}", r"\bgit (clone|push)\b", r"https?://\S+"):
            self.assertIsNotNone(regexgen.validate(ok), ok)

    def test_no_ignorecase(self):
        self.assertEqual(regexgen.validate("abc").flags & 2, 0)


class GenerateTests(unittest.TestCase):
    def test_success(self):
        self.assertEqual(regexgen.generate("ip", runner=lambda q: "`%s`" % IP_RE), IP_RE)

    def test_runner_none(self):
        self.assertIsNone(regexgen.generate("ip", runner=lambda q: None))

    def test_garbage(self):
        self.assertIsNone(regexgen.generate("ip", runner=lambda q: "(((("))
        self.assertIsNone(regexgen.generate("ip", runner=lambda q: ".*"))
        self.assertIsNone(regexgen.generate("ip", runner=lambda q: ""))


class RunFmTests(unittest.TestCase):
    def _cp(self, rc=0, out="x"):
        return subprocess.CompletedProcess([], rc, stdout=out, stderr="")

    def test_success_and_args(self):
        with mock.patch.dict(os.environ, {"FOO": "bar"}, clear=False), \
                mock.patch("subprocess.run", return_value=self._cp(out="abc\n")) as run:
            os.environ.pop("CS_FM_PATH", None)
            self.assertEqual(regexgen.run_fm("ip"), "abc\n")
        args, kwargs = run.call_args
        self.assertEqual(args[0][:5], ["/usr/bin/fm", "respond", "--no-stream", "-g", "-i"])
        self.assertEqual(args[0][5], regexgen.PROMPT)
        self.assertEqual(args[0][6], "request: ip ->")
        self.assertEqual(kwargs["timeout"], 5)
        self.assertEqual(kwargs["env"]["NO_COLOR"], "1")
        self.assertEqual(kwargs["env"]["FOO"], "bar")

    def test_fm_path_override(self):
        with mock.patch.dict(os.environ, {"CS_FM_PATH": "/x/fm"}), \
                mock.patch("subprocess.run", return_value=self._cp()) as run:
            regexgen.run_fm("ip")
        self.assertEqual(run.call_args[0][0][0], "/x/fm")

    def test_failures(self):
        for effect in (
            subprocess.TimeoutExpired("fm", 5),
            FileNotFoundError(),
            PermissionError(),
        ):
            with mock.patch("subprocess.run", side_effect=effect):
                self.assertIsNone(regexgen.run_fm("ip"))
        with mock.patch("subprocess.run", return_value=self._cp(rc=1)):
            self.assertIsNone(regexgen.run_fm("ip"))


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "sub", "regex_cache.json")

    def test_put_get_delete(self):
        c = regexgen.Cache(self.path)
        self.assertIsNone(c.get("ip"))
        c.put("ip", IP_RE)
        self.assertEqual(regexgen.Cache(self.path).get("ip"), IP_RE)
        c.delete("ip")
        self.assertIsNone(regexgen.Cache(self.path).get("ip"))
        c.delete("missing")

    def test_key_normalization(self):
        c = regexgen.Cache(self.path)
        c.put("  Phone   NUMBER ", "x1")
        self.assertEqual(c.get("phone number"), "x1")
        self.assertEqual(c.get("PHONE\tnumber"), "x1")

    def test_corrupt(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as f:
            f.write("{not json")
        c = regexgen.Cache(self.path)
        self.assertIsNone(c.get("ip"))
        c.put("ip", "z")
        with open(self.path) as f:
            self.assertEqual(json.load(f), {"ip": "z"})

    def test_non_dict_json(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as f:
            f.write("[1]")
        self.assertIsNone(regexgen.Cache(self.path).get("ip"))

    def test_dir_created(self):
        regexgen.Cache(self.path).put("a", "b")
        self.assertTrue(os.path.isfile(self.path))

    def test_default_path_env(self):
        with mock.patch.dict(os.environ, {"alfred_workflow_cache": self.tmp.name}):
            c = regexgen.Cache()
        self.assertEqual(c.path, os.path.join(self.tmp.name, "regex_cache.json"))

    def test_default_path_fallback(self):
        env = {k: v for k, v in os.environ.items() if k != "alfred_workflow_cache"}
        with mock.patch.dict(os.environ, env, clear=True):
            c = regexgen.Cache()
        self.assertEqual(
            c.path,
            os.path.expanduser("~/Library/Caches/clipboard-semantic-search/regex_cache.json"),
        )


if __name__ == "__main__":
    unittest.main()

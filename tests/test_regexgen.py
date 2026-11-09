from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
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

    def test_catastrophic_pattern_times_out_as_invalid(self):
        for bad in (r"([a-z ]+)*[0-9]", r"(\w+\s?)+$[0-9]"):
            start = time.time()
            self.assertIsNone(regexgen.validate(bad), bad)
            self.assertLess(time.time() - start, 2.0, bad)
            self.assertIsNone(regexgen.generate("x", runner=lambda q, b=bad: b), bad)

    def test_late_probe_timeout_does_not_escape(self):
        with mock.patch.object(regexgen, "_probe", side_effect=regexgen._ProbeTimeout()):
            self.assertIsNone(regexgen.validate("abc"))

    def test_timeout_during_disarm_does_not_escape(self):
        real = regexgen.signal.setitimer
        calls = []

        def fake(which, secs, *a):
            real(which, secs, *a)
            calls.append(secs)
            if len(calls) == 2:  # the disarm right after the probe
                raise regexgen._ProbeTimeout()

        with mock.patch.object(regexgen.signal, "setitimer", side_effect=fake):
            self.assertIsNone(regexgen.validate("abc"))
        self.assertEqual(real(regexgen.signal.ITIMER_REAL, 0)[0], 0.0)

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
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _script(self, body):
        path = os.path.join(self.tmp.name, "fm")
        with open(path, "w") as f:
            f.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, 0o755)
        return path

    def test_success_and_args(self):
        out = os.path.join(self.tmp.name, "args")
        fm = self._script('printf "%s\\n" "$@" > ' + out + '; echo "$NO_COLOR $FOO"')
        with mock.patch.dict(os.environ, {"CS_FM_PATH": fm, "FOO": "bar"}):
            self.assertEqual(regexgen.run_fm("ip"), "1 bar\n")
        with open(out) as f:
            args = f.read().split("\n")
        self.assertEqual(args[:5], ["respond", "--no-stream", "-g", "-i", regexgen.PROMPT.split("\n")[0]])
        self.assertEqual(args[-2], "request: ip ->")

    def test_default_path(self):
        with mock.patch.dict(os.environ), mock.patch("subprocess.Popen", side_effect=FileNotFoundError()) as p:
            os.environ.pop("CS_FM_PATH", None)
            self.assertIsNone(regexgen.run_fm("ip"))
        self.assertEqual(p.call_args[0][0][0], "/usr/bin/fm")

    def test_failures(self):
        with mock.patch.dict(os.environ, {"CS_FM_PATH": os.path.join(self.tmp.name, "missing")}):
            self.assertIsNone(regexgen.run_fm("ip"))
        with mock.patch.dict(os.environ, {"CS_FM_PATH": self._script("exit 1")}):
            self.assertIsNone(regexgen.run_fm("ip"))

    def test_timeout_kills_process_group(self):
        marker = os.path.join(self.tmp.name, "child_alive")
        fm = self._script("(sleep 2; touch %s) &\nsleep 30" % marker)
        with mock.patch.dict(os.environ, {"CS_FM_PATH": fm}), mock.patch.object(regexgen, "FM_TIMEOUT", 0.3):
            self.assertIsNone(regexgen.run_fm("ip"))
        time.sleep(2.5)
        self.assertFalse(os.path.exists(marker))

    def test_post_kill_communicate_is_bounded(self):
        fake = mock.Mock(pid=4242)
        fake.communicate.side_effect = [
            subprocess.TimeoutExpired("fm", 5),
            subprocess.TimeoutExpired("fm", 1),  # pipe held by a setsid grandchild
        ]
        with mock.patch("subprocess.Popen", return_value=fake), \
                mock.patch("os.killpg") as killpg:
            self.assertIsNone(regexgen.run_fm("ip"))
        killpg.assert_called_once_with(4242, regexgen.signal.SIGKILL)
        self.assertEqual(fake.communicate.call_args_list[1], mock.call(timeout=1))

    def test_sigterm_handler_restored_after_spawn_failure(self):
        prev = regexgen.signal.getsignal(regexgen.signal.SIGTERM)
        with mock.patch("subprocess.Popen", side_effect=FileNotFoundError()):
            self.assertIsNone(regexgen.run_fm("ip"))
        self.assertEqual(regexgen.signal.getsignal(regexgen.signal.SIGTERM), prev)

    def test_sigterm_during_spawn_is_handled(self):
        def popen(*a, **k):
            os.kill(os.getpid(), regexgen.signal.SIGTERM)
            raise AssertionError("handler should have raised SystemExit")
        with mock.patch("subprocess.Popen", side_effect=popen):
            with self.assertRaises(SystemExit):
                regexgen.run_fm("ip")

    def test_sigterm_kills_fm_group(self):
        pidfile = os.path.join(self.tmp.name, "pid")
        fm = self._script("echo $$ > %s\nsleep 30" % pidfile)
        code = ("import sys,os; sys.path.insert(0, %r); import regexgen; regexgen.run_fm('ip')"
                % os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workflow"))
        proc = subprocess.Popen([sys.executable, "-c", code], env={**os.environ, "CS_FM_PATH": fm})
        for _ in range(50):
            if os.path.exists(pidfile) and os.path.getsize(pidfile):
                break
            time.sleep(0.1)
        with open(pidfile) as f:
            fm_pid = int(f.read())
        proc.terminate()
        proc.wait(timeout=5)
        time.sleep(0.3)
        with self.assertRaises(ProcessLookupError):
            os.kill(fm_pid, 0)


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

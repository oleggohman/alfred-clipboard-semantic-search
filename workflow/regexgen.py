"""Turn a natural-language query into a validated Python regex via Apple's `fm` CLI."""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import tempfile
from typing import Callable, Optional

PROMPT = r"""You write grep -E regexes that find a KIND of data in clipboard text, not the literal words of the request. Output only the regex.
Examples:
request: phone number -> \+?[0-9][0-9 ()-]{7,}[0-9]
request: hex color -> #[0-9a-fA-F]{6}\b
request: git command -> \bgit (clone|commit|push|pull|checkout|status|log)\b
request: date -> [0-9]{4}-[0-9]{2}-[0-9]{2}"""

FM_TIMEOUT = 5
MAX_PATTERN_LEN = 500
VALIDATE_BUDGET = 0.2

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_PREFIX_RE = re.compile(r"^request:.*?->\s*")
_CATCH_ALL_PROBE = "hello world the quick brown fox jumps over the lazy dog"
_EMPTY_PROBE = "hello 123 a@b.c -_./:\n"


def parse_fm_output(text: str) -> str:
    text = _ANSI_RE.sub("", text or "")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("```"):
            continue
        line = line.strip("`").strip()
        line = _PREFIX_RE.sub("", line).strip().strip("`").strip()
        if len(line) >= 2 and line.startswith("/") and line.endswith("/"):
            line = line[1:-1]
        return line
    return ""


class _ProbeTimeout(Exception):
    pass


def _on_alarm(signum, frame):
    raise _ProbeTimeout()


def _probe(compiled: "re.Pattern[str]") -> bool:
    if compiled.fullmatch(""):
        return False
    # zero-width-only or optional-everything patterns (\b, lookaheads, a?)
    if any(m.end() == m.start() for m in compiled.finditer(_EMPTY_PROBE)):
        return False
    # catch-all: matches ordinary prose
    if any(m.group(0) for m in compiled.finditer(_CATCH_ALL_PROBE)):
        return False
    return True


def validate(pattern: str) -> Optional["re.Pattern[str]"]:
    if not pattern or len(pattern) > MAX_PATTERN_LEN:
        return None
    try:
        compiled = re.compile(pattern)
    except (re.error, RecursionError, OverflowError):
        return None
    # Model-written patterns can backtrack catastrophically even on the short
    # probes, so run them under a time budget; a timeout means invalid.
    prev_handler = signal.signal(signal.SIGALRM, _on_alarm)
    try:
        try:
            signal.setitimer(signal.ITIMER_REAL, VALIDATE_BUDGET)
            ok = _probe(compiled)
            # Disarm inside the try: an alarm landing here still counts as a timeout.
            signal.setitimer(signal.ITIMER_REAL, 0)
        except _ProbeTimeout:
            ok = False
    finally:
        # The timer is one-shot and has either fired or been disarmed; restore the handler.
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, prev_handler)
    return compiled if ok else None


def _kill_group(proc: "subprocess.Popen[str]") -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass


def run_fm(query: str) -> Optional[str]:
    fm_path = os.environ.get("CS_FM_PATH", "/usr/bin/fm")
    proc: "Optional[subprocess.Popen[str]]" = None

    def on_term(signum, frame):
        # Alfred kills the previous run when a new query arrives; take fm along.
        if proc is not None:
            _kill_group(proc)
        raise SystemExit(1)

    # Installed before Popen so a SIGTERM during spawn cannot orphan fm.
    prev_term = signal.signal(signal.SIGTERM, on_term)
    try:
        try:
            # Own session so the whole process group can be killed with it.
            proc = subprocess.Popen(
                [fm_path, "respond", "--no-stream", "-g", "-i", PROMPT, f"request: {query} ->"],
                env={**os.environ, "NO_COLOR": "1"},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except OSError:
            return None
        try:
            stdout, _ = proc.communicate(timeout=FM_TIMEOUT)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            try:
                # A setsid grandchild may hold the pipes open; do not wait for it.
                proc.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            return None
        except BaseException:
            _kill_group(proc)
            raise
    finally:
        signal.signal(signal.SIGTERM, prev_term)
    if proc.returncode != 0:
        return None
    return stdout


def generate(query: str, runner: Callable[[str], Optional[str]] = run_fm) -> Optional[str]:
    raw = runner(query)
    if raw is None:
        return None
    pattern = parse_fm_output(raw)
    if validate(pattern) is None:
        return None
    return pattern


def _normalize(query: str) -> str:
    return " ".join(query.lower().split())


class Cache:
    """JSON file mapping normalized query -> regex."""

    def __init__(self, path: Optional[str] = None) -> None:
        if path is None:
            base = os.environ.get("alfred_workflow_cache") or os.path.expanduser(
                "~/Library/Caches/clipboard-semantic-search"
            )
            path = os.path.join(base, "regex_cache.json")
        self.path = path

    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict) -> None:
        directory = os.path.dirname(self.path)
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".regex_cache")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def get(self, query: str) -> Optional[str]:
        value = self._load().get(_normalize(query))
        return value if isinstance(value, str) else None

    def put(self, query: str, pattern: str) -> None:
        data = self._load()
        data[_normalize(query)] = pattern
        self._save(data)

    def delete(self, query: str) -> None:
        data = self._load()
        if data.pop(_normalize(query), None) is not None:
            self._save(data)

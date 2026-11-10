"""Read Alfred's clipboard history and search it by regex or plain text."""
from __future__ import annotations

import signal
import sqlite3
from collections import namedtuple
from typing import List
from urllib.parse import quote

SCAN_CHARS = 20000
MAX_EXTRA = 99
DEFAULT_LIMIT = 100
DEFAULT_BUDGET = 2.0

Clip = namedtuple("Clip", "rowid item ts app apppath")
Hit = namedtuple("Hit", "clip match extra")
SearchResult = namedtuple("SearchResult", "hits scanned matched_total timed_out")


class ClipDBError(Exception):
    pass


class SearchTimeout(Exception):
    pass


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{quote(db_path)}?mode=ro", uri=True, timeout=2)
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    return conn


def load_clips(db_path: str) -> List[Clip]:
    try:
        conn = _connect(db_path)
        try:
            rows = conn.execute(
                "SELECT rowid, item, ts, app, apppath FROM clipboard "
                "WHERE dataType=0 AND item IS NOT NULL ORDER BY ts DESC"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise ClipDBError(f"Cannot read clipboard database: {exc}") from exc
    return [Clip(r[0], r[1], r[2], r[3] or "", r[4] or "") for r in rows]


def _on_alarm(signum, frame):
    raise SearchTimeout()


def regex_search(clips, pattern, limit: int = DEFAULT_LIMIT, budget: float = DEFAULT_BUDGET) -> SearchResult:
    hits: List[Hit] = []
    scanned = 0
    matched_total = 0
    timed_out = False
    prev_handler = signal.signal(signal.SIGALRM, _on_alarm)
    try:
        signal.setitimer(signal.ITIMER_REAL, budget)
        try:
            for clip in clips:
                scanned += 1
                first = None
                extra = 0
                for m in pattern.finditer(clip.item[:SCAN_CHARS]):
                    text = m.group(0)
                    if not text:
                        continue
                    if first is None:
                        first = text
                    else:
                        extra += 1
                        if extra >= MAX_EXTRA:
                            break
                if first is None:
                    continue
                matched_total += 1
                if len(hits) < limit:
                    hits.append(Hit(clip, first, extra))
        except SearchTimeout:
            timed_out = True
    finally:
        # Order matters: disarm the timer first, then restore the handler;
        # the reverse lets a late alarm hit the default handler and kill us.
        try:
            signal.setitimer(signal.ITIMER_REAL, 0)
        except SearchTimeout:  # alarm fired in the instant before disarming
            signal.setitimer(signal.ITIMER_REAL, 0)
            timed_out = True
        signal.signal(signal.SIGALRM, prev_handler)
    return SearchResult(hits, scanned, matched_total, timed_out)


def text_search(clips, query: str, limit: int = DEFAULT_LIMIT) -> List[Hit]:
    words = query.lower().split()
    if not words:
        return []
    hits: List[Hit] = []
    for clip in clips:
        low = clip.item.lower()
        if not all(w in low for w in words):
            continue
        match = ""
        for line in clip.item.splitlines():
            if words[0] in line.lower():
                match = line.strip()
                break
        hits.append(Hit(clip, match, 0))
        if len(hits) >= limit:
            break
    return hits

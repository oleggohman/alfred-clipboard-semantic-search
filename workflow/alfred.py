"""Format search results as Alfred Script Filter JSON."""
from __future__ import annotations

import re
import time
from typing import List, Optional

COCOA_EPOCH = 978307200
TITLE_MAX = 120
PREVIEW_MAX = 80
MARKERS = {"regex": "🧠 regex", "text": "🔤 text"}


def format_age(ts, now: Optional[float] = None) -> str:
    """Cocoa-epoch seconds -> 'just now' / '5m ago' / '2h ago' / '3d ago' / 'YYYY-MM-DD'; '' if invalid."""
    try:
        unix = float(ts) + COCOA_EPOCH
        current = time.time() if now is None else now
        delta = current - unix
        if delta < 60:
            return "just now"
        if delta < 3600:
            return f"{int(delta // 60)}m ago"
        if delta < 86400:
            return f"{int(delta // 3600)}h ago"
        if delta < 7 * 86400:
            return f"{int(delta // 86400)}d ago"
        return time.strftime("%Y-%m-%d", time.localtime(unix))
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _oneline(text: str, limit: int) -> str:
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _item(hit, mode: str, now: Optional[float] = None) -> dict:
    clip = hit.clip
    parts = [MARKERS.get(mode, mode)]
    if clip.app:
        parts.append(clip.app)
    date = format_age(clip.ts, now)
    if date:
        parts.append(date)
    if hit.extra > 0:
        parts.append(f"+{hit.extra} more")
    parts.append(_oneline(clip.item, PREVIEW_MAX))
    return {
        "uid": str(clip.rowid),
        "title": _oneline(hit.match, TITLE_MAX) or _oneline(clip.item, TITLE_MAX),
        "subtitle": " · ".join(parts),
        "arg": clip.item,
        "valid": True,
        "text": {"copy": clip.item, "largetype": clip.item},
        "mods": {
            "cmd": {"arg": hit.match or clip.item, "subtitle": "Paste matched part only"},
            "alt": {"arg": clip.item, "subtitle": "Copy full clip (no paste)"},
        },
    }


def to_items(hits: List, mode: str, now: Optional[float] = None) -> dict:
    return {"skipknowledge": True, "items": [_item(h, mode, now) for h in hits]}


def message_item(title: str, subtitle: str = "") -> dict:
    return {"title": title, "subtitle": subtitle, "valid": False}

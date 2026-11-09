"""Format search results as Alfred Script Filter JSON."""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import List, Optional

COCOA_EPOCH = 978307200
TITLE_MAX = 120
PREVIEW_MAX = 80
MARKERS = {"regex": "🧠 regex", "text": "🔤 text"}


def format_date(ts: float, tz: Optional[timezone] = None) -> str:
    """Cocoa-epoch seconds -> 'YYYY-MM-DD HH:MM' in local time (or tz)."""
    unix = float(ts) + COCOA_EPOCH
    if tz is None:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(unix))
    return datetime.fromtimestamp(unix, tz).strftime("%Y-%m-%d %H:%M")


def _safe_date(ts) -> str:
    try:
        return format_date(ts)
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _oneline(text: str, limit: int) -> str:
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _item(hit, mode: str) -> dict:
    clip = hit.clip
    parts = [MARKERS.get(mode, mode)]
    if clip.app:
        parts.append(clip.app)
    date = _safe_date(clip.ts)
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


def to_items(hits: List, mode: str) -> dict:
    return {"skipknowledge": True, "items": [_item(h, mode) for h in hits]}


def message_item(title: str, subtitle: str = "") -> dict:
    return {"title": title, "subtitle": subtitle, "valid": False}

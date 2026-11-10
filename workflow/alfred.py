"""Format search results as Alfred Script Filter JSON."""
from __future__ import annotations

import math
import os
import re
import time
from typing import List, Optional

COCOA_EPOCH = 978307200
TITLE_MAX = 120
PREVIEW_MAX = 80
MARKERS = {"text": "🔤 text"}


def format_age(ts, now: Optional[float] = None) -> str:
    """Cocoa-epoch seconds -> 'just now' / '5m ago' / '2h ago' / '3d ago' / 'YYYY-MM-DD'; '' if invalid."""
    try:
        unix = float(ts) + COCOA_EPOCH
        if not math.isfinite(unix):
            return ""
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
    title = _oneline(hit.match, TITLE_MAX) or _oneline(clip.item, TITLE_MAX)
    parts = []
    if mode in MARKERS:
        parts.append(MARKERS[mode])
    age = format_age(clip.ts, now)
    if age:
        parts.append(age)
    if hit.extra > 0:
        parts.append(f"+{hit.extra} more")
    preview = _oneline(clip.item, PREVIEW_MAX)
    # titles and previews have different caps, so compare by prefix, not equality
    if preview and not title.startswith(preview):
        parts.append(preview)
    item = {
        "uid": str(clip.rowid),
        "title": title,
        "subtitle": " · ".join(parts),
        # text fallback matches are a guessed line, so Enter copies the whole clip there
        "arg": clip.item if mode == "text" else (hit.match.strip() or clip.item),
        "valid": True,
        "text": {"copy": clip.item, "largetype": clip.item},
        "mods": {"cmd": {"arg": clip.item, "subtitle": "Copy whole clip"}},
    }
    if isinstance(clip.apppath, str) and clip.apppath and os.path.exists(clip.apppath):
        item["icon"] = {"type": "fileicon", "path": clip.apppath}
    return item


def to_items(hits: List, mode: str, now: Optional[float] = None) -> dict:
    return {"skipknowledge": True, "items": [_item(h, mode, now) for h in hits]}


def message_item(title: str, subtitle: str = "") -> dict:
    return {"title": title, "subtitle": subtitle, "valid": False}

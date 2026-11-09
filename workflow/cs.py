"""Alfred Script Filter entry point: `cs <query>` searches clipboard history by kind of data."""
from __future__ import annotations

import json
import os
import sys
from typing import Callable, Optional

import alfred
import clipdb
import regexgen

DEFAULT_DB = "~/Library/Application Support/Alfred/Databases/clipboard.alfdb"
CATCH_ALL_MIN_SCANNED = 20
CATCH_ALL_RATIO = 0.8


def _text_mode(clips, query: str) -> dict:
    hits = clipdb.text_search(clips, query)
    if not hits:
        return {"items": [alfred.message_item(f"No clips match '{query}'")]}
    return alfred.to_items(hits, "text")


def run(
    query: str,
    *,
    db_path: str,
    cache: regexgen.Cache,
    generator: Callable[[str], Optional[str]],
) -> dict:
    query = query.strip()
    if not query:
        return {"items": [alfred.message_item("Type what kind of data to find", "e.g. ip, email, url")]}
    try:
        clips = clipdb.load_clips(db_path)
    except clipdb.ClipDBError as exc:
        return {"items": [alfred.message_item("Clipboard database error", str(exc))]}

    cached = cache.get(query)
    pattern = cached if cached is not None else generator(query)
    compiled = regexgen.validate(pattern) if pattern else None
    if compiled is None:
        if cached is not None:
            cache.delete(query)
        return _text_mode(clips, query)

    result = clipdb.regex_search(clips, compiled)
    catch_all = (
        result.scanned >= CATCH_ALL_MIN_SCANNED
        and result.matched_total / result.scanned > CATCH_ALL_RATIO
    )
    if catch_all or not result.hits:
        if cached is not None:
            cache.delete(query)
        return _text_mode(clips, query)
    if result.timed_out:
        if cached is not None:
            cache.delete(query)
    elif cached is None:
        cache.put(query, pattern)
    return alfred.to_items(result.hits, "regex")


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        out = run(
            query,
            db_path=os.path.expanduser(DEFAULT_DB),
            cache=regexgen.Cache(),
            generator=regexgen.generate,
        )
    except Exception as exc:  # never let Alfred see a traceback
        out = {"items": [alfred.message_item("Clipboard search failed", f"{type(exc).__name__}: {exc}")]}
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

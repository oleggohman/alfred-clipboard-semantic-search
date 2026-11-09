# Clipboard Semantic Search (Alfred workflow)

## Overview
- Alfred workflow, keyword `cs <query>`, that searches Alfred's clipboard history by *kind of data* instead of literal text. `cs ip` lists every clip holding an IP address; `cs email` every clip with an email.
- Problem: Alfred's built-in clipboard search matches literal text only; "ip" never finds `10.0.0.1`.
- Uses Apple's on-device Foundation Model via `/usr/bin/fm` to turn the query into a regex. Fully local.
- Fallback: when `fm` fails, the regex is invalid/catch-all, times out, or matches nothing → plain case-insensitive text search.

## Context (from discovery)
- Fresh git repo, branch `feat/clipboard-semantic-search`, remote `origin` = github.com/oleggohman/alfred-clipboard-semantic-search (public).
- Alfred 5.8.1. Clipboard DB: `~/Library/Application Support/Alfred/Databases/clipboard.alfdb` (SQLite).
  - Schema: `clipboard(item, ts decimal, app, apppath, dataType integer, dataHash)`.
  - `dataType=0` text (1334 rows), `1` = non-text (skip). `ts` = seconds since 2001-01-01 UTC (Cocoa epoch; add 978307200 for Unix).
- `fm` CLI at `/usr/bin/fm` (license accepted). `fm respond --no-stream -g -i <instructions> <prompt>`. Colored output; set `NO_COLOR=1`.
- Alfred runs scripts with PATH `/usr/bin:/bin:/usr/sbin:/sbin` → `/usr/bin/python3` = **Python 3.9.6**. Code must be 3.9-compatible, stdlib only.
- Spike results (2026-11-09):
  - `fm` context ≈ 8K tokens; full clipboard ≈ 57K tokens → whole-clipboard-in-context rejected.
  - In-context matching recall 2/9 → rejected.
  - Few-shot query→regex (case-sensitive matching): ip 51/51, email 26/26, url 133/135, ~0.5–1.5s per call. Fails on rare kinds (mac address, jwt) → needs fallback.
  - Model emits `(?:...)` → target engine is Python `re`, not `grep -E`.
  - Model output sometimes wrapped in backticks or prefixed with `request: <q> ->` → strip.
  - `fm` fails with ModelManagerError 1008 inside Claude's sandbox; run real-`fm` checks with sandbox disabled. Not an issue under Alfred.

## Development Approach
- **testing approach**: TDD (tests first)
- complete each task fully before moving to the next; small, focused changes
- **CRITICAL: every task MUST include new/updated tests**, success and error scenarios
- **CRITICAL: all tests must pass before starting next task** - no exceptions
- **CRITICAL: update this plan file when scope changes during implementation**
- **Python 3.9 rules**: every module starts with `from __future__ import annotations` (PEP 604 `X | None` otherwise raises at import on 3.9); no `match`, no 3.10+ stdlib APIs. `py_compile` does NOT catch these — the test suite under `/usr/bin/python3` does.
- `workflow/` is a flat directory, not a package; modules import siblings as top-level (`import regexgen`) because Alfred runs `cs.py` from the workflow dir. `tests/__init__.py` inserts `<repo>/workflow` into `sys.path`.
- Test runner: `/usr/bin/python3 -m unittest discover -s tests -t . -v` (same interpreter Alfred uses)
- Lint: `ruff check workflow tests` if ruff is installed, plus `/usr/bin/python3 -m py_compile workflow/*.py`
- Unit tests never call the real `fm` or the real Alfred DB: `fm` runner injected/mocked; DB tests build a temp SQLite file with the same schema. Date tests pin TZ.

## Testing Strategy
- **unit tests**: required for every task.
- **integration check** (Task 6, smoke script, not in unit suite): real `fm` + real DB, sandbox disabled.
- No UI e2e framework; Alfred UI verified manually (Post-Completion).

## Progress Tracking
- mark completed items with `[x]` immediately when done
- add newly discovered tasks with ➕ prefix; blockers with ⚠️ prefix
- keep plan in sync with actual work done

## Solution Overview
```
cs <query>  (Alfred Script Filter, bash: /usr/bin/python3 cs.py "$1")
   │
   ├─ cache hit? ──► regex
   │     └─ miss → fm respond (timeout 5s) → parse → validate
   │
   ├─ regex OK → scan clips (newest first, SIGALRM budget 2s)
   │      hits > 0 and not catch-all → items (mode=regex); cache regex (only now)
   │
   └─ else (fm error / invalid / catch-all / timeout with 0 hits / 0 hits)
          → text search (all words, case-insensitive) → items (mode=text) or "No clips match"
   DB error at any point → single error item.

Alfred:  Enter → paste full clip | ⌘Enter → paste matched part | ⌥Enter → copy full only | ⌘L → large type
```
- Design decisions:
  - Regex cached per query **only after a successful search** → useless regexes are retried next time.
  - Python `re` engine, **no `re.IGNORECASE`** (spike precision measured case-sensitive).
  - ReDoS guard: whole regex scan runs under `signal.setitimer(ITIMER_REAL, budget)`; SIGALRM handler raises `SearchTimeout` (sre checks signals mid-match — verified on 3.9.6). Partial hits kept.
  - Modifier routing without variables/Conditional: Script Filter connects directly to two Copy to Clipboard outputs via modifier-specific connections.
  - Quick Look of full text via `text.largetype` (⌘L). `quicklookurl` needs a file on disk; skipped to avoid writing clip contents to new files.
  - Clip with several hits shows the first; subtitle adds `+N more` when N > 0.

## Technical Details
- **Module layout** (`workflow/`, shipped in the `.alfredworkflow`):
  - `regexgen.py` — `PROMPT` (raw string), `parse_fm_output(text) -> str`, `validate(pattern) -> Optional[re.Pattern]`, `generate(query, runner=run_fm) -> Optional[str]`, `run_fm(query) -> Optional[str]`, `Cache` (load/get/put/delete, JSON file).
  - `clipdb.py` — `ClipDBError`, `SearchTimeout`, `Clip` namedtuple (`rowid, item, ts, app`), `load_clips(db_path)`, `regex_search(clips, pattern, limit=100, budget=2.0) -> SearchResult`, `text_search(clips, query, limit=100) -> list[Hit]`.
    - `Hit` namedtuple: `clip, match, extra` (extra = additional match count).
    - `SearchResult` namedtuple: `hits, scanned, matched_total, timed_out`.
  - `alfred.py` — `format_date(ts, tz=None)`, `to_items(hits, mode) -> dict`, `message_item(title, subtitle) -> dict`.
  - `cs.py` — `run(query, *, db_path, cache, generator) -> dict`; `main()` reads `sys.argv[1]`, prints JSON, never raises (top-level `except Exception` → error item).
- **fm path**: `os.environ.get("CS_FM_PATH", "/usr/bin/fm")` (override for tests/smoke).
- **fm call**: `subprocess.run([fm_path, "respond", "--no-stream", "-g", "-i", PROMPT, f"request: {query} ->"], env={**os.environ, "NO_COLOR": "1"}, capture_output=True, text=True, timeout=5)`. Non-zero exit, `TimeoutExpired`, `FileNotFoundError`, `OSError` → `None`.
- **Prompt** (raw string `r"""..."""`, verbatim from spike):
  ```
  You write grep -E regexes that find a KIND of data in clipboard text, not the literal words of the request. Output only the regex.
  Examples:
  request: phone number -> \+?[0-9][0-9 ()-]{7,}[0-9]
  request: hex color -> #[0-9a-fA-F]{6}\b
  request: git command -> \bgit (clone|commit|push|pull|checkout|status|log)\b
  request: date -> [0-9]{4}-[0-9]{2}-[0-9]{2}
  ```
- **parse_fm_output**: strip ANSI escapes; first non-empty line after removing ```` ``` ```` / ```` ```regex ```` fence lines; strip whitespace and single backticks; strip leading `request: <anything> ->`; strip `/.../` delimiters.
- **validate** → compiled pattern or `None` when any of:
  - `re.compile` fails; len > 500;
  - pattern matches `""` via `fullmatch`;
  - catch-all: pattern finds a non-empty match in the prose probe `"hello world the quick brown fox jumps over the lazy dog"`.
- **Cache**: `$alfred_workflow_cache/regex_cache.json` (fallback `~/Library/Caches/clipboard-semantic-search/`); key = query lowercased + whitespace-collapsed. `cs.run` calls `put` only after a regex search returns hits and is not catch-all; never `put` when the search `timed_out` (even with partial hits); calls `delete` when a cached regex times out / has 0 hits / is catch-all. Corrupt file → empty. Atomic write (temp file + `os.replace`).
- **DB access**: `sqlite3.connect(f"file:{quote(path)}?mode=ro", uri=True, timeout=2)`; `conn.text_factory = lambda b: b.decode("utf-8", "replace")`; `SELECT rowid, item, ts, app FROM clipboard WHERE dataType=0 AND item IS NOT NULL ORDER BY ts DESC`. `app` NULL → `""`. Missing/locked/corrupt DB → `ClipDBError`.
- **Regex search**:
  - per clip, scan first 20,000 chars; `finditer`, take first match with non-empty `group(0)`; zero-length-only → no hit; `extra` = count of further non-empty matches (capped at 99).
  - whole scan wrapped in SIGALRM timer (`budget` seconds); `SearchTimeout` caught around the whole loop → return partial hits with `timed_out=True`; `finally` order: FIRST `signal.setitimer(signal.ITIMER_REAL, 0)`, THEN restore previous handler (reverse order lets a late alarm kill the process).
  - `matched_total` counts all matching clips (beyond `limit`) for the catch-all check.
- **Catch-all check** (in `cs.run`): `scanned >= 20 and matched_total / scanned > 0.8` → treat as failed regex → text search.
- **Text search**: split query on whitespace; clip matches when every word in `item.lower()`; `match` = first line containing the first query word (trimmed), so ⌘Enter pastes that line. Empty query → `[]`.
- Limit 100 results.
- **Alfred item JSON**:
  ```json
  {"uid": "<rowid>", "title": "<match, single line, ≤120 chars>",
   "subtitle": "🧠 regex · Slack · 2026-11-08 14:02 · +2 more · <preview ≤80 chars>",
   "arg": "<full clip>", "valid": true,
   "text": {"copy": "<full clip>", "largetype": "<full clip>"},
   "mods": {"cmd": {"arg": "<match>", "subtitle": "Paste matched part only"},
            "alt": {"arg": "<full clip>", "subtitle": "Copy full clip (no paste)"}}}
  ```
  Top-level `{"skipknowledge": true, "items": [...]}`. Text-mode marker `🔤 text`. Date local time `YYYY-MM-DD HH:MM`. Preview: whitespace collapsed. No results → one `valid:false` item "No clips match '<q>'". DB error → one `valid:false` item with message. Empty query (defensive; Script Filter requires an argument) → hint item.
- **info.plist** (Alfred 5, bundle id `com.oleggohman.clipboard-semantic-search`, name "Clipboard Semantic Search"):
  - Script Filter `alfred.workflow.input.scriptfilter`: `keyword`=`cs`, `type`=0 (bash), `script`=`/usr/bin/python3 cs.py "$1"`, `scriptargtype`=1, `argumenttype`=0, `withspace`=true, `queuemode`=1, `queuedelaymode`=0, `queuedelayimmediatelyinitially`=false, `queuedelaycustom`=3, `alfredfiltersresults`=false, `escaping`=102, `title`="Clipboard Semantic Search", `runningsubtext`="Asking on-device model…".
  - Output A `alfred.workflow.output.clipboard`: `clipboardtext`=`{query}`, `autopaste`=true.
  - Output B `alfred.workflow.output.clipboard`: `clipboardtext`=`{query}`, `autopaste`=false.
  - `connections[scriptfilter_uid]`: `{destinationuid: A, modifiers: 0}`, `{destinationuid: A, modifiers: 1048576}` (cmd), `{destinationuid: B, modifiers: 524288}` (alt).
  - `uidata` positions for the 3 objects; `readme` short usage text.
- **Packaging**: `build.sh [outdir]` (default `dist/`) → `<outdir>/ClipboardSemanticSearch.alfredworkflow` = zip of `workflow/` contents, excluding `__pycache__`, `*.pyc`, `.DS_Store`. `plutil -lint workflow/info.plist` must pass.

## What Goes Where
- **Implementation Steps**: code, tests, packaging, docs in this repo.
- **Post-Completion**: installing into Alfred and hands-on UI checks (user).

## Implementation Steps

### Task 1: Test scaffolding + query → regex generation with cache

**Files:**
- Create: `tests/__init__.py`
- Create: `workflow/regexgen.py`
- Create: `tests/test_regexgen.py`

- [x] create `tests/__init__.py` inserting `<repo>/workflow` into `sys.path`
- [x] write tests for `PROMPT`: `"\\b" in PROMPT`, `"\x08" not in PROMPT`, contains all 4 examples
- [x] write tests for `parse_fm_output`: plain regex, backtick-wrapped, ```` ```regex ```` fence, `request: ip -> ` prefix echo, ANSI codes, leading blank lines, `/pattern/` delimiters
- [x] write tests for `validate`: valid IP regex OK; invalid syntax, `.*`, `a?`, `\b`, `(?=\d)`, `\S+`, `\w+`, `.`, >500 chars → None
- [x] write tests for `generate`/`run_fm` with fake runner and patched `subprocess.run`: success; non-zero exit, `TimeoutExpired`, `FileNotFoundError`, garbage output → None; env passed inherits `os.environ` plus `NO_COLOR=1`; timeout=5; `CS_FM_PATH` override used, default `/usr/bin/fm`
- [x] write tests for `Cache`: put/get/delete, key normalization (case, whitespace), corrupt JSON → empty, missing dir created, env var vs fallback path
- [x] implement `workflow/regexgen.py` until tests pass
- [x] run tests - must pass before task 2

### Task 2: Clipboard DB read + regex/text search

**Files:**
- Create: `workflow/clipdb.py`
- Create: `tests/test_clipdb.py`

- [x] write `load_clips` tests (temp SQLite, Alfred schema): only `dataType=0`, newest first, NULL item skipped, NULL app → `""`, invalid-UTF-8 row (`CAST(x'fffe41' AS TEXT)`) loads with replacement chars, read-only (write fails), missing DB → `ClipDBError`
- [x] write `regex_search` tests: hits + matched text, `extra` count, zero-length-only matches → no hit, 0 hits, limit respected while `matched_total` counts all, 20K-char cap, ReDoS `(a+)+b` on `"a"*30` with budget 0.3 returns `timed_out=True` in <1s, SIGALRM handler restored afterwards, two back-to-back calls with budget 0.3 leave no stray alarm (sleep 0.5 after, process alive)
- [x] write `text_search` tests: all-words AND, case-insensitive, `match` = first line containing first word, limit, empty query → `[]`
- [x] implement `workflow/clipdb.py` until tests pass
- [x] run tests - must pass before task 3

### Task 3: Alfred JSON formatting

**Files:**
- Create: `workflow/alfred.py`
- Create: `tests/test_alfred.py`

- [x] write tests (TZ pinned to UTC via `os.environ["TZ"]` + `time.tzset()` in setUp/tearDown): `format_date(0)` → `2001-01-01 00:00`, fractional ts, real-range ts
- [x] write `to_items` tests: schema fields, title single-line + truncated to 120, subtitle has marker/app/date/`+N more` (only when N>0)/preview ≤80, mods cmd/alt args, `skipknowledge` true, both modes' markers
- [x] write `message_item` tests: `valid:false`
- [x] implement `workflow/alfred.py` until tests pass
- [x] run tests - must pass before task 4

### Task 4: Entry point + fallback chain

**Files:**
- Create: `workflow/cs.py`
- Create: `tests/test_cs.py`

- [x] write `cs.run` tests with fake generator, temp DB, temp cache:
  - regex path: cache miss → generate → hits → cache put after search
  - cache hit skips generator
  - generator returns None → text mode
  - invalid regex → text mode, not cached
  - 0 regex hits → text mode, not cached; cached regex with 0 hits → deleted
  - catch-all (>80% of ≥20 clips) → text mode, not cached
  - timeout with 0 hits → text mode; timeout with hits → regex mode with partial hits, NOT cached (and deleted if it was cached)
  - text mode 0 hits → "No clips match" item
  - DB error → error item
  - empty query → hint item (defensive)
- [x] write `main()` test: unexpected exception inside `run` → prints valid JSON error item, exit code 0
- [x] implement `workflow/cs.py` until tests pass
- [x] run tests - must pass before task 5

### Task 5: Alfred workflow definition + packaging

**Files:**
- Create: `workflow/info.plist`
- Create: `build.sh`
- Create: `tests/test_package.py`

- [x] write tests: `plutil -lint workflow/info.plist` passes; `plistlib` checks keyword `cs`, script `/usr/bin/python3 cs.py "$1"`, Script Filter keys from Technical Details, two clipboard outputs (autopaste true/false, `clipboardtext` `{query}`), three connections with modifiers 0 / 1048576 → autopaste, 524288 → no autopaste, bundle id
- [x] write test: `build.sh <tmpdir>` produces `ClipboardSemanticSearch.alfredworkflow` containing `info.plist`, `cs.py`, `regexgen.py`, `clipdb.py`, `alfred.py`; no `__pycache__`, `.pyc`, `.DS_Store`, `tests/`
- [x] create `workflow/info.plist` and `build.sh` (executable)
- [x] run tests - must pass before task 6

### Task 6: Verify acceptance criteria
- [x] create `scripts/smoke.sh`: runs `cd workflow && /usr/bin/python3 cs.py "<q>"` against the real DB with a temp `alfred_workflow_cache`, prints mode + hit count + elapsed (never prints clip contents) (done: scripts/smoke.sh prints only mode, hit count, elapsed, cached regex)
- [x] run smoke (sandbox disabled, real `fm`): `ip` → regex, ~51 hits; `email` → regex; `url` → regex; `zzqqxx nonsense` → "No clips match"; second `ip` run hits cache (<300ms) (done: ip -> regex, 51 hits, 2.08s cold fm; email -> regex, 26 hits, 1.06s; url -> regex, 100 hits (result cap), 0.64s; zzqqxx nonsense -> No clips match, 0.76s; second ip cached 0.08s. regexes: ip `\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b`, email `\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b`, url `\bhttps?://[^\s]+`)
- [x] simulate `fm` missing: `CS_FM_PATH=/nonexistent` smoke run → text mode still returns results (done: ip with CS_FM_PATH=/nonexistent -> text mode, 100 hits, 0.09s)
- [x] run full test suite: `/usr/bin/python3 -m unittest discover -s tests -t . -v` (done: 98 tests OK)
- [x] run lint: `ruff check workflow tests` (if installed) and `py_compile` (done: py_compile + plutil -lint OK; ruff not installed, skipped)
- [x] run `./build.sh` → `dist/ClipboardSemanticSearch.alfredworkflow` (done: dist/ClipboardSemanticSearch.alfredworkflow, 6.5K)

### Task 7: [Final] Update documentation
- [x] create `README.md`: what it does, install (double-click `.alfredworkflow`), requirements (macOS with Apple Intelligence, `sudo fm license` once, Alfred Powerpack, Accessibility permission for autopaste), usage + modifier keys, fallback behavior, cache reset (delete `regex_cache.json`), note that pasting re-adds the clip to history, build/test commands
- [x] create `CLAUDE.md`: Python 3.9 stdlib-only + `from __future__ import annotations`, flat `workflow/` imports, test/lint/build commands, `fm` sandbox note, never commit clipboard contents
- [x] move this plan to `docs/plans/completed/` (deferred to orchestrator)

## Post-Completion
*Items requiring manual intervention - informational only*

**Manual verification:**
- Install `dist/ClipboardSemanticSearch.alfredworkflow` (double-click) into Alfred 5.
- `cs ip` → IP clips, titles show the IP; Enter pastes full clip; ⌘Enter pastes just the IP; ⌥Enter copies only; ⌘L shows full text.
- `cs some literal words` with no regex hits → text-mode results.
- Typing quickly doesn't stack `fm` calls (terminate-previous queue mode).

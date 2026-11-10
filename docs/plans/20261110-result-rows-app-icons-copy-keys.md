# Result rows with app icons and copy-only keys

## Overview
- Redesign `cs` result rows (design A from brainstorming): real source-app icon per result, short subtitle with relative time, no redundant markers.
- Change keys to copy-only: Enter copies the matched value, ⌘Enter copies the whole clip, ⌥Enter removed. Nothing pastes anymore.
- Solves: every row shows the same generic icon, the subtitle repeats `🧠 regex` and the app name on every row, the preview often duplicates the title, and the user wants the found value (not the whole clip) on Enter without autopaste.
- Integrates with existing `clipdb` (reads one more column), `alfred` (item formatting) and `info.plist` (clipboard outputs/connections).

## Context (from discovery)
- `workflow/clipdb.py`: `Clip = namedtuple("Clip", "rowid item ts app")`; `load_clips` selects `rowid, item, ts, app`. Alfred's `clipboard` table also has `apppath` (e.g. `/Applications/agterm.app`, may be empty).
- `workflow/clipdb.py` `text_search`: `Hit.match` is the first line containing the first query word (not the whole clip).
- `workflow/alfred.py`: `_item` builds title/subtitle/arg/mods; `MARKERS` adds `🧠 regex` / `🔤 text`; `format_date` gives `YYYY-MM-DD HH:MM`.
- `workflow/info.plist`: two clipboard outputs (autopaste true `96B02F36…`, autopaste false `8B0D0031…`); script filter connections: none → paste, ⌘ → paste, ⌥ → copy.
- Tests: `tests/test_alfred.py` (item schema, subtitle), `tests/test_clipdb.py` (builds `Clip(i, t, ts, "App")`), `tests/test_package.py` (plist outputs and connections).
- `README.md`: key table, Accessibility prerequisite, "Enter copies but does not paste" troubleshooting, transient note.
- Constraints (CLAUDE.md): Python 3.9 stdlib only, `from __future__ import annotations`, flat `workflow/` modules, no real `fm` or real Alfred DB in tests, never print clip contents.

## Development Approach
- **testing approach**: TDD (tests first)
- complete each task fully before moving to the next
- make small, focused changes
- **CRITICAL: every task MUST include new/updated tests** for code changes in that task
- **CRITICAL: all tests must pass before starting next task** - no exceptions
- **CRITICAL: update this plan file when scope changes during implementation**
- run tests after each change: `/usr/bin/python3 -m unittest discover -s tests -t . -v`

## Testing Strategy
- **unit tests**: required for every task; fake `Clip`/`Hit` objects and temp SQLite files only
- **e2e tests**: none in project; manual check in Alfred listed under Post-Completion

## Progress Tracking
- mark completed items with `[x]` immediately when done
- add newly discovered tasks with ➕ prefix
- document issues/blockers with ⚠️ prefix
- keep plan in sync with actual work done

## Solution Overview
- Icon: Alfred Script Filter supports `"icon": {"type": "fileicon", "path": <app path>}`, which renders the app's real icon. No icon files to bundle.
- Relative time computed from Cocoa-epoch `ts` against an injectable `now` so tests are deterministic.
- Keys handled in two places that must agree: item JSON (`arg`, `mods`) and `info.plist` connections.

## Technical Details
- `Clip = namedtuple("Clip", "rowid item ts app apppath")`; SQL adds `apppath`; `None` → `""`.
- `format_age(ts, now=None) -> str` (unix `now`, default `time.time()`), age = `now - (ts + COCOA_EPOCH)`:
  - `< 60s` (including negative / future) → `just now`
  - `< 3600s` → `{m}m ago`
  - `< 86400s` → `{h}h ago`
  - `< 7 days` → `{d}d ago`
  - otherwise → local date `YYYY-MM-DD`
  - invalid ts → `""` (same safety as `_safe_date`)
- Item:
  - `title`: `_oneline(hit.match) or _oneline(clip.item)` (unchanged)
  - `subtitle` parts joined with ` · `: `🔤 text` (text mode only), age (if non-empty), `+N more` (if extra > 0), preview (`_oneline(clip.item, PREVIEW_MAX)`, omitted when `title.startswith(preview)` — titles and previews have different caps, so plain equality misses long one-line clips)
  - signature: `to_items(hits, mode, now=None)` passes `now` to `_item`; `cs.py` callers unchanged
  - `icon`: `{"type": "fileicon", "path": clip.apppath}` only when `clip.apppath` is non-empty and `os.path.exists` is true; otherwise no `icon` key (Alfred uses workflow icon)
  - `arg`: `hit.match or clip.item` (Enter copies what the title shows)
  - `mods`: `{"cmd": {"arg": clip.item, "subtitle": "Copy whole clip"}}`; no `alt`
  - `text` (⌘C / ⌘L) unchanged: whole clip
- `info.plist`:
  - delete the autopaste clipboard output `96B02F36…` from `objects` and from `uidata`
  - keep `8B0D0031-FCE0-4ADC-AB86-C4E829376D65` (autopaste false); script filter connections: modifiers `0` and `1048576` (⌘, `modifiersubtext` "Copy whole clip") → that output; remove `524288` (⌥)
  - rewrite the plist `readme` string: Enter copies matched value, ⌘Enter copies whole clip, ⌘L Large Type; no "paste"
  - remaining output keeps `transient: true`, `ignoredynamicplaceholders: true`, `clipboardtext: {query}`
- `MARKERS` reduced to text mode only.

## What Goes Where
- **Implementation Steps**: code, tests, plist, README in this repo
- **Post-Completion**: manual check in Alfred

## Implementation Steps

### Task 1: Read source app path from clipboard DB

**Files:**
- Modify: `workflow/clipdb.py`
- Modify: `tests/test_clipdb.py`
- Modify: `tests/test_alfred.py`

- [x] extend `tests/test_clipdb.py::make_db` to accept an optional 5th tuple element `apppath` (default `""`, `None` allowed) so existing 4-tuple callers (incl. `test_cs.py`) keep working
- [x] write failing test: `load_clips` on a temp SQLite DB returns `apppath` for each clip, and `""` when the column is NULL
- [x] add `apppath` to `Clip` and to the `SELECT` in `load_clips` (`workflow/clipdb.py:46`)
- [x] update `Clip(...)` call sites: `tests/test_clipdb.py` `clips()`, `tests/test_alfred.py` `make_hit` (add `apppath` kwarg, default `""`)
- [x] run tests - must pass before task 2

### Task 2: Relative age formatting

**Files:**
- Modify: `workflow/alfred.py`
- Modify: `tests/test_alfred.py`

- [x] write failing tests for `format_age` with fixed `now`: 30s → `just now`, future ts → `just now`, 5 min → `5m ago`, 2h → `2h ago`, 3d → `3d ago`, exactly 7d → date (expected value computed in the test with `time.strftime("%Y-%m-%d", time.localtime(...))` so it is timezone-safe), invalid ts → `""`
- [x] implement `format_age(ts, now=None)`
- [x] remove `format_date` and `_safe_date` (replaced by `format_age`), their tests in `tests/test_alfred.py`, and the now-unused `datetime`, `timezone`, `Optional` imports (ruff F401)
- [x] run tests - must pass before task 3

### Task 3: New item layout, icon and copy keys

**Files:**
- Modify: `workflow/alfred.py`
- Modify: `tests/test_alfred.py`
- Modify: `tests/test_cs.py`
- Modify: `scripts/smoke.sh`

- [x] write failing tests: regex-mode subtitle has no marker and no app name (`3d ago · +2 more · <preview>`); text-mode subtitle starts with `🔤 text`
- [x] write failing tests: preview omitted when title starts with it (incl. single-line clip > 80 chars with empty match); kept when different
- [x] update `tests/test_cs.py` asserts that look for `"regex"` in the subtitle (lines ~54, ~99, ~120) to check regex mode via `not subtitle.startswith("🔤 text")`, and text mode via `startswith("🔤 text")`
- [x] update `scripts/smoke.sh` mode detection to `"text" if subtitle.startswith("🔤 text") else "regex"`
- [x] write failing tests: `icon` is `fileicon` with app path when path exists (temp dir), absent when `apppath` empty or path missing
- [x] write failing tests: `arg` = match (falls back to clip when match blank); `mods` has only `cmd` with `arg` = whole clip and subtitle `Copy whole clip`; `text` unchanged
- [x] implement in `_item` / `to_items` (pass `now` through for tests, default real time)
- [x] run tests - must pass before task 4

### Task 4: Copy-only workflow wiring

**Files:**
- Modify: `workflow/info.plist`
- Modify: `tests/test_package.py`

- [x] write failing tests: exactly one clipboard output, `autopaste` false, transient, verbatim; connections are exactly modifiers `{0, 1048576}`, both to that output; ⌘ `modifiersubtext` is `Copy whole clip`
- [x] update `test_objects_have_uid_type_version_config` object count 3 → 2; add `set(uidata) == set(object uids)` check
- [x] add test: plist `readme` does not contain "paste" (case-insensitive)
- [x] edit `info.plist`: drop `96B02F36…` from `objects` and `uidata`, rewire Enter and ⌘ to `8B0D0031…`, drop ⌥, rewrite `readme`
- [x] `plutil -lint workflow/info.plist`
- [x] run tests - must pass before task 5

### Task 5: Verify acceptance criteria
- [ ] verify all requirements from Overview are implemented
- [ ] run full test suite: `/usr/bin/python3 -m unittest discover -s tests -t . -v`
- [ ] lint: `ruff check workflow tests` (if installed), `/usr/bin/python3 -m py_compile workflow/*.py`, `plutil -lint workflow/info.plist`
- [ ] build: `./build.sh`
- [ ] smoke: `scripts/smoke.sh "ip"` (sandbox disabled for real `fm`); confirm output shape only, never print clip contents

### Task 6: [Final] Update documentation
- [x] README: key table (Enter copies matched value, ⌘Enter copies whole clip, ⌘L Large Type), remove ⌥Enter row
- [x] README: drop Accessibility prerequisite and "Enter copies but does not paste" troubleshooting; reword "Pasting and copying are marked transient" (copying only); change "Results are marked `regex` or `text`" (only text fallback is marked now); describe app icon and relative time in subtitle
- [x] update CLAUDE.md if new patterns discovered
- [x] move this plan to `docs/plans/completed/` (done by orchestrator)

## Post-Completion
*Items requiring manual intervention or external systems - no checkboxes, informational only*

**Manual verification:**
- Install the built workflow, run `cs ip`: rows show agterm / Safari / Alfred icons, relative times, no `🧠 regex`
- Enter puts only the IP on the clipboard and does not paste; ⌘Enter puts the whole clip on the clipboard; ⌥Enter does nothing special
- Copies do not reappear in Alfred clipboard history

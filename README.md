# Clipboard Semantic Search

Search your Alfred clipboard history by **kind of data**, not by literal text.

```
cs ip      → every clip containing an IP address, titled with the address
cs email   → every clip containing an email address
cs url     → every clip containing a URL
```

Alfred's built-in clipboard search matches text, so `ip` never finds `10.0.0.1`. This workflow asks Apple's on-device Foundation Model to turn your query into a regular expression, then runs it over your clipboard history. Everything stays on your Mac.

## Contents

- [Requirements](#requirements)
- [Install](#install)
- [Usage](#usage)
- [How it works](#how-it-works)
- [Privacy](#privacy)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Releasing](#releasing)

## Requirements

- macOS with Apple Intelligence turned on (provides `/usr/bin/fm`)
- Alfred 5 with the Powerpack, clipboard history enabled
- The `fm` license accepted once (see below)

No third-party packages. The workflow runs on the system `/usr/bin/python3` (3.9).

## Install

### 1. Install the workflow

Download [ClipboardSemanticSearch.alfredworkflow](https://github.com/oleggohman/alfred-clipboard-semantic-search/releases/latest/download/ClipboardSemanticSearch.alfredworkflow) from the [latest release](https://github.com/oleggohman/alfred-clipboard-semantic-search/releases/latest) and double-click it.

Or build from source:

```sh
git clone https://github.com/oleggohman/alfred-clipboard-semantic-search.git
cd alfred-clipboard-semantic-search
./build.sh
open dist/ClipboardSemanticSearch.alfredworkflow
```

If `cs` does not respond afterwards, open Alfred Preferences > Workflows once so Alfred reloads its list.

### 2. Accept the `fm` license (one time)

`fm` refuses to run until its terms are accepted. Acceptance is machine-wide, so it needs `sudo`:

```sh
sudo fm license
fm respond 'Say OK'    # check the model answers
```

Without this step every search falls back to plain text search (results marked `🔤 text`).

## Usage

Type `cs <kind of data>` in Alfred.

| Key | Action |
| --- | --- |
| <kbd>Enter</kbd> | Copy the matched value (the IP, the email, ...). In text fallback, copy the whole clip |
| <kbd>⌘</kbd><kbd>Enter</kbd> | Copy the whole clip |
| <kbd>⌘</kbd><kbd>L</kbd> | Show the whole clip in Large Type |

Nothing is pasted, only copied. Copies are marked transient, so they do not re-enter Alfred's clipboard history. Clip text is copied verbatim (placeholders like `{date}` are not expanded).

Each result shows:

- **Icon**: the app the clip came from (workflow icon if unknown)
- **Title**: the matched value
- **Subtitle**: relative time (`just now`, `5m ago`, `2h ago`, `3d ago`, then the date), `+N more` when the clip has more matches, and a preview. Text-fallback results add `🔤 text`.

Measured on a real history of about 1,300 text clips:

| Query | Mode | Result | Time |
| --- | --- | --- | --- |
| `cs ip` | regex | 51 clips | 2.3 s cold, 0.09 s cached |
| `cs email` | regex | 26 clips | 1.1 s |
| `cs url` | regex | 100 clips (result cap) | 0.6 s |
| `cs docker` (`fm` unavailable) | text | 26 clips | 0.09 s |

## How it works

```
query ──► fm (on-device model) ──► clean + validate regex ──► scan clips ──► Alfred results
              │ fails / bad regex / no hits                        ▲
              └──────────────► plain text search ──────────────────┘
```

1. **Generate.** The query goes to `fm` (5 s timeout), which returns a regex for that kind of data.
2. **Validate.** Backticks, code fences, echoed prompts and `/.../` delimiters are stripped. The pattern is rejected if it does not compile, is over 500 characters, matches the empty string, or matches ordinary prose.
3. **Scan.** The regex runs over text clips, newest first: the first 20,000 characters of each clip, a 2 s budget, at most 100 results.
4. **Cache.** A regex that found results within the budget is cached per query, so repeat queries skip `fm`. A cached regex that later fails validation, finds nothing, matches nearly everything, or runs out of time is dropped.
5. **Fall back.** If `fm` fails, the regex is invalid, or it matches nothing or nearly everything (over 80% of scanned clips, once at least 20 are scanned), the workflow runs a case-insensitive text search where every word of the query must appear.

**Why a regex and not the model directly?** A spike showed the clipboard does not fit in the model's context (about 57K tokens of clips vs. roughly 8K of context), and asking the model to pick matching clips had poor recall (2 of 9). Regex generation from a few examples works well for common kinds (ip, email, url) and takes about 0.5 to 1.5 s cold. Rare kinds such as MAC addresses or JWTs may fail; the text fallback covers them.

## Privacy

- Fully local. Nothing goes over the network.
- The Alfred clipboard database (`~/Library/Application Support/Alfred/Databases/clipboard.alfdb`) is opened read-only.
- Only your short query is sent to the model, never clip contents.
- No clip contents are written to disk. The cache holds only query-to-regex pairs.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Every result shows `🔤 text` | `fm` is not working. Run `sudo fm license` and check Apple Intelligence is on in System Settings. |
| `fm` says "YOU HAVE NOT AGREED TO THE FOUNDATION MODELS CLI LEGAL NOTICE & TERMS" | Run `sudo fm license`. |
| A query keeps returning a bad regex | Delete `regex_cache.json` from the cache directory (below). |
| `cs` does nothing after install | Open Alfred Preferences > Workflows once. |
| `fm` fails with ModelManagerError 1008 | Happens inside some sandboxes. Does not affect Alfred. |

Cache directory:

- In Alfred: `~/Library/Caches/com.runningwithcrayons.Alfred/Workflow Data/com.oleggohman.clipboard-semantic-search/`
- Outside Alfred: `~/Library/Caches/clipboard-semantic-search/`

`CS_FM_PATH` overrides the `fm` binary path (default `/usr/bin/fm`); tests and the smoke script use it.

## Development

Layout:

| Path | Purpose |
| --- | --- |
| `workflow/cs.py` | Entry point: query → regex or text search → Alfred JSON |
| `workflow/regexgen.py` | Calls `fm`, cleans and validates the regex, caches it |
| `workflow/clipdb.py` | Read-only scan of Alfred's clipboard DB |
| `workflow/alfred.py` | Alfred Script Filter output (titles, subtitles, modifiers) |
| `workflow/info.plist` | Alfred workflow definition |
| `scripts/` | Release, version bump, smoke test, icon generator |
| `tests/` | Unit tests (temp SQLite DB, fake `fm`) |

`workflow/` is a flat directory, not a package. Target Python 3.9 (stdlib only, no 3.10+ syntax).

Commands:

```sh
/usr/bin/python3 -m unittest discover -s tests -t . -v   # tests on the interpreter Alfred uses
ruff check workflow tests                                # lint, if ruff is installed
/usr/bin/python3 -m py_compile workflow/*.py             # syntax check
plutil -lint workflow/info.plist
./build.sh [outdir]                                      # dist/ClipboardSemanticSearch.alfredworkflow
scripts/smoke.sh "ip"                                    # real fm + real clipboard DB
swift scripts/make_icon.swift workflow/icon.png 512      # regenerate the icon (edit the script, not the PNG)
```

`scripts/smoke.sh` prints only mode, hit count, elapsed time and the cached regex, never clip contents. Unit tests never touch the real `fm` or the real clipboard DB.

## Releasing

From a clean `main` that is in sync with `origin/main`:

```sh
scripts/release.sh 0.3.0
```

The script runs tests, lint and a build check, sets `version` in `workflow/info.plist`, commits `chore(release): v0.3.0`, tags `v0.3.0` and pushes both. The tag triggers the [Release workflow](.github/workflows/release.yml) on a macOS runner: it checks the tag matches the plist version, runs the tests, builds the package and attaches `ClipboardSemanticSearch.alfredworkflow` to a GitHub release with generated notes.

To rebuild the package for an existing tag:

```sh
gh workflow run release.yml -f tag=v0.2.1
```

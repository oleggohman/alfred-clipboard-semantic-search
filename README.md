# Clipboard Semantic Search

An Alfred 5 workflow that searches your clipboard history by the kind of data, not by literal text.

Alfred's built-in clipboard search matches literal text, so typing `ip` never finds `10.0.0.1`. With this workflow, `cs ip` lists every clip that contains an IP address, and the result title shows the address itself. `cs email`, `cs url` and similar queries work the same way.

## How it works

1. Your query (`ip`) goes to Apple's on-device Foundation Model through the `fm` CLI (`/usr/bin/fm`). It returns a regular expression for that kind of data.
2. The output is cleaned (backticks, code fences, echoed prompt, `/.../` delimiters) and validated. Patterns that fail to compile, exceed 500 characters, match the empty string or match ordinary prose are rejected.
3. The regex runs over your text clips, newest first (first 20,000 characters of each clip, 2 second budget, at most 100 results). A regex that worked is cached per query, so repeated queries skip `fm`.

Fallback chain: if `fm` is missing or fails (5 second timeout), the regex is invalid, matches nearly everything, or matches nothing, the workflow falls back to a plain case-insensitive text search where every word of the query must appear in the clip. Only plain-text fallback results are marked (`🔤 text` in the subtitle); regex results have no marker.

The regex approach is deliberate. A spike showed the whole clipboard does not fit in the model's context (about 57K tokens of clips against roughly 8K of context), and asking the model to pick matching clips directly had poor recall (2 of 9). Generating a regex from a few examples worked well for common kinds (ip, email, url) and is fast (about 0.5 to 1.5 seconds on a cold query). Rare kinds such as MAC addresses or JWTs can fail, which is what the text fallback is for.

## Prerequisites

- macOS with Apple Intelligence enabled (provides `/usr/bin/fm`)
- Alfred 5 with the Powerpack
- The Foundation Models CLI license accepted (see below)

No third-party Python packages are needed. The workflow runs on the system `/usr/bin/python3` (3.9).

### Accept the `fm` license (one time)

`fm` refuses to run until its Legal Notice & Terms are accepted. Acceptance applies to every user on the Mac, so it must be done with `sudo`:

```
sudo fm license
```

Read the terms and agree when prompted. Then check that the model works:

```
fm respond 'Say OK'
```

If you skip this step, every `fm` call fails with "YOU HAVE NOT AGREED TO THE FOUNDATION MODELS CLI LEGAL NOTICE & TERMS". The workflow still works in that case, but only through the plain text-search fallback (every result is marked `🔤 text`).

## Install

Download [ClipboardSemanticSearch.alfredworkflow](https://github.com/oleggohman/alfred-clipboard-semantic-search/releases/latest/download/ClipboardSemanticSearch.alfredworkflow) from the [latest release](https://github.com/oleggohman/alfred-clipboard-semantic-search/releases/latest) and double-click it. Alfred shows its import dialog.

Or build it from source:

```
git clone https://github.com/oleggohman/alfred-clipboard-semantic-search.git
cd alfred-clipboard-semantic-search
./build.sh
open dist/ClipboardSemanticSearch.alfredworkflow
```

If `cs` does not respond after installing, open Alfred Preferences > Workflows once so Alfred reloads its workflow list.

## Usage

Type `cs <kind of data>` in Alfred, for example `cs ip`.

| Key | Action |
| --- | --- |
| Enter | Copy the matched value (the IP, the email, ...) to the clipboard; in the plain-text fallback, copy the whole clip |
| ⌘Enter | Copy the whole clip to the clipboard |
| ⌘L | Show the whole clip in Large Type |

Nothing is pasted. The workflow only puts text on the clipboard.

Each result row shows:

- Icon: the app the clip was copied from (the workflow icon if unknown).
- Title: the matched value.
- Subtitle: relative time (`just now`, `5m ago`, `2h ago`, `3d ago`, and the date after a week), `+N more` if the clip has more matches, and a preview of the clip. Only the plain-text fallback adds `🔤 text`.

Example queries, measured on a real history of about 1,300 text clips:

| Query | Mode | Result | Time |
| --- | --- | --- | --- |
| `cs ip` | regex | 51 clips | 2.3 s cold, 0.09 s cached |
| `cs email` | regex | 26 clips | 1.1 s |
| `cs url` | regex | 100 clips (result cap) | 0.6 s |
| `cs docker` (with `fm` unavailable) | text | 26 clips | 0.09 s |

A clip with several matches shows the first one, with `+N more` in the subtitle. Copying is marked transient, so it is not added to Alfred's clipboard history again. Clip text is copied verbatim (dynamic placeholders such as `{date}` are not expanded).

## Privacy

Everything is local. The Alfred clipboard database (`~/Library/Application Support/Alfred/Databases/clipboard.alfdb`) is opened read-only. The only thing passed to the model is your short query, never clip contents. Nothing is sent over the network, and no clip contents are written to disk. The cache stores only query-to-regex pairs.

## Troubleshooting

- Every search shows `🔤 text`: `fm` is not working. Run `sudo fm license` once, and check that Apple Intelligence is turned on in System Settings.
- A query keeps returning a bad regex: reset the cache by deleting `regex_cache.json` from the workflow cache directory (in Alfred, Workflows > right-click the workflow > Open in Finder is the workflow folder; the cache is under `~/Library/Caches/com.runningwithcrayons.Alfred/Workflow Data/com.oleggohman.clipboard-semantic-search/`; outside Alfred it is `~/Library/Caches/clipboard-semantic-search/`). A regex that finds nothing, matches nearly everything or times out is dropped from the cache automatically.
- `CS_FM_PATH` overrides the `fm` binary path (default `/usr/bin/fm`). It is used by tests and the smoke script.
- `fm` fails with ModelManagerError 1008 when run inside some sandboxes. That does not affect Alfred.

## Development

```
/usr/bin/python3 -m unittest discover -s tests -t . -v   # tests, same interpreter Alfred uses
ruff check workflow tests                                # if ruff is installed
/usr/bin/python3 -m py_compile workflow/*.py             # syntax check
plutil -lint workflow/info.plist
./build.sh [outdir]                                      # builds dist/ClipboardSemanticSearch.alfredworkflow
scripts/smoke.sh "ip"                                    # real fm + real clipboard DB
swift scripts/make_icon.swift workflow/icon.png 512      # regenerate the workflow icon
```

`scripts/smoke.sh` prints only the mode, hit count, elapsed time and the cached regex, never clip contents. Unit tests use a temporary SQLite file and a fake `fm`.

## Releasing

From an up-to-date, clean `main`:

```
scripts/release.sh 0.2.0
```

The script runs the tests, lint and a build check, sets `version` in `workflow/info.plist`, commits `chore(release): v0.2.0`, tags `v0.2.0` and pushes both. Pushing the tag starts the [Release workflow](.github/workflows/release.yml) on a macOS runner. It checks that the tag matches the plist version, runs the tests on the system Python, builds the package and attaches `ClipboardSemanticSearch.alfredworkflow` to a GitHub release with generated notes.

To rebuild and re-upload the package for an existing tag, run the workflow manually: `gh workflow run release.yml -f tag=v0.1.0`.

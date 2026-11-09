#!/usr/bin/env bash
# Smoke-run cs.py against the real clipboard DB. Usage: smoke.sh "<query>" [cache_dir]
# Prints ONLY mode, hit count, elapsed and the cached regex -- never clip contents or titles.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
query="${1:?usage: smoke.sh \"<query>\" [cache_dir]}"
cache="${2:-${TMPDIR:-/tmp}/cs-smoke-cache}"
mkdir -p "$cache"
export alfred_workflow_cache="$cache"

start=$(/usr/bin/python3 -c 'import time; print(time.time())')
out="$(cd "$root/workflow" && /usr/bin/python3 cs.py "$query")"
end=$(/usr/bin/python3 -c 'import time; print(time.time())')

printf '%s' "$out" | /usr/bin/python3 -c '
import json, sys
start, end, query, cache = float(sys.argv[1]), float(sys.argv[2]), sys.argv[3], sys.argv[4]
items = json.load(sys.stdin)["items"]
hits = [i for i in items if i.get("valid")]
if not hits:
    # message item: print only a fixed prefix (it can echo the query, never clip data)
    mode = "none (" + items[0]["title"].split("\x27")[0].strip() + ")"
elif "regex" in hits[0]["subtitle"].split(" · ")[0]:
    mode = "regex"
else:
    mode = "text"
try:
    with open(cache + "/regex_cache.json", encoding="utf-8") as f:
        regex = json.load(f).get(" ".join(query.lower().split()), "-")
except (OSError, ValueError):
    regex = "-"
print("query=%r mode=%s hits=%d elapsed=%.2fs regex=%s" % (query, mode, len(hits), end - start, regex))
' "$start" "$end" "$query" "$cache"

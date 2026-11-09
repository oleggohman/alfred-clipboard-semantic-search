#!/usr/bin/env bash
# Build the .alfredworkflow archive. Usage: build.sh [outdir] (default: dist/)
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
outdir="${1:-dist}"
mkdir -p "$outdir"
outdir="$(cd "$outdir" && pwd)"
out="$outdir/ClipboardSemanticSearch.alfredworkflow"
rm -f "$out"

cd "$root/workflow"
zip -r -X "$out" . -x '*__pycache__*' -x '*.pyc' -x '*.DS_Store'
echo "Built $out"

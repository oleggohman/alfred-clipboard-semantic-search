#!/usr/bin/env bash
# Cut a release: verify, bump workflow/info.plist version, commit, tag vX.Y.Z and push.
# The Release GitHub Action then builds the .alfredworkflow and attaches it to the GitHub release.
# Usage: scripts/release.sh <version>   e.g. scripts/release.sh 0.2.0
set -euo pipefail

die() { echo "release: $*" >&2; exit 1; }

version="${1:-}"
version="${version#v}"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "usage: scripts/release.sh <X.Y.Z>"
tag="v$version"

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
plist="workflow/info.plist"

[ "$(git branch --show-current)" = "main" ] || die "must be on main"
[ -z "$(git status --porcelain)" ] || die "working tree is not clean"
git fetch --quiet --tags origin
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || die "main is not in sync with origin/main"
if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then die "tag $tag already exists"; fi

current="$(plutil -extract version raw "$plist")"
if [ "$current" != "$version" ]; then
    highest="$(printf '%s\n%s\n' "$current" "$version" | sort -V | tail -1)"
    [ "$highest" = "$version" ] || die "version $version is lower than current $current"
fi

echo "== tests"
/usr/bin/python3 -m unittest discover -s tests -t .
echo "== lint"
PYTHONPYCACHEPREFIX="${TMPDIR:-/tmp}/cs-pyc" /usr/bin/python3 -m py_compile workflow/*.py
plutil -lint "$plist"
echo "== build check"
build_dir="$(mktemp -d "${TMPDIR:-/tmp}/cs-release.XXXXXX")"
trap 'rm -rf "$build_dir"' EXIT
./build.sh "$build_dir" >/dev/null

if [ "$current" != "$version" ]; then
    /usr/bin/python3 scripts/bump_version.py "$plist" "$version"
    [ "$(plutil -extract version raw "$plist")" = "$version" ] || die "version bump failed"
    plutil -lint "$plist" >/dev/null
    git commit --quiet -m "chore(release): $tag" -- "$plist"
fi

git tag -a "$tag" -m "$tag"
git push --atomic origin main "$tag"
echo "Pushed $tag. The Release workflow builds and uploads the package:"
echo "  gh run watch \$(gh run list --workflow release.yml --limit 1 --json databaseId --jq '.[0].databaseId')"

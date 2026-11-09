"""Set the top-level version string in an Alfred info.plist without reformatting the file.

plutil -replace / plistlib would rewrite and reorder every dict; this only touches the one line.
Usage: bump_version.py <info.plist> <X.Y.Z>
"""
from __future__ import annotations

import re
import sys

VERSION_RE = re.compile(r"(<key>version</key>\s*<string>)[^<]*(</string>)")
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def bump(text: str, version: str) -> str:
    if not SEMVER_RE.match(version):
        raise ValueError("version must be X.Y.Z, got %r" % version)
    if len(VERSION_RE.findall(text)) != 1:
        raise ValueError("expected exactly one string-valued version key")
    return VERSION_RE.sub(lambda m: m.group(1) + version + m.group(2), text)


def main(argv: list) -> int:
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    path, version = argv[1], argv[2]
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        new = bump(text, version)
    except ValueError as e:
        print("bump_version: %s" % e, file=sys.stderr)
        return 1
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

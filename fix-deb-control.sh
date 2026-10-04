#!/bin/bash
# Repair an already-built deb whose DEBIAN/control contains blank lines.
#
# Why: a blank line ends a control paragraph, so dpkg parses the fields that
# follow it (Homepage, Description) as a second, malformed package stanza and
# refuses to install. Older builds emitted such a line for the `bundled`
# variant because an optional-field placeholder expanded to nothing.
#
# Usage: fix-deb-control.sh <package.deb> [output.deb]
set -euo pipefail
SRC="${1:?用法: fix-deb-control.sh <package.deb> [output.deb]}"
OUT="${2:-${SRC%.deb}.fixed.deb}"
[ -f "$SRC" ] || { echo "找不到 $SRC" >&2; exit 1; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
cd "$WORK"
ar x "$SRC"
mkdir ctrl && tar -xJf control.tar.xz -C ctrl

before=$(awk 'NF==0' ctrl/control | wc -l)
# Drop blank lines; keep field order and continuation lines intact.
python3 - "$PWD/ctrl/control" <<'PY'
import sys
path = sys.argv[1]
raw = open(path, encoding='utf8').read()
kept = [line for line in raw.split('\n') if line.strip() != '']
open(path, 'w', encoding='utf8').write('\n'.join(kept).rstrip('\n') + '\n')
PY
after=$(awk 'NF==0' ctrl/control | wc -l)

(cd ctrl && tar --owner=0 --group=0 --numeric-owner -cJf ../control.tar.xz .)
ar rc "$OUT" debian-binary control.tar.xz data.tar.xz
echo "空行: $before -> $after"
echo "已生成: $OUT"

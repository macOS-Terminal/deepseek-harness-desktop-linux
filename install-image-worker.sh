#!/bin/bash
# Install the out-of-process Sharp facade into one extracted desktop tree.
#
#   install-image-worker.sh <tree> <arch>
#     tree = out-x64 | out-arm64 | absolute tree path
#     arch = x64 | arm64
#
# Layout produced (all outside app.asar, which standalone Node cannot read):
#   <tree>/resources/image-worker/{client.cjs,worker.cjs}
#   <tree>/resources/image-worker/worker-modules/node_modules/{sharp,@img/*,...}
#   <tree>/resources/app/dsh/node_modules/sharp/  <- facade package replacing native sharp
#
# The script is idempotent. build-packages.sh calls it for every build, and the
# native Sharp source is recovered from the previous backup or worker closure
# after .sharp-native-backup has been removed.
set -euo pipefail

TREE="${1:?用法: install-image-worker.sh <tree> <arch>}"
ARCH="${2:?用法: install-image-worker.sh <tree> <arch>}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
case "$TREE" in
  /*) SRC="$TREE/resources" ;;
  *)  SRC="$ROOT/$TREE/resources" ;;
esac
NM="$SRC/app/dsh/node_modules"
WORKER="$SRC/image-worker"
W="$WORKER/worker-modules/node_modules"

[ -d "$NM" ] || { echo "找不到 node_modules: $NM" >&2; exit 1; }
case "$ARCH" in
  x64|arm64) ;;
  *) echo "未知架构: $ARCH" >&2; exit 1 ;;
esac

is_facade() {
  [ -f "$1/package.json" ] && grep -q 'Out-of-process Sharp facade' "$1/package.json"
}

echo "== 安装 image-worker ($ARCH) -> $TREE"

# Find the real native package before replacing anything. On a second run the
# top-level package is already the facade, so use the previous backup or the
# native copy retained inside the worker closure.
NATIVE_SHARP=""
if [ -d "$NM/sharp" ] && ! is_facade "$NM/sharp"; then
  NATIVE_SHARP="$NM/sharp"
elif [ -d "$NM/.sharp-native-backup/sharp" ] && ! is_facade "$NM/.sharp-native-backup/sharp"; then
  NATIVE_SHARP="$NM/.sharp-native-backup/sharp"
elif [ -d "$W/sharp" ] && ! is_facade "$W/sharp"; then
  NATIVE_SHARP="$W/sharp"
else
  echo "找不到原生 sharp；不能从 facade 重建 worker。请先重跑 swap-native-linux.sh" >&2
  exit 1
fi

# ---------------------------------------------------------------- worker ----
mkdir -p "$W"
cp "$ROOT/image-worker-src/client.cjs" "$WORKER/client.cjs"
cp "$ROOT/image-worker-src/worker.cjs" "$WORKER/worker.cjs"

# --------------------------------------------------- private sharp closure ---
# Only what `sharp` needs to load libvips out of process: the JS package itself plus
# the platform binaries and its two runtime dependencies.
rm -rf "$W/@img" "$W/detect-libc" "$W/semver"
if [ "$NATIVE_SHARP" != "$W/sharp" ]; then
  rm -rf "$W/sharp"
  cp -a "$NATIVE_SHARP" "$W/sharp"
fi
mkdir -p "$W/@img"
cp -a "$NM/@img/colour" "$W/@img/colour"
cp -a "$NM/@img/sharp-linux-$ARCH" "$W/@img/sharp-linux-$ARCH"
cp -a "$NM/@img/sharp-libvips-linux-$ARCH" "$W/@img/sharp-libvips-linux-$ARCH"
for dep in detect-libc semver; do
  [ -d "$NM/$dep" ] && cp -a "$NM/$dep" "$W/$dep"
done
echo "  闭包: $(find "$WORKER/worker-modules" -type f | wc -l) 个文件, $(du -sh "$WORKER/worker-modules" | cut -f1)"

# ------------------------------------------------------- facade replacement --
# Move the native sharp aside only on the first run. Subsequent runs leave the
# existing facade in place until its atomic replacement below.
if ! is_facade "$NM/sharp"; then
  rm -rf "$NM/.sharp-native-backup"
  mkdir -p "$NM/.sharp-native-backup"
  mv "$NM/sharp" "$NM/.sharp-native-backup/sharp"
fi
SHARP_VER="$(python3 -c "import json; print(json.load(open('$W/sharp/package.json'))['version'])" 2>/dev/null || echo 0.35.5)"
FACADE="$NM/sharp"
rm -rf "$FACADE"
mkdir -p "$FACADE/dist"
cat > "$FACADE/package.json" <<JSON
{
  "name": "sharp",
  "version": "$SHARP_VER",
  "description": "Out-of-process Sharp facade: keeps libvips out of the Electron process on Linux.",
  "main": "./dist/index.cjs",
  "type": "commonjs",
  "engines": { "node": ">=20.9.0" },
  "license": "Apache-2.0"
}
JSON
cat > "$FACADE/dist/index.cjs" <<'JS'
'use strict';
/**
 * Sharp facade entry point.
 *
 * Mirrors the real package's `main` so `createRequire(...)("sharp")` resolves here.
 * The implementation lives in the resources-level image-worker directory because it
 * must spawn a standalone Node process, and standalone Node cannot read `app.asar`.
 */
const { existsSync } = require('node:fs');
const { dirname, join } = require('node:path');

/** Resources root: this file sits at <resources>/app/dsh/node_modules/sharp/dist/. */
function resourcesRoot() {
  const configured = process.env.DSH_DESKTOP_RESOURCES_DIR;
  if (configured !== undefined && configured !== '') return configured;
  return join(__dirname, '..', '..', '..', '..', '..');
}

const candidates = [
  join(resourcesRoot(), 'image-worker', 'client.cjs'),
  process.env.DSH_DESKTOP_RESOURCES_DIR
    ? join(process.env.DSH_DESKTOP_RESOURCES_DIR, 'image-worker', 'client.cjs')
    : '',
];

for (const candidate of candidates) {
  if (candidate !== '' && existsSync(candidate)) {
    module.exports = require(candidate);
    return;
  }
}

throw new Error(
  'sharp: image worker is missing. Expected <resources>/image-worker/client.cjs; ' +
  'the DeepSeek Harness Linux build ships it beside the runtime payload.',
);
JS

# --------------------------------------------------------------- self-check --
for required in \
  "$WORKER/client.cjs" "$WORKER/worker.cjs" \
  "$W/sharp/package.json" "$W/@img/sharp-linux-$ARCH/lib" \
  "$W/@img/sharp-libvips-linux-$ARCH/lib" \
  "$FACADE/package.json" "$FACADE/dist/index.cjs"; do
  [ -e "$required" ] || { echo "image-worker 自检失败，缺少: $required" >&2; exit 1; }
done
if is_facade "$W/sharp"; then
  echo "image-worker 自检失败：worker 闭包里误放了 facade，必须保留原生 sharp" >&2
  exit 1
fi
node --check "$WORKER/client.cjs"
node --check "$WORKER/worker.cjs"
node --check "$FACADE/dist/index.cjs"

echo "  facade: $FACADE"
echo "  ✓ image-worker 布局与语法自检通过"

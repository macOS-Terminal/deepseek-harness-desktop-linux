#!/bin/bash
# Install the out-of-process Sharp facade into one extracted desktop tree.
#
#   install-image-worker.sh <tree> <arch>
#     tree = out-x64 | out-arm64
#     arch = x64 | arm64
#
# Layout produced (all outside app.asar, which standalone Node cannot read):
#   <tree>/resources/image-worker/{client.cjs,worker.cjs}
#   <tree>/resources/image-worker/worker-modules/node_modules/{sharp,@img/*,...}
#   <tree>/resources/app/dsh/node_modules/sharp/  <- facade package replacing native sharp
set -euo pipefail

TREE="${1:?用法: install-image-worker.sh <tree> <arch>}"
ARCH="${2:?用法: install-image-worker.sh <tree> <arch>}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="$ROOT/$TREE/resources"
NM="$SRC/app/dsh/node_modules"
WORKER="$SRC/image-worker"

[ -d "$NM" ] || { echo "找不到 node_modules: $NM" >&2; exit 1; }

echo "== 安装 image-worker ($ARCH) -> $TREE"

# ---------------------------------------------------------------- worker ----
mkdir -p "$WORKER/worker-modules/node_modules"
cp "$ROOT/image-worker-src/client.cjs" "$WORKER/client.cjs"
cp "$ROOT/image-worker-src/worker.cjs" "$WORKER/worker.cjs"

# --------------------------------------------------- private sharp closure ---
# Only what `sharp` needs to load libvips out of process: the JS package itself plus
# the platform binaries and its two runtime dependencies.
W="$WORKER/worker-modules/node_modules"
rm -rf "$W/sharp" "$W/@img" "$W/detect-libc" "$W/semver"
mkdir -p "$W/@img"
cp -a "$NM/sharp" "$W/sharp"
cp -a "$NM/@img/colour" "$W/@img/colour"
case "$ARCH" in
  x64)
    cp -a "$NM/@img/sharp-linux-x64" "$W/@img/sharp-linux-x64"
    cp -a "$NM/@img/sharp-libvips-linux-x64" "$W/@img/sharp-libvips-linux-x64"
    ;;
  arm64)
    cp -a "$NM/@img/sharp-linux-arm64" "$W/@img/sharp-linux-arm64"
    cp -a "$NM/@img/sharp-libvips-linux-arm64" "$W/@img/sharp-libvips-linux-arm64"
    ;;
  *) echo "未知架构: $ARCH" >&2; exit 1 ;;
esac
for dep in detect-libc semver; do
  [ -d "$NM/$dep" ] && cp -a "$NM/$dep" "$W/$dep"
done
echo "  闭包: $(find "$WORKER/worker-modules" -type f | wc -l) 个文件, $(du -sh "$WORKER/worker-modules" | cut -f1)"

# ------------------------------------------------------- facade replacement --
# Move the native sharp aside (kept for diagnostics but no longer resolvable) and
# install a facade that mirrors the real package's `main` so the Host's
# createRequire(...)("sharp") resolves here.
if [ -d "$NM/sharp" ] && [ ! -d "$NM/.sharp-native-backup/sharp" ]; then
  mkdir -p "$NM/.sharp-native-backup"
  mv "$NM/sharp" "$NM/.sharp-native-backup/sharp"
fi
FACADE="$NM/sharp"
mkdir -p "$FACADE/dist"
cat > "$FACADE/package.json" <<'JSON'
{
  "name": "sharp",
  "version": "0.35.4",
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

echo "  facade: $FACADE"
echo "  完成"

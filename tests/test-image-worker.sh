#!/bin/bash
# Verify Sharp isolation twice on one tree: the second run exercises recovery
# from the worker's private native closure after the backup has been removed.
set -euo pipefail
B="$(cd "$(dirname "$0")/.." && pwd)"
TREE="${1:-out-x64}"
ARCH="${2:-x64}"
case "$TREE" in
  /*) OUT="$TREE" ;;
  *)  OUT="$B/$TREE" ;;
esac
case "$ARCH" in
  x64) HOST=x86_64 ;;
  arm64) HOST=aarch64 ;;
  *) echo "未知架构: $ARCH" >&2; exit 1 ;;
esac

grep -q '"$B/install-image-worker.sh" "$SRC" "$ARCH"' "$B/build-packages.sh" \
  || { echo 'build-packages.sh 未强制安装 image-worker' >&2; exit 1; }

"$B/install-image-worker.sh" "$OUT" "$ARCH"
rm -rf "$OUT/resources/app/dsh/node_modules/.sharp-native-backup"
"$B/install-image-worker.sh" "$OUT" "$ARCH"
rm -rf "$OUT/resources/app/dsh/node_modules/.sharp-native-backup"

if [ "$(uname -m)" != "$HOST" ]; then
  echo "  · 当前 $(uname -m) 不能执行 $ARCH Electron；仅完成布局与幂等检查"
  exit 0
fi
ELECTRON_BIN=""
if [ -x "$OUT/deepseek-harness" ]; then
  ELECTRON_BIN="$OUT/deepseek-harness"
elif [ -n "${DSH_ELECTRON_BIN:-}" ]; then
  ELECTRON_BIN="$DSH_ELECTRON_BIN"
else
  for candidate in electron45 electron44 electron43 electron42 electron41 electron40 electron39 electron; do
    if command -v "$candidate" >/dev/null 2>&1; then
      ELECTRON_BIN="$(command -v "$candidate")"
      break
    fi
  done
fi
[ -n "$ELECTRON_BIN" ] || { echo '找不到可用于验证的 Electron' >&2; exit 1; }
ELECTRON_RUN_AS_NODE=1 DSH_DESKTOP_RESOURCES_DIR="$OUT/resources" \
  "$ELECTRON_BIN" "$B/image-worker-src/verify-image-worker.cjs"

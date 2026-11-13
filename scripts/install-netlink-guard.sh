#!/bin/bash
# Build and install the netlink retry-backoff guard into one application tree.
#   install-netlink-guard.sh <out-x64|out-arm64|absolute-tree> <x64|arm64>
set -euo pipefail
B="$(cd "$(dirname "$0")/.." && pwd)"
TREE="${1:?用法: install-netlink-guard.sh <tree> <x64|arm64>}"
ARCH="${2:?用法: install-netlink-guard.sh <tree> <x64|arm64>}"
case "$TREE" in
  /*) OUT="$TREE" ;;
  *)  OUT="$B/$TREE" ;;
esac
case "$ARCH" in
  x64)
    CC_BIN="${CC_X64:-${CC:-cc}}"
    WANT='x86-64'
    ;;
  arm64)
    if [ "$(uname -m)" = aarch64 ]; then
      CC_BIN="${CC_ARM64:-${CC:-cc}}"
    else
      CC_BIN="${CC_ARM64:-aarch64-linux-gnu-gcc}"
    fi
    WANT='ARM aarch64'
    ;;
  *) echo "未知架构: $ARCH（应为 x64 或 arm64）" >&2; exit 1 ;;
esac
command -v "$CC_BIN" >/dev/null 2>&1 || {
  echo "找不到 $ARCH C 编译器: $CC_BIN（可用 CC_X64 / CC_ARM64 指定）" >&2
  exit 1
}
[ -d "$OUT/resources" ] || { echo "找不到应用 resources 目录: $OUT/resources" >&2; exit 1; }

DEST_DIR="$OUT/resources/netlink-guard"
DEST="$DEST_DIR/libdsh-netlink-guard.so"
SRC="$B/netlink-guard/netlink_guard.c"
mkdir -p "$DEST_DIR"
TMP="$DEST.tmp.$$"
trap 'rm -f "$TMP"' EXIT
"$CC_BIN" -std=c11 -O2 -fPIC -shared -pthread \
  -Wall -Wextra -Werror -Wl,--no-undefined -Wl,-z,relro,-z,now \
  "$SRC" -ldl -o "$TMP"
GOT="$(file -b "$TMP")"
case "$GOT" in
  *"$WANT"*) ;;
  *) echo "编译产物架构错误：期望 $WANT，实际 $GOT" >&2; exit 1 ;;
esac
chmod 755 "$TMP"
mv -f "$TMP" "$DEST"
trap - EXIT
printf '  ✓ netlink 退避守卫: %s (%s)\n' "$DEST" "$WANT"

#!/bin/bash
# 把已装配的应用树换成另一个 Electron 版本（保留 resources/app、resources/runtime、托盘图标）。
#
#   swap-electron.sh <tree> <electron-*.zip> <x64|arm64>
#
# 上游 dmg 自带 44.7.0；测试 / 换运行时只需替换骨架，不必重跑装配。
set -euo pipefail
B="$(cd "$(dirname "$0")/.." && pwd)"
TREE="${1:?用法: swap-electron.sh <tree> <electron.zip> <x64|arm64>}"
ZIP="${2:?缺少 electron zip}"
ARCH="${3:?缺少架构 (x64|arm64)}"
[ -d "$TREE/resources" ] || { echo "不是应用树: $TREE" >&2; exit 1; }
[ -s "$ZIP" ] || { echo "缺少 $ZIP" >&2; exit 1; }

case "$ARCH" in
  x64)   want='x86-64' ;;
  arm64) want='ARM aarch64' ;;
  *) echo "未知架构: $ARCH" >&2; exit 1 ;;
esac

W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
unzip -q "$ZIP" -d "$W/x"
old="$(cat "$TREE/version" 2>/dev/null || echo '?')"
new="$(cat "$W/x/version" 2>/dev/null || echo '?')"

got=$(file -b "$W/x/electron" | grep -oE 'ARM aarch64|x86-64' | head -1)
[ "$got" = "$want" ] || { echo "架构不符: $ZIP -> $got（应为 $want）" >&2; exit 1; }

# 只保留应用自己的东西：resources/（含 app、runtime、tray.png）
mv "$TREE/resources" "$W/resources"
find "$TREE" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
mv "$W/resources" "$TREE/resources"
cp -a "$W/x/." "$TREE/"
mv "$TREE/electron" "$TREE/deepseek-harness"
chmod 755 "$TREE/deepseek-harness"
rm -f "$TREE/resources/default_app.asar"
chmod 4755 "$TREE/chrome-sandbox" 2>/dev/null || true

printf '  · Electron %s -> %s (%s)\n' "$old" "$new" "$ARCH"

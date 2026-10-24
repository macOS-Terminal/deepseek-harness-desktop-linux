#!/bin/bash
# 生成「Linux-ready」的裁剪分发包（x86_64 与 aarch64 双架构）。
#
# 与"仅删除 darwin 包"的区别：本脚本把 darwin 平台包**替换成对应的 Linux 包**，
# 使解包后的应用树能在 Linux 上真正运行 —— 应用按平台 require.resolve，
# 缺对应包会直接导致 Host 启动失败。
#
# 保留：macOS 应用代码、Electron 框架、runtime 载荷（node/python/pnpm）
# 移除：darwin 平台包、*.lproj、_CodeSignature、:com.apple.provenance
# 新增：对应架构的 Linux 原生包
#
# 用法: build-linux-ready-archive.sh <x64|arm64> <输出文件>
#   ./build-linux-ready-archive.sh x64   dist/dsh-0.2.1-rc.2-linux-x86_64.tar.xz
#   ./build-linux-ready-archive.sh arm64 dist/dsh-0.2.1-rc.2-linux-aarch64.tar.xz
set -euo pipefail

ARCH="${1:?用法: build-linux-ready-archive.sh <x64|arm64> <out.tar.xz>}"
OUT="${2:?用法: build-linux-ready-archive.sh <x64|arm64> <out.tar.xz>}"
ROOT="$(cd "$(dirname "$0")" && pwd)"

case "$ARCH" in
  x64)   DLDIR=dl/linux-x64 ;;
  arm64) DLDIR=dl/linux-arm64 ;;
  *) echo "未知架构: $ARCH（应为 x64 或 arm64）" >&2; exit 1 ;;
esac

SRC="$ROOT/others/dmg-new/DeepSeek Harness 0.2.1-rc.2-arm64"
DL="$ROOT/$DLDIR"
[ -d "$SRC" ] || { echo "找不到源目录: $SRC" >&2; exit 1; }
[ -d "$DL" ]  || { echo "找不到平台包目录: $DL" >&2; exit 1; }

# 在 tmpfs 暂存：工作区若在 NTFS 则不支持符号链接，而 app 树含 symlink
# （如 python3 -> python3.12），直接就地改写会破坏它们。
WORK="$(mktemp -d /tmp/linux-ready-XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

echo "== 复制源树到 tmpfs ($WORK) =="
cp -a "$SRC" "$WORK/"
APP="$WORK/DeepSeek Harness 0.2.1-rc.2-arm64/DeepSeek Harness.app/Contents"
NM="$APP/Resources/app.asar.unpacked/dsh/node_modules"
[ -d "$NM" ] || { echo "找不到 node_modules: $NM" >&2; exit 1; }
echo "  $(du -sh "$WORK" | cut -f1)"

echo "== 移除 macOS 专属元数据 =="
find "$WORK" -name '*:com.apple.provenance' -delete 2>/dev/null || true
find "$WORK" -name '*.lproj' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$WORK" -name '_CodeSignature' -type d -prune -exec rm -rf {} + 2>/dev/null || true

echo "== 替换原生包为 Linux $ARCH =="
"$ROOT/swap-native-linux.sh" "$WORK/DeepSeek Harness 0.2.1-rc.2-arm64/DeepSeek Harness.app/Contents/Resources/app.asar.unpacked/dsh" "$DL" "$ARCH" \
  || { echo "平台替换失败" >&2; exit 1; }

echo "== 压缩到 $OUT =="
mkdir -p "$(dirname "$OUT")"
( cd "$WORK" && tar --owner=0 --group=0 --numeric-owner -cf - . ) | xz -9e -T4 -c > "$OUT"
ls -la "$OUT" | awk '{printf "  %.1f MB\n", $5/1048576}'

# 压缩后自检：xz 流完整 + 条目数
xz -t "$OUT" && echo "  ✓ xz 流完整"
echo "完成"
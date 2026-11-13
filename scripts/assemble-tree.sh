#!/bin/bash
# 装配一个架构的完整应用树（out-x64 / out-arm64）。
#   1) 铺 Electron 骨架
#   2) 放入已展开的 app（app-new）
#   3) 装配 runtime 载荷（node / python / pnpm）
#   4) 交叉安装 Python 站点包
#   5) 替换原生模块为 Linux 版
#
# 用法: assemble-tree.sh <x64|arm64>
set -euo pipefail
B="$(cd "$(dirname "$0")/.." && pwd)"
ARCH="${1:?用法: assemble-tree.sh <x64|arm64>}"
DMG="$B/others/dmg/DeepSeek Harness 0.2.2-rc.1-arm64/DeepSeek Harness.app/Contents/Resources"
case "$ARCH" in
  x64)   TREE=out-x64;   NODE_ARCH=x64;   PY_ARCH=x64;   PIP_PLAT="--platform manylinux_2_28_x86_64 --platform manylinux_2_27_x86_64" ;;
  arm64) TREE=out-arm64; NODE_ARCH=arm64; PY_ARCH=arm64; PIP_PLAT="--platform manylinux_2_28_aarch64 --platform manylinux_2_27_aarch64" ;;
  *) echo "未知架构: $ARCH" >&2; exit 1 ;;
esac
OUT="$B/$TREE"
say() { printf '\n== %s ==\n' "$*"; }

say "1/6 铺 Electron 骨架 -> $TREE"
rm -rf "$OUT"; mkdir -p "$OUT"
unzip -oq "$B/dl/electron-44.7.0-linux-$NODE_ARCH.zip" -d "$OUT"
mv "$OUT/electron" "$OUT/deepseek-harness"
chmod 755 "$OUT/deepseek-harness"
rm -f "$OUT/resources/default_app.asar"
echo "  electron: $("$OUT/deepseek-harness" --version 2>/dev/null || echo '（无法执行，稍后验证）')"
echo "  chrome-sandbox: $(ls -l "$OUT/chrome-sandbox" | awk '{print $1}')"

say "2/6 放入应用载荷 resources/app"
cp -a "$B/app-new/." "$OUT/resources/app/"
# dmg 出来的 xattr 影子文件无用
find "$OUT/resources/app" -name '*:com.apple.*' -delete 2>/dev/null || true
echo "  app 文件数: $(find "$OUT/resources/app" -type f | wc -l)"

say "3/6 装配 runtime 载荷"
RT="$OUT/resources/runtime"
rm -rf "$RT"; mkdir -p "$RT"
cp -a "$DMG/runtime/bin" "$DMG/runtime/cli" "$DMG/runtime/office-skills" "$DMG/runtime/versions.json" "$RT/"
mkdir -p "$RT/primary-runtime"
cp -a "$DMG/runtime/primary-runtime/runtime.json" "$RT/primary-runtime/"
DEPS="$RT/primary-runtime/dependencies"; mkdir -p "$DEPS"

# node: 用官方 Linux 发行版，保留 dmg 的 node_modules 布局
echo "  · node $("$B/dl"/node-v24.21.0-linux-$NODE_ARCH/bin/node --version 2>/dev/null || echo '?')"
rm -rf "$DEPS/node"; mkdir -p "$DEPS/node"
tar xJf "$B/dl/node-v24.21.0-linux-$NODE_ARCH.tar.xz" -C /tmp "node-v24.21.0-linux-$NODE_ARCH"
cp -a "/tmp/node-v24.21.0-linux-$NODE_ARCH/bin" "$DEPS/node/"
cp -a "/tmp/node-v24.21.0-linux-$NODE_ARCH/lib" "$DEPS/node/" 2>/dev/null || true
cp -a "/tmp/node-v24.21.0-linux-$NODE_ARCH/include" "$DEPS/node/" 2>/dev/null || true
cp -a "/tmp/node-v24.21.0-linux-$NODE_ARCH/share" "$DEPS/node/" 2>/dev/null || true
cp -a "/tmp/node-v24.21.0-linux-$NODE_ARCH/LICENSE" "$DEPS/node/" 2>/dev/null || true
mkdir -p "$DEPS/node/node_modules"
rm -rf "/tmp/node-v24.21.0-linux-$NODE_ARCH"

# pnpm: 纯 JS，直接沿用 dmg 里的 11.28.5
echo "  · pnpm 11.28.5 (沿用 dmg)"
cp -a "$DMG/runtime/primary-runtime/dependencies/pnpm" "$DEPS/pnpm"

# python: install_only_stripped 变体
echo "  · python 3.12.14"
rm -rf "$DEPS/python" /tmp/pyx-$ARCH
mkdir -p /tmp/pyx-$ARCH
tar xzf "$B/dl/python-3.12.14-$PY_ARCH.tar.gz" -C /tmp/pyx-$ARCH
cp -a /tmp/pyx-$ARCH/python "$DEPS/python"
rm -rf /tmp/pyx-$ARCH
SITE="$DEPS/python/lib/python3.12/site-packages"
mkdir -p "$SITE"

say "4/6 交叉安装 Python 站点包 ($ARCH)"
pip3 install --quiet --no-cache-dir --target "$SITE" $PIP_PLAT \
  --python-version 3.12 --implementation cp --only-binary=:all: \
  numpy==2.3.5 pandas==3.0.1 Pillow==12.3.0 lxml==6.1.3 \
  python-docx==1.2.0 python-pptx==1.0.2 openpyxl==3.1.5 XlsxWriter==3.2.9 \
  python-dateutil==2.9.0.post0 six==1.17.0 tzdata==2025.2 \
  typing_extensions==4.16.0 et_xmlfile==2.0.0
echo "  site-packages: $(ls "$SITE" | wc -l) 项, $(du -sh "$SITE" | cut -f1)"

# 修正 runtime.json 的平台字段
python3 - "$RT/primary-runtime/runtime.json" "$ARCH" <<'PY'
import json, sys
p, arch = sys.argv[1], sys.argv[2]
d = json.load(open(p))
d["platform"] = "linux"
d["arch"] = "x64" if arch == "x64" else "arm64"
json.dump(d, open(p, "w"), indent=2, ensure_ascii=False)
print("  runtime.json:", d["platform"], d["arch"])
PY

say "5/6 替换原生模块 -> Linux $ARCH"
"$B/swap-native-linux.sh" "$OUT/resources/app" "$B/dl/linux-$ARCH" "$ARCH"

say "6/6 安装 netlink 收包失败退避守卫"
"$B/scripts/install-netlink-guard.sh" "$OUT" "$ARCH"

say "完成 $TREE  大小: $(du -sh "$OUT" | cut -f1)"

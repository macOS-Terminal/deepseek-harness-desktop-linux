#!/bin/bash
# 把 Electron 官方 linux 预编译包打成 Arch 包（electron45）。
#
#   build-electron-pkg.sh <x64|arm64> [版本] [zip 路径]
#
# 产物: dist/electron45-<版本>-1-<arch>.pkg.tar.zst
# 安装布局与 Arch 官方 electron 包一致，只是目录带主版本号：
#   /usr/lib/electron45/…   /usr/bin/electron45 -> /usr/lib/electron45/electron
#
# 为什么单独成包：DSH 的 pkg.tar.zst 是「系统 Electron」构建，不带运行时；
# 上游只认 43/44/45-alpha 三套指纹，必须有确定的 45.x 运行时可用。
set -euo pipefail
B="$(cd "$(dirname "$0")/.." && pwd)"
ARCH="${1:?用法: build-electron-pkg.sh <x64|arm64> [版本] [zip]}"
VER="${2:-45.2.3}"
ZIP="${3:-$B/dl45/electron-v${VER}-linux-${ARCH}.zip}"

case "$ARCH" in
  x64)   PKGARCH=x86_64;  ZIPARCH=x64 ;;
  arm64) PKGARCH=aarch64; ZIPARCH=arm64 ;;
  *) echo "未知架构: $ARCH（应为 x64 或 arm64）" >&2; exit 1 ;;
esac
# 允许用 x64/arm64 之外的名字传 zip（例如先下载成 electron-v45.2.3-linux-x64.zip）
[ -f "$ZIP" ] || ZIP="$B/dl45/electron-v${VER}-linux-${ZIPARCH}.zip"
[ -s "$ZIP" ] || { echo "缺少 electron 压缩包: $ZIP" >&2; exit 1; }

ZSTD_OPTS="${ZSTD_OPTS:--19 -T0 --long=27}"
OUT="$B/dist-electron"
WORK="/tmp/electron-pkg-$ARCH"
rm -rf "$WORK"; mkdir -p "$WORK" "$OUT"

say() { printf '\n== %s ==\n' "$*"; }

say "解包 electron ${VER} (${ZIPARCH})"
unzip -q "$ZIP" -d "$WORK/x"
[ -x "$WORK/x/electron" ] || { echo "压缩包里没有 electron 可执行文件" >&2; exit 1; }
printf '  · %s\n' "$("$WORK/x/electron" --version 2>/dev/null || echo '（本机无法执行，稍后按目标架构核验）')"

R="$WORK/root"
mkdir -p "$R/usr/lib/electron45" "$R/usr/bin"
cp -a "$WORK/x/." "$R/usr/lib/electron45/"
# 注意：**保留** resources/default_app.asar —— 它是 `electron45 /path/to/app`
# 这种「跑别人应用」用法的入口；只有 DSH 自己的树才需要删掉（它自带 resources/app）。
[ -f "$R/usr/lib/electron45/resources/default_app.asar" ] \
  || { echo "缺少 resources/default_app.asar，electron45 将无法加载外部应用" >&2; exit 1; }
ln -sf /usr/lib/electron45/electron "$R/usr/bin/electron45"

# 权限归一：官方包解压后已是 755，这里只兜底，避免 umask 影响
find "$R/usr/lib/electron45" -type f \
  \( -name 'electron' -o -name 'chrome-sandbox' -o -name 'chrome_crashpad_handler' \
     -o -name '*.so' -o -name '*.so.*' \) -exec chmod 755 {} +
chmod 4755 "$R/usr/lib/electron45/chrome-sandbox"
chmod 755 "$R/usr/bin/electron45" 2>/dev/null || true

# 架构核验：防止把 x64 包装成 aarch64
want=$([ "$ARCH" = x64 ] && echo 'x86-64' || echo 'ARM aarch64')
for f in "$R/usr/lib/electron45/electron" "$R/usr/lib/electron45/libffmpeg.so"; do
  got=$(file -b "$f" | grep -oE 'ARM aarch64|x86-64' | head -1)
  [ "$got" = "$want" ] || { echo "架构不符: $f -> $got（应为 $want）" >&2; exit 1; }
done
printf '  · 架构核验通过: %s\n' "$want"

size=$(du -sb "$R" | cut -f1)
cat > "$R/.PKGINFO" <<EOF
pkgname = electron45
pkgbase = electron45
pkgver = ${VER}-1
pkgdesc = Electron ${VER} runtime for Linux (standalone, from the official prebuilt release)
url = https://www.electronjs.org
builddate = $(date +%s)
packager = DeepSeek Harness Linux port
size = $size
arch = $PKGARCH
license = MIT
depend = gtk3
depend = nss
depend = libxss
depend = libxtst
depend = libnotify
depend = libsecret
depend = libcups
depend = libdrm
depend = mesa
depend = libxkbcommon
depend = libxcomposite
depend = libxdamage
depend = libxfixes
depend = libxrandr
depend = libx11
depend = libxcb
depend = at-spi2-core
depend = libuuid
depend = alsa-lib
depend = glibc
optdepend = xdg-utils: 打开外部链接
provides = electron45
provides = electron
conflicts = electron45-bin
EOF
cat > "$R/.INSTALL" <<'EOF'
post_install() {
  chown root:root usr/lib/electron45/chrome-sandbox 2>/dev/null || true
  chmod 4755 usr/lib/electron45/chrome-sandbox 2>/dev/null || true
}
post_upgrade() { post_install; }
EOF

( cd "$R" && bsdtar -cf .MTREE --format=mtree --uid 0 --gid 0 --numeric-owner \
    --options='!all,use-set,type,uid,gid,mode,size,md5,time,link' .PKGINFO .INSTALL usr \
  && gzip -9 -f .MTREE )

NAME="electron45-${VER}-1-${PKGARCH}.pkg.tar.zst"
( cd "$R" && tar --owner=0 --group=0 --numeric-owner --sort=name -cf - .PKGINFO .INSTALL .MTREE.gz usr ) \
  | zstd $ZSTD_OPTS -q -o "$OUT/$NAME" -f

echo
echo "  ✓ $OUT/$NAME  $(du -h "$OUT/$NAME" | cut -f1)"
echo "  sha256: $(sha256sum "$OUT/$NAME" | cut -d' ' -f1)"
rm -rf "$WORK"

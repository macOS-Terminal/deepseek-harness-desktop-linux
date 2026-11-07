#!/bin/bash
# 逐个解包并实际启动 4 种 x64 产物格式，确认应用能正常起来（web 监听）。
# 每种格式之间等待 19387 端口释放，避免上一次实例残留导致 EADDRINUSE 误判。
set -uo pipefail
B="$(cd "$(dirname "$0")" && pwd)"
D="${1:-$B/dist}"
T=/tmp/launch-verify
rm -rf "$T"; mkdir -p "$T"
pass=0; fail=0

APPIMAGE="$(find "$D" -maxdepth 1 -name 'DeepSeek-Harness-*-x86_64.AppImage' | sort -V | tail -1)"
DEB="$(find "$D" -maxdepth 1 -name 'deepseek-harness_*_amd64.bundled.deb' | sort -V | tail -1)"
RPM="$(find "$D" -maxdepth 1 -name 'deepseek-harness-*.x86_64.rpm' | sort -V | tail -1)"
PKGTAR="$(find "$D" -maxdepth 1 -name 'deepseek-harness-desktop-*-x86_64.pkg.tar.zst' | sort -V | tail -1)"

echo "验证目录: $D"
echo "  AppImage   : ${APPIMAGE:-未找到}"
echo "  bundled.deb: ${DEB:-未找到}"
echo "  rpm        : ${RPM:-未找到}"
echo "  pkg.tar.zst: ${PKGTAR:-未找到}"

waitport() {
  for _ in $(seq 1 30); do
    ss -tln 2>/dev/null | grep -q 19387 || return 0
    sleep 2
  done
  return 0
}

check() { # $1=label $2=logfile
  if grep -aq 'dsh web' "$2"; then
    echo "  ✓ $1 启动成功"
    pass=$((pass+1))
  else
    echo "  ✗ $1 启动失败"
    grep -a 'FatalError\|EADDRINUSE\|Error:' "$2" 2>/dev/null | head -2
    fail=$((fail+1))
  fi
}

run() { # $1=label $2=binary $3=home
  waitport
  mkdir -p "$3/.dsh"
  HOME="$3" DSH_HOME="$3/.dsh" timeout 70 xvfb-run -a "$2" --ozone-platform=x11 --disable-gpu >"$T/$1.log" 2>&1
  check "$1" "$T/$1.log"
}

echo '######## 1/4 AppImage ########'
run AppImage "$APPIMAGE" "$T/h1"
rm -rf "$T/h1"

echo '######## 2/4 bundled.deb ########'
mkdir -p "$T/b" && (
  cd "$T/b"
  ar x "$DEB"
  if [ -f data.tar.zst ]; then
    tar --zstd -xf data.tar.zst
  else
    tar -xJf data.tar.xz
  fi
)
run bundled.deb "$T/b/usr/lib/deepseek-harness/deepseek-harness" "$T/h2"
rm -rf "$T/b" "$T/h2"

echo '######## 3/4 rpm ########'
mkdir -p "$T/r" && (cd "$T/r" && bsdtar -xf "$RPM" 2>/dev/null)
run rpm "$T/r/usr/lib/deepseek-harness/deepseek-harness" "$T/h3"
rm -rf "$T/r" "$T/h3"

echo '######## 4/4 pkg.tar.zst ########'
mkdir -p "$T/p" && (cd "$T/p" && bsdtar -xf "$PKGTAR" 2>/dev/null)
sed "s|APP_DIR=/usr/lib/deepseek-harness/resources|APP_DIR=$T/p/usr/lib/deepseek-harness/resources|" "$T/p/usr/bin/deepseek-harness" > "$T/pl.sh"
chmod 755 "$T/pl.sh"
run pkg.tar.zst "$T/pl.sh" "$T/h4"
rm -rf "$T/p" "$T/h4" "$T/pl.sh"

echo
echo "===== x64 启动实测: $pass/4 通过, $fail 失败 ====="
rm -rf "$T"

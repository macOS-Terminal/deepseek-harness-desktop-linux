#!/bin/bash
# 逐个解包并实际启动 5 种 x64 格式，确认应用能正常起来（web 监听）。
# 每种格式之间等待 19387 端口释放，避免上一次实例残留导致 EADDRINUSE 误判。
D=/mnt/60CC4C56CC4C289C/Projects/dsh-desktop-linux/dist
T=/tmp/launch-verify
rm -rf "$T"; mkdir -p "$T"
pass=0; fail=0

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

echo '######## 1/5 AppImage ########'
run AppImage "$D/DeepSeek-Harness-0.2.0-rc.2-x86_64.AppImage" "$T/h1"
rm -rf "$T/h1"

echo '######## 2/5 bundled.deb ########'
mkdir -p "$T/b" && (cd "$T/b" && ar x "$D/deepseek-harness_0.2.0-rc.2_amd64.bundled.deb" data.tar.xz && tar -xJf data.tar.xz)
run bundled.deb "$T/b/usr/lib/deepseek-harness/deepseek-harness" "$T/h2"
rm -rf "$T/b" "$T/h2"

echo '######## 3/5 system.deb ########'
mkdir -p "$T/s" && (cd "$T/s" && ar x "$D/deepseek-harness_0.2.0-rc.2_amd64.system.deb" data.tar.xz && tar -xJf data.tar.xz)
sed "s|APP_DIR=/usr/lib/deepseek-harness/resources|APP_DIR=$T/s/usr/lib/deepseek-harness/resources|" "$T/s/usr/bin/deepseek-harness" > "$T/sl.sh"
chmod 755 "$T/sl.sh"
run system.deb "$T/sl.sh" "$T/h3"
rm -rf "$T/s" "$T/h3" "$T/sl.sh"

echo '######## 4/5 rpm ########'
mkdir -p "$T/r" && (cd "$T/r" && rpm2cpio "$D/deepseek-harness-0.2.0-0.rc2.x86_64.rpm" | cpio -idm --quiet 2>/dev/null)
run rpm "$T/r/usr/lib/deepseek-harness/deepseek-harness" "$T/h4"
rm -rf "$T/r" "$T/h4"

echo '######## 5/5 pkg.tar.zst ########'
mkdir -p "$T/p" && (cd "$T/p" && bsdtar -xf "$D/deepseek-harness-desktop-0.2.0_rc.2-1-x86_64.pkg.tar.zst" 2>/dev/null)
sed "s|APP_DIR=/usr/lib/deepseek-harness/resources|APP_DIR=$T/p/usr/lib/deepseek-harness/resources|" "$T/p/usr/bin/deepseek-harness" > "$T/pl.sh"
chmod 755 "$T/pl.sh"
run pkg.tar.zst "$T/pl.sh" "$T/h5"
rm -rf "$T/p" "$T/h5" "$T/pl.sh"

echo
echo "===== x64 启动实测: $pass/5 通过, $fail 失败 ====="
rm -rf "$T"

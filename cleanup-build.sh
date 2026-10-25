#!/bin/bash
# 清理构建垃圾。保留：dist 产物与文档、源码包、补丁脚本、dl 平台包、tools、原始 dmg。
# 用法: cleanup-build.sh [--purge-dmg]
set -u
R=/mnt/60CC4C56CC4C289C/Projects/dsh-desktop-linux
cd "$R" || exit 1
PURGE_DMG=0
[ "${1:-}" = "--purge-dmg" ] && PURGE_DMG=1

before=$(df --output=avail -k /mnt/60CC4C56CC4C289C | tail -1 | awk '{print $1}')

echo "== /tmp 里的解包暂存 =="
for d in /tmp/vnew /tmp/va /tmp/vb /tmp/tt /tmp/tt2 /tmp/trayt /tmp/ic /tmp/fulltest \
         /tmp/dsh-build-* /tmp/linux-ready-* /tmp/pkgmode /tmp/dhrun* /tmp/swaptest /tmp/swapv \
         /tmp/dban /tmp/trimtest* /tmp/restore /tmp/apply-test* /tmp/chain; do
  [ -e "$d" ] && { rm -rf "$d"; printf '  - %s\n' "$d"; }
done

echo "== /tmp 里的临时脚本与日志 =="
rm -f /tmp/roster*.mjs /tmp/r[0-9].mjs /tmp/cdp*.mjs /tmp/shot.mjs /tmp/dump*.mjs \
      /tmp/probe.mjs /tmp/*.log /tmp/*.sh.bak /tmp/new.sha /tmp/*.xz /tmp/*.zst 2>/dev/null
echo "  - /tmp 临时文件"

echo "== 项目内的旧日志 =="
rm -f "$R"/build-*.log "$R"/alpha-test*.mjs "$R"/cdp-probe.mjs "$R"/click-test.mjs "$R"/dbg.mjs 2>/dev/null
echo "  - 旧调试脚本与构建日志"

if [ "$PURGE_DMG" = "1" ]; then
  echo "== 原始 dmg（需 --purge-dmg）=="
  rm -f "$R"/others/*.dmg && echo "  - others/*.dmg"
else
  echo "== 保留 others/*.dmg（重建时需要；加 --purge-dmg 可删）=="
fi

after=$(df --output=avail -k /mnt/60CC4C56CC4C289C | tail -1 | awk '{print $1}')
echo
echo "== 释放 $(( (after-before)/1024 )) MB =="
df -h /mnt/60CC4C56CC4C289C | tail -1
echo
echo "== 保留项 =="
printf '  dist/:  %s (%s 个文件)\n' "$(du -sh dist 2>/dev/null | cut -f1)" "$(ls dist | wc -l)"
printf '  dl/:    %s\n' "$(du -sh dl 2>/dev/null | cut -f1)"
printf '  tools/: %s\n' "$(du -sh tools 2>/dev/null | cut -f1)"
printf '  others/: %s\n' "$(du -sh others 2>/dev/null | cut -f1)"
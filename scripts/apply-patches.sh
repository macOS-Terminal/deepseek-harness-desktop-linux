#!/bin/bash
# 按 AGENT_PROMPT 规定的顺序给一棵已装配的应用树打补丁。
#   ① patch-main.py      平台准入 / 资源根 / 托盘 / 窗口控制 IPC
#   ② patch-titlebar.py  隐藏原生标题栏
#   ③ patch-mac-chrome.py macOS 风格装饰（内部依次调 kde-material / fullscreen-reveal / linux-identity）
#   ④ patch-fingerprint.py 放宽 V8 指纹门禁
# 顺序不可颠倒：③ 替换的正是 ② 产生的 titleBarOverlay 分支。
#
# 用法: apply-patches.sh <out-x64|out-arm64> <x64|arm64>
set -euo pipefail
B="$(cd "$(dirname "$0")/.." && pwd)"
TREE="${1:?用法: apply-patches.sh <tree> <x64|arm64>}"
ARCH="${2:?用法: apply-patches.sh <tree> <x64|arm64>}"
APP="$B/$TREE/resources/app"

echo "######## ① patch-main.py ########"
python3 "$B/patches/patch-main.py" "$APP/lib/main.js"

echo; echo "######## ② patch-titlebar.py ########"
python3 "$B/patches/patch-titlebar.py" "$APP/lib/main.js"

echo; echo "######## ③ patch-mac-chrome.py ########"
python3 "$B/patches/patch-mac-chrome.py" "$APP"

echo; echo "######## ④ patch-fingerprint.py ########"
if [ "$ARCH" = x64 ]; then
  NODE_ADDON="$APP/dsh/node_modules/node-addon-require-builtin-linux-x64-gnu/prebuilt/linux-x64-gnu-napi-v9.node"
else
  NODE_ADDON="$APP/dsh/node_modules/node-addon-require-builtin-linux-arm64-gnu/prebuilt/linux-arm64-gnu-napi-v9.node"
fi
python3 "$B/patches/patch-fingerprint.py" "$NODE_ADDON"

echo; echo "######## 补丁痕迹核验 ########"
for p in desktopResourcesRoot desktopIsPackaged linux-window-control syncing fsync; do :; done
for p in desktopResourcesRoot desktopIsPackaged linux-window-control syncTilingFullscreen dsh-mac-vibrancy; do
  printf '  %-24s %s\n' "$p" "$(grep -rl "$p" "$APP/lib" 2>/dev/null | xargs -r -n1 basename | tr '\n' ' ')"
done

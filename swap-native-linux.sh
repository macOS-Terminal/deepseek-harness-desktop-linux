#!/bin/bash
# 把应用树里的 darwin 原生包替换为对应的 Linux 包（x86_64 或 aarch64）。
#
# 背景：官方 macOS dmg 只带 darwin 预编译产物。Linux 上应用通过 require.resolve
# 按平台解析：darwin 包永不加载，但**对应 Linux 包必须存在**，否则 require 失败、
# Host 启动中止。因此必须做双向替换 —— 删 darwin、装 linux。
#
# 用法: swap-native-linux.sh <app-tree> <dl-dir> <x64|arm64>
#   app-tree  含 dsh/node_modules 的应用树根
#   dl-dir    含 Linux 平台包的目录（见 dl/linux-x64 或 dl/linux-arm64）
#   arch      x64 或 arm64
set -euo pipefail

APP="${1:?用法: swap-native-linux.sh <app-tree> <dl-dir> <x64|arm64>}"
DL="${2:?用法: swap-native-linux.sh <app-tree> <dl-dir> <x64|arm64>}"
ARCH="${3:?用法: swap-native-linux.sh <app-tree> <dl-dir> <x64|arm64>}"

case "$ARCH" in
  x64)   NPM_ARCH=x64;   PTY_ARCH=linux-x64 ;;
  arm64) NPM_ARCH=arm64; PTY_ARCH=linux-arm64 ;;
  *) echo "未知架构: $ARCH（应为 x64 或 arm64）" >&2; exit 1 ;;
esac

NM="$APP/dsh/node_modules"
[ -d "$NM" ] || { echo "找不到 node_modules: $NM" >&2; exit 1; }

install_tgz() {
  local tgz="$1" dest="$2"
  [ -s "$tgz" ] || { echo "  缺少 $tgz" >&2; return 1; }
  rm -rf "$dest"; mkdir -p "$(dirname "$dest")"
  local tmp; tmp="$(mktemp -d)"; tar xzf "$tgz" -C "$tmp"
  mv "$tmp/package" "$dest"; rm -rf "$tmp"
  printf '  ✓ %s\n' "$(basename "$dest")"
}

echo "== 移除 darwin 包 =="
for p in \
  "$NM/@img/sharp-darwin-arm64" \
  "$NM/@img/sharp-libvips-darwin-arm64" \
  "$NM/@koromix/koffi-darwin-arm64" \
  "$NM/sherpa-onnx-darwin-arm64" \
  "$NM/node-addon-require-builtin-darwin-arm64" \
  "$NM/@vscode/ripgrep-darwin-arm64" \
  "$NM/@deepseek-ai/node-addon-system-darwin-arm64" \
  "$NM/@deepseek-ai/libreoffice-kit-darwin-arm64" \
  "$NM/node-pty/prebuilds/darwin-arm64" ; do
  if [ -e "$p" ]; then rm -rf "$p"; printf '  - %s\n' "$(basename "$p")"; fi
done

echo "== 安装 Linux $ARCH 包 =="
install_tgz "$DL/sharp-linux-$NPM_ARCH.tgz"          "$NM/@img/sharp-linux-$NPM_ARCH"
install_tgz "$DL/sharp-libvips-linux-$NPM_ARCH.tgz"  "$NM/@img/sharp-libvips-linux-$NPM_ARCH"
install_tgz "$DL/koffi-linux-$NPM_ARCH.tgz"          "$NM/@koromix/koffi-linux-$NPM_ARCH"
install_tgz "$DL/sherpa-onnx-linux-$NPM_ARCH.tgz"    "$NM/sherpa-onnx-linux-$NPM_ARCH"
install_tgz "$DL/ARB-linux-$NPM_ARCH.tgz"            "$NM/node-addon-require-builtin-linux-$NPM_ARCH-gnu"
install_tgz "$DL/ripgrep-linux-$NPM_ARCH.tgz"        "$NM/@vscode/ripgrep-linux-$NPM_ARCH"
install_tgz "$DL/nas-linux-$NPM_ARCH.tgz"            "$NM/@deepseek-ai/node-addon-system-linux-$NPM_ARCH"
install_tgz "$DL/lowasm.tgz"                         "$NM/@deepseek-ai/libreoffice-kit-wasm"

echo "  · node-pty/prebuilds/$PTY_ARCH"
tmp="$(mktemp -d)"; tar xzf "$DL/node-pty.tgz" -C "$tmp" "package/prebuilds/$PTY_ARCH"
mkdir -p "$NM/node-pty/prebuilds"
rm -rf "$NM/node-pty/prebuilds/$PTY_ARCH"
cp -a "$tmp/package/prebuilds/$PTY_ARCH" "$NM/node-pty/prebuilds/"
rm -rf "$tmp"
printf '    ✓ %s 个文件\n' "$(find "$NM/node-pty/prebuilds/$PTY_ARCH" -type f | wc -l)"

echo "== 清理 macOS 扩展属性影子文件 =="
# 从 dmg 直接复制会带出 *:com.apple.provenance 这类 0 字节元数据文件；
# 它们不是包，但会让"darwin 残留"计数失真，且对 Linux 无意义。
find "$NM" -name '*:com.apple.provenance' -delete 2>/dev/null || true

# 必备的跨平台包：dsh-sandbox-local 顶层静态 import 它，删掉会让整个
# dsh-sandbox-local 插件加载失败（sandbox/shell/ptcRuntime/workflowEngine
# 四个服务随之缺失，Agent 预设的标准/PTC/创造模式会显示「加载失败」）。
# 它虽是 Windows 专用的 ACL 沙箱，但 ESM 静态 import 无法按平台条件化，
# Linux 上同样会被求值，因此必须保留。缺失时从 npm 取回。
ACL="$NM/@deepseek-ai/dsh-sandbox-windows-acl"
if [ ! -d "$ACL" ]; then
  echo "  · 补装 dsh-sandbox-windows-acl（dsh-sandbox-local 静态依赖，不可裁剪）"
  ver=$(python3 -c "
import json
print(json.load(open('$NM/@deepseek-ai/dsh-sandbox-local/package.json'))['version'])" 2>/dev/null)
  tmp="$(mktemp -d)"
  if curl -sL --max-time 120 -o "$tmp/a.tgz" \
      "https://registry.npmjs.org/@deepseek-ai/dsh-sandbox-windows-acl/-/dsh-sandbox-windows-acl-${ver}.tgz" \
      && tar xzf "$tmp/a.tgz" -C "$tmp" 2>/dev/null; then
    mv "$tmp/package" "$ACL"; printf '    ✓ %s\n' "$ver"
  else
    echo "    ✗ 补装失败：$ACL 缺失会导致 sandbox 插件加载失败" >&2
  fi
  rm -rf "$tmp"
fi

echo "== 结果核对 =="
printf '  darwin 残留: %s\n' "$(find "$NM" -maxdepth 2 -name '*darwin*' 2>/dev/null | wc -l)"
printf '  linux 包:    %s\n' "$(find "$NM" -maxdepth 2 -name '*linux*' 2>/dev/null | wc -l)"

# 架构核验：所有 .node/.so 必须匹配目标架构
echo "== 架构核验（应为 ${ARCH}）=="
want=$([ "$ARCH" = x64 ] && echo 'x86-64' || echo 'ARM aarch64')
bad=0
while IFS= read -r f; do
  got=$(file -b "$f" 2>/dev/null | grep -oE 'ARM aarch64|x86-64' | head -1)
  if [ -n "$got" ] && [ "$got" != "$want" ]; then
    printf '  ✗ %s → %s\n' "${f#$NM/}" "$got"; bad=$((bad+1))
  fi
done < <(find "$NM" -type f \( -name '*.node' -o -name '*.so' -o -name '*.so.*' \) 2>/dev/null)
printf '  架构不符: %s\n' "$bad"
[ "$bad" -eq 0 ] && echo "  ✓ 全部匹配 $want" || exit 1
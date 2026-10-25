#!/bin/bash
# 精简应用树中「运行时确实用不到」的载荷。
#
# 设计原则：只删**有证据证明不被使用**的东西，每一项都标注依据。
# 不删任何会削弱功能的内容（例如 node/include/node 下的核心头文件 ——
# pnpm 内置 node-gyp，用户安装带原生扩展的插件时需要它们）。
#
# 实测收益说明：这些内容大多是文本/头文件，xz 压缩率极高（约 17:1）。
# 删除约 106 MB 原始体积，在 257 MB 的成品 deb 里只减少约 0.2 MB。
# 因此本脚本的**主要目的是减少解包后的磁盘占用与安装体积**，
# 而不是显著缩小下载包。真正的体积来自 Electron / python / node 二进制，
# 那些是功能必需，无法裁剪。
#
# 用法: trim-app-tree.sh <app-root>
#   <app-root> 为应用树根。兼容两种布局：
#     打包布局  .../deepseek-harness/resources/app/dsh/node_modules
#     平铺布局  .../app/dsh/node_modules
#   两者都由本脚本自行定位。
set -euo pipefail

APP="${1:?用法: trim-app-tree.sh <app-root>}"

# 定位 resources 根：优先 <app>/resources，其次 <app> 自身（平铺布局）
if [ -d "$APP/resources/app/dsh/node_modules" ]; then
  RES="$APP/resources"
elif [ -d "$APP/dsh/node_modules" ]; then
  RES="$APP"
else
  echo "找不到应用树（期望 $APP/resources/app/dsh/node_modules 或 $APP/dsh/node_modules）" >&2
  exit 1
fi
echo "== 应用树根: $APP  (resources 根: $RES) =="

D="$RES/runtime/primary-runtime/dependencies"
before=$(du -sb "$APP" 2>/dev/null | cut -f1)

# 记录每项的依据，便于日后复核
trim() {
  local path="$1" why="$2"
  if [ -e "$path" ]; then
    local sz; sz=$(du -sb "$path" 2>/dev/null | cut -f1)
    rm -rf "$path"
    printf '  - %-58s %6.1f MB  (%s)\n' "${path#$APP/}" "$(echo "$sz" | awk '{print $1/1048576}')" "$why"
  fi
}

echo "== 裁剪运行时冗余 =="

# npm 与 pnpm 功能重复，应用只调用 pnpm（main.js 中 0 处引用 npm）
trim "$D/node/lib/node_modules/npm"      "应用使用 pnpm，不引用 npm"
trim "$D/node/lib/node_modules/corepack" "corepack 仅用于管理包管理器版本"

# man 手册与调试脚本，运行期不读取
trim "$D/node/share"                     "man/doc 与 gdb/lldb 脚本，运行期不读取"

# openssl 头文件里 21 个平台变体，Linux 只需本架构
OSSL="$D/node/include/node/openssl/archs"
if [ -d "$OSSL" ]; then
  keep=$(uname -m)
  case "$keep" in
    x86_64)  keep=linux-x86_64 ;;
    aarch64) keep=linux-aarch64 ;;
    *)       keep="" ;;
  esac
  if [ -n "$keep" ] && [ -d "$OSSL/$keep" ]; then
    for d in "$OSSL"/*; do
      [ "$(basename "$d")" = "$keep" ] || rm -rf "$d"
    done
    printf '  - %-58s           (仅保留 %s，其余 20 个平台变体)\n' \
      "${OSSL#$APP/}" "$keep"
  fi
fi

# Python 里对桌面应用无用的部分
PY="$D/python"
trim "$PY/include"                                   "C 头文件，仅编译扩展时需要"
trim "$PY/lib/python3.12/idlelib"                    "GUI IDE，应用不启动"
trim "$PY/lib/python3.12/tkinter"                    "GUI 工具包，无 Tk 界面"
trim "$PY/lib/python3.12/turtledemo"                 "教学示例"
trim "$PY/lib/python3.12/pydoc_data"                 "文档数据"
trim "$PY/lib/python3.12/lib2to3"                    "已废弃的 2to3 转换器"
trim "$PY/lib/python3.12/ensurepip"                  "自带 pip 引导，运行时不安装"
trim "$PY/lib/python3.12/site-packages/pip"          "运行时不安装 Python 包（站点包已预置）"

# 刻意保留 dsh-sandbox-windows-acl：
#   虽然它是 Windows 专用的 ACL 沙箱，但 dsh-sandbox-local 在**顶层静态 import** 它
#   （import { AclWriteGrant, ... } from "@deepseek-ai/dsh-sandbox-windows-acl"）。
#   ESM 的静态 import 无法按平台条件化，Linux 上同样会被求值 —— 删掉该包会抛
#   ERR_MODULE_NOT_FOUND，使整个 dsh-sandbox-local 插件加载失败，
#   进而让 sandbox / shell / ptcRuntime / workflowEngine 四个服务全部缺失。
#   结果是 Agent 预设里的标准/PTC/创造三个模式被判定为「加载失败」（等待上述服务），
#   只有不含这些依赖的「极简模式」正常。
#   该包仅 72 KB，为保住功能必须保留。

# Chromium 许可证全文（合规信息，安装包内另附 licenses/）
trim "$APP/LICENSES.chromium.html"                   "Chromium 许可证全文，非运行时资源"

# 清理 macOS 扩展属性残留（若从 dmg 复制而来）
find "$RES" -name '*:com.apple.provenance' -delete 2>/dev/null || true

# ---- 自检：静态 import 的包是否都还在 -------------------------------------
# 裁剪平台包时最容易踩的坑：某个包在别的插件里被**顶层静态 import**，删掉它会让
# 那个插件整体加载失败，表现为「某个功能整体消失」而非「某个工具缺失」。
# 这里解析所有 @deepseek-ai 包的顶层静态 import，核对目标是否仍可解析。
echo
echo "== 自检：静态 import 完整性 =="
python3 - "$RES" <<'PYEOF'
import os, re, sys
res = sys.argv[1]
candidates = [
    os.path.join(res, 'app', 'dsh', 'node_modules'),
    os.path.join(res, 'dsh', 'node_modules'),
]
nm = next((c for c in candidates if os.path.isdir(c)), None)
if nm is None:
    print('  跳过（未找到 node_modules）')
    raise SystemExit(0)
scope = os.path.join(nm, '@deepseek-ai')
if not os.path.isdir(scope):
    print('  跳过（未找到 @deepseek-ai 作用域）')
    raise SystemExit(0)

missing = {}
for pkg in sorted(os.listdir(scope)):
    lib = os.path.join(scope, pkg, 'lib')
    if not os.path.isdir(lib):
        continue
    for name in sorted(os.listdir(lib)):
        if not name.endswith('.js'):
            continue
        path = os.path.join(lib, name)
        try:
            text = open(path, encoding='utf8', errors='replace').read()
        except OSError:
            continue
        for m in re.finditer(r'''^import\s+(?:[\w*{},\s]+\s+from\s+)?["'](@deepseek-ai/[^"']+)["']''', text, re.M):
            missing.setdefault(m.group(1), set()).add(f'{pkg}/{name}')

broken = {}
for target, users in missing.items():
    sub = target.split('/', 1)[1].split('/')[0]
    if not os.path.isdir(os.path.join(scope, sub)):
        broken[target] = users
if not broken:
    print(f'  ✓ {len(missing)} 个静态 import 目标全部可解析')
else:
    print(f'  ✗ {len(broken)} 个静态 import 目标缺失 —— 会导致对应插件整体加载失败：')
    for target, users in sorted(broken.items()):
        print(f'      {target}  ←  {", ".join(sorted(users)[:3])}')
    raise SystemExit(1)
PYEOF

after=$(du -sb "$APP" 2>/dev/null | cut -f1)
echo
echo "== 结果 =="
printf '  裁剪前: %.1f MB\n' "$(echo "$before" | awk '{print $1/1048576}')"
printf '  裁剪后: %.1f MB\n' "$(echo "$after"  | awk '{print $1/1048576}')"
printf '  减少:   %.1f MB（解包后占用）\n' \
  "$(echo "$before $after" | awk '{print ($1-$2)/1048576}')"
echo
echo "  注意：以上多为文本/头文件，xz 压缩率很高（约 17:1），"
echo "  成品下载包的体积减少幅度远小于此（实测约 0.2 MB / 257 MB）。"
echo "  成品体积主要由 Electron(62MB) / 应用依赖(66MB) / python(53MB) / node(28MB) 决定，"
echo "  这些是功能必需，未作裁剪。"
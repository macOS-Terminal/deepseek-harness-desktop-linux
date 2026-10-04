# ========================================================= 阶段 2：生成应用树 ==
normalize_modes() {  # 与 build-packages.sh 的 normalize_modes 保持一致
  python3 - "$1" <<'PYEOF'
import os, sys
root = sys.argv[1]
for dp, dns, fns in os.walk(root):
    for d in dns:
        try: os.chmod(os.path.join(dp, d), 0o755)
        except OSError: pass
    for fn in fns:
        fp = os.path.join(dp, fn)
        if os.path.islink(fp):
            continue
        try:
            with open(fp, 'rb') as f:
                head = f.read(4)
        except OSError:
            continue
        executable = (
            head.startswith(b'\x7fELF')
            or head[:2] == b'#!'
            or fn.endswith(('.so', '.node'))
            or '.so.' in fn
        )
        try: os.chmod(fp, 0o755 if executable else 0o644)
        except OSError: pass
PYEOF
}

# 找一个带 pip 的解释器；都没有就在 store 里建一个 venv（自带 pip），
# 不去动系统的 Python，也不要求 root。
pip_python() {
  local candidate
  for candidate in "$(command -v python3 2>/dev/null || true)"; do
    [ -n "$candidate" ] || continue
    if "$candidate" -c 'import pip' >/dev/null 2>&1; then printf '%s' "$candidate"; return 0; fi
  done
  local venv="$DL/pip-venv" base
  base="$(command -v python3 2>/dev/null || true)"
  if [ -n "$base" ]; then
    if [ -x "$venv/bin/python" ] && "$venv/bin/python" -c 'import pip' >/dev/null 2>&1; then
      printf '%s' "$venv/bin/python"; return 0
    fi
    if "$base" -m venv "$venv" >/dev/null 2>&1 \
       && "$venv/bin/python" -c 'import pip' >/dev/null 2>&1; then
      step "系统 python3 没有 pip，已在 $(rel "$venv") 建好自带 pip 的 venv" >&2
      printf '%s' "$venv/bin/python"; return 0
    fi
  fi
  return 1
}

install_python_payload() {  # <arch> <目标 python 目录> <版本> <需求列表>
  local arch="$1" dest="$2" pyver="$3" requirements="$4"
  local tarball="$DL/python-${pyver}-${arch}.tar.gz"
  local stage="$WORK_BASE/$arch/python-payload"
  drop "$stage"; mkdir -p "$stage"
  tar -xzf "$tarball" -C "$stage"
  local inner
  inner="$(find "$stage" -maxdepth 1 -mindepth 1 | head -1)"
  [ -n "$inner" ] && [ -d "$inner" ] || die "python 载荷布局异常: $tarball"
  mkdir -p "$(dirname "$dest")"
  drop "$dest"
  mv "$inner" "$dest"

  local pylib site
  pylib="$(find "$dest/lib" -maxdepth 1 -name 'python3.*' -type d | head -1)"
  [ -n "$pylib" ] || die "python 载荷里找不到 lib/python3.x: $dest"
  site="$pylib/site-packages"
  [ -d "$site" ] || mkdir -p "$site"

  local pip
  pip="$(pip_python)" || die "没有可用的 pip：需要带 pip 的 python3 或可用的 python3 -m venv"
  local plat; plat="$(arch_pypi "$arch")"
  step "交叉安装 $(echo "$requirements" | wc -w) 个 manylinux 轮子（$plat）"
  # 源按顺序重试：配置的镜像 → 阿里云 → 官方 PyPI。
  local mirrors=("$PYPI_MIRROR" "https://mirrors.aliyun.com/pypi/simple" "https://pypi.org/simple")
  local mirror ok=0
  for mirror in "${mirrors[@]}"; do
    if "$pip" -m pip install --upgrade --target "$site" \
         --platform "manylinux_2_28_$plat" --platform "manylinux_2_27_$plat" --platform "manylinux2014_$plat" \
         --python-version "$(basename "$pylib" | sed 's/^python//')" --implementation cp --only-binary=:all: \
         --no-compile --disable-pip-version-check --index-url "$mirror" $requirements; then
      ok=1
      [ "$mirror" = "$PYPI_MIRROR" ] || step "已改用备源：$mirror"
      break
    fi
    warn "源 $mirror 失败，换下一个"
  done
  [ "$ok" -eq 1 ] || die "python 站点包交叉安装失败（已试 ${#mirrors[@]} 个源）"
}

rewrite_cli_launcher() {  # <resources 目录>
  local resources="$1" launcher="$1/runtime/cli/bin/dsh"
  [ -f "$launcher" ] || return 0
  cat > "$launcher" <<'LAUNCH'
#!/bin/sh
# Run the installed CLI without changing the invoking shell or working directory.
# Linux 版：官方 dmg 的启动器写死了 macOS 路径（../MacOS/DeepSeek Harness 与
# app.asar），这里改为自动定位发行版 electron 或内置二进制。
set -e
launcher=$0
while [ -L "$launcher" ]; do
  directory=$(CDPATH= cd -- "$(dirname -- "$launcher")" && pwd -P)
  target=$(readlink "$launcher")
  case "$target" in
    /*) launcher=$target ;;
    *) launcher=$directory/$target ;;
  esac
done
resources=$(CDPATH= cd -- "$(dirname -- "$launcher")/../../.." && pwd -P)
app="$resources/app"
[ -d "$app/dsh" ] || app="$resources/app.asar"
cli="$app/dsh/node_modules/@deepseek-ai/dsh-desktop-host/lib/cli.js"
# 内置二进制在 resources 的**上一级**（AppImage/发行包里就是应用根目录）。
approot=$(CDPATH= cd -- "$resources/.." && pwd -P)
find_electron() {
  for candidate in "$approot/deepseek-harness" "$approot/electron"; do
    [ -x "$candidate" ] && { printf '%s' "$candidate"; return 0; }
  done
  for name in electron electron44 nodejs-electron; do
    command -v "$name" >/dev/null 2>&1 && { command -v "$name"; return 0; }
  done
  for candidate in /usr/lib/electron44/electron /usr/lib/electron/electron \
                   /usr/lib64/electron/electron /usr/lib/nodejs-electron/electron; do
    [ -x "$candidate" ] && { printf '%s' "$candidate"; return 0; }
  done
  return 1
}
electron=$(find_electron) || {
  echo "dsh: 未找到 Electron 运行时（内置二进制或发行版 electron）。" >&2
  exit 1
}
export DSH_DESKTOP_FORCE_PACKAGED=1
export DSH_DESKTOP_RESOURCES_DIR="$resources"
export DSH_DESKTOP_NODE_EXECUTABLE="$electron"
ELECTRON_RUN_AS_NODE=1 exec "$electron" --expose-internals "$cli" "$@"
LAUNCH
  chmod 755 "$launcher"
  step "runtime/cli/bin/dsh 已改写为 Linux 启动器"
}

build_tree() {  # <arch>
  local arch="$1"
  local out="$ROOT/out-$arch"
  if [ "$DRY_RUN" -eq 1 ]; then
    say "阶段 2/3 生成应用树 out-$arch"
    step "[dry-run] 解包 dmg → Electron 骨架 → 展开 app.asar → 换 node/python 载荷"
    step "[dry-run] → 原生模块换 Linux 版 → 打补丁 → 装 image-worker"
    return 0
  fi
  local resources pyver nodever appver
  resources="$(dmg_resources)"
  read -r pyver nodever appver < <(runtime_json "$resources/runtime/primary-runtime/runtime.json")
  printf '%s\n' "$appver" > "$OTHERS/.app-version"

  say "阶段 2/3 生成应用树 out-$arch"
  mkdir -p "$WORK_BASE/$arch"
  drop "$out"
  mkdir -p "$out"

  # 1) Electron 骨架
  unzip -oq "$DL/electron-${ELECTRON_VERSION}-$(arch_node "$arch").zip" -d "$out"
  mv "$out/electron" "$out/deepseek-harness"
  rm -f "$out/resources/default_app.asar"
  step "Electron ${ELECTRON_VERSION} 骨架就位"

  # 2) 展开 app.asar → resources/app
  python3 "$ROOT/scripts/extract-asar.py" "$resources/app.asar" "$out/resources/app" \
    --unpacked "$resources/app.asar.unpacked"

  # 3) 运行时载荷：runtime/ + icon.png（跳过 macOS 附加流）
  copy_tree "$resources/runtime" "$out/resources/runtime" '*:com.apple.*' '.DS_Store'
  cp -f "$resources/icon.png" "$out/resources/icon.png"
  rm -f "$out/resources/app-update.yml"
  step "resources 载荷就位（runtime / icon.png）"

  # 4) node / python 换成 Linux 构建
  local node_stage="$WORK_BASE/$arch/node-payload"
  drop "$node_stage"; mkdir -p "$node_stage"
  tar -xJf "$DL/node-v${nodever}-$(arch_node "$arch").tar.xz" -C "$node_stage" \
    --strip-components=2 "node-v${nodever}-$(arch_node "$arch")/bin/node"
  install -m 755 "$node_stage/node" "$out/resources/runtime/primary-runtime/dependencies/node/bin/node"
  rm -f "$out/resources/runtime/primary-runtime/dependencies/node/bin/node.cmd"
  step "Node ${nodever}（$(arch_node "$arch")）已就位"

  local reqs
  reqs="$(python3 -c '
import json, sys
data = json.load(open(sys.argv[1], encoding="utf8"))
print(" ".join(f"{k}=={v}" for k, v in data["pythonPackages"].items()))
' "$resources/runtime/primary-runtime/runtime.json")"
  install_python_payload "$arch" "$out/resources/runtime/primary-runtime/dependencies/python" "$pyver" "$reqs"

  python3 - "$out/resources/runtime/primary-runtime/runtime.json" "$arch" <<'PYEOF'
import json, sys
path, arch = sys.argv[1], sys.argv[2]
data = json.load(open(path, encoding='utf8'))
data['platform'] = 'linux'
data['arch'] = arch
with open(path, 'w', encoding='utf8') as handle:
    json.dump(data, handle, ensure_ascii=False, indent=2)
    handle.write('\n')
PYEOF
  step "runtime.json → platform=linux, arch=$arch"

  # 5) 托盘图标：Linux 用 PNG（32×32）
  if [ -f "$resources/tray.png" ]; then
    cp -f "$resources/tray.png" "$out/resources/tray.png"
  elif have ffmpeg; then
    ffmpeg -loglevel error -y -i "$ROOT/icons/deepseek-harness.png" -vf scale=32:32 \
      "$out/resources/tray.png"
  else
    cp -f "$ROOT/icons/32x32/deepseek-harness.png" "$out/resources/tray.png"
  fi
  step "托盘图标 tray.png（32×32）"

  # 6) 原生模块换 Linux 版
  # 原生包必须同版本替换；失败即中止（--allow-drift 才允许放宽版本）。
  local drift_args=()
  [ "$ALLOW_DRIFT" -eq 1 ] && drift_args=(--allow-drift)
  python3 "$ROOT/scripts/npm-linux-swap.py" --app "$out/resources/app" --arch "$arch" \
    --registry "$NPM_REGISTRY" --fallback-registry "$NPM_FALLBACK" --cache "$DL/npm" \
    ${drift_args[@]+"${drift_args[@]}"}

  # 7) 补丁
  python3 "$ROOT/patches/patch-main.py" "$out/resources/app/lib/main.js"
  python3 "$ROOT/patches/patch-mac-chrome.py" "$out/resources/app"
  local fingerprint
  fingerprint="$(find "$out/resources/app/dsh/node_modules" -path '*node-addon-require-builtin-linux-*' -name '*.node' | head -1)"
  [ -n "$fingerprint" ] || die "找不到 node-addon-require-builtin 的 Linux 原生模块"
  python3 "$ROOT/patches/patch-fingerprint.py" "$fingerprint"

  # 8) Sharp 进程隔离 + CLI 启动器 + 权限归一
  "$ROOT/install-image-worker.sh" "out-$arch" "$arch"
  # Native Sharp backup stays available for diagnostics; AppImage packaging excludes it.
  rewrite_cli_launcher "$out/resources"
  normalize_modes "$out"
  say "应用树完成: out-$arch（$(human "$out")）"
}

verify_tree() {  # <arch>
  local arch="$1" out="$ROOT/out-$arch"
  [ "$VERIFY" -eq 1 ] || { step "指定了 --no-verify，跳过 out-$arch 自检"; return 0; }
  [ "$DRY_RUN" -eq 1 ] && return 0
  local electron="$out/deepseek-harness"
  if [ "$arch" != "$HOST_ARCH" ]; then
    say "自检 out-$arch：目标架构与本机（$HOST_ARCH）不同，需要 qemu 才能跑，跳过"
    return 0
  fi
  say "自检 out-$arch"
  [ -x "$electron" ] || die "找不到 $electron，自检无法进行（可用 --no-verify 跳过）"
  # 自检失败就是失败：不能把「图片链路坏了」的树打成 AppImage。
  if DSH_DESKTOP_RESOURCES_DIR="$out/resources" ELECTRON_RUN_AS_NODE=1 \
     "$electron" "$ROOT/image-worker-src/verify-image-worker.cjs" 2>&1 | tail -30; then
    step "image-worker 自检通过"
  else
    die "image-worker 自检失败，已中止（修好后重跑，或用 --no-verify 明确跳过自检）"
  fi

  # 有 xvfb 就再跑一次真实启动（README 的冒烟方法）
  if have xvfb-run; then
    local smoke="$WORK_BASE/$arch/smoke-home"
    drop "$smoke"; mkdir -p "$smoke"
    step "启动冒烟（xvfb-run，最多 90 秒）"
    HOME="$smoke" DSH_HOME="$smoke/.dsh" timeout 90 xvfb-run -a "$electron" \
      --ozone-platform=x11 --disable-gpu --disable-dev-shm-usage >"$smoke/smoke.log" 2>&1 || true
    if grep -q 'dsh web: http://127.0.0.1:' "$smoke/smoke.log"; then
      step "启动冒烟通过：$(grep -o 'dsh web: http://127.0.0.1:[0-9]*/' "$smoke/smoke.log" | head -1)"
    else
      warn "启动冒烟没看到 web-ready 日志，详见 $smoke/smoke.log"
    fi
  else
    step "没有 xvfb-run，跳过启动冒烟（可在有图形环境的机器上手动运行）"
  fi
}

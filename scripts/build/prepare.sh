# =============================================================== 阶段 1：准备 ==
# appimagetool 要在**本机**运行，所以按主机架构取（不是目标架构）。
appimagetool_name() {
  case "$HOST_ARCH" in
    arm64) printf 'appimagetool-aarch64.AppImage' ;;
    *)     printf 'appimagetool-x86_64.AppImage' ;;
  esac
}

# mksquashfs 的“能不能跑”必须实测：架构不对或依赖缺失时要当场失败，
# 而不是等到打包阶段才发现工具是坏的。
mksquashfs_works() { [ -x "$1" ] && "$1" -version >/dev/null 2>&1; }

provision_mksquashfs() {
  if mksquashfs_works "$TOOLS/usr/bin/mksquashfs" && [ "$FORCE" -eq 0 ]; then
    step "mksquashfs 已就绪（$( "$TOOLS/usr/bin/mksquashfs" -version 2>/dev/null | head -1 )）"
    return 0
  fi
  [ "$DRY_RUN" -eq 1 ] && return 0
  mkdir -p "$TOOLS/usr/bin"
  rm -f "$TOOLS/usr/bin/mksquashfs"
  if have mksquashfs; then
    ln -sf "$(command -v mksquashfs)" "$TOOLS/usr/bin/mksquashfs"
    mksquashfs_works "$TOOLS/usr/bin/mksquashfs" \
      || die "系统的 mksquashfs 无法运行：$(command -v mksquashfs)"
    step "复用系统 mksquashfs: $(command -v mksquashfs)"
    return 0
  fi
  [ -n "$SEVENZ" ] || die "缺少 7z，无法从 appimagetool 里取出 mksquashfs"
  local name; name="$(appimagetool_name)"
  local appimage="$DL/$name"
  [ -s "$appimage" ] || die "缺少 $appimage（本机架构 $(uname -m) 需要它；先跑 --only prepare）"
  step "从 $name 中提取静态 mksquashfs"
  local stage="$TOOLS/.appimagetool-extract"
  drop "$stage"; mkdir -p "$stage"
  "$SEVENZ" x -y -o"$stage" "$appimage" >/dev/null || die "$name 解包失败"
  [ -f "$stage/usr/bin/mksquashfs" ] || die "$name 里没有 usr/bin/mksquashfs"
  cp "$stage/usr/bin/mksquashfs" "$TOOLS/usr/bin/mksquashfs"
  chmod 755 "$TOOLS/usr/bin/mksquashfs"
  mksquashfs_works "$TOOLS/usr/bin/mksquashfs" || die \
    "提取出的 mksquashfs 在本机（$(uname -m)）无法运行；请安装发行版的 squashfs-tools 后重跑"
  step "mksquashfs 就绪（$( "$TOOLS/usr/bin/mksquashfs" -version 2>/dev/null | head -1 )）"
}

# 与官方 SHA256SUMS 比对。清单按版本缓存（换版本不会沿用旧清单）；
# 清单里找不到当前文件就**明确失败**，绝不静默放过。
# 注意：清单里的名字是**上游资产名**（如 electron-v44.4.5-linux-x64.zip），
# 与本地另存的文件名可能不同，所以必须单独传进来。
verify_sha256sums() {  # <清单缓存文件> <本地文件> <上游资产名> <说明> <清单 URL 候选...>
  local sums_file="$1" target="$2" asset="$3" label="$4"; shift 4
  [ -n "$asset" ] || asset="$(basename "$target")"
  if [ "$CHECK_SHA" -eq 0 ]; then
    warn "$label: 指定了 --no-sha256，跳过官方校验和比对（只剩归档完整性检查）"
    return 0
  fi
  local url
  if [ "$FORCE" -eq 1 ] || [ ! -s "$sums_file" ]; then
    rm -f "$sums_file"
    for url in "$@"; do
      curl -fsSL --max-time 30 -o "$sums_file" "$url" && break
    done
  fi
  [ -s "$sums_file" ] || die "$label: 取不到官方 SHA256SUMS（候选：$*）；确认无法取到时可用 --no-sha256"
  local expect
  expect="$(sha256_expect "$sums_file" "$asset")"
  [ -n "$expect" ] || die "$label: 清单 $(basename "$sums_file") 里没有 $asset 这一条——清单与请求的版本不一致，拒绝继续"
  [ "$expect" = "$(sha256sum "$target" | cut -d' ' -f1)" ] \
    || die "$label: SHA256 与官方清单不符（下载不完整或被篡改）"
  step "$label SHA256 校验通过（$asset）"
}

phase_prepare() {
  say "阶段 1/3 准备：下载外部依赖"
  local missing=() tool
  for tool in curl tar xz unzip python3 sha256sum realpath; do have "$tool" || missing+=("$tool"); done
  [ -n "$SEVENZ" ] || missing+=(7z)
  [ "${#missing[@]}" -eq 0 ] || \
    die "缺少命令: ${missing[*]}（Debian: apt install p7zip-full curl tar xz-utils unzip python3 coreutils）"

  # 1) 官方 dmg 先落地。Node/Python 的版本要从它里面的 runtime.json 读，
  #    所以不能在下完 dmg 之前就去读“兜底版本”。
  FETCH_DOWNLOADED=0
  if [ -n "$DMG_URL_OVERRIDE" ]; then
    step "使用 --dmg 指定的 URL"
    fetch "$DMG" "$DMG_URL_OVERRIDE"
  elif [ -n "$DMG_GIVEN" ]; then
    [ -s "$DMG" ] || die "找不到本地 dmg: $DMG"
    step "使用本地 dmg: $DMG"
  else
    fetch "$DMG" "$DMG_OFFICIAL" \
      "$(gh "$DMG_MIRROR/$DMG_MIRROR_TAG/deepseek-harness-${DMG_MIRROR_TAG#v}-mac-arm64.dmg")"
  fi
  if [ -z "$DMG_GIVEN" ] || [ -n "$DMG_URL_OVERRIDE" ]; then
    dmg_provenance "${DMG_URL_OVERRIDE:-$DMG_OFFICIAL}"
  fi

  # 2) 读上游 pinned 的版本（node/python/站点包都在 runtime.json 里）
  local pyver nodever appver
  read -r pyver nodever appver < <(upstream_versions)
  step "上游载荷：dsh-desktop $appver / node $nodever / python $pyver"
  [ "$DRY_RUN" -eq 1 ] || printf '%s\n' "$appver" > "$OTHERS/.app-version"

  # 3) Electron / Node / Python 载荷：每个都给「代理 + 直连」两个地址
  local groups=() arch node_file url
  for arch in "${ARCHES[@]}"; do
    node_file="node-v${nodever}-$(arch_node "$arch").tar.xz"
    groups+=("$DL/electron-${ELECTRON_VERSION}-$(arch_node "$arch").zip|$(gh "https://github.com/electron/electron/releases/download/v${ELECTRON_VERSION}/electron-v${ELECTRON_VERSION}-$(arch_node "$arch").zip")|${ELECTRON_MIRROR}/${ELECTRON_VERSION}/electron-v${ELECTRON_VERSION}-$(arch_node "$arch").zip")
    groups+=("$DL/$node_file|${NODE_MIRROR}/v${nodever}/${node_file}|https://nodejs.org/dist/v${nodever}/${node_file}")
  done
  for arch in "${ARCHES[@]}"; do
    url="$(resolve_python_url "$pyver" "$(arch_triple "$arch")")" \
      || die "找不到 python-build-standalone ${pyver} 的 $(arch_triple "$arch") 载荷"
    groups+=("$DL/python-${pyver}-${arch}.tar.gz|$(gh "$url")|$url")
  done
  fetch_par "${groups[@]}"

  # 4) AppImage 工具链（appimagetool 按主机架构，runtime 按目标架构）
  local tool_groups=() at_name; at_name="$(appimagetool_name)"
  for arch in "${ARCHES[@]}"; do
    tool_groups+=("$TOOLS/runtime-$(arch_target "$arch")|$(gh "$RUNTIME_REPO/runtime-$(arch_target "$arch")")|$RUNTIME_REPO/runtime-$(arch_target "$arch")")
  done
  if ! mksquashfs_works "$TOOLS/usr/bin/mksquashfs"; then
    tool_groups+=("$DL/$at_name|$(gh "$APPIMAGETOOL_BASE/$at_name")|$APPIMAGETOOL_BASE/$at_name")
  fi
  [ "${#tool_groups[@]}" -eq 0 ] || fetch_par "${tool_groups[@]}"
  provision_mksquashfs

  # 5) 校验：归档完整性 + 官方 SHA256SUMS（清单按版本缓存，缺条目即失败）
  if [ "$DRY_RUN" -eq 1 ]; then say "阶段 1/3 完成（dry-run 未实际下载）"; return 0; fi
  for arch in "${ARCHES[@]}"; do
    node_file="node-v${nodever}-$(arch_node "$arch").tar.xz"
    check_archive zip "$DL/electron-${ELECTRON_VERSION}-$(arch_node "$arch").zip"
    check_archive tar.xz "$DL/$node_file"
    check_archive tar.gz "$DL/python-${pyver}-${arch}.tar.gz"
    verify_sha256sums "$DL/.SHASUMS256-electron-${ELECTRON_VERSION}" \
      "$DL/electron-${ELECTRON_VERSION}-$(arch_node "$arch").zip" \
      "electron-v${ELECTRON_VERSION}-$(arch_node "$arch").zip" \
      "Electron $(arch_node "$arch")" \
      "$(gh "https://github.com/electron/electron/releases/download/v${ELECTRON_VERSION}/SHASUMS256.txt")" \
      "https://github.com/electron/electron/releases/download/v${ELECTRON_VERSION}/SHASUMS256.txt" \
      "${ELECTRON_MIRROR}/${ELECTRON_VERSION}/SHASUMS256.txt"
    verify_sha256sums "$DL/.SHASUMS256-node-v${nodever}" "$DL/$node_file" "$node_file" \
      "Node $(arch_node "$arch")" \
      "${NODE_MIRROR}/v${nodever}/SHASUMS256.txt" \
      "https://nodejs.org/dist/v${nodever}/SHASUMS256.txt"
  done
  say "阶段 1/3 完成"
}

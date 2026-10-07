# Download and upstream payload helpers.
# ------------------------------------------------------------------- 下载 ----
FETCH_DOWNLOADED=0   # 上一次 fetch 是否真的下载了（用于记录 dmg 的上游指纹）

fetch() {  # fetch <目标路径> <URL>...
  local dest="$1"; shift
  local urls=("$@") url
  if [ -s "$dest" ] && [ "$FORCE" -eq 0 ]; then
    step "已就绪 ${dest#"$ROOT"/}（$(human "$dest")）"
    return 0
  fi
  if [ "$DRY_RUN" -eq 1 ]; then step "[dry-run] 下载 ${urls[0]} → $(rel "$dest")"; return 0; fi
  mkdir -p "$(dirname "$dest")"
  # 每个 URL 用自己的 .part：换镜像时绝不把上一个源的断点数据接上去。
  local idx=0 url part
  for url in "${urls[@]}"; do
    part="$dest.part$idx"
    idx=$((idx + 1))
    step "下载 $url"
    if curl -fL --retry 3 --retry-delay 2 --connect-timeout 20 -C - --progress-bar -o "$part" "$url"; then
      mv -f "$part" "$dest"
      FETCH_DOWNLOADED=1
      step "完成 $(rel "$dest")（$(human "$dest")）"
      return 0
    fi
    warn "该地址失败，换下一个镜像"
  done
  die "无法下载 $(rel "$dest")（已尝试 ${#urls[@]} 个地址）"
}

fetch_par() {  # 并行下载：每个参数是 "<目标>|<URL1>|<URL2>..."
  local groups=("$@") group pid status=0 running=0
  local pids=()
  for group in "${groups[@]}"; do
    local parts=()
    IFS='|' read -r -a parts <<<"$group"
    fetch "${parts[@]}" &
    pids+=("$!")
    running=$((running + 1))
    if [ "$running" -ge "$JOBS" ]; then
      wait "${pids[0]}" || status=1
      pids=("${pids[@]:1}")
      running=$((running - 1))
    fi
  done
  for pid in ${pids[@]+"${pids[@]}"}; do
    wait "$pid" || status=1
  done
  [ "$status" -eq 0 ] || die "有下载任务失败（见上方日志）；重跑本命令即可断点续传"
}

sha256_expect() {  # <SHA256SUMS 文件> <文件名> → 期望的 sha256
  awk -v f="$2" '$2 == f || $2 == "*" f { print $1; exit }' "$1"
}

check_archive() {  # <zip|tar.xz|tar.gz> <文件>
  local kind="$1" file="$2" base
  base="$(basename "$file")"
  case "$kind" in
    zip)    unzip -tq "$file" >/dev/null || die "$base 不是有效的 zip" ;;
    tar.xz) tar -tf "$file" >/dev/null || die "$base 不是有效的 tar.xz" ;;
    tar.gz) tar -tzf "$file" >/dev/null || die "$base 不是有效的 tar.gz" ;;
  esac
  step "归档完整性通过 $base"
}

# dmg 不做哈希校验：官方对 dsh-latest-macos-arm64.dmg 不发布任何校验和
# （SHA256SUMS / *.sha256 / 目录索引均为 404），而且文件名就是滚动的 latest，
# 哈希本来就会随上游发布而变。改用 HEAD 的 Content-Length / ETag / Last-Modified
# 判断“上游换过没有”：只提示，不自动重下（要换新版用 --force）。
dmg_head_signature() {  # <URL> → "size|etag|last-modified"
  local headers
  headers="$(curl -fsSI -L --connect-timeout 20 --max-time 30 "$1" 2>/dev/null | tr -d '\r')" || return 1
  [ -n "$headers" ] || return 1
  local size etag modified
  size="$(printf '%s\n' "$headers" | awk 'tolower($1) == "content-length:" { v = $2 } END { print v }')"
  etag="$(printf '%s\n' "$headers" | awk 'tolower($1) == "etag:" { v = $2 } END { print v }')"
  modified="$(printf '%s\n' "$headers" | sed -n 's/^[Ll]ast-[Mm]odified: *//p' | tail -1)"
  [ -n "$size" ] || return 1
  printf '%s|%s|%s' "$size" "$etag" "$modified"
}

dmg_provenance() {  # <URL>
  local record="$OTHERS/.dmg-head" current
  # dry-run 不发网络请求。
  [ "$DRY_RUN" -eq 1 ] && return 0
  current="$(dmg_head_signature "$1")" \
    || { warn "查不到上游 dmg 的指纹（HEAD 失败），跳过更新检查"; return 0; }
  if [ "$FETCH_DOWNLOADED" -eq 1 ] || [ ! -s "$record" ]; then
    [ "$DRY_RUN" -eq 1 ] || printf '%s\n' "$current" > "$record"
    step "记录上游 dmg 指纹（$(printf '%s' "$current" | cut -d'|' -f1) 字节），下次据此判断上游是否更新"
    return 0
  fi
  if [ "$current" != "$(cat "$record")" ]; then
    warn "官方 dmg 已更新（上游与上次记录不一致），本次仍用本地这一份构建"
    warn "要换成新版：./auto-build.sh --force，或删除 ${DMG#"$ROOT"/} 后重跑"
    warn "（不校验哈希：官方未发布校验和，这里只比对 Content-Length / ETag / Last-Modified）"
  else
    step "官方 dmg 未更新（Content-Length / ETag / Last-Modified 均与上次一致）"
  fi
}

# python-build-standalone 的资产名带日期标签：先按已知标签探测，再问 GitHub API。
resolve_python_url() {  # <python 版本> <triple>
  local pyver="$1" triple="$2" tag name url found
  # dry-run 不发任何网络请求，只报第一个候选地址。
  if [ "$DRY_RUN" -eq 1 ]; then
    printf 'https://github.com/astral-sh/python-build-standalone/releases/download/%s/cpython-%s+%s-%s-install_only_stripped.tar.gz' \
      "${PBS_TAGS[0]}" "$pyver" "${PBS_TAGS[0]}" "$triple"
    return 0
  fi
  for tag in "${PBS_TAGS[@]}"; do
    name="cpython-${pyver}+${tag}-${triple}-install_only_stripped.tar.gz"
    url="https://github.com/astral-sh/python-build-standalone/releases/download/${tag}/${name}"
    # 代理优先；代理不通就直连试探。
    if curl -fsIL --max-time 25 "$(gh "$url")" >/dev/null 2>&1 \
       || curl -fsIL --max-time 25 "$url" >/dev/null 2>&1; then
      printf '%s' "$url"; return 0
    fi
  done
  # 已知标签都没命中，才去问 GitHub API（代理与直连各试一次）。
  local api='https://api.github.com/repos/astral-sh/python-build-standalone/releases?per_page=8'
  found="$( { curl -fsSL --max-time 40 "$(gh "$api")" 2>/dev/null \
              || curl -fsSL --max-time 40 "$api" 2>/dev/null || true; } \
    | PBS_TRIPLE="$triple" PBS_VER="$pyver" python3 -c '
import json, os, sys
triple, ver = os.environ["PBS_TRIPLE"], os.environ["PBS_VER"]
try:
    releases = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for release in releases:
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.startswith(f"cpython-{ver}+") and triple in name and name.endswith("install_only_stripped.tar.gz"):
            print(asset.get("browser_download_url", ""))
            sys.exit(0)
' || true)"
  [ -n "$found" ] || return 1
  printf '%s' "$found"
}

# --------------------------------------------------------------- dmg 解包 ----
# 注意：本函数的标准输出**只有路径一行**（调用方用 $(dmg_resources) 接收），
# 所有进度/清理信息一律走 stderr——否则日志会被拼进路径里。
dmg_resources() {
  local signature
  signature="$(sha256sum "$DMG" | cut -d' ' -f1)"
  if [ "$(cat "$DMG_DIR/.extracted" 2>/dev/null || true)" != "$signature" ] || [ "$FORCE" -eq 1 ]; then
    [ -n "$SEVENZ" ] || die "缺少 7z（Debian: apt install p7zip-full）"
    step "解包 dmg → $(rel "$DMG_DIR")（约 1 GB，只做一次）" >&2
    DROP_QUIET=1 drop "$DMG_DIR" >&2
    mkdir -p "$DMG_DIR"
    "$SEVENZ" x -y -o"$DMG_DIR" "$DMG" >/dev/null || die "dmg 解包失败: $DMG"
    printf '%s\n' "$signature" > "$DMG_DIR/.extracted"
  fi
  local found
  found="$(find "$DMG_DIR" -maxdepth 5 -type d -path '*.app/Contents/Resources' | head -1)"
  [ -n "$found" ] || die "dmg 里找不到 *.app/Contents/Resources"
  printf '%s' "$found"
}

runtime_json() { python3 -c '
import json, sys
data = json.load(open(sys.argv[1], encoding="utf8"))
print(data["python"], data["node"], data["desktopVersion"], sep="\t")
' "$1"; }

# 读出上游要求的确切版本。非 dry-run 时**只认 dmg 里的 runtime.json**：
# dsh 的 Node/Python/站点包版本是 pinned 在载荷里的，绝不能拿脚本里的兜底值顶上，
# 否则上游换了新 dmg 就会「新 dmg 配旧运行时」。
upstream_versions() {  # → "pyver nodever appver"
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '%s\t%s\t%s\n' "$FALLBACK_PY_VERSION" "$FALLBACK_NODE_VERSION" "0.2.0-rc.2"
    return 0
  fi
  local resources runtime
  resources="$(dmg_resources)"
  runtime="$resources/runtime/primary-runtime/runtime.json"
  [ -f "$runtime" ] || die "dmg 里读不到 $runtime（上游布局变了？）"
  runtime_json "$runtime"
}

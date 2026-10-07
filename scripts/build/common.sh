# Shared helpers; sourced by auto-build.sh.
# ------------------------------------------------------------------ 基础工具 ----
say()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
step() { printf '   %s\n' "$*"; }
warn() { printf '\033[1;33m[警告]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[错误]\033[0m %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
human() { du -sh "$1" 2>/dev/null | cut -f1; }   # -s：目录只输出一行合计
rel() { case "$1" in "$ROOT"/*) printf '%s' "${1#"$ROOT"/}" ;; *) printf '%s' "$1" ;; esac; }

usage() {
  cat <<'EOF'
DeepSeek Harness — Linux 一键构建

用法:
  ./auto-build.sh [选项] [x64|arm64|all]

选项:
  --formats 格式[,格式] appimage / deb / pacman / rpm / all（默认 appimage）
  --electron 模式        bundled / system / both（默认 both）；筛选相应类型的安装包
  --package-jobs N       打包压缩线程数（正整数；默认沿用各格式设置）
  --arch x64|arm64|all   目标架构（默认：本机架构）
  --only 阶段[,阶段]     prepare / tree / package 的子集（默认全跑）
  --proxy URL            自定义 GitHub 加速前缀
  --no-proxy             关闭 GitHub 加速（直连）
  --jobs N               并行下载数（默认 4）
  --store 目录          依赖与解包物的落点（默认仓库根）。指定后 dl/ others/ tools/
                         与打包暂存都放到该目录下，例如 --store /tmp/dsh-store；
                         应用树 out-*/ 与产物 dist/ 仍在仓库根
  --work 目录            AppImage 暂存目录（默认 /tmp/dsh-appimage；给了 --store 则是
                         <store>/work）
  --dmg 路径|URL         使用自备的官方 dmg（URL 会先下到 <store>/others/ 再当本地文件用）
  --force                忽略已存在的下载/中间产物，重新生成
  --clean                成功后清理解包物、pip 缓存和打包暂存；已打包的应用树也删除
  --translucent-sidebar   自动请求桌面模糊，失败回退实色磨砂（构建时选项）
  --opaque-sidebar        不透明实色侧栏（默认；构建时选项）
  --no-verify            跳过应用树自检（默认自检失败即中止）
  --no-sha256            跳过 Electron/Node 的官方 SHA256 比对（不推荐）
  --allow-drift          原生包找不到同版本时允许改用别的版本（默认直接失败）
  --dry-run              只打印将要执行的步骤（零写入，且不发任何网络请求）
  -h, --help

版本策略：Node / Python / 13 个站点包的版本**全部来自 dmg 里的 runtime.json**
（上游 pinned 的那一套），脚本不写死、也不主动升级；原生模块要求**同版本**替换，
找不到就停下。`--dry-run` 里显示的版本只是占位。

默认保留全部缓存、解包物、应用树与打包暂存文件。
--clean 仅在所有阶段成功后清理中间物；失败时保留现场。
下载的 dmg、运行时归档、npm 包、工具与 dist/ 成品始终保留。
仅生成应用树（--only tree）时，即使 --clean 也保留 out-<arch>/。

环境变量: DSH_GH_PROXY DSH_NPM_REGISTRY DSH_NODE_MIRROR DSH_ELECTRON_MIRROR
          DSH_PYPI_MIRROR DSH_ELECTRON_VERSION DSH_DMG_URL DSH_PBS_TAGS DSH_STORE
          DSH_TRANSLUCENT_SIDEBAR
EOF
}

arch_target() { case "$1" in x64) echo x86_64 ;; arm64) echo aarch64 ;; esac; }
arch_node()   { case "$1" in x64) echo linux-x64 ;; arm64) echo linux-arm64 ;; esac; }
arch_triple() { case "$1" in x64) echo x86_64-unknown-linux-gnu ;; arm64) echo aarch64-unknown-linux-gnu ;; esac; }
arch_pypi()   { case "$1" in x64) echo x86_64 ;; arm64) echo aarch64 ;; esac; }

want_phase() { case ",$ONLY," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }
gh() { case "$1" in https://github.com/*|https://raw.githubusercontent.com/*|https://api.github.com/*) printf '%s%s' "$GH_PROXY" "$1" ;; *) printf '%s' "$1" ;; esac; }

# 只删 $ROOT 或暂存目录下的路径：变量为空/指错时不会误伤别处。
# DROP_QUIET=1 时静默删除（调用方自己打印说明）。
drop() {
  local target="$1"
  [ -L "$target" ] && die "拒绝清理符号链接：$target"
  target="$(realpath -m -- "$target")"
  case "$target" in
    "$ROOT"/*|"$STORE"/*|"$WORK_BASE"/*) ;;
    *) die "拒绝删除工作区之外的路径: $target" ;;
  esac
  [ "$DRY_RUN" -eq 1 ] && return 0
  [ -e "$target" ] || return 0
  [ "${DROP_QUIET:-0}" -eq 1 ] || step "清理 $target"
  python3 -c 'import shutil, sys; shutil.rmtree(sys.argv[1])' "$target"
}

# 目录拷贝；可排除 macOS 的 AppleDouble 附加流（7z 解 dmg 时会带出来）。
copy_tree() {
  local src="$1" dest="$2"; shift 2
  mkdir -p "$dest"
  local args=() pattern
  for pattern in "$@"; do args+=("--exclude=$pattern"); done
  ( cd "$src" && tar "${args[@]}" -cf - . ) | ( cd "$dest" && tar -xf - )
}

# Explicit cleanup runs only after every selected phase succeeds.
clean_after_success() {
  if [ "$CLEAN" -eq 0 ]; then
    step "默认保留全部缓存、解包物、应用树与打包暂存（--clean 可在成功后清理）"
    return 0
  fi
  say "收尾清理（--clean；下载依赖、工具与成品保留）"
  local arch target
  local targets=("$DMG_DIR" "$DL/pip-cache" "$TOOLS/.appimagetool-extract")
  for arch in "${ARCHES[@]}"; do
    targets+=("$WORK_BASE/$arch" "$DL/npm/node-pty-$arch-staging")
    if want_phase package; then
      targets+=("$ROOT/out-$arch")
    elif want_phase tree; then
      targets+=("$ROOT/out-$arch/resources/app/dsh/node_modules/.sharp-native-backup")
    fi
  done
  for target in "${targets[@]}"; do
    if [ "$DRY_RUN" -eq 1 ]; then
      step "[dry-run] 成功后清理 $target"
    else
      drop "$target"
    fi
  done
}

# A requested package thread count takes precedence over format defaults.
package_threads() { printf '%s' "${PACKAGE_JOBS:-$1}"; }
package_xz_options() {
  if [ -n "$PACKAGE_JOBS" ]; then
    printf '%s' "${XZ_OPT:-} -T$PACKAGE_JOBS"
  else
    printf '%s' "${XZ_OPT:--T2}"
  fi
}

want_format() { case ",$FORMATS," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }

# Fail before downloads/staging when a selected distribution tool is unavailable.
check_package_tools() {
  local tools=(python3 tar xz sha256sum) missing=() tool
  want_format deb && tools+=(ar) || true
  want_format pacman && tools+=(bsdtar gzip zstd) || true
  want_format rpm && tools+=(rpmbuild) || true
  for tool in "${tools[@]}"; do have "$tool" || missing+=("$tool"); done
  if [ "${#missing[@]}" -gt 0 ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      warn "实际打包需要命令：${missing[*]}（Debian 的 rpm 提供 rpmbuild，libarchive-tools 提供 bsdtar）"
    else
      die "缺少打包命令：${missing[*]}；请自行安装（Debian: rpm / libarchive-tools / zstd / binutils）"
    fi
  fi
}

package_version() {
  python3 - "$ROOT/out-$1/resources/runtime/primary-runtime/runtime.json" <<'PYEOF'
import json, re, sys
with open(sys.argv[1], encoding='utf8') as handle:
    version = json.load(handle)['desktopVersion']
if not isinstance(version, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)*(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?', version):
    raise SystemExit(f'不支持的应用版本：{version!r}')
print(version)
PYEOF
}

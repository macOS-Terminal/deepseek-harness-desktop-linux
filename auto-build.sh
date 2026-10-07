#!/usr/bin/env bash
# =============================================================================
# DeepSeek Harness — Linux AppImage 一键构建（准备 → 生成应用树 → 打包）
#
#   ./auto-build.sh                    # x86_64：全部阶段
#   ./auto-build.sh --arch all         # x86_64 + aarch64
#   ./auto-build.sh --only prepare     # 只下载外部依赖
#   ./auto-build.sh --help
#
# 国内网络策略（均可用环境变量覆盖）：
#   * GitHub 资源（Electron / python-build-standalone / AppImage runtime）
#     默认经 https://gh-proxy.org/ 加速，--no-proxy 改直连；
#   * 官方 dmg 直接取自 download.deepseek.com，失败才回退 GitHub 镜像；
#   * Node 官方 tar.xz 取自 npmmirror 二进制镜像，npm 包取自 registry.npmmirror.com，
#     pip 交叉安装（下载 manylinux 轮子）取自清华 TUNA。
#
# 幂等：已下载的文件与已解包的 dmg 会复用；--force 强制重来。
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# ----------------------------------------------------------------- 可调参数 ----
GH_PROXY="${DSH_GH_PROXY-https://gh-proxy.org/}"          # GitHub 加速前缀，空=直连
NPM_REGISTRY="${DSH_NPM_REGISTRY:-https://registry.npmmirror.com}"
NPM_FALLBACK="${DSH_NPM_FALLBACK:-https://registry.npmjs.org}"
NODE_MIRROR="${DSH_NODE_MIRROR:-https://registry.npmmirror.com/-/binary/node}"
ELECTRON_MIRROR="${DSH_ELECTRON_MIRROR:-https://registry.npmmirror.com/-/binary/electron}"
PYPI_MIRROR="${DSH_PYPI_MIRROR:-https://pypi.tuna.tsinghua.edu.cn/simple}"
PBS_TAGS=(${DSH_PBS_TAGS:-20260924 20260901 20260825 20260812})   # python-build-standalone 标签，按序探测
ELECTRON_VERSION="${DSH_ELECTRON_VERSION:-44.4.5}"        # ≥44.4.5：44.0.0 有 Linux 托盘回归
DMG_OFFICIAL="${DSH_DMG_URL:-https://download.deepseek.com/desktop/dsh-latest-macos-arm64.dmg}"
DMG_MIRROR_TAG="${DSH_DMG_MIRROR_TAG:-v0.2.0-rc.2}"
DMG_MIRROR="${DSH_DMG_MIRROR:-https://github.com/LinJianKun/deepseek-harness-desktop-mirror/releases/download}"
RUNTIME_REPO="${DSH_RUNTIME_REPO:-https://github.com/AppImage/type2-runtime/releases/download/continuous}"
APPIMAGETOOL_BASE="${DSH_APPIMAGETOOL_BASE:-https://github.com/AppImage/appimagetool/releases/download/continuous}"
FALLBACK_NODE_VERSION="${DSH_NODE_VERSION:-24.21.0}"      # 仅 --dry-run 用来展示计划
FALLBACK_PY_VERSION="${DSH_PY_VERSION:-3.12.14}"          # （真实构建一律以 dmg 的 runtime.json 为准）

# 依赖与解包物的落点。默认全在仓库根（dl/ others/ tools/）；
# --store DIR 可整体搬到别处（例如 /tmp/dsh-store），解析完参数后由 apply_store() 重算。
STORE="${DSH_STORE:-$ROOT}"
DMG_GIVEN=""
DL="$STORE/dl"; OTHERS="$STORE/others"; TOOLS="$STORE/tools"
DMG="$OTHERS/dsh-latest-macos-arm64.dmg"
DMG_DIR="$OTHERS/dmg"

ARCHES=(); ONLY="prepare,tree,package"; FORCE=0; CLEAN=0; JOBS=4
WORK=""; VERIFY=1; DRY_RUN=0; CHECK_SHA=1; ALLOW_DRIFT=0
DMG_URL_OVERRIDE=""
FORMATS=appimage
ELECTRON_MODE=both
PACKAGE_JOBS=""
TRANSLUCENT_SIDEBAR="${DSH_TRANSLUCENT_SIDEBAR:-0}"
case "$TRANSLUCENT_SIDEBAR" in
  1|true|yes|on) TRANSLUCENT_SIDEBAR=1 ;;
  0|false|no|off) TRANSLUCENT_SIDEBAR=0 ;;
  *) die "DSH_TRANSLUCENT_SIDEBAR 需要 0/1 或 true/false" ;;
esac

for module in common download prepare tree package native-packages; do
  source "$ROOT/scripts/build/$module.sh"
done

while [ $# -gt 0 ]; do
  case "$1" in
    --translucent-sidebar) TRANSLUCENT_SIDEBAR=1; shift ;;
    --opaque-sidebar) TRANSLUCENT_SIDEBAR=0; shift ;;
    --electron) ELECTRON_MODE="${2:?--electron 需要一个值}"; shift 2 ;;
    --package-jobs) PACKAGE_JOBS="${2:?--package-jobs 需要一个值}"; shift 2 ;;
    --formats)  FORMATS="${2:?--formats 需要一个值}"; shift 2 ;;
    --arch)     ARCHES+=("${2:?--arch 需要一个值}"); shift 2 ;;
    --only)     ONLY="${2:?--only 需要一个值}"; shift 2 ;;
    --proxy)    GH_PROXY="${2:?--proxy 需要一个值}"; shift 2 ;;
    --no-proxy) GH_PROXY=""; shift ;;
    --jobs)     JOBS="${2:?--jobs 需要一个值}"; shift 2 ;;
    --store)    STORE="${2:?--store 需要一个值}"; shift 2 ;;
    --work)     WORK="${2:?--work 需要一个值}"; shift 2 ;;
    --dmg)      DMG_GIVEN="${2:?--dmg 需要一个值}"; shift 2 ;;
    --force)    FORCE=1; shift ;;
    --clean)    CLEAN=1; shift ;;
    --no-verify) VERIFY=0; shift ;;
    --no-sha256) CHECK_SHA=0; shift ;;
    --allow-drift) ALLOW_DRIFT=1; shift ;;
    --dry-run)  DRY_RUN=1; shift ;;
    -h|--help)  usage; exit 0 ;;
    -*)         die "未知选项: $1（--help 查看用法）" ;;
    *)          ARCHES+=("$1"); shift ;;
  esac
done

case "$(uname -m)" in
  x86_64|amd64) HOST_ARCH=x64 ;;
  aarch64|arm64) HOST_ARCH=arm64 ;;
  *) die "不支持的本机架构：$(uname -m)" ;;
esac
[ "${#ARCHES[@]}" -gt 0 ] || ARCHES=("$HOST_ARCH")
EXPANDED=()
for arch in "${ARCHES[@]}"; do
  case "$arch" in
    all) EXPANDED+=(x64 arm64) ;;
    x64|arm64) EXPANDED+=("$arch") ;;
    *) die "未知架构: $arch" ;;
  esac
done
ARCHES=()
for arch in "${EXPANDED[@]}"; do
  case " ${ARCHES[*]-} " in *" $arch "*) ;; *) ARCHES+=("$arch") ;; esac
done
[[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || die "--jobs 需要正整数"
if [ -n "$PACKAGE_JOBS" ]; then
  [[ "$PACKAGE_JOBS" =~ ^[1-9][0-9]*$ ]] || die "--package-jobs 需要正整数"
fi
case "$ELECTRON_MODE" in bundled|system|both) ;; *) die "--electron 需要 bundled / system / both" ;; esac
IFS=, read -r -a phases <<<"$ONLY"
[ -n "$ONLY" ] || die "--only 不能为空"
case "$ONLY" in ,*|*,|*,,*) die "--only 包含空阶段" ;; esac
for phase in "${phases[@]}"; do
  case "$phase" in prepare|tree|package) ;; *) die "未知阶段：$phase" ;; esac
done

IFS=, read -r -a requested_formats <<<"$FORMATS"
case "$FORMATS" in ''|,*|*,|*,,*) die "--formats 包含空格式" ;; esac
selected_formats=()
for format in "${requested_formats[@]}"; do
  case "$format" in
    all) selected_formats+=(appimage deb pacman rpm) ;;
    appimage|deb|pacman|rpm) selected_formats+=("$format") ;;
    *) die "未知打包格式：$format" ;;
  esac
done
# Filter unsupported format/mode pairs before downloads or tool checks.
FORMATS=,
for format in "${selected_formats[@]}"; do
  case "$format:$ELECTRON_MODE" in
    appimage:system|rpm:system|pacman:bundled) continue ;;
  esac
  case "$FORMATS" in *",$format,"*) ;; *) FORMATS+="$format," ;; esac
done
FORMATS="${FORMATS#,}"; FORMATS="${FORMATS%,}"
[ -n "$FORMATS" ] || die "所选格式不提供 $ELECTRON_MODE 包（AppImage/RPM: bundled；pacman: system；deb: 两者）"
if want_phase package; then check_package_tools; fi

# --store：把依赖下载（dl/）、官方 dmg 与解包物（others/）、工具（tools/）整体搬到别处。
# 这个脚本会删除 store 下的解包物，所以先拒绝系统目录与相对路径。
apply_store() {
  case "$STORE" in
    /*) ;;
    *) die "--store 需要绝对路径：$STORE" ;;
  esac
  STORE="$(realpath -m -- "$STORE")"
  case "$STORE" in
    /|/usr|/usr/*|/etc|/etc/*|/bin|/bin/*|/sbin|/sbin/*|/lib|/lib/*|/lib64|/lib64/*|\
    /boot|/boot/*|/var|/var/*|/opt|/opt/*|/proc|/proc/*|/sys|/sys/*|/dev|/dev/*)
      die "--store 不能指向系统目录：$STORE" ;;
  esac
  DL="$STORE/dl"; OTHERS="$STORE/others"; TOOLS="$STORE/tools"
  DMG="$OTHERS/dsh-latest-macos-arm64.dmg"
  DMG_DIR="$OTHERS/dmg"
}
apply_store
# --dmg 既接受本地文件，也接受 URL（URL 会先下到 store 的 others/ 下再当作本地文件用）。
if [ -n "$DMG_GIVEN" ]; then
  case "$DMG_GIVEN" in
    http://*|https://*)
      DMG_URL_OVERRIDE="$DMG_GIVEN"
      local_name="$(basename "${DMG_GIVEN%%\?*}")"
      case "$local_name" in ''|*/*) local_name="dsh-custom.dmg" ;; esac
      DMG="$OTHERS/$local_name"
      ;;
    *) DMG="$(realpath -m -- "$DMG_GIVEN")" ;;
  esac
fi
if [ -n "$WORK" ]; then
  case "$WORK" in /*) ;; *) die "--work 需要绝对路径：$WORK" ;; esac
  WORK_BASE="$(realpath -m -- "$WORK")"
  case "$WORK_BASE" in
    /|/usr|/usr/*|/etc|/etc/*|/bin|/bin/*|/sbin|/sbin/*|/lib|/lib/*|/lib64|/lib64/*|/boot|/boot/*|/var|/var/*|/opt|/opt/*|/proc|/proc/*|/sys|/sys/*|/dev|/dev/*)
      die "--work 不能指向系统目录：$WORK_BASE" ;;
  esac
elif [ "$STORE" != "$ROOT" ]; then
  WORK_BASE="$STORE/work"
else
  WORK_BASE="/tmp/dsh-appimage"
fi

export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$DL/pip-cache}"
# --dry-run 承诺零写入，连目录都不建。
[ "$DRY_RUN" -eq 1 ] || mkdir -p "$DL" "$OTHERS" "$TOOLS" "$PIP_CACHE_DIR"

SEVENZ="$(command -v 7z || command -v 7za || true)"

# =================================================================== 主流程 ==
say "DeepSeek Harness — Linux 构建"
step "仓库:   $ROOT"
step "架构:   ${ARCHES[*]}（host=$HOST_ARCH）"
step "阶段:   $ONLY"
step "格式:   $FORMATS"
step "Electron: $ELECTRON_MODE"
step "打包线程: ${PACKAGE_JOBS:-各格式默认}"
step "侧栏:   $([ "$TRANSLUCENT_SIDEBAR" -eq 1 ] && echo 自动系统模糊或实色磨砂回退 || echo 不透明实色)"
step "加速:   ${GH_PROXY:-（直连 GitHub）}"
step "暂存:   $WORK_BASE/<arch>"

if want_phase prepare; then phase_prepare; fi
for arch in "${ARCHES[@]}"; do
  if want_phase tree; then
    build_tree "$arch"
    verify_tree "$arch"
  fi
done
for arch in "${ARCHES[@]}"; do
  if want_phase package; then
    if want_format appimage; then build_appimage "$arch"; fi
    if want_format deb || want_format pacman || want_format rpm; then build_native_packages "$arch"; fi
  fi
done

clean_after_success

say "全部完成"
if [ -d "$ROOT/dist" ]; then ls -la "$ROOT/dist"; fi
step "产物在 dist/ 下，校验：cd dist && sha256sum -c *.sha256"
if want_format appimage; then
  cat <<EOF
运行 AppImage：chmod +x dist/DeepSeek-Harness-*.AppImage
./dist/DeepSeek-Harness-*.AppImage
需要 FUSE；没有 FUSE 时加 --appimage-extract-and-run。
EOF
fi

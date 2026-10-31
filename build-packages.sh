#!/bin/bash
# Package one DeepSeek Harness Linux tree into every supported distribution format.
#
#   build-packages.sh <x64|arm64>
#
# Notes for this host:
#   * the workspace lives on NTFS (fuseblk), which reports every file as 0777 and
#     ignores chmod, so staging happens on tmpfs and permissions are restored from
#     file content before archiving;
#   * archives record root:root ownership regardless of the build user.
set -euo pipefail
B="$(cd "$(dirname "$0")" && pwd)"
ARCH="${1:?用法: build-packages.sh <x64|arm64>}"

case "$ARCH" in
  x64)   TREE=out-x64;   DEBARCH=amd64;   PKGARCH=x86_64;  RPMARCH=x86_64;  AIARCH=x86_64 ;;
  arm64) TREE=out-arm64; DEBARCH=arm64;   PKGARCH=aarch64; RPMARCH=aarch64; AIARCH=aarch64 ;;
  *) echo "未知架构: $ARCH（应为 x64 或 arm64）" >&2; exit 1 ;;
esac
SRC="$B/$TREE"

# 上游版本号：优先取构建树里 runtime.json 的 desktopVersion（应用载荷的真实版本），
# 环境变量 DSH_VER 可显式覆盖。之前硬编码在脚本里，上游升版后忘了改就会打错包名
# —— rc.5 的构建就发生过一次（产物叫 rc.5 而仓库脚本仍写 rc.2）。
RUNTIME_JSON="$SRC/resources/runtime/primary-runtime/runtime.json"
if [ -n "${DSH_VER:-}" ]; then
  VER="$DSH_VER"
elif [ -f "$RUNTIME_JSON" ]; then
  VER=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('desktopVersion',''))" "$RUNTIME_JSON" 2>/dev/null || true)
fi
[ -n "${VER:-}" ] || { echo "无法确定上游版本：$RUNTIME_JSON 缺失或无 desktopVersion（可用 DSH_VER=x.y.z 覆盖）" >&2; exit 1; }
VER_PKG="${VER/-/_}"   # 0.2.1-rc.5 -> 0.2.1_rc.5（与历史产物命名一致）

WORK="/tmp/dsh-build-$ARCH"          # tmpfs: real POSIX permissions, writable
OUT="$B/dist"
rm -rf "$WORK"; mkdir -p "$OUT" "$WORK"
say() { printf '\n== %s ==\n' "$*"; }

# rpm 的 Version/Release 需与上游一致：0.2.1-rc.5 -> Version 0.2.1 / Release 0.rc5
RPM_VERSION="${VER%%-*}"          # 0.2.1
RPM_RELEASE_RAW="${VER#*-}"       # rc.5
RPM_RELEASE="0.${RPM_RELEASE_RAW//./}"  # 0.rc5（rpm 不接受 rc.5 里的点）
RPMVER="${RPM_VERSION}-${RPM_RELEASE}"   # 0.2.1-0.rc5（文件名里再拼架构）

# Restore sane modes: NTFS reports 0777 for everything, so infer from content.
# 精简运行时冗余（详见 trim-app-tree.sh）。每次打包复制后调用，
# 保证四种产物格式都得到同样裁剪。
trim_tree() {
  local target="$1"
  local script="$B/trim-app-tree.sh"
  [ -x "$script" ] || return 0
  # 只裁剪含 resources/ 的目录
  if [ -d "$target/resources" ]; then
    "$script" "$target" >/dev/null 2>&1 || echo "  ! 裁剪跳过（$target）" >&2
  fi
}

normalize_modes() { python3 - "$1" <<'PYEOF'
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

# ---------------------------------------------------------------- metadata ----
META="$WORK/meta"; mkdir -p "$META"
cat > "$META/deepseek-harness.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=DeepSeek Harness Desktop
Name[zh_CN]=DeepSeek Harness 桌面客户端
GenericName=AI Development Harness
GenericName[zh_CN]=AI 开发工具
Comment=Run the DeepSeek Harness desktop workspace
Comment[zh_CN]=运行 DeepSeek Harness 桌面工作区
Exec=deepseek-harness %U
Icon=deepseek-harness
Terminal=false
Categories=Development;
Keywords=DeepSeek;Harness;AI;
Keywords[zh_CN]=DeepSeek;Harness;AI;开发;
StartupWMClass=deepseek-harness
StartupNotify=true
MimeType=x-scheme-handler/dsh;
EOF
cp "$B/icons/deepseek-harness.png" "$META/"
for s in 16 24 32 48 64 128 256 512; do
  mkdir -p "$META/icons/${s}x${s}"
  cp "$B/icons/${s}x${s}/deepseek-harness.png" "$META/icons/${s}x${s}/"
done

# Tray icon for the Linux build.
#
# Upstream's packaged branch reads `tray.ico` from the resources root, but the
# upstream dmg ships no such file, and nativeImage.createFromPath() on a missing
# file yields an EMPTY image rather than throwing — so the tray is created and
# renders nothing. Ship a real 32x32 PNG as `tray.png` in the resources root of
# each build tree so the tray actually shows an icon.
for tree in out-x64 out-arm64; do
  [ -d "$B/$tree/resources" ] || continue
  cp "$B/icons/32x32/deepseek-harness.png" "$B/$tree/resources/tray.png"
  printf '  · %s/resources/tray.png\n' "$tree"
done

# Launcher used by the system-Electron variants.
cat > "$META/launcher" <<'LAUNCH'
#!/bin/sh
# DeepSeek Harness launcher (system-wide Electron build).
set -e
APP_DIR=/usr/lib/deepseek-harness/resources
find_electron() {
  for c in electron electron44 electron43 electron42 electron41 electron40 electron39 nodejs-electron; do
    command -v "$c" >/dev/null 2>&1 && { command -v "$c"; return 0; }
  done
  for p in /usr/lib/electron44/electron /usr/lib/electron/electron \
           /usr/lib64/electron/electron /usr/lib/nodejs-electron/electron \
           /opt/electron/electron; do
    [ -x "$p" ] && { echo "$p"; return 0; }
  done
  return 1
}
ELECTRON_BIN=$(find_electron) || {
  echo "deepseek-harness: 未找到 Electron 运行时。" >&2
  echo "Arch: 安装 electron；Fedora/openSUSE: 安装 nodejs-electron 或 electron。" >&2
  echo "Debian/Ubuntu 官方仓库无 electron 包，请安装第三方 electron 包或改用 bundled 版本。" >&2
  exit 1
}
export DSH_DESKTOP_FORCE_PACKAGED=1
export DSH_DESKTOP_RESOURCES_DIR="$APP_DIR"
export DSH_DESKTOP_NODE_EXECUTABLE="$ELECTRON_BIN"
exec "$ELECTRON_BIN" "$APP_DIR/app" "$@"
LAUNCH
chmod 755 "$META/launcher"

# -------------------------------------------------------------------- deb ----
# Only the bundled build is shipped. A system-Electron variant would need a
# distribution electron package, and Debian/Ubuntu ship none, so it could not
# be installed there without a third-party source. Keeping the function
# single-purpose also removes the optional-field handling that used to emit a
# blank line into the control file (issue #1).
build_deb() {
  local d="$WORK/deb"
  local deps=""
  rm -rf "$d"; mkdir -p "$d/control" "$d/data"
  local D="$d/data"
  mkdir -p "$D/usr/lib/deepseek-harness" "$D/usr/bin" "$D/usr/share/applications" "$D/usr/share/icons/hicolor"
  cp -a "$SRC/." "$D/usr/lib/deepseek-harness/"
  normalize_modes "$D/usr/lib/deepseek-harness"
  trim_tree "$D/usr/lib/deepseek-harness"
  printf '#!/bin/sh\nexec /usr/lib/deepseek-harness/deepseek-harness "$@"\n' > "$D/usr/bin/deepseek-harness"
  deps="libgtk-3-0, libnotify4, libnss3, libxss1, libxtst6, xdg-utils, libatspi2.0-0, libuuid1, libsecret-1-0, libgbm1, libasound2, libdrm2, libxkbcommon0, libxcomposite1, libxdamage1, libxfixes3, libxrandr2, libcups2, libx11-xcb1, libxcb-dri3-0"
  chmod 755 "$D/usr/bin/deepseek-harness"
  cp "$B/icons/deepseek-harness.desktop" "$D/usr/share/applications/"
  for s in 16 24 32 48 64 128 256 512; do
    mkdir -p "$D/usr/share/icons/hicolor/${s}x${s}/apps"
    cp "$META/icons/${s}x${s}/deepseek-harness.png" "$D/usr/share/icons/hicolor/${s}x${s}/apps/"
  done
  local size; size=$(du -sk "$D" | cut -f1)
  cat > "$d/control/control" <<EOF
Package: deepseek-harness
Version: $VER
Section: utils
Priority: optional
Architecture: $DEBARCH
Maintainer: DeepSeek Harness Linux port <noreply@localhost>
Installed-Size: $size
Depends: $deps
Homepage: https://harness.deepseek.com
Description: DeepSeek Harness desktop client
 DeepSeek Harness desktop application repackaged for Linux.
 This build bundles its own Electron runtime.
EOF
  cat > "$d/control/postinst" <<'P'
#!/bin/sh
set -e
if [ -f /usr/lib/deepseek-harness/chrome-sandbox ]; then
  chown root:root /usr/lib/deepseek-harness/chrome-sandbox 2>/dev/null || true
  chmod 4755 /usr/lib/deepseek-harness/chrome-sandbox 2>/dev/null || true
fi
update-desktop-database -q 2>/dev/null || true
gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
exit 0
P
  cat > "$d/control/postrm" <<'P'
#!/bin/sh
set -e
update-desktop-database -q 2>/dev/null || true
gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
exit 0
P
  chmod 755 "$d/control/postinst" "$d/control/postrm"
  echo "2.0" > "$d/debian-binary"
  # zstd 压缩的 deb。Ubuntu 21.04+（dpkg 1.20.9ubuntu1+）与 Debian 12+ 支持；
  # Debian 11 及更早不支持。详见 docs/ARTIFACTS.md 的「系统要求」。
  ( cd "$d" && tar --owner=0 --group=0 --numeric-owner -c -C data . \
      | zstd $ZSTD_OPTS -q -o data.tar.zst \
    && tar --owner=0 --group=0 --numeric-owner -c -C control . \
      | zstd $ZSTD_OPTS -q -o control.tar.zst \
    && ar rc "$OUT/deepseek-harness_${VER}_${DEBARCH}.bundled.deb" \
         debian-binary control.tar.zst data.tar.zst )
  echo "  ✓ deb: $(du -h "$OUT/deepseek-harness_${VER}_${DEBARCH}.bundled.deb" | cut -f1)"
  rm -rf "$d"; sync
}

# -------------------------------------------------------------------- rpm ----
build_rpm() {
  local top="$WORK/rpmbuild"
  rm -rf "$top"; mkdir -p "$top"/{BUILD,RPMS,SOURCES,SPECS,SRPMS,tmp,BUILDROOT}
  cp -a "$SRC" "$top/SOURCES/app"
  normalize_modes "$top/SOURCES/app"
  trim_tree "$top/SOURCES/app"
  cp "$B/icons/deepseek-harness.desktop" "$top/SOURCES/"
  cp -a "$META/icons" "$top/SOURCES/icons"
  cat > "$top/SPECS/deepseek-harness.spec" <<SPEC
Name:           deepseek-harness
Version:        ${RPM_VERSION}
Release:        ${RPM_RELEASE}%{?dist}
Summary:        DeepSeek Harness desktop client
License:        MIT
URL:            https://harness.deepseek.com
BuildArch:      $RPMARCH
AutoReqProv:    no
# 禁止 rpmbuild 触碰厂商预编译产物（python/node/原生模块）
%global __os_install_post %{nil}
%global __strip /bin/true
%global __brp_strip /bin/true
Requires:       gtk3, nss, libXScrnSaver, libXtst, xdg-utils, at-spi2-atk, libuuid,
Requires:       libsecret, mesa-libgbm, alsa-lib, libdrm, libxkbcommon,
Requires:       libXcomposite, libXdamage, libXfixes, libXrandr, cups-libs, libxcb
%description
DeepSeek Harness desktop application repackaged for Linux.
This build bundles its own Electron 44.4.5 runtime.
%prep
%build
%install
mkdir -p %{buildroot}/usr/lib/deepseek-harness
cp -a %{_sourcedir}/app/. %{buildroot}/usr/lib/deepseek-harness/
mkdir -p %{buildroot}/usr/bin
printf '#!/bin/sh\nexec /usr/lib/deepseek-harness/deepseek-harness "\$@"\n' > %{buildroot}/usr/bin/deepseek-harness
chmod 755 %{buildroot}/usr/bin/deepseek-harness
mkdir -p %{buildroot}/usr/share/applications
cp %{_sourcedir}/deepseek-harness.desktop %{buildroot}/usr/share/applications/
for s in 16 24 32 48 64 128 256 512; do
  mkdir -p %{buildroot}/usr/share/icons/hicolor/\${s}x\${s}/apps
  cp %{_sourcedir}/icons/\${s}x\${s}/deepseek-harness.png %{buildroot}/usr/share/icons/hicolor/\${s}x\${s}/apps/
done
%files
%defattr(-,root,root,-)
/usr/lib/deepseek-harness
%exclude /usr/lib/deepseek-harness/chrome-sandbox
/usr/bin/deepseek-harness
/usr/share/applications/deepseek-harness.desktop
/usr/share/icons/hicolor/*/apps/deepseek-harness.png
%attr(4755,root,root) /usr/lib/deepseek-harness/chrome-sandbox
%post
update-desktop-database -q 2>/dev/null || true
gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
%postun
update-desktop-database -q 2>/dev/null || true
gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
SPEC
  local -a rc=()
  if [ "$RPMARCH" = aarch64 ]; then
    # x86_64 hosts refuse aarch64 targets unless the compat table allows it; this is
    # a pure repack of prebuilt payload, so widening the table is safe.
    local localrc="$top/rpmrc-local"
    cp /usr/lib/rpm/rpmrc "$localrc"
    cat >> "$localrc" <<'EOF'
buildarch_compat: x86_64: aarch64 noarch
arch_compat: x86_64: aarch64
EOF
    rc=(--rcfile /usr/lib/rpm/rpmrc --rcfile "$localrc")
  fi
  TMPDIR="$top/tmp" rpmbuild "${rc[@]}" --define "_topdir $top" --define "_tmppath $top/tmp" \
    --define "_binary_payload w19.zstdio" --target "${RPMARCH}-linux" -bb "$top/SPECS/deepseek-harness.spec" \
    >"$WORK/rpm.log" 2>&1 || { tail -20 "$WORK/rpm.log"; return 1; }
  local built; built=$(find "$top/RPMS" -name '*.rpm' | head -1)
  cp "$built" "$OUT/deepseek-harness-${RPMVER}.${RPMARCH}.rpm"
  echo "  ✓ rpm: $(du -h "$OUT/deepseek-harness-${RPMVER}.${RPMARCH}.rpm" | cut -f1)"
  rm -rf "$top"; sync
}

# ------------------------------------------------------------------- Arch ----
build_pkgtar() {
  local r="$WORK/pkgroot"
  rm -rf "$r"; mkdir -p "$r/usr/lib/deepseek-harness" "$r/usr/bin" \
    "$r/usr/share/applications" "$r/usr/share/icons/hicolor"
  cp -a "$SRC/resources" "$r/usr/lib/deepseek-harness/resources"
  normalize_modes "$r/usr/lib/deepseek-harness"
  trim_tree "$r/usr/lib/deepseek-harness"
  rm -f "$r/usr/lib/deepseek-harness/resources/app-update.yml"
  cp "$META/launcher" "$r/usr/bin/deepseek-harness"
  chmod 755 "$r/usr/bin/deepseek-harness"
  cp "$B/icons/deepseek-harness.desktop" "$r/usr/share/applications/"
  for s in 16 24 32 48 64 128 256 512; do
    mkdir -p "$r/usr/share/icons/hicolor/${s}x${s}/apps"
    cp "$META/icons/${s}x${s}/deepseek-harness.png" "$r/usr/share/icons/hicolor/${s}x${s}/apps/"
  done
  local size; size=$(du -sb "$r" | cut -f1)
  cat > "$r/.PKGINFO" <<EOF
pkgname = deepseek-harness-desktop
pkgbase = deepseek-harness-desktop
pkgver = ${VER_PKG}-1
pkgdesc = DeepSeek Harness desktop client (system-wide Electron build)
url = https://harness.deepseek.com
builddate = $(date +%s)
packager = DeepSeek Harness Linux port
size = $size
arch = $PKGARCH
license = MIT
depend = electron
EOF
  cat > "$r/.INSTALL" <<'EOF'
post_install() {
  update-desktop-database -q 2>/dev/null || true
  gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
  if [ -f /usr/lib/deepseek-harness/chrome-sandbox ]; then
    chmod 4755 /usr/lib/deepseek-harness/chrome-sandbox 2>/dev/null || true
  fi
}
post_upgrade() { post_install; }
post_remove() {
  update-desktop-database -q 2>/dev/null || true
  gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
}
EOF
  ( cd "$r" && bsdtar -cf .MTREE --format=mtree --uid 0 --gid 0 --numeric-owner \
      --options='!all,use-set,type,uid,gid,mode,size,md5,time,link' .PKGINFO .INSTALL usr \
    && gzip -9 -f .MTREE )
  local name="deepseek-harness-desktop-${VER_PKG}-1-${PKGARCH}.pkg.tar.zst"
  ( cd "$r" && tar --owner=0 --group=0 --numeric-owner --sort=name -cf - .PKGINFO .INSTALL .MTREE.gz usr ) \
    | zstd $ZSTD_OPTS -q -o "$OUT/$name" -f
  echo "  ✓ pkg.tar.zst: $(du -h "$OUT/$name" | cut -f1)"
  rm -rf "$r"; sync
}

# --------------------------------------------------------------- AppImage ----
build_appimage() {
  local A="$WORK/DeepSeek-Harness.AppDir"
  rm -rf "$A" "$WORK/app.squashfs"; mkdir -p "$A"
  cp -a "$SRC/." "$A/"
  normalize_modes "$A"
  trim_tree "$A"
  mkdir -p "$A/usr/share/applications" "$A/usr/share/icons/hicolor"
  cp "$B/icons/deepseek-harness.desktop" "$A/usr/share/applications/"
  cp "$B/icons/deepseek-harness.desktop" "$A/deepseek-harness.desktop"
  cp "$META/deepseek-harness.png" "$A/deepseek-harness.png"
  cp "$META/deepseek-harness.png" "$A/.DirIcon"
  for s in 16 24 32 48 64 128 256 512; do
    mkdir -p "$A/usr/share/icons/hicolor/${s}x${s}/apps"
    cp "$META/icons/${s}x${s}/deepseek-harness.png" "$A/usr/share/icons/hicolor/${s}x${s}/apps/"
  done
  printf '#!/bin/sh\nHERE="$(dirname "$(readlink -f "$0")")"\nexec "$HERE/deepseek-harness" "$@"\n' > "$A/AppRun"
  chmod 755 "$A/AppRun"
  # squashfs 的 zstd 用 1M 块 + level 19；-Xdict-size 提高跨块去重效果。
  "$B/tools/usr/bin/mksquashfs" "$A" "$WORK/app.squashfs" -root-owned -noappend \
    -comp zstd -Xcompression-level "$ZSTD_LEVEL" -Xdict-size 100% -b 1M -processors 0 >/dev/null 2>&1
  cat "$B/tools/runtime-$AIARCH" "$WORK/app.squashfs" > "$OUT/DeepSeek-Harness-${VER}-${AIARCH}.AppImage"
  chmod 755 "$OUT/DeepSeek-Harness-${VER}-${AIARCH}.AppImage"
  echo "  ✓ AppImage: $(du -h "$OUT/DeepSeek-Harness-${VER}-${AIARCH}.AppImage" | cut -f1)"
  rm -rf "$A" "$WORK/app.squashfs"; sync
}

say "构建 $ARCH 全部格式 (工作区: $WORK)"
# Only the bundled deb is shipped: the system variant depends on a
# distribution Electron package, and Debian/Ubuntu ship none, so it could not be
# installed there without a third-party source. The bundled build is
# self-contained and is what the release notes point users at.
build_deb
build_pkgtar
build_rpm
build_appimage
say "完成 $ARCH"

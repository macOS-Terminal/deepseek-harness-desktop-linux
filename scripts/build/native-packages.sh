# Distribution package builders, adapted from the original build-packages.sh.
# Shared with both CLI entry points; retain staging unless --clean is requested.
write_package_checksum() {
  (cd "$OUT" && sha256sum "$1" | tee "$1.sha256")
}

build_native_packages() {
  local arch="$1"
  local B="$ROOT" SRC="$ROOT/out-$1" OUT="$ROOT/dist"
  local WORK="$WORK_BASE/$1/packages" META="$WORK_BASE/$1/packages/meta"
  local DEBARCH PKGARCH RPMARCH
  case "$arch" in
    x64) DEBARCH=amd64; PKGARCH=x86_64; RPMARCH=x86_64 ;;
    arm64) DEBARCH=arm64; PKGARCH=aarch64; RPMARCH=aarch64 ;;
  esac
  if [ "$DRY_RUN" -eq 1 ]; then
    want_format deb && step "[dry-run] 打包 deb（bundled + system，$DEBARCH）" || true
    want_format pacman && step "[dry-run] 打包 pacman（pkg.tar.zst，$PKGARCH）" || true
    want_format rpm && step "[dry-run] 打包 rpm（$RPMARCH）" || true
    return 0
  fi
  [ -d "$SRC" ] || die "缺少应用树 $SRC（先跑 --only tree）"
  local VER VER_PKG RPM_VERSION RPM_RELEASE PACKAGED_ELECTRON_VERSION
  VER="$(package_version "$arch")"
  VER_PKG="${VER//-/_}"
  RPM_VERSION="${VER%%-*}"
  if [[ "$VER" == *-* ]]; then RPM_RELEASE="0.${VER#*-}.1"; else RPM_RELEASE=1; fi
  RPM_RELEASE="${RPM_RELEASE//-/.}"
  PACKAGED_ELECTRON_VERSION="$(cat "$SRC/version" 2>/dev/null || printf '%s' "$ELECTRON_VERSION")"
  mkdir -p "$WORK" "$OUT"
  prepare_package_metadata
  say "阶段 3/3 打包发行包（$arch，应用版本 $VER）"
  if want_format deb; then build_deb bundled; build_deb system; fi
  if want_format pacman; then build_pkgtar; fi
  if want_format rpm; then build_rpm; fi
}

prepare_package_metadata() {
  mkdir -p "$META"
  install -m 644 "$B/icons/deepseek-harness.desktop" "$META/deepseek-harness.desktop"
  for size in 16 24 32 48 64 128 256 512; do
    mkdir -p "$META/icons/${size}x${size}"
    install -m 644 "$B/icons/${size}x${size}/deepseek-harness.png" "$META/icons/${size}x${size}/"
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

}

build_deb() {
  local variant="$1"
  local d="$WORK/deb-$variant"
  local deps="" rec=""
  drop "$d"; mkdir -p "$d/control" "$d/data"
  local D="$d/data"
  mkdir -p "$D/usr/lib/deepseek-harness" "$D/usr/bin" "$D/usr/share/applications" "$D/usr/share/icons/hicolor"
  if [ "$variant" = bundled ]; then
    copy_tree "$SRC" "$D/usr/lib/deepseek-harness" .sharp-native-backup
    normalize_modes "$D/usr/lib/deepseek-harness"
    printf '#!/bin/sh\nexec /usr/lib/deepseek-harness/deepseek-harness "$@"\n' > "$D/usr/bin/deepseek-harness"
    deps="libgtk-3-0, libnotify4, libnss3, libxss1, libxtst6, xdg-utils, libatspi2.0-0, libuuid1, libsecret-1-0, libgbm1, libasound2, libdrm2, libxkbcommon0, libxcomposite1, libxdamage1, libxfixes3, libxrandr2, libcups2, libx11-xcb1, libxcb-dri3-0"
  else
    copy_tree "$SRC/resources" "$D/usr/lib/deepseek-harness/resources" .sharp-native-backup
    normalize_modes "$D/usr/lib/deepseek-harness"
    rm -f "$D/usr/lib/deepseek-harness/resources/app-update.yml"
    cp "$META/launcher" "$D/usr/bin/deepseek-harness"
    deps="libgtk-3-0, libnotify4, libnss3, libxss1, libxtst6, xdg-utils, libatspi2.0-0, libuuid1, libsecret-1-0, libgbm1, libasound2, libdrm2, libxkbcommon0, libxcomposite1, libxdamage1, libxfixes3, libxrandr2, libcups2, libx11-xcb1, libxcb-dri3-0"
    # Debian/Ubuntu ship no electron package: a hard dependency would fail apt.
    rec="electron | electron44 | electron43 | electron42 | electron41 | nodejs-electron"
  fi
  chmod 755 "$D/usr/bin/deepseek-harness"
  cp "$META/deepseek-harness.desktop" "$D/usr/share/applications/"
  for s in 16 24 32 48 64 128 256 512; do
    mkdir -p "$D/usr/share/icons/hicolor/${s}x${s}/apps"
    cp "$META/icons/${s}x${s}/deepseek-harness.png" "$D/usr/share/icons/hicolor/${s}x${s}/apps/"
  done
  local size; size=$(du -sk "$D" | cut -f1)
  # Optional fields must be omitted entirely, never emitted as an empty line:
  # a blank line ends the paragraph, so everything after it (Homepage,
  # Description) would be parsed as a second, malformed package stanza and
  # dpkg/apt would refuse to install the archive.
  local recommends_line=""
  if [ -n "$rec" ]; then
    recommends_line="Recommends: $rec
"
  fi
  cat > "$d/control/control" <<EOF
Package: deepseek-harness
Version: $VER
Section: utils
Priority: optional
Architecture: $DEBARCH
Maintainer: DeepSeek Harness Linux port <noreply@localhost>
Installed-Size: $size
Depends: $deps
${recommends_line}Homepage: https://harness.deepseek.com
Description: DeepSeek Harness desktop client ($variant Electron build)
 DeepSeek Harness desktop application repackaged for Linux.
 This build $([ "$variant" = bundled ] && echo "bundles its own Electron $PACKAGED_ELECTRON_VERSION runtime" || echo "uses the distribution-provided Electron runtime").
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
  ( cd "$d" && XZ_OPT="${XZ_OPT:--T2}" tar --owner=0 --group=0 --numeric-owner -cJf data.tar.xz -C data . \
    && XZ_OPT="${XZ_OPT:--T2}" tar --owner=0 --group=0 --numeric-owner -cJf control.tar.xz -C control . \
    && ar rc "$OUT/deepseek-harness_${VER}_${DEBARCH}.${variant}.deb" debian-binary control.tar.xz data.tar.xz )
  write_package_checksum "deepseek-harness_${VER}_${DEBARCH}.${variant}.deb"
  echo "  ✓ deb ($variant): $(du -h "$OUT/deepseek-harness_${VER}_${DEBARCH}.${variant}.deb" | cut -f1)"
}

# -------------------------------------------------------------------- rpm ----
build_rpm() {
  local top="$WORK/rpmbuild"
  drop "$top"; mkdir -p "$top"/{BUILD,RPMS,SOURCES,SPECS,SRPMS,tmp,BUILDROOT,rpmdb}
  copy_tree "$SRC" "$top/SOURCES/app" .sharp-native-backup
  normalize_modes "$top/SOURCES/app"
  cp "$META/deepseek-harness.desktop" "$top/SOURCES/"
  cp -a "$META/icons" "$top/SOURCES/icons"
  cat > "$top/SPECS/deepseek-harness.spec" <<SPEC
Name:           deepseek-harness
Version:        $RPM_VERSION
Release:        $RPM_RELEASE
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
This build bundles its own Electron $PACKAGED_ELECTRON_VERSION runtime.
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
  TMPDIR="$top/tmp" rpmbuild "${rc[@]}" --define "_topdir $top" --define "_tmppath $top/tmp" --define "_dbpath $top/rpmdb" \
    --define "_binary_payload w6.xzdio" --target "${RPMARCH}-linux" --noclean -bb "$top/SPECS/deepseek-harness.spec" \
    >"$WORK/rpm.log" 2>&1 || { tail -20 "$WORK/rpm.log"; return 1; }
  local built; built=$(find "$top/RPMS" -name '*.rpm' | head -1)
  cp "$built" "$OUT/deepseek-harness-${RPM_VERSION}-${RPM_RELEASE}.${RPMARCH}.rpm"
  write_package_checksum "deepseek-harness-${RPM_VERSION}-${RPM_RELEASE}.${RPMARCH}.rpm"
  echo "  ✓ rpm: $(du -h "$OUT/deepseek-harness-${RPM_VERSION}-${RPM_RELEASE}.${RPMARCH}.rpm" | cut -f1)"
}

# ------------------------------------------------------------------- Arch ----
build_pkgtar() {
  local r="$WORK/pkgroot"
  drop "$r"; mkdir -p "$r/usr/lib/deepseek-harness" "$r/usr/bin" \
    "$r/usr/share/applications" "$r/usr/share/icons/hicolor"
  copy_tree "$SRC/resources" "$r/usr/lib/deepseek-harness/resources" .sharp-native-backup
  normalize_modes "$r/usr/lib/deepseek-harness/resources"
  rm -f "$r/usr/lib/deepseek-harness/resources/app-update.yml"
  cp "$META/launcher" "$r/usr/bin/deepseek-harness"
  chmod 755 "$r/usr/bin/deepseek-harness"
  cp "$META/deepseek-harness.desktop" "$r/usr/share/applications/"
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
    | zstd -19 -T4 -o "$OUT/$name" -q -f
  write_package_checksum "$name"
  echo "  ✓ pkg.tar.zst: $(du -h "$OUT/$name" | cut -f1)"
}

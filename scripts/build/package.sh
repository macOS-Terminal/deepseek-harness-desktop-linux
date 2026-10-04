# ============================================================== 阶段 3：打包 ==
build_appimage() {  # <arch>
  local arch="$1"
  local out="$ROOT/out-$arch"
  local target; target="$(arch_target "$arch")"
  local appver
  local work="$WORK_BASE/$arch"
  local appdir="$work/DeepSeek-Harness.AppDir"
  local mksquashfs="$TOOLS/usr/bin/mksquashfs"
  local runtime="$TOOLS/runtime-$target"

  say "阶段 3/3 打包 AppImage（$target）"
  if [ "$DRY_RUN" -eq 1 ]; then step "[dry-run] mksquashfs + runtime → dist/"; return 0; fi
  appver="$(package_version "$arch")"
  [ -d "$out" ] || die "缺少应用树 $out（先跑 --only tree）"
  [ -x "$mksquashfs" ] || die "缺少 mksquashfs（$mksquashfs），先跑 --only prepare"
  [ -s "$runtime" ] || die "缺少 AppImage runtime（$runtime）"

  mkdir -p "$work" "$ROOT/dist"
  drop "$appdir"
  mkdir -p "$appdir"
  # Keep the diagnostic native Sharp backup in the tree, but omit it from the package.
  copy_tree "$out" "$appdir" .sharp-native-backup
  normalize_modes "$appdir"

  mkdir -p "$appdir/usr/share/applications" "$appdir/usr/share/icons/hicolor"
  cp "$ROOT/icons/deepseek-harness.desktop" "$appdir/usr/share/applications/"
  cp "$ROOT/icons/deepseek-harness.desktop" "$appdir/deepseek-harness.desktop"
  cp "$ROOT/icons/deepseek-harness.png" "$appdir/deepseek-harness.png"
  cp "$ROOT/icons/deepseek-harness.png" "$appdir/.DirIcon"
  local size
  for size in 16 24 32 48 64 128 256 512; do
    mkdir -p "$appdir/usr/share/icons/hicolor/${size}x${size}/apps"
    cp "$ROOT/icons/${size}x${size}/deepseek-harness.png" \
       "$appdir/usr/share/icons/hicolor/${size}x${size}/apps/"
  done
  # AppRun 保持最小实现，与 build-packages.sh 里生成的完全一致。
  # 这里刻意不加任何 Chromium 开关（包括 Wayland 下的 Vulkan 相关开关）：
  # 那类现象属上游行为，说明只写在 README.zh.md「六、常见坑」，
  # 由使用者按需自行在命令行追加参数，工具链不做默认干预。
  cat > "$appdir/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/deepseek-harness" "$@"
APPRUN
  chmod 755 "$appdir/AppRun"

  local squash="$work/app.squashfs"
  rm -f "$squash"
  step "mksquashfs（zstd -19，$(nproc 2>/dev/null || echo 4) 线程）"
  "$mksquashfs" "$appdir" "$squash" -root-owned -noappend -comp zstd \
    -Xcompression-level 19 -b 1M -processors "$(nproc 2>/dev/null || echo 4)" >/dev/null \
    || die "mksquashfs 失败"

  local name="DeepSeek-Harness-${appver}-${target}.AppImage"
  cat "$runtime" "$squash" > "$ROOT/dist/$name"
  chmod 755 "$ROOT/dist/$name"
  step "产物 dist/$name（$(human "$ROOT/dist/$name")）"
  (cd "$ROOT/dist" && sha256sum "$name" | tee "$name.sha256")
  step "暂存保留在 $work（AppDir 与 app.squashfs）"
}

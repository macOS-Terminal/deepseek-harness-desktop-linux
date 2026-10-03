#!/usr/bin/env python3
"""Apply Linux-adaptation patches to one extracted dsh-desktop app tree.

Usage: patch-main.py <path-to-resources/app/lib/main.js>

Patches (all verified against the 0.2.0-rc.2 bundle):
  1. platform allowlist: accept linux (was win32/darwin only -> threw on Linux)
  2. x-client-platform: report desktop-linux instead of falling through to mac
  3. DesktopPlatformView platform argument: pass linux through
  4. resources root: allow DSH_DESKTOP_RESOURCES_DIR override (system Electron)
  5. packaged detection: allow DSH_DESKTOP_FORCE_PACKAGED=1
  6. tray: create on Linux too, and use a PNG icon there
  7. window close: quit (not hide) when no tray can bring the app back
  8. command manager: keep the CLI installer on the overridden resources root
"""
import sys

def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding='utf8').read()
    orig = src
    done = []
    missing = []

    def sub(old, new, label, count=1):
        nonlocal src
        if src.count(old) != count:
            missing.append(f'{label} (found {src.count(old)}, expected {count})')
            return
        src = src.replace(old, new)
        done.append(label)

    # 1) platform allowlist ---------------------------------------------------
    sub(
        'if (!["win32", "darwin"].includes(process.platform)',
        'if (!["win32", "darwin", "linux"].includes(process.platform)',
        '平台准入：允许 linux',
    )

    # 2) client platform header ---------------------------------------------
    sub(
        'return { "x-client-platform": platform === "win32" ? "desktop-win" : "desktop-mac" };',
        'return { "x-client-platform": platform === "win32" ? "desktop-win" : platform === "linux" ? "desktop-linux" : "desktop-mac" };',
        '平台上报：desktop-linux',
    )

    # 3) platform view argument ---------------------------------------------
    sub(
        'process.platform === "win32" ? "win32" : "darwin");',
        'process.platform === "win32" ? "win32" : process.platform === "linux" ? "linux" : "darwin");',
        'PlatformView 平台参数透传',
    )

    # 4) + 5) helpers --------------------------------------------------------
    anchor = None
    for candidate in (
        'function runtimeResources() {\n\tconst development = !app.isPackaged;',
        'function desktopResourcesRoot',
    ):
        if candidate in src:
            anchor = candidate
            break
    if anchor is None:
        missing.append('资源根/打包态 helper 插入点')
    else:
        helpers = (
            '/** Package-state override so a system-wide Electron build is not treated as development. */\n'
            'function desktopIsPackaged() {\n'
            '\treturn app.isPackaged || process.env.DSH_DESKTOP_FORCE_PACKAGED === "1";\n'
            '}\n'
            '/** Resources root override for builds launched by a distribution Electron. */\n'
            'function desktopResourcesRoot() {\n'
            '\tconst override = process.env.DSH_DESKTOP_RESOURCES_DIR;\n'
            '\treturn override === void 0 || override === "" ? process.resourcesPath : override;\n'
            '}\n'
        )
        if anchor.startswith('function runtimeResources'):
            src = src.replace(anchor, helpers + anchor, 1)
            done.append('注入 helper：desktopResourcesRoot / desktopIsPackaged')
        else:
            missing.append('helper 已存在但布局陌生，跳过')

    # 4b) route resourcesPath users through the override ---------------------
    for old, new, label in (
        ('existsSync(join(process.resourcesPath, "app-update.yml"))',
         'existsSync(join(desktopResourcesRoot(), "app-update.yml"))',
         '更新器探测改走 resources 根'),
        ('join(process.resourcesPath, "runtime", "bin")',
         'join(desktopResourcesRoot(), "runtime", "bin")',
         'nodeBin 路径改走 resources 根'),
        ('join(process.resourcesPath, "runtime", "pnpm", "bin", "pnpm.mjs")',
         'join(desktopResourcesRoot(), "runtime", "pnpm", "bin", "pnpm.mjs")',
         'pnpm 路径改走 resources 根'),
        ('join(process.resourcesPath, "runtime", "primary-runtime")',
         'join(desktopResourcesRoot(), "runtime", "primary-runtime")',
         'primaryRuntime 路径改走 resources 根'),
        ('join(process.resourcesPath, "icon.png")',
         'join(desktopResourcesRoot(), "icon.png")',
         '应用图标路径改走 resources 根'),
        ('resources: process.resourcesPath,',
         'resources: desktopResourcesRoot(),',
         'CLI 命令管理器 resources 改走 resources 根'),
    ):
        sub(old, new, label)

    # 5b) packaged-state users ----------------------------------------------
    occurrences = src.count('app.isPackaged')
    if occurrences:
        src = src.replace('app.isPackaged', 'desktopIsPackaged()')
        # restore inside the helper itself
        src = src.replace(
            'return desktopIsPackaged() || process.env.DSH_DESKTOP_FORCE_PACKAGED === "1";',
            'return app.isPackaged || process.env.DSH_DESKTOP_FORCE_PACKAGED === "1";',
        )
        done.append(f'打包态判定改走 desktopIsPackaged()（{occurrences} 处）')
    else:
        missing.append('app.isPackaged 未找到')

    # 6) tray icon + creation ------------------------------------------------
    sub(
        'const trayIconPath = development ? join(app.getAppPath(), "resources", "tray-windows.ico") : join(process.resourcesPath, "tray.ico");',
        'const trayIconPath = process.platform === "linux" ? development ? join(app.getAppPath(), "resources", "icon.png") : join(desktopResourcesRoot(), "tray.png") : development ? join(app.getAppPath(), "resources", "tray-windows.ico") : join(desktopResourcesRoot(), "tray.ico");',
        '托盘图标：Linux 使用 PNG',
    )
    sub(
        'if (process.platform === "win32") try {\n\t\ttray = new DesktopTray({',
        'if (process.platform === "win32" || process.platform === "linux") try {\n\t\ttray = new DesktopTray({',
        '托盘创建：放行 Linux',
    )

    # 7) close-to-tray fallback ---------------------------------------------
    sub(
        '\t\t\tif (backgroundNotice === void 0) hide();\n\t\t\telse backgroundNotice.close(hide);',
        '\t\t\t// 没有托盘可召回时不能隐藏窗口，否则应用会成为不可见的孤岛。\n'
        '\t\t\tif (tray === void 0) {\n'
        '\t\t\t\tquitting = true;\n'
        '\t\t\t\tapp.quit();\n'
        '\t\t\t\treturn;\n'
        '\t\t\t}\n'
        '\t\t\tif (backgroundNotice === void 0) hide();\n'
        '\t\t\telse backgroundNotice.close(hide);',
        '关窗：无托盘时退出而非隐藏',
    )

    if src != orig:
        open(path, 'w', encoding='utf8').write(src)

    print(f'== {path}')
    for item in done:
        print(f'  ✓ {item}')
    for item in missing:
        print(f'  ✗ 未应用：{item}')
    print(f'  字节 {len(orig)} -> {len(src)}')
    return 1 if missing else 0


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Hide the native title bar on Linux, matching the Windows build's chrome.

The upstream bundle styles its own title bar for win32 (titleBarStyle hidden +
titleBarOverlay) and darwin (hiddenInset), and gives Linux nothing — so the Linux
build shows a native title bar stacked above the app's own header.

On Linux the renderer has no -webkit-app-region drag areas and the preload exposes no
window controls, so plain `titleBarStyle: "hidden"` would leave a window that cannot be
dragged or closed. Electron's titleBarOverlay solves both on Linux: GTK draws the
minimize/maximize/close buttons (server-side decorations) and the header remains
draggable.

Usage: patch-titlebar.py <path-to-lib/main.js>
"""
import sys


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding='utf8').read()
    orig = src
    done, missing = [], []

    def sub(old, new, label):
        nonlocal src
        if src.count(old) != 1:
            missing.append(f'{label}（匹配 {src.count(old)} 处）')
            return
        src = src.replace(old, new)
        done.append(label)

    # 1) Main window: add a Linux branch next to the win32/darwin ones.
    sub(
        '\t\t...process.platform === "win32" && primary ? {\n'
        '\t\t\ttitleBarStyle: "hidden",\n'
        '\t\t\ttitleBarOverlay: {\n'
        '\t\t\t\theight: 40,\n'
        '\t\t\t\tcolor: chromeFallbackFill(),\n'
        '\t\t\t\tsymbolColor: nativeTheme.shouldUseDarkColors ? "#f9fafb" : "#0f1115"\n'
        '\t\t\t}\n'
        '\t\t} : {},',
        '\t\t...process.platform === "win32" && primary ? {\n'
        '\t\t\ttitleBarStyle: "hidden",\n'
        '\t\t\ttitleBarOverlay: {\n'
        '\t\t\t\theight: 40,\n'
        '\t\t\t\tcolor: chromeFallbackFill(),\n'
        '\t\t\t\tsymbolColor: nativeTheme.shouldUseDarkColors ? "#f9fafb" : "#0f1115"\n'
        '\t\t\t}\n'
        '\t\t} : {},\n'
        '\t\t...process.platform === "linux" && primary ? {\n'
        '\t\t\ttitleBarStyle: "hidden",\n'
        '\t\t\ttitleBarOverlay: {\n'
        '\t\t\t\theight: 40,\n'
        '\t\t\t\tsymbolColor: nativeTheme.shouldUseDarkColors ? "#f9fafb" : "#0f1115"\n'
        '\t\t\t}\n'
        '\t\t} : {},',
        '主窗口：Linux 隐藏标题栏并启用系统装饰',
    )

    # 2) Welcome window: same treatment (its win32 branch uses a fixed symbol color).
    sub(
        '\t\t...platform === "win32" ? {\n'
        '\t\t\ttitleBarStyle: "hidden",\n'
        '\t\t\ttitleBarOverlay: {\n'
        '\t\t\t\tcolor: "#00000000",\n'
        '\t\t\t\tsymbolColor: "#0F1115",\n'
        '\t\t\t\theight: 42\n'
        '\t\t\t},\n'
        '\t\t\tbackgroundMaterial: "acrylic"\n'
        '\t\t} : {},',
        '\t\t...platform === "win32" ? {\n'
        '\t\t\ttitleBarStyle: "hidden",\n'
        '\t\t\ttitleBarOverlay: {\n'
        '\t\t\t\tcolor: "#00000000",\n'
        '\t\t\t\tsymbolColor: "#0F1115",\n'
        '\t\t\t\theight: 42\n'
        '\t\t\t},\n'
        '\t\t\tbackgroundMaterial: "acrylic"\n'
        '\t\t} : {},\n'
        '\t\t...platform === "linux" ? {\n'
        '\t\t\ttitleBarStyle: "hidden",\n'
        '\t\t\ttitleBarOverlay: {\n'
        '\t\t\t\theight: 42,\n'
        '\t\t\t\tsymbolColor: nativeTheme.shouldUseDarkColors ? "#f9fafb" : "#0f1115"\n'
        '\t\t\t}\n'
        '\t\t} : {},',
        '欢迎窗口：Linux 隐藏标题栏并启用系统装饰',
    )

    if src != orig:
        open(path, 'w', encoding='utf8').write(src)

    print(f'== {path}')
    for item in done:
        print(f'  ✓ {item}')
    for item in missing:
        print(f'  ✗ 未应用：{item}')
    return 1 if missing else 0


if __name__ == '__main__':
    raise SystemExit(main())

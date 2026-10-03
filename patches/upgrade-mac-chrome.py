#!/usr/bin/env python3
"""把已注入的 macOS chrome 代码就地升级到「模糊层 + 折叠 toggle 归位」版本。

patch-mac-chrome.py 是幂等的（已注入就跳过），因此修复已注入过的树需要
在原地做等价替换。用法: upgrade-mac-chrome.py <resources/app 目录>
"""
import sys

OLD_CSS_BLOCK = """/* macOS vibrancy approximation: translucent sidebar over a blurred backdrop. */
html[data-dsh-mac-chrome] [class*="_sidebarCol"] {
	background: linear-gradient(to bottom, #7a9bf01a, #7a9bf000 35%, #8f89b800 68%, #8f89b817),
		color-mix(in srgb, color-mix(in srgb, var(--dsw-specific-sidebar-fill) 97%, #7a9bf0) 40%, transparent) !important;
	backdrop-filter: blur(40px) saturate(150%);
	-webkit-backdrop-filter: blur(40px) saturate(150%);
	border-right: none !important;
}
html[data-dsh-mac-chrome][data-ds-dark-theme] [class*="_sidebarCol"],
html[data-dsh-mac-chrome] body[data-ds-dark-theme] [class*="_sidebarCol"] {
	background: linear-gradient(to bottom, #7a9bf014, #7a9bf000 35%, #8f89b800 68%, #8f89b812),
		color-mix(in srgb, var(--dsw-specific-sidebar-fill) 50%, transparent) !important;
}"""

NEW_CSS_BLOCK = """/* macOS vibrancy approximation.
   The blur lives on a dedicated background layer instead of the sidebar itself:
   backdrop-filter turns its element into the containing block for fixed-position
   descendants and clips them by its own overflow, which broke the app's
   fixed-position collapse toggle and cut a notch out of the frame. Keeping the
   filter on a pointer-transparent sibling avoids both. */
#dsh-mac-vibrancy {
	position: fixed; inset: 0 auto 0 0; width: var(--dsh-linux-sidebar-width, 280px);
	z-index: 0; pointer-events: none;
	background: linear-gradient(to bottom, #7a9bf01a, #7a9bf000 35%, #8f89b800 68%, #8f89b817),
		color-mix(in srgb, color-mix(in srgb, var(--dsw-specific-sidebar-fill) 97%, #7a9bf0) 40%, transparent);
	backdrop-filter: blur(40px) saturate(150%);
	-webkit-backdrop-filter: blur(40px) saturate(150%);
}
html[data-dsh-mac-chrome][data-ds-dark-theme] #dsh-mac-vibrancy,
html[data-dsh-mac-chrome] body[data-ds-dark-theme] #dsh-mac-vibrancy {
	background: linear-gradient(to bottom, #7a9bf014, #7a9bf000 35%, #8f89b800 68%, #8f89b812),
		color-mix(in srgb, var(--dsw-specific-sidebar-fill) 50%, transparent);
}
/* The sidebar itself only goes transparent so the layer above shows through. */
html[data-dsh-mac-chrome] [class*="_sidebarCol"] {
	background: 0 0 !important;
	border-right: none !important;
}"""

OLD_TOGGLE = 'html[data-dsh-mac-chrome] [class*="_toggle"] { left: var(--dsh-linux-toggle-left, 240px) !important; right: auto; }'
NEW_TOGGLE = OLD_TOGGLE + """
/* Collapsed: the app turns the toggle into a 28px round button on the rail and
   expects it at the leading edge, so keep it clear of the traffic lights there. */
html[data-dsh-mac-chrome] [class*="_collapsed"] [class*="_toggle"] { left: 88px !important; }"""

OLD_APPLY = """		if (document.getElementById(LIGHTS_ID) === null && document.body !== null) {
			lights = buildLights();
			document.body.appendChild(lights);
		}"""
NEW_APPLY = """		if (document.getElementById(VIBRANCY_ID) === null && document.body !== null) {
			const vibrancy = document.createElement("div");
			vibrancy.id = VIBRANCY_ID;
			vibrancy.setAttribute("aria-hidden", "true");
			// Insert *before* the application root so the blurred surface sits
			// underneath the whole UI rather than participating in its subtree.
			const appRoot = document.getElementById("root");
			if (appRoot !== null && appRoot.parentElement === document.body) document.body.insertBefore(vibrancy, appRoot);
			else document.body.appendChild(vibrancy);
		}
		if (document.getElementById(LIGHTS_ID) === null && document.body !== null) {
			lights = buildLights();
			document.body.appendChild(lights);
		}"""

OLD_IDS = '\tconst LIGHTS_ID = "dsh-mac-lights";'
NEW_IDS = '\tconst LIGHTS_ID = "dsh-mac-lights";\n\tconst VIBRANCY_ID = "dsh-mac-vibrancy";'

OLD_MEASURE = """			const width = Math.round(sidebar.getBoundingClientRect().width);
			if (width > 0) {"""
NEW_MEASURE = """			const width = Math.round(sidebar.getBoundingClientRect().width);
			if (width >= 0) {"""


# ---- v2：清晰度 / 圆角空隙 / 全屏布局 ----
V2_CSS = """
/* Keep the vibrancy layer behind the whole application so sidebar text
   rasterises on its own layer instead of being blended through the blur. */
html[data-dsh-mac-chrome] #dsh-mac-vibrancy { z-index: -1 !important; }
/* The bundle rounds the content column's top-left corner for its Windows
   frameless look; filling the screen leaves that radius as a blank notch. */
html[data-dsh-mac-chrome] [class*="_centerCol"] { border-radius: 0 !important; }
/* Fullscreen follows the bundle's own macOS behaviour: traffic lights hide and
   the collapse control returns to the leading edge. */
html[data-dsh-mac-chrome][data-fullscreen] #dsh-mac-lights { display: none !important; }
html[data-dsh-mac-chrome][data-fullscreen] [class*="_toggle"] { left: 12px !important; }
html[data-dsh-mac-chrome][data-fullscreen] [class*="_leadingSeat"] { left: 12px !important; }
"""


# ---- v3：Linux 全屏事件 + leadingSeat 让位 ----
OLD_FS = '''\tif (process.platform === "darwin" || process.platform === "win32") {
\t\tconst sendFullscreen = () => {
\t\t\tif (!window.isDestroyed()) window.webContents.send(DESKTOP_IPC.windowFullscreen, window.isFullScreen());
\t\t};
\t\twindow.on("enter-full-screen", sendFullscreen);
\t\twindow.on("leave-full-screen", sendFullscreen);
\t\twindow.webContents.on("did-finish-load", sendFullscreen);
\t}'''
NEW_FS = '''\t// Linux is included here: the renderer keys its fullscreen layout (traffic
\t// lights hidden, collapse control at the leading edge) off `data-fullscreen`,
\t// which only this channel sets. Tiling compositors treat a "fullscreen" window
\t// as merely maximised, so maximised also counts as fullscreen on Linux.
\tif (process.platform === "darwin" || process.platform === "win32" || process.platform === "linux") {
\t\tconst sendFullscreen = () => {
\t\t\tif (window.isDestroyed()) return;
\t\t\tconst fullscreen = window.isFullScreen() || (process.platform === "linux" && window.isMaximized());
\t\t\twindow.webContents.send(DESKTOP_IPC.windowFullscreen, fullscreen);
\t\t};
\t\twindow.on("enter-full-screen", sendFullscreen);
\t\twindow.on("leave-full-screen", sendFullscreen);
\t\twindow.on("maximize", sendFullscreen);
\t\twindow.on("unmaximize", sendFullscreen);
\t\twindow.webContents.on("did-finish-load", sendFullscreen);
\t}'''

OLD_SEAT_FULL = 'html[data-dsh-mac-chrome][data-fullscreen] [class*="_leadingSeat"] { left: 12px !important; }'
NEW_SEAT_FULL = '''/* The bundle reserves this seat for host-drawn window controls (on macOS the
   traffic lights) and parks it at 88px; our lights sit at 16..68px, so the seat
   must stay to their right in every state rather than sliding underneath. */
html[data-dsh-mac-chrome] [class*="_leadingSeat"] { left: 88px !important; }'''


# ---- v4：平铺合成器全屏自检 + preload 全屏监听纳入 Linux ----
TILING_DETECT = """\t/**
\t * Tiling compositors (niri, Hyprland, sway) fill the screen without telling
\t * Electron: neither isFullScreen() nor isMaximized() flips, so the shell never
\t * emits the fullscreen channel the bundle's layout keys off. Treat a viewport
\t * that covers the display work area as fullscreen.
\t */
\tconst syncTilingFullscreen = () => {
\t\tconst root = document.documentElement;
\t\tif (root === null) return;
\t\tconst coversWidth = window.innerWidth >= window.screen.availWidth - 2;
\t\tconst coversHeight = window.innerHeight >= window.screen.availHeight - 2;
\t\troot.dataset.dshTilingFullscreen = coversWidth && coversHeight ? "true" : "false";
\t\tconst effective = (root.dataset.dshWindowFullscreen === "true") || (root.dataset.dshTilingFullscreen === "true");
\t\tif (effective) root.dataset.fullscreen = "true";
\t\telse delete root.dataset.fullscreen;
\t};
\tsyncTilingFullscreen();
\twindow.addEventListener("resize", syncTilingFullscreen);

"""
PRE_OLD_FS = '''function syncWindowFullscreen() {
\tif (process.platform !== "darwin" && process.platform !== "win32") return;'''
PRE_NEW_FS = '''function syncWindowFullscreen() {
\t// Linux is included: the shell reports real fullscreen and maximise there too,
\t// and the mac-style chrome keys its layout off data-fullscreen.
\tif (process.platform !== "darwin" && process.platform !== "win32" && process.platform !== "linux") return;'''
PRE_ANCHOR = '\tlet lights = null;\n\tconst send = (action) => { electron.ipcRenderer.invoke(CHANNEL, action); };'


def upgrade_main_js(app_dir: str) -> None:
    """把 Linux 全屏事件注册补进 lib/main.js（幂等）。"""
    path = f'{app_dir}/lib/main.js'
    src = open(path, encoding='utf8').read()
    if 'process.platform === "linux" && window.isMaximized()' in src:
        print(f'  · 全屏事件已注册: {path}')
        return
    if OLD_FS in src:
        open(path, 'w', encoding='utf8').write(src.replace(OLD_FS, NEW_FS, 1))
        print(f'  ✓ 注册 Linux 全屏事件: {path}')
    else:
        print(f'  ✗ 未匹配全屏事件段: {path}')


OLD_RAIL = """html[data-dsh-mac-chrome] [class*="_collapsed"] [class*="_toggle"] { left: 88px !important; }"""
NEW_RAIL = """html[data-dsh-mac-chrome]:not([data-fullscreen]) [class*="_collapsed"] [class*="_newSession"] { left: 88px !important; }
html[data-dsh-mac-chrome]:not([data-fullscreen]) [class*="_collapsed"] [class*="_toggle"] { left: 128px !important; }"""
OLD_INACTIVE = "#dsh-mac-lights[data-inactive] button { background: #4a4a4c; }"
NEW_INACTIVE = "#dsh-mac-lights[data-inactive] button { filter: saturate(.55) brightness(.72); }"

def main(app_dir: str) -> int:
    upgrade_main_js(app_dir)
    for name in ('preload-app.cjs', 'preload-welcome.cjs'):
        path = f'{app_dir}/lib/{name}'
        src = open(path, encoding='utf8').read()
        if 'installLinuxChrome' not in src:
            print(f'  · 未注入，跳过: {path}')
            continue
        notes = []
        if 'dsh-mac-vibrancy { z-index: -1' not in src and 'const CSS = `' in src:
            cut = src.index('`;', src.index('const CSS = `'))
            src = src[:cut] + V2_CSS + src[cut:]
            notes.append('  ✓ 追加 v2 CSS（清晰度/圆角/全屏）')
        elif 'dsh-mac-vibrancy { z-index: -1' in src:
            notes.append('  · v2 CSS 已存在')
        # 每步用「应用后才会出现的唯一标记」判重，避免 old 同时是 new 前缀时重复插入
        steps = (
            (OLD_CSS_BLOCK, NEW_CSS_BLOCK, '模糊移到独立层 #dsh-mac-vibrancy', 'sidebarCol"] {\n\tbackground: 0 0 !important;'),
            (OLD_TOGGLE, NEW_TOGGLE, '折叠态 toggle 归位 left:88px', '_collapsed"] [class*="_toggle"]'),
            (OLD_APPLY, NEW_APPLY, '创建 vibrancy 背景层', 'getElementById(VIBRANCY_ID) === null'),
            (OLD_IDS, NEW_IDS, '声明 VIBRANCY_ID', 'const VIBRANCY_ID'),
            (OLD_MEASURE, NEW_MEASURE, '折叠态也更新宽度变量', 'if (width >= 0) {'),
            (OLD_SEAT_FULL, NEW_SEAT_FULL, 'leadingSeat 给交通灯让位', '_leadingSeat"] { left: 88px'),
            (OLD_RAIL, NEW_RAIL, '折叠态导轨按钮右移', '_collapsed"] [class*="_newSession"] { left: 88px'),
            (OLD_INACTIVE, NEW_INACTIVE, '失焦态交通灯保留色相', 'filter: saturate(.55) brightness(.72)'),
        )
        if 'syncTilingFullscreen' not in src and PRE_ANCHOR.replace('\\t','\t') in src:
            src = src.replace(PRE_ANCHOR.replace('\\t','\t'), TILING_DETECT.replace('\\t','\t') + PRE_ANCHOR.replace('\\t','\t'), 1)
            notes.append('  ✓ 平铺全屏自检')
        if PRE_NEW_FS.replace('\\t','\t') not in src and PRE_OLD_FS.replace('\\t','\t') in src:
            src = src.replace(PRE_OLD_FS.replace('\\t','\t'), PRE_NEW_FS.replace('\\t','\t'), 1)
            notes.append('  ✓ 全屏监听纳入 Linux')
        for old, new, label, applied_marker in steps:
            if applied_marker in src:
                notes.append(f'  · 已应用: {label}')
                continue
            if old in src:
                src = src.replace(old, new, 1)
                notes.append(f'  ✓ {label}')
            else:
                notes.append(f'  ✗ 未匹配: {label}')
        open(path, 'w', encoding='utf8').write(src)
        print(f'== {path}')
        print('\n'.join(notes))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1]))

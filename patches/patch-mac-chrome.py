#!/usr/bin/env python3
"""macOS 风格窗口装饰（Linux）——把三大金刚键移到左上角 + 侧栏毛玻璃。

设计要点（均基于对 0.2.0-rc.2 载荷的实际代码阅读，不是猜测）：

1. **不自造轮子**：应用本身已有「自绘标题栏」模式 `html[data-windows-titlebar]`，
   自带顶部预留带（`--dsh-windows-titlebar-height`）、自动拖拽区
   （`._frame::before{-webkit-app-region:drag}`）、页面标题内边距与 toggle 重定位。
   该模式只在 Windows 启用（`syncWindowsAppearance` 里有 `platform !== "win32"` 早退）。
   我们只是把同一个标记在 Linux 上打开，不新增布局机制。

2. **绝不动 `data-platform`**：应用用 `html[data-platform=darwin]` 切材质，但同一属性
   也决定快捷键把 `primary` 解析成 Meta(⌘) 还是 Control —— 在 Linux 上伪造 darwin
   会让快捷键显示成 ⌘ 且修饰键映射错误。所以只**复刻 darwin 的材质数值**。

3. **毛玻璃配方直接取自应用自身的 darwin 规则**：
   `color-mix(in srgb, var(--dsw-specific-sidebar-fill) 50%, transparent)` 叠一条竖向渐变，
   再补 `backdrop-filter: blur(40px) saturate(150%)`（应用菜单材质用的同一档位）。

4. **窗口层**：Linux 用 `titleBarStyle:"hidden"` + `transparent:true`，并去掉上一版的
   `titleBarOverlay`（那正是按钮跑到右上角的原因）；欢迎窗额外 `frame:false`。

5. **交通灯**：按应用自身 darwin 常量 `trafficLightPosition {x:16,y:18}` 摆放，
   点击经 IPC 走 minimize / maximize / close。

用法: patch-mac-chrome.py <resources/app 目录>
"""
import sys

TITLEBAR_HEIGHT = 48

PRELOAD_FN = r'''
/* ------------------------------------------------------------------------ *
 * Linux macOS-style window chrome.
 *
 * Reuses the application's own custom-titlebar layout mode
 * (`data-windows-titlebar`) for the top band, drag region and page clearances,
 * then layers the macOS vibrancy recipe (copied from the bundle's own
 * `[data-platform=darwin]` rules) plus left-aligned traffic lights on top.
 * `data-platform` deliberately stays "linux" so shortcut modifiers keep
 * resolving `primary` to Control rather than Meta.
 * ------------------------------------------------------------------------ */
function installLinuxChrome() {
	if (process.platform !== "linux") return;
	const CHANNEL = "dsh-desktop:linux-window-control";
	const HEIGHT = __TITLEBAR_HEIGHT__;
	const LIGHTS_ID = "dsh-mac-lights";
	const VIBRANCY_ID = "dsh-mac-vibrancy";
	const STYLE_ID = "dsh-mac-chrome-style";
	const CSS = `
html[data-dsh-mac-chrome] [class*="_frame"] { background: 0 0 !important; }
html[data-dsh-mac-chrome] [class*="_frame"]::before {
	background: linear-gradient(to right,
		color-mix(in srgb, var(--dsw-specific-sidebar-fill) 50%, transparent) 0 var(--dsh-linux-sidebar-width, 280px),
		var(--dsw-alias-bg-base) var(--dsh-linux-sidebar-width, 280px) 100%) !important;
}
/* The sidebar's inner root paints an opaque fill of its own; the bundle's own
   darwin recipe clears it ([data-platform=darwin] ._3WPZCG_root{background:0 0}),
   so do the same here or the tint above stays hidden behind it. */
html[data-dsh-mac-chrome] [class*="_sidebarCol"] [class*="_root"] { background: 0 0 !important; }
/* The document background must be transparent too, otherwise it hides the
   desktop behind the translucent sidebar. */
html[data-dsh-mac-chrome], html[data-dsh-mac-chrome] body { background: transparent !important; }
/* macOS vibrancy approximation.
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
}
/* Traffic lights where macOS puts them: 16px in, 18px down, 12px dots. */
#dsh-mac-lights {
	position: fixed; left: 16px; top: 18px; z-index: 2147483646;
	display: flex; gap: 8px; -webkit-app-region: no-drag;
}
#dsh-mac-lights button {
	box-sizing: border-box; width: 12px; height: 12px; min-width: 0; padding: 0; margin: 0;
	border: 0; border-radius: 50%; cursor: default; -webkit-app-region: no-drag;
	box-shadow: inset 0 0 0 .5px rgba(0, 0, 0, .16);
	display: grid; place-items: center;
	font: 700 8px/1 system-ui, sans-serif; color: rgba(0, 0, 0, .56);
}
#dsh-mac-lights button.close { background: #ff5f57; }
#dsh-mac-lights button.minimize { background: #febc2e; }
#dsh-mac-lights button.maximize { background: #28c840; }
#dsh-mac-lights button > span { opacity: 0; transition: opacity .12s ease; pointer-events: none; }
#dsh-mac-lights:hover button > span { opacity: 1; }
/* macOS keeps the lights tinted when the window loses focus and only dims them,
   so mirror that instead of flattening them to grey. */
#dsh-mac-lights[data-inactive] button { filter: saturate(.55) brightness(.72); }
#dsh-mac-lights[data-inactive] button > span { opacity: 0; }
/* Keep the collapse toggle at the sidebar trailing edge, clear of the lights. */
html[data-dsh-mac-chrome]:not([data-fullscreen]) [class*="_toggle"] { left: var(--dsh-linux-toggle-left, 240px) !important; right: auto; }
/* The bundle parks the collapsed rail buttons at 48px (new session) and 88px
   (collapse toggle) because Windows keeps its window controls on the right,
   leaving the leading edge free. Our traffic lights occupy 16..68px, so both
   rail buttons shift right and line up exactly as they do in fullscreen, where
   the lights are hidden. */
html[data-dsh-mac-chrome]:not([data-fullscreen]) [class*="_collapsed"] [class*="_newSession"] { left: 88px !important; }
html[data-dsh-mac-chrome]:not([data-fullscreen]) [class*="_collapsed"] [class*="_toggle"] { left: 128px !important; }
html[data-dsh-mac-chrome] [class*="_brand"] { padding-left: 4px; }

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
/* The bundle reserves this seat for host-drawn window controls (on macOS the
   traffic lights) and parks it at 88px; our lights sit at 16..68px, so the seat
   must stay to their right in every state rather than sliding underneath. */
html[data-dsh-mac-chrome] [class*="_leadingSeat"] { left: 88px !important; }
__EXTRA_CSS__`;
	/**
	 * Tiling compositors (niri, Hyprland, sway) fill the screen without telling
	 * Electron: neither isFullScreen() nor isMaximized() flips, so the shell never
	 * emits the fullscreen channel the bundle's layout keys off. Treat a viewport
	 * that covers the display work area as fullscreen.
	 */
	const syncTilingFullscreen = () => {
		const root = document.documentElement;
		if (root === null) return;
		const coversWidth = window.innerWidth >= window.screen.availWidth - 2;
		const coversHeight = window.innerHeight >= window.screen.availHeight - 2;
		root.dataset.dshTilingFullscreen = coversWidth && coversHeight ? "true" : "false";
		const effective = (root.dataset.dshWindowFullscreen === "true") || (root.dataset.dshTilingFullscreen === "true");
		if (effective) root.dataset.fullscreen = "true";
		else delete root.dataset.fullscreen;
	};
	syncTilingFullscreen();
	window.addEventListener("resize", syncTilingFullscreen);
	let lights = null;
	const send = (action) => { electron.ipcRenderer.invoke(CHANNEL, action); };
	const buildLights = () => {
		const host = document.createElement("div");
		host.id = LIGHTS_ID;
		host.setAttribute("role", "group");
		host.setAttribute("aria-label", "窗口控制");
		for (const [action, label, glyph] of [["close", "关闭", "✕"], ["minimize", "最小化", "−"], ["maximize", "缩放", "+"]]) {
			const button = document.createElement("button");
			button.type = "button";
			button.className = action;
			button.dataset.action = action;
			button.setAttribute("aria-label", label);
			button.tabIndex = -1;
			const glyphNode = document.createElement("span");
			glyphNode.textContent = glyph;
			button.appendChild(glyphNode);
			button.addEventListener("pointerdown", (event) => { event.stopPropagation(); });
			button.addEventListener("click", (event) => {
				event.preventDefault();
				event.stopPropagation();
				send(action);
			});
			host.appendChild(button);
		}
		return host;
	};
	const apply = () => {
		const root = document.documentElement;
		if (root === null) return;
		root.dataset.windowsTitlebar = "";
		root.dataset.dshMacChrome = "";
		root.style.setProperty("--dsh-windows-titlebar-height", `${HEIGHT}px`);
		const sidebar = document.querySelector('[class*="_sidebarCol"]');
		if (sidebar !== null) {
			if (sidebarObserver !== null && sidebar !== observedSidebar) {
				if (observedSidebar !== null) sidebarObserver.unobserve(observedSidebar);
				observedSidebar = sidebar;
				sidebarObserver.observe(sidebar);
			}
			const width = Math.round(sidebar.getBoundingClientRect().width);
			if (width >= 0) {
				const toggleLeft = `${Math.max(88, width - 40)}px`;
				if (root.style.getPropertyValue("--dsh-linux-toggle-left") !== toggleLeft) {
					root.style.setProperty("--dsh-linux-sidebar-width", `${width}px`);
					root.style.setProperty("--dsh-linux-toggle-left", toggleLeft);
				}
			}
		}
		if (document.getElementById(STYLE_ID) === null) {
			const style = document.createElement("style");
			style.id = STYLE_ID;
			style.textContent = CSS;
			(document.head ?? root).appendChild(style);
		}
		if (document.getElementById(VIBRANCY_ID) === null && document.body !== null) {
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
		}
	};
	apply();
	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", apply);
	window.addEventListener("resize", apply);
	window.addEventListener("focus", () => { if (lights !== null) lights.removeAttribute("data-inactive"); });
	window.addEventListener("blur", () => { if (lights !== null) lights.setAttribute("data-inactive", ""); });
	// The sidebar only exists after the host finishes booting, which can take
	// tens of seconds, so keep re-measuring instead of sampling a few early ticks.
	const poll = setInterval(apply, 500);
	setTimeout(() => clearInterval(poll), 120000);
	let observedSidebar = null;
	const sidebarObserver = typeof ResizeObserver === "function" ? new ResizeObserver(() => apply()) : null;
	let scheduled = false;
	const observer = new MutationObserver(() => {
		if (scheduled) return;
		scheduled = true;
		requestAnimationFrame(() => {
			scheduled = false;
			apply();
		});
	});
	const startObserving = () => {
		const target = document.body ?? document.documentElement;
		if (target !== null) observer.observe(target, { childList: true, subtree: true });
	};
	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", startObserving);
	else startObserving();
}
'''

# 欢迎窗是独立页面（#root 自身铺 tint，.titlebar 已带 app-region:drag），
# 只需给交通灯让出左侧空间，不套用主窗的 frame/sidebar 规则。
WELCOME_EXTRA_CSS = '\nhtml[data-dsh-mac-chrome] .titlebar { padding-left: 68px; }\n'

PRELOAD_FULLSCREEN_OLD = '''function syncWindowFullscreen() {
	if (process.platform !== "darwin" && process.platform !== "win32") return;'''
PRELOAD_FULLSCREEN_NEW = '''function syncWindowFullscreen() {
	// Linux is included: the shell reports real fullscreen and maximise there too,
	// and the mac-style chrome keys its layout off data-fullscreen.
	if (process.platform !== "darwin" && process.platform !== "win32" && process.platform !== "linux") return;'''

MAIN_MARK_CALL = 'syncNativeTheme();\n'
WELCOME_MARK_CALL = 'electron.contextBridge.exposeInMainWorld("dshWelcome", api);\n'


def inject_preload(path: str, call_anchor: str, extra_css: str) -> str:
    src = open(path, encoding='utf8').read()
    if 'installLinuxChrome' in src:
        return f'  · 已注入过，跳过: {path}'
    if call_anchor not in src:
        return f'  ✗ 找不到锚点: {path}'
    src = src.replace(PRELOAD_FULLSCREEN_OLD, PRELOAD_FULLSCREEN_NEW, 1)
    block = PRELOAD_FN.replace('__TITLEBAR_HEIGHT__', str(TITLEBAR_HEIGHT)).replace('__EXTRA_CSS__', extra_css)
    src = src.replace(call_anchor, call_anchor + '\n' + block + '\ninstallLinuxChrome();\n', 1)
    open(path, 'w', encoding='utf8').write(src)
    return f'  ✓ 注入 installLinuxChrome(): {path}'


def replace_once(src: str, old: str, new: str, label: str, notes: list) -> str:
    if old not in src:
        notes.append(f'  ✗ 未匹配: {label}')
        return src
    notes.append(f'  ✓ {label}')
    return src.replace(old, new, 1)


def main(app_dir: str) -> int:
    notes: list[str] = []
    main_js = f'{app_dir}/lib/main.js'
    src = open(main_js, encoding='utf8').read()

    # --- 1a) 欢迎窗底色：透明 ---
    src = replace_once(
        src,
        '\t\tbackgroundColor: platform === "darwin" || platform === "win32" ? "#00000000" : "#FFFFFF",',
        '\t\tbackgroundColor: "#00000000",',
        '欢迎窗：底色改透明',
        notes,
    )

    # --- 1b) 欢迎窗 linux 分支：无边框 + 透明（移除右侧 overlay 按钮）---
    src = replace_once(
        src,
        '''\t\t...platform === "linux" ? {
\t\t\ttitleBarStyle: "hidden",
\t\t\ttitleBarOverlay: {
\t\t\t\theight: 42,
\t\t\t\tsymbolColor: nativeTheme.shouldUseDarkColors ? "#f9fafb" : "#0f1115"
\t\t\t}
\t\t} : {},''',
        '''\t\t...platform === "linux" ? {
\t\t\ttitleBarStyle: "hidden",
\t\t\tframe: false,
\t\t\ttransparent: true
\t\t} : {},''',
        '欢迎窗：Linux 透明无边框（移除右上角 overlay 按钮）',
        notes,
    )

    # --- 2) 主窗口：透明 + 无边框，交通灯改由 Web 层左置 ---
    src = replace_once(
        src,
        '''		...process.platform === "linux" && primary ? {
			titleBarStyle: "hidden",
			titleBarOverlay: {
				height: 40,
				symbolColor: nativeTheme.shouldUseDarkColors ? "#f9fafb" : "#0f1115"
			}
		} : {},''',
        '''		...process.platform === "linux" && primary ? {
			titleBarStyle: "hidden",
			transparent: true,
			backgroundColor: "#00000000",
			hasShadow: true
		} : {},''',
        '主窗口：Linux 透明无边框（交通灯左置）',
        notes,
    )

    # --- 2b) 确保 screen 模块可用（maximize 兜底需要判断工作区）---
    src = replace_once(
        src,
        'import { BrowserWindow, Menu, Notification, Tray, WebContentsView, app, clipboard, dialog, ipcMain, nativeImage, nativeTheme, net, powerMonitor, protocol, session, shell, systemPreferences } from "electron"',
        'import { BrowserWindow, Menu, Notification, Tray, WebContentsView, app, clipboard, dialog, ipcMain, nativeImage, nativeTheme, net, powerMonitor, protocol, screen, session, shell, systemPreferences } from "electron"',
        '导入 screen 模块',
        notes,
    )

    # --- 4) Linux 全屏事件（data-fullscreen 的来源）---
    src = replace_once(
        src,
        '''\tif (process.platform === "darwin" || process.platform === "win32") {
\t\tconst sendFullscreen = () => {
\t\t\tif (!window.isDestroyed()) window.webContents.send(DESKTOP_IPC.windowFullscreen, window.isFullScreen());
\t\t};
\t\twindow.on("enter-full-screen", sendFullscreen);
\t\twindow.on("leave-full-screen", sendFullscreen);
\t\twindow.webContents.on("did-finish-load", sendFullscreen);
\t}''',
        '''\t// Linux is included here: the renderer keys its fullscreen layout (traffic
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
\t}''',
        'Linux 全屏/最大化事件注册',
        notes,
    )

    # --- 3) 窗口控制 IPC ---
    anchor = '\tipcMain.handle(DESKTOP_IPC.directoryPick, async (event) => {'
    handler = '''\t/**
\t* Window controls for the Linux traffic lights.
\t*
\t* The Linux build draws its own macOS-style controls in the renderer: GTK
\t* places native decorations on the right, and the Window Controls Overlay
\t* cannot be repositioned. Only the sender's own window is ever affected.
\t*/
\tipcMain.handle("dsh-desktop:linux-window-control", (event, action) => {
\t\tconst window = BrowserWindow.fromWebContents(event.sender);
\t\tif (window === null || window.isDestroyed()) return false;
\t\tif (action === "close") window.close();
\t\telse if (action === "minimize") window.minimize();
\t\telse if (action === "maximize") {
\t\t\t// Wayland compositors such as niri do not report isMaximized(), so treat a
\t\t\t// window that already fills the work area as maximized.
\t\t\tconst area = screen.getDisplayMatching(window.getBounds()).workArea;
\t\t\tconst bounds = window.getBounds();
\t\t\tconst fills = Math.abs(bounds.width - area.width) <= 2 && Math.abs(bounds.height - area.height) <= 2;
\t\t\tif (window.isMaximized() || fills) window.unmaximize();
\t\t\telse window.maximize();
\t\t} else if (action === "state") return {
\t\t\tmaximized: window.isMaximized(),
\t\t\tfullscreen: window.isFullScreen()
\t\t};
\t\telse return false;
\t\treturn true;
\t});
'''
    if 'dsh-desktop:linux-window-control' in src:
        notes.append('  · IPC 处理器已存在，跳过')
    else:
        src = replace_once(src, anchor, handler + anchor, '窗口控制 IPC 处理器', notes)

    open(main_js, 'w', encoding='utf8').write(src)
    print(f'== {main_js}')
    notes.append(f'  · IPC 处理器共 {src.count("dsh-desktop:linux-window-control")} 处（应为 1）')
    print('\n'.join(notes))
    print(inject_preload(f'{app_dir}/lib/preload-app.cjs', MAIN_MARK_CALL, ''))
    print(inject_preload(f'{app_dir}/lib/preload-welcome.cjs', WELCOME_MARK_CALL, WELCOME_EXTRA_CSS))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1]))

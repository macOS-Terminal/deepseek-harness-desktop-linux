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
import re
from pathlib import Path

TITLEBAR_HEIGHT = 48

LINUX_WELCOME_RE = re.compile(r'\t\t\.\.\.platform === "linux" \? \{.*?\n\t\t\} : \{\},\n', re.S)
LINUX_MAIN_RE = re.compile(r'\t\t\.\.\.process\.platform === "linux" && primary \? \{.*?\n\t\t\} : \{\},\n', re.S)

# 上一次插入留下的行粘连：`} : {},` 与下一行并到了同一行（块尾缺换行导致）。
# 不修掉的话，下一轮匹配不到自己的块，会以为“还没有分支”而重复插入。
MERGED_BLOCK_RE = re.compile(r'(\n\t\t\} : \{\},)\t+(\.\.\.)')

CHROME_BEGIN = '/* dsh-linux-chrome:begin v3 */'
CHROME_END = '/* dsh-linux-chrome:end */'
CHROME_BEGIN_RE = re.compile(r'/\* dsh-linux-chrome:begin v\d+ \*/')



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
    """Insert or replace the marked preload block, including legacy migration."""
    src = Path(path).read_text(encoding='utf8')
    src = src.replace(PRELOAD_FULLSCREEN_OLD, PRELOAD_FULLSCREEN_NEW, 1)
    block = PRELOAD_FN.replace('__TITLEBAR_HEIGHT__', str(TITLEBAR_HEIGHT)).replace('__EXTRA_CSS__', extra_css)
    target = f'{CHROME_BEGIN}\n{block}\ninstallLinuxChrome();\n{CHROME_END}'

    marker = CHROME_BEGIN_RE.search(src)
    if marker is not None:
        begin = marker.start()
        finish = src.find(CHROME_END, begin)
        if finish == -1:
            return f'  ✗ 注入块标记不完整（缺 {CHROME_END}）: {path}'
        finish += len(CHROME_END)
        if src[begin:finish] == target:
            return f'  · 已注入过且内容一致（标题栏），跳过: {path}'
        src = src[:begin] + target + src[finish:]
        Path(path).write_text(src, encoding='utf8')
        return f'  ✓ 注入块内容已更新为标题栏配方: {path}'

    if 'installLinuxChrome' in src:
        if call_anchor not in src:
            return f'  ✗ 旧版注入块存在但找不到锚点，无法迁移: {path}'
        head = src.index(call_anchor) + len(call_anchor)
        tail = src.index('installLinuxChrome();', head) + len('installLinuxChrome();')
        src = src[:head] + '\n' + target + src[tail:]
        Path(path).write_text(src, encoding='utf8')
        return f'  ✓ 旧版注入块已迁移到 {CHROME_BEGIN}: {path}'

    if call_anchor not in src:
        return f'  ✗ 找不到锚点: {path}'
    src = src.replace(PRELOAD_FULLSCREEN_OLD, PRELOAD_FULLSCREEN_NEW, 1)
    src = src.replace(call_anchor, call_anchor + '\n' + target + '\n', 1)
    Path(path).write_text(src, encoding='utf8')
    return f'  ✓ 注入 installLinuxChrome(): {path}'


def replace_once(src: str, old: str, new: str, label: str, notes: list) -> str:
    if new in src:
        notes.append(f'  · 已应用: {label}')
        return src
    if old not in src:
        notes.append(f'  ✗ 未匹配: {label}')
        return src
    notes.append(f'  ✓ {label}')
    return src.replace(old, new, 1)


def ensure_linux_block(src: str, pattern, new: str, anchor: str, label: str, notes: list) -> str:
    """把某个窗口的 Linux 分支做成**恰好一份**目标形态。三种来源都要走通：

    * 官方 dmg 解出来的树：没有该分支 → 在 `anchor`（同窗 win32 分支）前新增；
    * 已打过上一版补丁的树：分支形态可能是旧的 `titleBarOverlay`，也可能是内联的
      `transparent: true` → **用正则找到已有分支并整体替换**；
    * 已经被插成多份的树（历史 bug）→ 先全部删掉再写一份。

    只认某一种旧形态是不够的：识别不到就会以为“还没有分支”而再插一份，
    同一窗口出现两份配置 —— 后一份生效、前一份被断言读到，两边说法不一致。
    """
    repaired = MERGED_BLOCK_RE.sub(r'\1\n\t\t\2', src)
    if repaired != src:
        notes.append(f'  ! {label}：修复了上一次插入留下的行粘连')
        src = repaired
    if not new.endswith('\n'):
        new += '\n'
    found = list(pattern.finditer(src))
    collapsed = 0
    if len(found) > 1:
        collapsed = len(found)
        notes.append(f'  ! {label}：发现 {collapsed} 份 Linux 分支，收敛为 1 份')
        src = pattern.sub('', src)
        found = []
    if len(found) == 1:
        if found[0].group(0) == new:
            notes.append(f'  · {label}：已是目标形态，跳过')
            return src
        notes.append(f'  ✓ {label}（替换已有 Linux 分支）')
        return src[:found[0].start()] + new + src[found[0].end():]
    if anchor in src:
        notes.append(f'  ✓ {label}（{"收敛后重新写入" if collapsed else "原生树：新增"}）')
        return src.replace(anchor, new + anchor, 1)
    notes.append(f'  ✗ 未匹配: {label}（既没有已有分支，也找不到插入锚点）')
    return src


def apply_patch(app_dir: str) -> int:
    notes: list[str] = []
    main_js = f'{app_dir}/lib/main.js'
    src = Path(main_js).read_text(encoding='utf8')

    # --- 1a) 欢迎窗底色：透明 ---
    src = replace_once(
        src,
        '\t\tbackgroundColor: platform === "darwin" || platform === "win32" ? "#00000000" : "#FFFFFF",',
        '\t\tbackgroundColor: "#00000000",',
        '欢迎窗：底色改透明',
        notes,
    )

    src = ensure_linux_block(src, LINUX_WELCOME_RE, WELCOME_LINUX,
                             '\t\t...platform === "win32" ? {', '欢迎窗 Linux 无边框', notes)
    src = ensure_linux_block(src, LINUX_MAIN_RE, MAIN_LINUX,
                             '\t\t...process.platform === "win32" && primary ? {', '主窗口 Linux 无边框', notes)

    # --- 2b) 确保 screen 模块可用（maximize 兜底需要判断工作区）---
    src = replace_once(
        src,
        'import { BrowserWindow, Menu, Notification, Tray, WebContentsView, app, clipboard, dialog, ipcMain, nativeImage, nativeTheme, net, powerMonitor, protocol, session, shell, systemPreferences } from "electron"',
        'import { BrowserWindow, Menu, Notification, Tray, WebContentsView, app, clipboard, dialog, ipcMain, nativeImage, nativeTheme, net, powerMonitor, protocol, screen, session, shell, systemPreferences } from "electron"',
        '导入 screen 模块',
        notes,
    )

    src = src.replace('window.isFullScreen() || (process.platform === "linux" && window.isMaximized())',
                      'window.isFullScreen()')
    src = src.replace('\t// which only this channel sets. Tiling compositors treat a "fullscreen" window\n'
                      '\t// as merely maximised, so maximised also counts as fullscreen on Linux.',
                      '\t// which only this channel sets. Maximized windows keep their traffic lights.')

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
\t// which only this channel sets. Maximized windows keep their traffic lights.
\tif (process.platform === "darwin" || process.platform === "win32" || process.platform === "linux") {
\t\tconst sendFullscreen = () => {
\t\t\tif (window.isDestroyed()) return;
\t\t\tconst fullscreen = window.isFullScreen();
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

    src = src.replace('window.isFullScreen() || (process.platform === "linux" && window.isMaximized())',
                      'window.isFullScreen()')

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

    Path(main_js).write_text(src, encoding='utf8')
    print(f'== {main_js}')
    notes.append(f'  · IPC 处理器共 {src.count("dsh-desktop:linux-window-control")} 处（应为 1）')
    print('\n'.join(notes))
    print(inject_preload(f'{app_dir}/lib/preload-app.cjs', MAIN_MARK_CALL, ''))
    print(inject_preload(f'{app_dir}/lib/preload-welcome.cjs', WELCOME_MARK_CALL, WELCOME_EXTRA_CSS))
    return verify_end_state(app_dir)


WELCOME_LINUX = '\t\t...platform === "linux" ? {\n\t\t\ttitleBarStyle: "hidden",\n\t\t\tframe: false,\n\t\t\ttransparent: true\n\t\t} : {},'
MAIN_LINUX = '\t\t...process.platform === "linux" && primary ? {\n\t\t\ttitleBarStyle: "hidden",\n\t\t\tframe: false,\n\t\t\ttransparent: true,\n\t\t\tbackgroundColor: "#00000000",\n\t\t\thasShadow: true\n\t\t} : {},'

def verify_end_state(app_dir):
    main = Path(app_dir, 'lib/main.js').read_text()
    if main.count('...platform === "linux" ? {') != 1 or main.count('...process.platform === "linux" && primary ? {') != 1:
        return 1
    for pattern in (LINUX_WELCOME_RE, LINUX_MAIN_RE):
        match = pattern.search(main)
        if match is None or 'frame: false' not in match.group() or 'titleBarOverlay' in match.group():
            return 1
    if re.search(r'import\s*\{[^}]*\bscreen\b[^}]*\}\s*from\s*"electron"', main) is None:
        return 1
    if main.count('dsh-desktop:linux-window-control') != 1 or 'const fullscreen = window.isFullScreen();' not in main:
        return 1
    for name in ('preload-app.cjs', 'preload-welcome.cjs'):
        text = Path(app_dir, 'lib', name).read_text()
        if text.count(CHROME_BEGIN) != 1 or text.count(CHROME_END) != 1 or 'syncTilingFullscreen' in text:
            return 1
        if name == "preload-app.cjs" and 'process.platform !== "win32" && process.platform !== "linux"' not in text:
            return 1
    return 0

def main(app_dir: str) -> int:
    import shutil
    import tempfile
    target = Path(app_dir) / "lib"
    names = ("main.js", "preload-app.cjs", "preload-welcome.cjs")
    with tempfile.TemporaryDirectory(prefix="dsh-chrome-patch-") as folder:
        staged = Path(folder)
        (staged / "lib").mkdir()
        for name in names:
            shutil.copy2(target / name, staged / "lib" / name)
        if apply_patch(str(staged)) != 0:
            return 1
        for name in names:
            shutil.copyfile(staged / "lib" / name, target / name)
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1]))

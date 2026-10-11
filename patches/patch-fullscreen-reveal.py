#!/usr/bin/env python3
"""Reveal Linux fullscreen traffic lights at the full-width top edge; keep upstream state detection."""
from pathlib import Path
import sys
import re

CSS = '''
/* dsh-fullscreen-reveal:v8 */
/* Wayland cannot report a global cursor; its fullscreen strip must emit DOM events. */
html[data-dsh-mac-chrome][data-fullscreen][data-dsh-dom-pointer] [class*="_frame"]::before,
html[data-dsh-mac-chrome][data-fullscreen][data-dsh-dom-pointer] .titlebar { -webkit-app-region: no-drag !important; }
#dsh-fullscreen-reveal {
    display: none; position: fixed; top: 0; left: 0; width: 100%; height: 4px;
    z-index: 2147483645; -webkit-app-region: no-drag;
}
html[data-dsh-mac-chrome][data-fullscreen] #dsh-fullscreen-reveal { display: block; }
/* Reserve room by moving the existing controls, without painting a new surface. */
html[data-dsh-mac-chrome][data-fullscreen] button[class*="_toggle"],
html[data-dsh-mac-chrome][data-fullscreen] [class*="_collapsed"] button[class*="_newSession"] {
    translate: 0 0; transition: translate 160ms ease 80ms;
}
html[data-dsh-mac-chrome][data-fullscreen][data-dsh-reveal-controls] button[class*="_toggle"],
html[data-dsh-mac-chrome][data-fullscreen][data-dsh-reveal-controls] [class*="_collapsed"] button[class*="_newSession"] {
    translate: 76px 0; transition-delay: 0ms;
}
html[data-dsh-mac-chrome][data-fullscreen] #dsh-mac-lights {
    display: flex !important; opacity: 0; visibility: hidden; pointer-events: none;
    transition: opacity 80ms ease, visibility 0s linear 80ms;
}
html[data-dsh-mac-chrome][data-fullscreen][data-dsh-reveal-controls] #dsh-mac-lights {
    opacity: 1; visibility: visible; pointer-events: auto;
    transition: opacity 100ms ease 160ms, visibility 0s linear 160ms;
}
@media (prefers-reduced-motion: reduce) {
    html[data-dsh-mac-chrome][data-fullscreen] button[class*="_toggle"],
    html[data-dsh-mac-chrome][data-fullscreen] [class*="_collapsed"] button[class*="_newSession"],
    html[data-dsh-mac-chrome][data-fullscreen] #dsh-mac-lights { transition: none !important; }
}
'''
JS = r'''
	// dsh-fullscreen-reveal:v8
	let revealHideTimer = null;
	const hideFullscreenControls = () => {
		clearTimeout(revealHideTimer);
		revealHideTimer = null;
		delete document.documentElement.dataset.dshRevealControls;
	};
	const revealFullscreenControls = () => {
		clearTimeout(revealHideTimer);
		revealHideTimer = null;
		if (document.documentElement.hasAttribute("data-fullscreen")) document.documentElement.dataset.dshRevealControls = "";
	};
	const deferHideFullscreenControls = () => {
		if (revealHideTimer !== null || !document.documentElement.hasAttribute("data-dsh-reveal-controls")) return;
		revealHideTimer = setTimeout(hideFullscreenControls, 200);
	};
	const syncFullscreenReveal = () => {
		if (!document.documentElement.hasAttribute("data-fullscreen")) hideFullscreenControls();
		if (document.body !== null && document.getElementById("dsh-fullscreen-reveal") === null) {
			const edge = document.createElement("div");
			edge.id = "dsh-fullscreen-reveal";
			edge.setAttribute("aria-hidden", "true");
			edge.addEventListener("pointerenter", revealFullscreenControls);
			document.body.appendChild(edge);
		}
	};
	const pointerInsideToolbar = (event) => {
		// The visual top strip is painted by the frame's ::before layer.
		const frame = document.querySelector('[class*="_frame"]');
		const welcome = document.querySelector('.titlebar');
		let bounds = null;
		if (frame !== null) {
			const rect = frame.getBoundingClientRect();
			const style = getComputedStyle(frame, "::before");
			const height = parseFloat(style.height);
			const width = parseFloat(style.width);
			if (height > 0 && width > 0) {
				const left = rect.left + (parseFloat(style.left) || 0);
				const top = rect.top + (parseFloat(style.top) || 0);
				bounds = { left, top, right: left + width, bottom: top + height };
			}
		} else if (welcome !== null) bounds = welcome.getBoundingClientRect();
		return bounds !== null && event.clientX >= bounds.left && event.clientX < bounds.right && event.clientY >= bounds.top && event.clientY < bounds.bottom;
	};
	const updateFullscreenPointer = (event) => {
		if (!document.documentElement.hasAttribute("data-fullscreen")) return;
		if (event.pointerType === "touch") return;
		if (event.clientX >= 0 && event.clientX < window.innerWidth && event.clientY >= 0 && event.clientY <= 4) revealFullscreenControls();
		else if (document.documentElement.hasAttribute("data-dsh-reveal-controls") && pointerInsideToolbar(event)) revealFullscreenControls();
		else deferHideFullscreenControls();
	};
	window.addEventListener("pointermove", updateFullscreenPointer, true);
	window.addEventListener("blur", hideFullscreenControls);
	window.addEventListener("dblclick", (event) => {
		if (!document.documentElement.hasAttribute("data-dsh-dom-pointer") || !document.documentElement.hasAttribute("data-fullscreen")) return;
		if (!pointerInsideToolbar(event) || event.target.closest('button, a, input, [role="button"]') !== null) return;
		electron.ipcRenderer.invoke(CHANNEL, "titlebar-double-click");
	}, true);
	document.addEventListener("pointerleave", () => {
		if (document.documentElement.hasAttribute("data-dsh-dom-pointer")) deferHideFullscreenControls();
	});
	// Native drag regions suppress DOM pointer events. Read the cursor from the
	// owning window instead, preserving native drag and double-click behavior.
	let pointerPollPending = false;
	const pollFullscreenPointer = async () => {
		if (pointerPollPending || document.documentElement === null) return;
		pointerPollPending = true;
		try {
			const state = await electron.ipcRenderer.invoke(CHANNEL, "pointer-state");
			if (!state || typeof state.fullscreen !== "boolean") return;
			const root = document.documentElement;
			if (state.domPointer) root.dataset.dshDomPointer = "";
			else delete root.dataset.dshDomPointer;
			const effective = state.fullscreen || state.maximized;
			if (root.dataset.dshWindowFullscreen !== String(effective)) {
				root.dataset.dshWindowFullscreen = String(effective);
				syncTilingFullscreen();
			}
			if (!state.focused) hideFullscreenControls();
			else if (Number.isFinite(state.x) && Number.isFinite(state.y)) updateFullscreenPointer({ clientX: state.x, clientY: state.y });
		} catch { /* Keep DOM hover available when the host cannot report a cursor. */ }
		finally { pointerPollPending = false; }
	};
	const pointerPoll = setInterval(pollFullscreenPointer, 100);
	window.addEventListener("beforeunload", () => clearInterval(pointerPoll), { once: true });
	const fullscreenRevealObserver = new MutationObserver(syncFullscreenReveal);
	const observeFullscreenReveal = () => {
		if (document.documentElement !== null) fullscreenRevealObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-fullscreen"] });
	};
	if (document.documentElement !== null) observeFullscreenReveal();
	else document.addEventListener("DOMContentLoaded", observeFullscreenReveal, { once: true });
'''

MAIN_POINTER = r'''
		if (action === "titlebar-double-click") {
			if (!window.isFullScreen()) {
				if (window.isMaximized()) window.unmaximize(); else window.maximize();
			}
			return true;
		}
		// dsh-fullscreen-pointer:v2: content coordinates, including zoom and monitor offsets.
		if (action === "pointer-state") {
			if (event.senderFrame !== event.sender.mainFrame) return false;
			const platform = app.commandLine.getSwitchValue("ozone-platform");
			const domPointer = platform === "wayland" || (platform !== "x11" && process.env.XDG_SESSION_TYPE === "wayland");
			const base = { domPointer, focused: window.isFocused(), fullscreen: window.isFullScreen(), maximized: window.isMaximized() };
			if (domPointer) return base;
			const cursor = screen.getCursorScreenPoint();
			const bounds = window.getContentBounds();
			const zoom = event.sender.getZoomFactor();
			return { x: (cursor.x - bounds.x) / zoom, y: (cursor.y - bounds.y) / zoom,
				...base };
		}
'''

def transform_main(src):
    if '// dsh-fullscreen-pointer:v2' in src:return src
    if '// dsh-fullscreen-pointer:v1' in src:
        src=re.sub(r'\n\t\t// dsh-fullscreen-pointer:v1:.*?\n\t\t\}\n', '\n',src,count=1,flags=re.S)
    anchor='\t\tif (action === "chrome-style") {'
    if src.count(anchor)!=1:raise ValueError('Unknown window control IPC anchor')
    return src.replace(anchor,MAIN_POINTER+'\n'+anchor,1)

def transform(src):
    if '// dsh-fullscreen-reveal:v8' in src:return src
    if any(f'// dsh-fullscreen-reveal:v{version}' in src for version in (2, 3, 4, 5, 6, 7)):
        css_pattern = r'\n/\* dsh-fullscreen-reveal:v[234567] \*/.*?#dsh-mac-lights \{ transition: none !important; \}\n\}\n'
        js_pattern = r'\n\t// dsh-fullscreen-reveal:v[234567].*?\telse document.addEventListener\("DOMContentLoaded", observeFullscreenReveal, \{ once: true \}\);\n'
        src, css_count = re.subn(css_pattern, lambda _: CSS, src, count=1, flags=re.S)
        src, js_count = re.subn(js_pattern, lambda _: JS, src, count=1, flags=re.S)
        if css_count != 1 or js_count != 1:raise ValueError('Unknown previous fullscreen reveal patch')
        src = re.sub(r"\n/\* A native drag region.*?no-drag !important; \}\n", "\n", src, count=1, flags=re.S)
        src = src.replace("width: 180px; height: 4px", "width: 100%; height: 4px", 1)
        return src
    if '// dsh-fullscreen-reveal:v1' in src:
        css_pattern = r'\n/\* dsh-fullscreen-reveal:v1 \*/.*?html\[data-dsh-mac-chrome\]\[data-fullscreen\]\[data-dsh-reveal-controls\] #dsh-mac-lights \{ display: flex !important; \}\n'
        js_pattern = r'\n\t// dsh-fullscreen-reveal:v1.*?\telse document.addEventListener\("DOMContentLoaded", observeFullscreenReveal, \{ once: true \}\);\n'
        src, css_count = re.subn(css_pattern, lambda _: CSS, src, count=1, flags=re.S)
        src, js_count = re.subn(js_pattern, lambda _: JS, src, count=1, flags=re.S)
        if css_count != 1 or js_count != 1:raise ValueError('Unknown previous fullscreen reveal patch')
        return src
    css='html[data-dsh-mac-chrome][data-fullscreen] #dsh-mac-lights { display: none !important; }'
    declaration='\tlet lights = null;'
    apply='\t\tsyncChromeStyle();'
    for anchor in [css,declaration,apply]:
        if src.count(anchor)!=1:raise ValueError(f'Unknown chrome anchor: {anchor}')
    src=src.replace(css,css+CSS,1).replace(declaration,declaration+JS,1)
    return src.replace(apply,'\t\tsyncFullscreenReveal();\n'+apply,1)

def main(app_dir):
    root=Path(app_dir)/'lib'
    try:
        main_path=root/'main.js'
        pending={main_path:transform_main(main_path.read_text())}
        for name in ['preload-app.cjs','preload-welcome.cjs']:
            p=root/name;pending[p]=transform(p.read_text())
    except (OSError,ValueError) as error:
        print(f'Fullscreen reveal patch failed: {error}',file=sys.stderr);return 1
    for p,text in pending.items():
        if p.read_text()!=text:p.write_text(text)
    return 0
if __name__=='__main__':raise SystemExit(main(sys.argv[1]))

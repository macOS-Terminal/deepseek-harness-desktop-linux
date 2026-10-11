#!/usr/bin/env python3
"""Request KWin blur on verified X11 windows, otherwise keep KDE opaque."""
from pathlib import Path
import re
import sys

MAIN_JS = r'''
	// dsh-kde-material:v1
	const kdeBlurResults = new WeakMap();
	const configureKdeBlur = (window) => {
		if (kdeBlurResults.has(window)) return kdeBlurResults.get(window);
		const request = (async () => {
			const desktop = `${process.env.XDG_CURRENT_DESKTOP ?? ""} ${process.env.DESKTOP_SESSION ?? ""}`.toLowerCase();
			const kde = desktop.includes("kde") || desktop.includes("plasma") || Boolean(process.env.KDE_FULL_SESSION);
			if (process.platform !== "linux" || !kde || app.commandLine.getSwitchValue("ozone-platform") === "wayland") return false;
			try {
				const handle = window.getNativeWindowHandle();
				const id = handle.length === 8 ? handle.readBigUInt64LE() : BigInt(handle.readUInt32LE());
				if (id === 0n || id > 0xffffffffn) return false;
				const xid = `0x${id.toString(16)}`;
				const xprop = (args) => new Promise((resolve, reject) => {
					execFile("xprop", args, { timeout: 2000, maxBuffer: 65536, encoding: "utf8" }, (error, stdout) => {
						if (error) reject(error); else resolve(stdout);
					});
				});
				// Verify actual X11 ownership; a Wayland session can also have DISPLAY.
				const owner = await xprop(["-id", xid, "_NET_WM_PID"]);
				if (!new RegExp(`_NET_WM_PID\\(CARDINAL\\) = ${process.pid}\\s*$`).test(owner) || window.isDestroyed()) return false;
				await xprop(["-id", xid, "-f", "_KDE_NET_WM_BLUR_BEHIND_REGION", "32c", "-set", "_KDE_NET_WM_BLUR_BEHIND_REGION", "0"]);
				return !window.isDestroyed();
			} catch (error) {
				console.warn("KDE X11 blur unavailable; using opaque background:", error.message);
				return false;
			}
		})();
		kdeBlurResults.set(window, request);
		return request;
	};
'''

PRELOAD_POLICY = r'''		// KDE starts opaque; only a verified X11 blur request enables translucency.
		const desktopSession = `${process.env.XDG_CURRENT_DESKTOP ?? ""} ${process.env.DESKTOP_SESSION ?? ""}`.toLowerCase();
		const kdeSession = desktopSession.includes("kde") || desktopSession.includes("plasma")
			|| Boolean(process.env.KDE_FULL_SESSION);
		if (kdeSession && !kdeBlurReady) root.dataset.dshOpaqueSidebar = "";
		else delete root.dataset.dshOpaqueSidebar;
'''

def transform_main(src):
    if '// dsh-kde-material:v1' in src:
        return src
    anchor = '\tipcMain.handle("dsh-desktop:linux-window-control", async (event, action, css) => {'
    state = '\t\tif (action === "chrome-style") {'
    if src.count(anchor) != 1 or src.count(state) != 1:
        raise ValueError('Unknown Linux window-control IPC handler')
    src = src.replace(anchor, MAIN_JS + anchor, 1)
    return src.replace(state, '\t\tif (action === "material") return configureKdeBlur(window);\n' + state, 1)

def transform_preload(src):
    if '// dsh-kde-material:v1' in src:
        return src
    style = '\tlet chromeStyleApplied = false;'
    invoke = '\t\t\tchromeStyleApplied = await electron.ipcRenderer.invoke(CHANNEL, "chrome-style", CSS) === true;'
    if src.count(style) != 1 or src.count(invoke) != 1:
        raise ValueError('Unknown chrome preload stylesheet installer')
    src = src.replace(style, '\t// dsh-kde-material:v1\n\tlet kdeBlurReady = false;\n' + style, 1)
    src = src.replace(invoke, invoke + '\n\t\t\tif (chromeStyleApplied) {\n\t\t\t\tkdeBlurReady = await electron.ipcRenderer.invoke(CHANNEL, "material") === true;\n\t\t\t\tapply();\n\t\t\t}', 1)
    pattern = r'\t\t// KDE Plasma.*?\t\telse delete root.dataset.dshOpaqueSidebar;\n'
    src, count = re.subn(pattern, lambda _: PRELOAD_POLICY, src, count=1, flags=re.S)
    if count != 1:
        raise ValueError('Unknown KDE opaque-background policy')
    return src

def main(app_dir):
    root = Path(app_dir)/'lib'
    try:
        pending = {root/'main.js': transform_main((root/'main.js').read_text())}
        for name in ['preload-app.cjs','preload-welcome.cjs']:
            p=root/name;pending[p]=transform_preload(p.read_text())
    except (OSError, ValueError) as error:
        print(f'KDE material patch failed: {error}', file=sys.stderr)
        return 1
    for p,text in pending.items():
        if p.read_text()!=text:p.write_text(text)
    return 0

if __name__=='__main__':
    raise SystemExit(main(sys.argv[1]))

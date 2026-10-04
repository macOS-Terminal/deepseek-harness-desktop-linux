"""Patch migration and generated JS runtime checks; no downloads or dependencies.

Run: python3 -m unittest discover -s tests -v
"""
import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("chrome", ROOT / "patches/patch-mac-chrome.py")
chrome = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chrome)


class LinuxChromeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dsh-chrome-test-")
        self.app = Path(self.temp.name)
        (self.app / "lib").mkdir()
        (self.app / "lib/main.js").write_text('''
function welcomeWindowOptions(platform) {
    return {
\t\t...platform === "win32" ? { titleBarStyle: "hidden" } : {},
    };
}
function createWindow(primary) {
    return {
\t\t...process.platform === "win32" && primary ? { titleBarStyle: "hidden" } : {},
    };
}
function registerIpc() {
\tipcMain.handle(DESKTOP_IPC.directoryPick, async (event) => {});
}
function wireFullscreen(window) {
\tif (process.platform === "darwin" || process.platform === "win32") {
\t\tconst sendFullscreen = () => {
\t\t\tif (!window.isDestroyed()) window.webContents.send(DESKTOP_IPC.windowFullscreen, window.isFullScreen());
\t\t};
\t\twindow.on("enter-full-screen", sendFullscreen);
\t\twindow.on("leave-full-screen", sendFullscreen);
\t\twindow.webContents.on("did-finish-load", sendFullscreen);
\t}
}
''')
        (self.app / "lib/preload-app.cjs").write_text(chrome.MAIN_MARK_CALL)
        (self.app / "lib/preload-welcome.cjs").write_text(chrome.WELCOME_MARK_CALL)

    def tearDown(self):
        self.temp.cleanup()

    def apply(self, automatic=True):
        with patch.object(chrome, "SIDEBAR_TRANSLUCENT", automatic), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(chrome.main(str(self.app)), 0)

    def contents(self):
        return {p.name: p.read_bytes() for p in (self.app / "lib").iterdir()}

    def test_fresh_tree_and_idempotency(self):
        self.apply()
        once = self.contents()
        self.apply()
        self.assertEqual(once, self.contents())
        for path in (self.app / "lib").iterdir():
            subprocess.run(["node", "--check", str(path)], check=True, capture_output=True)

    def test_switch_material_and_upgrade_v2(self):
        self.apply(False)
        for path in (self.app / "lib").glob("preload-*.cjs"):
            path.write_text(path.read_text().replace(chrome.CHROME_BEGIN, "/* dsh-linux-chrome:begin v2 */"))
        self.apply(True)
        self.assertNotIn(b"begin v2", self.contents()["preload-app.cjs"])
        self.apply(False)
        self.assertNotIn(b"filter: blur(28px)", self.contents()["preload-app.cjs"])
        self.apply(True)
        self.assertIn(b"filter: blur(28px)", self.contents()["preload-app.cjs"])

    def test_legacy_handler_upgrade(self):
        self.apply(False)
        path = self.app / "lib/main.js"
        path.write_text(path.read_text().replace(
            'ipcMain.handle("dsh-desktop:linux-window-control", async (event, action)',
            'ipcMain.handle("dsh-desktop:linux-window-control", (event, action)'
        ).replace('\t\tif (action === "blur") return requestLinuxBlur(window);\n', ''))
        self.apply()
        self.assertEqual(path.read_text().count('if (action === "blur")'), 1)

    def test_missing_upstream_anchor_leaves_sources_untouched(self):
        path = self.app / "lib/preload-welcome.cjs"
        path.write_text("// upstream changed the preload entry\n")
        before = self.contents()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(chrome.main(str(self.app)), 1)
        self.assertEqual(before, self.contents())

    def test_legacy_unmarked_tree_migration(self):
        self.apply()
        for path in (self.app / "lib").glob("preload-*.cjs"):
            path.write_text(path.read_text().replace(chrome.CHROME_BEGIN, "").replace(chrome.CHROME_END, ""))
        self.apply()
        self.assertEqual(self.contents()["preload-welcome.cjs"].count(chrome.CHROME_BEGIN.encode()), 1)

    def test_generated_runtime(self):
        for automatic in (True, False):
            self.apply(automatic)
            result = subprocess.run(
                ["node", str(ROOT / "tests/linux-blur-runtime.cjs"), str(self.app),
                 "auto" if automatic else "solid"], text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("runtime checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()

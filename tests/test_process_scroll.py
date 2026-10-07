"""Optional browser regression for the long-reasoning resize feedback loop."""
import importlib.util
from pathlib import Path
import shutil
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("chrome_scroll", ROOT / "patches/patch-mac-chrome.py")
chrome = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chrome)


class ProcessScrollTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("chromium") and shutil.which("node"), "requires Chromium and Node")
    def test_long_reasoning_keeps_process_body_visible(self):
        css = chrome.PRELOAD_FN.split("const CSS = `", 1)[1].split("`;", 1)[0]
        css = re.sub(r"__[A-Z_]+__", "", css)
        result = subprocess.run(
            ["node", str(ROOT / "tests/process-scroll-runtime.cjs"), shutil.which("chromium")],
            input=css, text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

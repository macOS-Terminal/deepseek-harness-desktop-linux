from test_kde_material import load, chrome
from pathlib import Path
import subprocess
import unittest
import json
reveal=load('patch-fullscreen-reveal')
ROOT=Path(__file__).resolve().parents[1]
class FullscreenRevealTests(unittest.TestCase):
 def test_pointer_lifecycle_and_normal_window(self):
  r=subprocess.run(['node',str(ROOT/'tests/fullscreen-reveal-runtime.cjs')],input=reveal.JS,text=True,capture_output=True)
  self.assertEqual(r.returncode,0,r.stdout+r.stderr)
 def test_generated_preload_keeps_upstream_detection(self):
  src=chrome.PRELOAD_FN.replace('__TITLEBAR_HEIGHT__','48').replace('__EXTRA_CSS__',chrome.WELCOME_EXTRA_CSS)
  patched=reveal.transform(src)
  self.assertEqual(reveal.transform(patched),patched)
  self.assertIn("[data-dsh-dom-pointer] .titlebar",patched)
  before=src[src.index('\tconst syncTilingFullscreen'):src.index('\tlet chromeStylePending')]
  self.assertIn(before,patched)
  r=subprocess.run(['node','--check'],input=patched,text=True,capture_output=True)
  self.assertEqual(r.returncode,0,r.stderr)
 def test_native_pointer_coordinates_and_wayland_state(self):
  r=subprocess.run(['node',str(ROOT/'tests/fullscreen-pointer-runtime.cjs')],input=json.dumps({'main':reveal.MAIN_POINTER,'preload':reveal.JS}),text=True,capture_output=True)
  self.assertEqual(r.returncode,0,r.stdout+r.stderr)
 def test_unknown_payload_rejected(self):
  with self.assertRaises(ValueError):reveal.transform('unknown preload')

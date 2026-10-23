import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'patches'/f'{name}.py')
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
material=load('patch-kde-material');chrome=load('patch-mac-chrome')
class KdeMaterialTests(unittest.TestCase):
 def test_actual_x11_ownership_and_safe_fallback(self):
  r=subprocess.run(['node',str(ROOT/'tests/kde-material-runtime.cjs')],input=material.MAIN_JS,text=True,capture_output=True)
  self.assertEqual(r.returncode,0,r.stdout+r.stderr)
 def test_preload_idempotency_and_syntax(self):
  src=chrome.PRELOAD_FN.replace('__TITLEBAR_HEIGHT__','48').replace('__EXTRA_CSS__',chrome.WELCOME_EXTRA_CSS)
  patched=material.transform_preload(src)
  self.assertEqual(material.transform_preload(patched),patched)
  r=subprocess.run(['node','--check'],input=patched,text=True,capture_output=True)
  self.assertEqual(r.returncode,0,r.stderr)
 def test_unrecognized_payload_is_not_written(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'lib';root.mkdir()
   main='function register(){\n\tipcMain.handle("dsh-desktop:linux-window-control", async (event, action, css) => {\n\t\tif (action === "chrome-style") {}\n});\n}'
   (root/'main.js').write_text(main)
   for n in ['preload-app.cjs','preload-welcome.cjs']:(root/n).write_text('unknown preload')
   before={p.name:p.read_text() for p in root.iterdir()}
   self.assertEqual(material.main(d),1)
   self.assertEqual(before,{p.name:p.read_text() for p in root.iterdir()})

from test_kde_material import chrome
from pathlib import Path
import subprocess
import tempfile
import unittest

class WelcomeSurfaceTests(unittest.TestCase):
 def test_existing_welcome_upgrade_is_idempotent_and_scoped(self):
  with tempfile.TemporaryDirectory() as d:
   lib=Path(d)/'lib';lib.mkdir()
   app=lib/'preload-app.cjs';app.write_text('unchanged main preload')
   welcome=lib/'preload-welcome.cjs'
   welcome.write_text(chrome.PRELOAD_FN.replace('__TITLEBAR_HEIGHT__','48').replace('__EXTRA_CSS__','\nhtml[data-dsh-mac-chrome] .titlebar { padding-left: 68px; }\n'))
   chrome.upgrade_welcome_surface(d)
   once=welcome.read_text();chrome.upgrade_welcome_surface(d)
   self.assertEqual(welcome.read_text(),once)
   self.assertEqual(app.read_text(),'unchanged main preload')
   subprocess.run(['node','--check',str(welcome)],check=True,capture_output=True)
 def test_unknown_welcome_is_not_modified(self):
  with tempfile.TemporaryDirectory() as d:
   lib=Path(d)/'lib';lib.mkdir();p=lib/'preload-welcome.cjs';p.write_text('unknown')
   with self.assertRaises(ValueError):chrome.upgrade_welcome_surface(d)
   self.assertEqual(p.read_text(),'unknown')

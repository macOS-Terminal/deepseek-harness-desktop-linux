import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('identity',ROOT/'patches/patch-linux-identity.py')
identity=importlib.util.module_from_spec(spec);spec.loader.exec_module(identity)
class LinuxIdentityTests(unittest.TestCase):
 def test_desktop_entry_match_and_metadata_preserved(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'package.json'
   package={'name':'@deepseek-ai/dsh-desktop','version':'0.2.0-rc.2','main':'lib/main.js','dshDesktopAppId':'com.deepseek.dsh'}
   path.write_text(json.dumps(package))
   identity.main(directory)
   actual=json.loads(path.read_text())
   self.assertEqual({k:v for k,v in actual.items() if k!='desktopName'},package)
   self.assertEqual(actual['desktopName'], 'deepseek-harness.desktop')
   self.assertTrue((ROOT/'icons'/actual['desktopName']).is_file())
   first=path.read_bytes();identity.main(directory);self.assertEqual(path.read_bytes(),first)

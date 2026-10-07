"""Architecture mismatch and symbol-targeted fingerprint regression tests."""
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from elf_payload import ELF

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

PATCH = load('fingerprint', ROOT / 'patches/patch-fingerprint.py')
AUDIT = load('architecture', ROOT / 'scripts/verify-architecture.py')

def payload(machine, duplicate=False, changed=False):
    data = bytearray(1024)
    data[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', data, 18, machine)
    struct.pack_into('<Q', data, 40, 64)
    struct.pack_into('<HH', data, 58, 64, 4)
    original, _ = PATCH.LAYOUTS[machine]
    data[400:400 + len(original)] = original
    data[440:440 + len(original)] = original  # decoy prologue must not be patched
    if changed:
        data[400] = 0
    names = b'\0' + PATCH.SYMBOL + b'\0'
    data[700:700 + len(names)] = names
    sections = [(0,) * 10, (0, 1, 6, 0x1000, 400, 80, 0, 0, 1, 0),
                (0, 2, 0, 0, 600, 48 if duplicate else 24, 3, 0, 8, 24),
                (0, 3, 0, 0, 700, len(names), 0, 0, 1, 0)]
    for index, section in enumerate(sections):
        struct.pack_into('<IIQQQQIIQQ', data, 64 + index * 64, *section)
    struct.pack_into('<IBBHQQ', data, 600, 1, 2, 0, 1, 0x1000, 32)
    if duplicate:
        struct.pack_into('<IBBHQQ', data, 624, 1, 2, 0, 1, 0x1028, 32)
    return data

class ArchitectureTests(unittest.TestCase):
    def test_patch_uses_machine_and_symbol_not_filename_or_prologue_scan(self):
        for machine in PATCH.LAYOUTS:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'unrelated-name.node'
                data = payload(machine)
                path.write_bytes(data)
                PATCH.patch(path)
                expected = bytearray(data)
                replacement = PATCH.LAYOUTS[machine][1]
                expected[400:400 + len(replacement)] = replacement
                self.assertEqual(path.read_bytes(), expected)
                PATCH.patch(path)
                self.assertEqual(path.read_bytes(), expected)

    def test_unknown_and_ambiguous_layouts_fail_without_writes(self):
        for options in ({'duplicate': True}, {'changed': True}):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'addon.node'
                data = payload(183, **options)
                path.write_bytes(data)
                with self.assertRaises(ValueError):
                    PATCH.patch(path)
                self.assertEqual(path.read_bytes(), data)
        with self.assertRaises(ValueError):
            ELF(b'not an ELF file')

    def test_audit_rejects_mixed_architecture_and_missing_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(ValueError):
                AUDIT.audit(root, 'arm64')
            for name in ['deepseek-harness',
                         'resources/runtime/primary-runtime/dependencies/node/bin/node',
                         'resources/runtime/primary-runtime/dependencies/python/bin/python3']:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload(183))
            self.assertEqual(AUDIT.audit(root, 'arm64'), 3)
            (root / 'bad.node').write_bytes(payload(62))
            with self.assertRaisesRegex(ValueError, 'bad.node'):
                AUDIT.audit(root, 'arm64')

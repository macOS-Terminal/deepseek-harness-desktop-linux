"""Offline regression tests for build orchestration and payload conversion."""
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ASAR = load('extract-asar')
NPM = load('npm-linux-swap')


class BuildCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.root.mkdir()
        shutil.copy2(ROOT / 'auto-build.sh', self.root)
        shutil.copytree(ROOT / 'scripts', self.root / 'scripts')
        self.bin = Path(self.temp.name) / 'bin'
        self.bin.mkdir()
        self.marker = Path(self.temp.name) / 'network-used'
        # Any curl call marks this run as having touched the network.
        curl = self.bin / 'curl'
        curl.write_text('#!/bin/sh\ntouch "$NETWORK_MARKER"\nexit 99\n')
        curl.chmod(0o755)
        self.env = dict(os.environ, PATH=f'{self.bin}:{os.environ["PATH"]}',
                        NETWORK_MARKER=str(self.marker))
        self.env.pop('DSH_STORE', None)

    def run_cli(self, *args):
        return subprocess.run(['bash', str(self.root / 'auto-build.sh'), *args],
                              env=self.env, capture_output=True, text=True)

    def test_help_and_dry_run_do_not_write_or_use_network(self):
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        for args in [('--help',), ('--dry-run', '--arch', 'all'),
                     ('--dry-run', '--force', '--only', 'tree,package'),
                     ('--dry-run', '--clean', '--arch', 'all')]:
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')))
        self.assertFalse(self.marker.exists())

    def test_invalid_options_fail_before_writes(self):
        for args in [('--unknown',), ('--only', 'bogus'), ('--only', 'tree,'),
                     ('--jobs', '0'), ('--jobs', 'abc'), ('--arch', 'sparc'),
                     ('--store', '/tmp/../etc'), ('--work', '/tmp/../usr'),
                     ('--work', 'relative')]:
            result = self.run_cli(*args)
            self.assertNotEqual(result.returncode, 0, args)
        self.assertFalse((self.root / 'dl').exists())

    def test_architectures_are_deduplicated(self):
        result = self.run_cli('--dry-run', '--only', 'tree', '--arch', 'all', 'x64')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count('阶段 2/3 生成应用树 out-x64'), 1)

    def test_local_dmg_does_not_download_dmg(self):
        local = Path(self.temp.name) / 'input.dmg'
        local.write_bytes(b'fixture')
        result = self.run_cli('--dry-run', '--only', 'prepare', '--dmg', str(local))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('使用本地 dmg', result.stdout)
        self.assertNotIn('下载 https://download.deepseek.com/', result.stdout)
        self.assertFalse(self.marker.exists())

    def package_fixture(self, fail=False):
        shutil.copytree(ROOT / 'icons', self.root / 'icons')
        tree = self.root / 'out-x64'
        tree.mkdir()
        (tree / 'payload').write_bytes(b'app')
        backup = tree / 'resources/app/dsh/node_modules/.sharp-native-backup'
        backup.mkdir(parents=True)
        (backup / 'diagnostic').write_bytes(b'backup')
        store = Path(self.temp.name) / 'store'
        for name in ['others/dmg', 'dl/pip-cache', 'tools/usr/bin', 'dl/npm', 'work/x64']:
            (store / name).mkdir(parents=True, exist_ok=True)
        (store / 'others/input.dmg').write_bytes(b'dmg')
        (store / 'dl/npm/pkg.tgz').write_bytes(b'cached')
        (store / 'tools/runtime-x86_64').write_bytes(b'runtime')
        tool = store / 'tools/usr/bin/mksquashfs'
        tool.write_text('#!/bin/sh\n' + ('exit 1\n' if fail else
                        'test ! -e "$1/resources/app/dsh/node_modules/.sharp-native-backup" || exit 2\n'
                        'printf squashfs > "$2"\n'))
        tool.chmod(0o755)
        return store

    def test_default_keeps_all_build_outputs(self):
        store = self.package_fixture()
        result = self.run_cli('--only', 'package', '--store', str(store))
        self.assertEqual(result.returncode, 0, result.stderr)
        for path in ['others/dmg', 'dl/pip-cache', 'work/x64/DeepSeek-Harness.AppDir',
                     'work/x64/app.squashfs']:
            self.assertTrue((store / path).exists(), path)
        self.assertTrue((self.root / 'out-x64/resources/app/dsh/node_modules/.sharp-native-backup').exists())

    def test_explicit_clean_preserves_downloads_and_final_artifacts(self):
        store = self.package_fixture()
        result = self.run_cli('--only', 'package', '--store', str(store), '--clean')
        self.assertEqual(result.returncode, 0, result.stderr)
        for path in ['others/dmg', 'dl/pip-cache', 'work/x64']:
            self.assertFalse((store / path).exists(), path)
        self.assertFalse((self.root / 'out-x64').exists())
        for path in ['others/input.dmg', 'dl/npm/pkg.tgz', 'tools/runtime-x86_64']:
            self.assertTrue((store / path).exists(), path)
        self.assertTrue(list((self.root / 'dist').glob('*.AppImage')))
        self.assertTrue(list((self.root / 'dist').glob('*.sha256')))

    def test_failed_build_keeps_files_even_with_clean(self):
        store = self.package_fixture(fail=True)
        result = self.run_cli('--only', 'package', '--store', str(store), '--clean')
        self.assertNotEqual(result.returncode, 0)
        for path in ['others/dmg', 'dl/pip-cache', 'work/x64/DeepSeek-Harness.AppDir']:
            self.assertTrue((store / path).exists(), path)
        self.assertTrue((self.root / 'out-x64').exists())


class AsarExtraction(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def archive(self, files, payload=b'hello'):
        data = json.dumps({'files': files}).encode()
        padded = (len(data) + 3) // 4 * 4
        archive = self.root / 'app.asar'
        archive.write_bytes(struct.pack('<IIII', 4, padded + 8, padded + 4, len(data))
                            + data + b'\0' * (padded - len(data)) + payload)
        return archive

    def test_packed_unpacked_and_link(self):
        archive = self.archive({'a': {'size': 5, 'offset': '0', 'executable': True},
                                'b': {'size': 1, 'unpacked': True}, 'c': {'link': 'a'}})
        unpacked = self.root / 'unpacked'
        unpacked.mkdir()
        (unpacked / 'b').write_bytes(b'x')
        dest = self.root / 'out'
        ASAR.main(['extract', str(archive), str(dest), '--unpacked', str(unpacked)])
        self.assertEqual((dest / 'a').read_bytes(), b'hello')
        self.assertTrue((dest / 'a').stat().st_mode & 0o100)
        self.assertEqual((dest / 'b').read_bytes(), b'x')
        self.assertEqual((dest / 'c').read_bytes(), b'hello')

    def test_invalid_entries_and_missing_payload_fail(self):
        for files, payload in [({'..': {'files': {}}}, b''),
                               ({'a': {'size': 10, 'offset': '0'}}, b'x'),
                               ({'a': {'size': 1, 'unpacked': True}}, b''),
                               ({'a': {'link': '../outside'}}, b'')]:
            archive = self.archive(files, payload)
            with self.assertRaises(SystemExit):
                ASAR.main(['extract', str(archive), str(self.root / 'out')])


class NpmConversion(unittest.TestCase):
    def test_exact_version_required_unless_explicitly_allowed(self):
        class Registry:
            def versions(self, name):
                return ['1.0.0', '1.2.0']
        self.assertEqual(NPM.pick_version(Registry(), 'pkg', '1.2.0')[0], '1.2.0')
        with self.assertRaises(LookupError):
            NPM.pick_version(Registry(), 'pkg', '1.1.0')
        self.assertEqual(NPM.pick_version(Registry(), 'pkg', '1.1.0', True)[0], '1.0.0')

    def test_digest_verification(self):
        digest = base64.b64encode(hashlib.sha512(b'payload').digest()).decode()
        self.assertTrue(NPM.verify_digest_bytes(b'payload', f'sha512-{digest}'))
        self.assertFalse(NPM.verify_digest_bytes(b'corrupt', f'sha512-{digest}'))

    def test_cached_tarball_is_verified_before_reuse(self):
        payload = b'valid'
        digest = base64.b64encode(hashlib.sha512(payload).digest()).decode()

        class Registry(NPM.Registry):
            def metadata(self, name, version=None):
                return {'dist': {'integrity': f'sha512-{digest}', 'tarball': 'https://fixture/pkg'}}

            def _get(self, url, timeout=30):
                return payload

        with tempfile.TemporaryDirectory() as temporary:
            cached = Path(temporary) / 'pkg-1.0.tgz'
            cached.write_bytes(b'corrupt')
            registry = Registry(['https://fixture'], temporary)
            self.assertEqual(Path(registry.tarball('pkg', '1.0', None)).read_bytes(), payload)

    def test_platform_and_wasm_plans(self):
        package = {'name': '@img/sharp-darwin-arm64', 'token': 'darwin-arm64', 'version': '1.0'}
        self.assertEqual(NPM.plan_for(package, 'x64', {})['name'], '@img/sharp-linux-x64')
        package['name'] = '@deepseek-ai/libreoffice-kit-darwin-arm64'
        plan = NPM.plan_for(package, 'arm64', {'wasm': '0.1.0'})
        self.assertEqual((plan['name'], plan['version']), ('@deepseek-ai/libreoffice-kit-wasm', '0.1.0'))

    def test_tar_extraction_rejects_escape_and_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, kind in [('package/file', tarfile.REGTYPE),
                               ('package/../../outside', tarfile.REGTYPE),
                               ('package/link', tarfile.SYMTYPE)]:
                archive = root / 'pkg.tgz'
                with tarfile.open(archive, 'w:gz') as handle:
                    entry = tarfile.TarInfo(name)
                    entry.type = kind
                    entry.size = 1 if kind == tarfile.REGTYPE else 0
                    entry.linkname = '../../outside' if kind == tarfile.SYMTYPE else ''
                    handle.addfile(entry, io.BytesIO(b'x') if entry.size else None)
                if name == 'package/file':
                    self.assertEqual(NPM.extract_package(str(archive), str(root / 'out')), 1)
                    self.assertEqual((root / 'out/file').read_bytes(), b'x')
                else:
                    with self.assertRaises(ValueError):
                        NPM.extract_package(str(archive), str(root / 'out'))
                self.assertFalse((root.parent / 'outside').exists())


if __name__ == '__main__':
    unittest.main()

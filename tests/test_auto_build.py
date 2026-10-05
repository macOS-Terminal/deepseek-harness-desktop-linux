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
        shutil.copy2(ROOT / 'build-packages.sh', self.root)
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
        self.env.pop('DSH_TRANSLUCENT_SIDEBAR', None)

    def run_cli(self, *args):
        return subprocess.run(['bash', str(self.root / 'auto-build.sh'), *args],
                              env=self.env, capture_output=True, text=True)

    def test_help_and_dry_run_do_not_write_or_use_network(self):
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        for args in [('--help',), ('--dry-run', '--arch', 'all'),
                     ('--dry-run', '--translucent-sidebar'),
                     ('--dry-run', '--opaque-sidebar'),
                     ('--dry-run', '--force', '--only', 'tree,package'),
                     ('--dry-run', '--clean', '--arch', 'all')]:
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')))
        self.assertFalse(self.marker.exists())

    def test_invalid_options_fail_before_writes(self):
        for args in [('--unknown',), ('--only', 'bogus'), ('--only', 'tree,'),
                     ('--jobs', '0'), ('--jobs', 'abc'), ('--arch', 'sparc'),
                     ('--package-jobs', '0'), ('--package-jobs', '-1'), ('--package-jobs', 'abc'),
                     ('--electron', 'invalid'), ('--formats', 'appimage', '--electron', 'system'),
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
        runtime = tree / 'resources/runtime/primary-runtime/runtime.json'
        runtime.parent.mkdir(parents=True)
        runtime.write_text(json.dumps({'desktopVersion': '0.2.0-rc.2'}))
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

    def test_format_selection_and_legacy_entry(self):
        result = self.run_cli('--dry-run', '--only', 'package', '--formats', 'deb,deb')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count('打包 deb（'), 1)
        self.assertNotIn('阶段 3/3 打包 AppImage', result.stdout)
        self.assertNotIn('打包 rpm（', result.stdout)
        result = subprocess.run(['bash', str(self.root / 'build-packages.sh'), 'x64', '--dry-run'],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for format in ['appimage', 'deb', 'pacman', 'rpm']:
            self.assertIn(format, result.stdout)
        result = subprocess.run(['bash', str(self.root / 'build-packages.sh'), 'x64', '--dry-run',
                                 '--formats', 'deb', '--electron', 'system', '--package-jobs', '2'],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('打包 deb（system，', result.stdout)
        self.assertIn('打包线程: 2', result.stdout)

    def test_electron_mode_filters_supported_formats(self):
        for mode, included, excluded in [
                ('bundled', ['appimage', 'deb', 'rpm'], ['pacman']),
                ('system', ['deb', 'pacman'], ['appimage', 'rpm'])]:
            result = self.run_cli('--dry-run', '--only', 'package', '--formats', 'all',
                                  '--electron', mode, '--package-jobs', '3')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('格式:   ' + ','.join(included), result.stdout)
            self.assertIn('打包 deb（' + mode + '，', result.stdout)
            self.assertIn('打包线程: 3', result.stdout)
            for name in excluded:
                self.assertNotIn('打包 ' + name + '（', result.stdout)
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.root / 'dl').exists())

    @unittest.skipUnless(shutil.which('dpkg-deb') and shutil.which('ar'), 'deb tools unavailable')
    def test_deb_single_variant_and_explicit_threads(self):
        store = self.native_fixture()
        xz = self.bin / 'xz'
        actual_xz = shutil.which('xz')
        log = Path(self.temp.name) / 'xz-options'
        xz.write_text('#!/bin/sh\nprintf "%s\\n" "$XZ_OPT" >> "$XZ_LOG"\nexec "' + actual_xz + '" "$@"\n')
        xz.chmod(0o755)
        self.env.update(XZ_LOG=str(log), XZ_OPT='-1 -T7')
        for mode in ['bundled', 'system']:
            result = self.run_cli('--only', 'package', '--formats', 'deb', '--store', str(store),
                                  '--electron', mode, '--package-jobs', '1')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            archives = list((self.root / 'dist').glob('*.deb'))
            self.assertEqual([p.name for p in archives], [f'deepseek-harness_1.3.7-rc.4_amd64.{mode}.deb'])
            members = subprocess.check_output(['dpkg-deb', '-c', str(archives[0])], text=True)
            self.assertEqual('/usr/lib/deepseek-harness/deepseek-harness' in members, mode == 'bundled')
            shutil.rmtree(self.root / 'dist')
        self.assertTrue(log.read_text().splitlines())
        self.assertTrue(all(line == '-1 -T7 -T1' for line in log.read_text().splitlines()))

    def test_appimage_explicit_threads_reach_mksquashfs(self):
        store = self.package_fixture()
        tool = store / 'tools/usr/bin/mksquashfs'
        tool.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$SQUASH_ARGS"\nprintf squashfs > "$2"\n')
        tool.chmod(0o755)
        log = Path(self.temp.name) / 'squash-options'
        self.env['SQUASH_ARGS'] = str(log)
        result = self.run_cli('--only', 'package', '--store', str(store), '--package-jobs', '3')
        self.assertEqual(result.returncode, 0, result.stderr)
        args = log.read_text().splitlines()
        self.assertEqual(args[args.index('-processors') + 1], '3')

    def test_non_appimage_prepare_skips_appimage_downloads(self):
        result = self.run_cli('--dry-run', '--only', 'prepare', '--formats', 'deb')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('AppImage/type2-runtime', result.stdout)
        self.assertNotIn('AppImage/appimagetool', result.stdout)
        self.assertFalse(self.marker.exists())

    def test_invalid_format_fails_before_writes(self):
        for format in ['zip', 'deb,', 'deb,,rpm']:
            result = self.run_cli('--formats', format)
            self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'dl').exists())

    def test_missing_format_tool_fails_before_downloads(self):
        for name in ['bash', 'dirname', 'uname', 'python3', 'tar', 'xz', 'sha256sum']:
            (self.bin / name).symlink_to(shutil.which(name))
        self.env['PATH'] = str(self.bin)
        result = self.run_cli('--formats', 'rpm')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('rpmbuild', result.stderr)
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.root / 'dl').exists())

    def native_fixture(self):
        store = self.package_fixture()
        tree = self.root / 'out-x64'
        (tree / 'version').write_text('44.4.5')
        for name in ['deepseek-harness', 'chrome-sandbox']:
            (tree / name).write_text('#!/bin/sh\nexit 0\n')
            (tree / name).chmod(0o755)
        runtime = tree / 'resources/runtime/primary-runtime/runtime.json'
        runtime.write_text(json.dumps({'desktopVersion': '1.3.7-rc.4'}))
        return store

    @unittest.skipUnless(shutil.which('dpkg-deb') and shutil.which('ar'), 'deb tools unavailable')
    def test_real_deb_metadata_payload_and_checksums(self):
        store = self.native_fixture()
        result = self.run_cli('--only', 'package', '--formats', 'deb', '--store', str(store))
        self.assertEqual(result.returncode, 0, result.stderr)
        for variant in ['bundled', 'system']:
            archive = self.root / 'dist' / f'deepseek-harness_1.3.7-rc.4_amd64.{variant}.deb'
            fields = subprocess.check_output(['dpkg-deb', '-f', str(archive)], text=True)
            self.assertIn('Version: 1.3.7-rc.4', fields)
            self.assertIn('Architecture: amd64', fields)
            self.assertIn('Description:', fields)
            if variant == 'bundled':
                self.assertIn('Electron 44.4.5', fields)
            self.assertEqual('Recommends:' in fields, variant == 'system')
            extracted = Path(self.temp.name) / variant
            subprocess.run(['dpkg-deb', '-x', str(archive), str(extracted)], check=True)
            resources = extracted / 'usr/lib/deepseek-harness/resources'
            self.assertTrue((resources / 'runtime/primary-runtime/runtime.json').exists())
            desktop = extracted / 'usr/share/applications/deepseek-harness.desktop'
            self.assertEqual(desktop.stat().st_mode & 0o777, 0o644)
            self.assertFalse((resources / 'app/dsh/node_modules/.sharp-native-backup').exists())
            self.assertEqual((extracted / 'usr/lib/deepseek-harness/deepseek-harness').exists(), variant == 'bundled')
            subprocess.run(['sha256sum', '-c', archive.name + '.sha256'], cwd=archive.parent,
                           check=True, stdout=subprocess.DEVNULL)
        self.assertTrue((store / 'work/x64/packages/deb-bundled').exists())
        self.assertFalse(list((self.root / 'dist').glob('*.AppImage')))

    @unittest.skipUnless(shutil.which('bsdtar') and shutil.which('zstd'), 'pacman tools unavailable')
    def test_real_pacman_metadata_and_archive(self):
        store = self.native_fixture()
        actual_zstd = shutil.which('zstd')
        log = Path(self.temp.name) / 'zstd-options'
        wrapper = self.bin / 'zstd'
        wrapper.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ZSTD_LOG"\nexec "' + actual_zstd + '" "$@"\n')
        wrapper.chmod(0o755)
        self.env['ZSTD_LOG'] = str(log)
        result = self.run_cli('--only', 'package', '--formats', 'pacman', '--store', str(store), '--package-jobs', '1')
        self.assertEqual(result.returncode, 0, result.stderr)
        archive = self.root / 'dist/deepseek-harness-desktop-1.3.7_rc.4-1-x86_64.pkg.tar.zst'
        info = subprocess.check_output(['bsdtar', '-xOf', str(archive), '.PKGINFO'], text=True)
        self.assertIn('pkgver = 1.3.7_rc.4-1', info)
        self.assertIn('arch = x86_64', info)
        members = subprocess.check_output(['bsdtar', '-tf', str(archive)], text=True)
        self.assertIn('.MTREE.gz', members)
        self.assertIn('-T1', log.read_text().splitlines())
        self.assertIn('.INSTALL', members)
        self.assertNotIn('.sharp-native-backup', members)

    @unittest.skipUnless(shutil.which('rpmbuild') and shutil.which('rpm'), 'rpm tools unavailable')
    def test_real_rpm_metadata_and_payload(self):
        store = self.native_fixture()
        result = self.run_cli('--only', 'package', '--formats', 'rpm', '--store', str(store), '--package-jobs', '2')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        archive = self.root / 'dist/deepseek-harness-1.3.7-0.rc.4.1.x86_64.rpm'
        info = subprocess.check_output(['rpm', '--dbpath', str(store / 'work/x64/packages/rpmbuild/rpmdb'), '-qp', '--qf', '%{VERSION} %{RELEASE} %{ARCH}', str(archive)], text=True)
        self.assertEqual(info, '1.3.7 0.rc.4.1 x86_64')
        members = subprocess.check_output(['rpm', '--dbpath', str(store / 'work/x64/packages/rpmbuild/rpmdb'), '-qpl', str(archive)], text=True)
        self.assertIn('/usr/lib/deepseek-harness/deepseek-harness', members)
        flags = subprocess.check_output(['rpm', '--dbpath', str(store / 'work/x64/packages/rpmbuild/rpmdb'),
                                         '-qp', '--qf', '%{PAYLOADFLAGS}', str(archive)], text=True)
        self.assertEqual(flags, '6T2')
        self.assertNotIn('.sharp-native-backup', members)
        top = store / 'work/x64/packages/rpmbuild'
        self.assertTrue(list(top.glob('BUILD/**/BUILDROOT/usr/bin/deepseek-harness')))


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

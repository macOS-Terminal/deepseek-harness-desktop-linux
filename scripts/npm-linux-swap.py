#!/usr/bin/env python3
"""把 macOS/Windows 应用树里的平台专属原生包替换成对应的 Linux 包。

官方 dmg 里所有原生依赖都是 darwin-arm64 预编译产物；Linux 需要同名包族的
linux-x64 / linux-arm64 版本。本脚本扫描应用树，逐个定位这些包，从 npm
registry 取对应 Linux 包（默认国内镜像 registry.npmmirror.com）就地替换。

用法:
    npm-linux-swap.py --app <resources/app 目录> --arch x64|arm64
                      [--registry URL] [--fallback-registry URL]
                      [--cache 目录] [--dry-run] [--keep-foreign]

约定:
  * 只处理“原生平台包”（名字带平台标记且目录里确有 .node/.dylib/.dll/.so
    或 bin/ 可执行文件）；纯 JS 的 win32 辅助包会被原样保留。
  * LibreOffice 引擎在 Linux 上没有官方原生包，按应用自身的回退逻辑
    换成 @deepseek-ai/libreoffice-kit-wasm（版本取自应用代码里的 ENGINE_VERSIONS）。
  * node-pty 是同一包内的多平台 prebuilds，只补充 prebuilds/linux-<arch>。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import urllib.error
import urllib.request

PLATFORM_TOKENS = (
    'darwin-arm64', 'darwin-x64', 'darwin-universal',
    'win32-x64', 'win32-arm64', 'win32-ia32',
    'win-x64', 'win-arm64', 'win-ia32',
)
NATIVE_SUFFIXES = ('.node', '.dylib', '.dll', '.so')
LIBREOFFICE_PREFIX = '@deepseek-ai/libreoffice-kit'
WASM_PACKAGE = f'{LIBREOFFICE_PREFIX}-wasm'


def log(message: str) -> None:
    print(message, flush=True)


def warn(message: str) -> None:
    print(f'  警告: {message}', file=sys.stderr, flush=True)


# --------------------------------------------------------------- 探测 ----
def has_native_artifact(directory: str) -> bool:
    for root, dirs, files in os.walk(directory):
        for name in files:
            if name.endswith(NATIVE_SUFFIXES):
                return True
            if os.path.basename(root) == 'bin' and name in ('rg', 'node', 'libreoffice-kit'):
                return True
        if root.count(os.sep) - directory.count(os.sep) > 3:
            dirs[:] = []
    return False


def platform_token(name: str) -> str | None:
    """返回包名里的平台标记；不带的（纯 JS 包）不参与替换。"""
    for token in PLATFORM_TOKENS:
        if token in name:
            return token
    return None


def find_packages(app: str) -> list[dict]:
    found = []
    for root, dirs, files in os.walk(app):
        if 'package.json' not in files:
            continue
        path = os.path.join(root, 'package.json')
        try:
            with open(path, encoding='utf8') as handle:
                meta = json.load(handle)
        except (OSError, ValueError):
            continue
        name = meta.get('name') or ''
        token = platform_token(name)
        if token is None:
            continue
        if not has_native_artifact(root):
            continue
        found.append({
            'directory': root,
            'name': name,
            'version': str(meta.get('version') or ''),
            'token': token,
        })
    return found


def engine_versions(app: str) -> dict:
    """从应用自带的 libreoffice-kit 适配层里读取它期望的引擎版本表。"""
    for root, dirs, files in os.walk(app):
        if os.path.basename(root) != 'libreoffice-kit':
            continue
        for name in files:
            if not name.endswith(('.js', '.cjs', '.mjs')):
                continue
            try:
                text = open(os.path.join(root, name), encoding='utf8').read()
            except OSError:
                continue
            match = re.search(r'ENGINE_VERSIONS\s*=\s*Object\.freeze\(\{(.*?)\}\)', text, re.S)
            if not match:
                continue
            table = dict(re.findall(r'"?([\w.-]+)"?\s*:\s*"([^"]+)"', match.group(1)))
            if table:
                return table
    return {}


# --------------------------------------------------------------- registry ----
class Registry:
    def __init__(self, mirrors: list[str], cache: str):
        self.mirrors = mirrors
        self.cache = cache
        os.makedirs(cache, exist_ok=True)

    def _get(self, url: str, timeout: int = 30) -> bytes:
        request = urllib.request.Request(url, headers={'User-Agent': 'dsh-linux-port/1.0'})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()

    def metadata(self, name: str, version: str | None = None) -> dict:
        suffix = f'/{version}' if version else ''
        errors = []
        for mirror in self.mirrors:
            try:
                return json.loads(self._get(f'{mirror}/{name}{suffix}'))
            except urllib.error.HTTPError as error:
                errors.append(f'{mirror} -> HTTP {error.code}')
            except Exception as error:  # noqa: BLE001 - 网络层任何失败都换镜像
                errors.append(f'{mirror} -> {error}')
        raise LookupError(f'{name}{suffix}: ' + '; '.join(errors))

    def versions(self, name: str) -> list[str]:
        try:
            return list(self.metadata(name).get('versions') or [])
        except LookupError:
            return []

    def tarball(self, name: str, version: str, integrity: str | None) -> str:
        safe = name.replace('/', '_').replace('@', '')
        target = os.path.join(self.cache, f'{safe}-{version}.tgz')
        meta = self.metadata(name, version)
        dist = meta.get('dist') or {}
        expected = dist.get('integrity') or integrity
        if os.path.exists(target) and os.path.getsize(target) > 0:
            if expected is None or verify_digest(target, expected):
                return target
            warn(f'{target} 校验不符，重新下载')
            os.remove(target)
        urls = [dist.get('tarball')]
        for mirror in self.mirrors:
            urls.append(f'{mirror}/{name}/-/{os.path.basename(name)}-{version}.tgz')
        last = None
        for url in urls:
            if not url:
                continue
            try:
                data = self._get(url, timeout=120)
            except Exception as error:  # noqa: BLE001
                last = error
                continue
            if expected and not verify_digest_bytes(data, expected):
                last = ValueError(f'{url} 摘要不符')
                continue
            with open(target, 'wb') as handle:
                handle.write(data)
            return target
        raise LookupError(f'{name}@{version} 下载失败: {last}')


def verify_digest(path: str, integrity: str) -> bool:
    with open(path, 'rb') as handle:
        return verify_digest_bytes(handle.read(), integrity)


def verify_digest_bytes(data: bytes, integrity: str) -> bool:
    for token in integrity.split():
        algo, _, value = token.partition('-')
        if algo not in ('sha512', 'sha256', 'sha1') or not value:
            continue
        import base64

        digest = hashlib.new(algo, data).digest()
        if base64.b64encode(digest).decode() == value:
            return True
        if hashlib.new(algo, data).hexdigest() == value:
            return True
    return False


def extract_package(tarball: str, destination: str, only_prefix: str | None = None) -> int:
    from pathlib import Path, PurePosixPath

    os.makedirs(destination, exist_ok=True)
    root = Path(destination).resolve()
    count = 0
    with tarfile.open(tarball, 'r:gz') as tar:
        for member in tar.getmembers():
            parts = member.name.split('/', 1)
            if len(parts) < 2 or not parts[1]:
                continue
            relative = parts[1]
            path = PurePosixPath(relative)
            if parts[0] != "package" or path.is_absolute() or ".." in path.parts:
                raise ValueError(f"非法 npm 归档路径: {member.name}")
            target = (root / relative).resolve()
            if not target.is_relative_to(root):
                raise ValueError(f"npm 归档路径越界: {member.name}")
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"不支持的 npm 归档条目: {member.name}")
            if only_prefix and not relative.startswith(only_prefix):
                continue
            member.name = relative
            tar.extract(member, destination, filter="data")
            count += 1
    return count


# --------------------------------------------------------------- 主流程 ----
def plan_for(package: dict, arch: str, engines: dict) -> dict | None:
    name = package['name']
    if name.startswith(f'{LIBREOFFICE_PREFIX}-'):
        version = engines.get('wasm') or package['version']
        return {'kind': 'wasm', 'name': WASM_PACKAGE, 'version': version, 'source': package}
    linux = name.replace(package['token'], f'linux-{arch}')
    return {'kind': 'native', 'name': linux, 'version': package['version'], 'source': package}


def pick_version(registry: Registry, name: str, wanted: str, allow_drift: bool = False) -> tuple[str, str]:
    """只接受**完全相同的版本**：这些原生包与应用/JS 侧是配套 pin 住的。

    找不到同版本时默认报错退出，而不是悄悄换成别的版本——否则可能造出
    「原生模块与 JS 版本不匹配」的包，症状还很难查。确实需要放宽时用 --allow-drift。
    """
    meta_versions = registry.versions(name)
    if not meta_versions:
        raise LookupError(f'registry 上没有 {name}')
    if wanted in meta_versions:
        return wanted, f'同版本 {wanted}'
    if not allow_drift:
        nearby = ', '.join(meta_versions[-6:])
        raise LookupError(
            f'{name}@{wanted} 不存在（该包最近可用版本: {nearby}）；'
            f'本脚本不做版本漂移替换，确需放宽请加 --allow-drift'
        )

    def key(value: str) -> tuple:
        return tuple(int(part) for part in re.findall(r'\d+', value))

    stable = [v for v in meta_versions if not re.search(r'[a-zA-Z]', v)] or meta_versions
    below = [v for v in stable if key(v) <= key(wanted)]
    chosen = max(below, key=key) if below else min(stable, key=key)
    warn(f'{name}@{wanted} 不存在，--allow-drift 生效，改用 {chosen}')
    return chosen, f'放宽为 {chosen}（--allow-drift）'


def swap_native(registry: Registry, package: dict, arch: str, dry_run: bool,
                allow_drift: bool = False) -> bool:
    name = package['name']
    linux = name.replace(package['token'], f'linux-{arch}')
    candidates = [linux, f'{linux}-gnu']
    errors = []
    for candidate in candidates:
        try:
            version, note = pick_version(registry, candidate, package['version'], allow_drift)
        except LookupError as error:
            errors.append(str(error))
            continue
        log(f'  {name}@{package["version"]}  ->  {candidate}@{version}  ({note})')
        if dry_run:
            return True
        tarball = registry.tarball(candidate, version, None)
        target = os.path.join(os.path.dirname(package['directory']), os.path.basename(candidate))
        if os.path.isdir(target):
            shutil.rmtree(target)
        extract_package(tarball, target)
        shutil.rmtree(package['directory'], ignore_errors=True)
        return True
    warn(f'{name}: 替换失败 —— ' + ('; '.join(errors) if errors else '没有对应的 Linux 包'))
    return False


def swap_wasm(registry: Registry, plan: dict, dry_run: bool, allow_drift: bool = False) -> bool:
    source = plan['source']
    target = os.path.join(os.path.dirname(source['directory']), os.path.basename(plan['name']))
    try:
        version, note = pick_version(registry, plan['name'], plan['version'], allow_drift)
    except LookupError as error:
        warn(f'{plan["name"]}: {error}')
        return False
    log(f'  {source["name"]}@{source["version"]}  ->  {plan["name"]}@{version}  ({note}, WASM 回退)')
    if dry_run:
        return True
    tarball = registry.tarball(plan['name'], version, None)
    if os.path.isdir(target):
        shutil.rmtree(target)
    extract_package(tarball, target)
    shutil.rmtree(source['directory'], ignore_errors=True)
    return True


def swap_node_pty(registry: Registry, app: str, arch: str, dry_run: bool, cache_note: list) -> str:
    """返回 'absent'（这棵树里没有 node-pty）/'ok'/'failed'。"""
    root = os.path.join(app, 'dsh', 'node_modules', 'node-pty')
    manifest = os.path.join(root, 'package.json')
    if not os.path.isfile(manifest):
        return 'absent'
    with open(manifest, encoding='utf8') as handle:
        version = json.load(handle).get('version')
    target = os.path.join(root, 'prebuilds', f'linux-{arch}')
    if os.path.isfile(os.path.join(target, 'pty.node')):
        log(f'  node-pty@{version}  prebuilds/linux-{arch} 已存在')
        return 'ok'
    log(f'  node-pty@{version}  ->  补充 prebuilds/linux-{arch}')
    if dry_run:
        return 'ok'
    try:
        tarball = registry.tarball('node-pty', version, None)
    except LookupError as error:
        warn(f'node-pty: {error}')
        return 'failed'
    cache_note.append(tarball)
    # 同一 tgz 里还有 darwin/win32 prebuilds：只取 linux-<arch> 一段。
    staging = os.path.join(os.path.dirname(tarball), f'node-pty-{arch}-staging')
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    extract_package(tarball, staging, only_prefix=f'prebuilds/linux-{arch}/')
    source = os.path.join(staging, 'prebuilds', f'linux-{arch}')
    if not os.path.isdir(source):
        warn(f'node-pty@{version} 的 tgz 里没有 prebuilds/linux-{arch}')
        return 'failed'
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.isdir(target):
        shutil.rmtree(target)
    shutil.move(source, target)
    return 'ok'


def audit(app: str) -> list[str]:
    """替换结束后复查：应用树里不应再有带原生产物的 darwin/win32 平台包。

    只认“本身就是一个包”的目录（含 package.json）。像
    node-pty/prebuilds/darwin-arm64 这类多平台包内部的归档目录不算：
    运行时由 node-pty 自行挑选 prebuilds/linux-<arch>。
    """
    leftovers = []
    for root, dirs, files in os.walk(app):
        for name in list(dirs):
            if not any(token in name for token in PLATFORM_TOKENS):
                continue
            candidate = os.path.join(root, name)
            if not os.path.isfile(os.path.join(candidate, 'package.json')):
                continue
            if has_native_artifact(candidate):
                leftovers.append(candidate)
            dirs.remove(name)
    return leftovers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='把原生包换成 Linux 版本')
    parser.add_argument('--app', required=True, help='resources/app 目录')
    parser.add_argument('--arch', required=True, choices=['x64', 'arm64'])
    parser.add_argument('--registry', default='https://registry.npmmirror.com')
    parser.add_argument('--fallback-registry', default='https://registry.npmjs.org')
    parser.add_argument('--cache', required=True)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--keep-foreign', action='store_true', help='保留未替换的 darwin/win32 包')
    parser.add_argument('--allow-drift', action='store_true',
                        help='找不到同版本时允许改用别的版本（默认禁止，直接失败）')
    args = parser.parse_args(argv)

    app = os.path.abspath(args.app)
    if not os.path.isdir(app):
        raise SystemExit(f'找不到应用树: {app}')
    mirrors = [args.registry] + ([args.fallback_registry] if args.fallback_registry else [])
    registry = Registry(mirrors, os.path.abspath(args.cache))

    packages = find_packages(app)
    log(f'== 原生包替换 (arch={args.arch}, 命中 {len(packages)} 个平台专属包'
        + ('，--allow-drift 已开启' if args.allow_drift else '') + ')')
    engines = engine_versions(app)

    # 深层包优先处理：先动子包，父包被删除时不会有路径失效问题。
    packages.sort(key=lambda p: p['directory'].count(os.sep), reverse=True)
    done = 0
    failures: list[str] = []
    for package in packages:
        plan = plan_for(package, args.arch, engines)
        ok = swap_wasm(registry, plan, args.dry_run, args.allow_drift) if plan['kind'] == 'wasm' \
            else swap_native(registry, package, args.arch, args.dry_run, args.allow_drift)
        if ok:
            done += 1
        else:
            failures.append(package['name'])

    pty = swap_node_pty(registry, app, args.arch, args.dry_run, [])
    if pty == 'ok':
        done += 1
    elif pty == 'failed':
        failures.append('node-pty')

    if not args.dry_run:
        leftovers = audit(app)
        for path in leftovers:
            warn(f'仍存在平台专属原生包: {os.path.relpath(path, app)}')
        if leftovers and not args.keep_foreign and not failures:
            failures.append(f'{len(leftovers)} 个残留的平台专属原生包')

    log(f'  完成: 替换 {done} 项, 失败 {len(failures)} 项')
    if failures:
        # 关键依赖失败必须让整个构建停下：否则会打出「终端/图片/办公功能坏掉」的包。
        for name in failures:
            print(f'  失败项: {name}', file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

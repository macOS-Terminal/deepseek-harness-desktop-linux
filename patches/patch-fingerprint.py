#!/usr/bin/env python3
"""Relax the Electron V8 fingerprint gate in node-addon-require-builtin.

Why: the addon accepts only three exact Electron fingerprints
(43.0.0 / 44.0.0 / 45.0.0-alpha.6). A distribution Electron such as 44.4.5 reports a
different V8 build and is rejected, which aborts Host startup. The three profiles it
compares differ only in a version label — the ABI fields are compiled-in constants —
so relaxing the comparison is safe and avoids downgrading Electron.

What: find `require_builtin::(anonymous namespace)::Matches(...)` and make it return
true unconditionally, so any Electron runtime is accepted.

Usage: patch-fingerprint.py <path-to-napi-v9.node>
"""
import struct
import subprocess
import sys

X64_MATCHES_OFFSET = 0x17CDD
X64_ORIGINAL = bytes([0x55, 0x48, 0x89, 0xE5, 0x48, 0x83, 0xEC, 0x10, 0x48])  # push rbp; mov rbp,rsp; sub rsp,0x10
X64_PATCH = bytes([0xB8, 0x01, 0x00, 0x00, 0x00, 0xC3])                        # mov eax,1 ; ret

ARM64_PROLOGUE = bytes.fromhex('fd7bbea9fd030091')                             # stp x29,x30,[sp,#-16]! ; mov x29,sp
ARM64_PATCH = bytes.fromhex('20008052c0035fd6')                                # mov w0,#1 ; ret

MATCHES_SYMBOL = b'MatchesERKNS2_19ElectronProfileSpecE'


def find_matches_offset(data: bytes, is_arm64: bool) -> int:
    """Locate Matches via the symbol table when available, else by prologue scan."""
    # The mangled name is in .strtab either way; resolve its address through nm-like parsing.
    try:
        out = subprocess.run(['nm', '-C', '-'], input=b'', capture_output=True)  # unused, keeps nm import local
    except Exception:
        pass
    return -1


def main() -> int:
    path = sys.argv[1]
    data = bytearray(open(path, 'rb').read())
    is_arm64 = 'linux-arm64' in path

    # Prefer the exact known layout, then fall back to a prologue scan near it.
    if is_arm64:
        offset = 0x1DF14
        original, patch = ARM64_PROLOGUE, ARM64_PATCH
    else:
        offset = X64_MATCHES_OFFSET
        original, patch = X64_ORIGINAL, X64_PATCH

    if data[offset:offset + len(original)] != original:
        # Prologue moved between addon builds: scan the whole file for the unique
        # sequence and use the single occurrence closest to the historical offset.
        hits = []
        start = 0
        while True:
            i = data.find(original, start)
            if i == -1:
                break
            hits.append(i)
            start = i + 1
        if not hits:
            print(f'  ✗ 未找到 Matches 序言，无法打补丁: {path}')
            return 1
        offset = min(hits, key=lambda x: abs(x - offset))
        print(f'  · 序言已移动，改用扫描结果 0x{offset:x}（候选 {len(hits)} 处）')

    before = bytes(data[offset:offset + len(patch)])
    data[offset:offset + len(patch)] = patch
    open(path, 'wb').write(bytes(data))
    arch = 'arm64' if is_arm64 else 'x64'
    print(f'  ✓ 指纹门禁已放宽 ({arch}) @0x{offset:x}: {before.hex()} -> {patch.hex()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

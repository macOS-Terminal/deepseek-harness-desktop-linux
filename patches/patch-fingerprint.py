#!/usr/bin/env python3
"""Relax the Electron V8 fingerprint gate in node-addon-require-builtin.

Why: the addon accepts only three exact Electron fingerprints
(43.0.0 / 44.0.0 / 45.0.0-alpha.6). A distribution Electron (44.4.5, 44.7.0, …)
reports a different V8 build and is rejected, which aborts Host startup. The three
profiles differ only in a version label — the ABI fields are compiled-in constants —
so relaxing the comparison is safe and avoids downgrading Electron.

What: locate `require_builtin::(anonymous namespace)::Matches(...)` through the ELF
symbol table and make it return true unconditionally.

Why symbols, not offsets: the previous implementation hardcoded a file offset and
fell back to scanning for the function prologue. On a newer addon build that scan
matched 233 unrelated functions and patched the wrong one, silently corrupting the
binary while reporting success. The symbol table names the exact function, so this
version either patches the right address or refuses to patch at all.

Usage: patch-fingerprint.py <path-to-napi-v9.node>
"""
import struct
import sys
from pathlib import Path

# Mangled name fragment of require_builtin::(anonymous namespace)::Matches(
MATCHES_SYMBOL = b'MatchesERKNS2_19ElectronProfileSpecE'

# Byte sequences per ELF machine type.
#   x64   : push rbp; mov rbp,rsp; sub rsp,0x10   -> mov eax,1; ret
#   arm64 : stp x29,x30,[sp,#-16]!; mov x29,sp    -> mov w0,#1; ret
LAYOUTS = {
    62: (bytes.fromhex('554889e54883ec1048'), bytes.fromhex('b801000000c3')),
    183: (bytes.fromhex('fd7bbea9fd030091'), bytes.fromhex('20008052c0035fd6')),
}


def find_symbol(data, fragment):
    """Return (machine, file_offset, size) for a unique symbol match.

    Parses the ELF section table directly, so no external tooling is required.
    Raises ValueError when the match is absent or ambiguous.
    """
    if data[:6] != b'\x7fELF\x02\x01' or len(data) < 64:
        raise ValueError('expected little-endian ELF64')
    machine = struct.unpack_from('<H', data, 18)[0]
    shoff = struct.unpack_from('<Q', data, 40)[0]
    shentsize, shnum = struct.unpack_from('<HH', data, 58)
    if shentsize != 64 or shoff + shnum * shentsize > len(data):
        raise ValueError('invalid ELF section table')

    sections = [struct.unpack_from('<IIQQQQIIQQ', data, shoff + i * shentsize)
                for i in range(shnum)]

    hits = set()
    for section in sections:
        # SHT_SYMTAB (2) and SHT_DYNSYM (11) carry symbol tables.
        if section[1] not in (2, 11):
            continue
        _, _, _, _, offset, length, link, _, _, stride = section
        if stride != 24 or link >= len(sections) or offset + length > len(data):
            continue
        strings = sections[link]
        names = data[strings[4]:strings[4] + strings[5]]
        for pos in range(offset, offset + length, stride):
            name, info, _, index, address, size = struct.unpack_from('<IBBHQQ', data, pos)
            # STT_FUNC == 2; section index 0 (SHN_UNDEF) is not a definition.
            if info & 15 != 2 or index == 0 or index >= len(sections):
                continue
            if fragment not in names[name:].split(b'\0', 1)[0]:
                continue
            target = sections[index]
            file_offset = target[4] + address - target[3]
            if not (target[4] <= file_offset < target[4] + target[5]):
                raise ValueError('symbol is not file content')
            hits.add((file_offset, size))
    if len(hits) != 1:
        raise ValueError(f'expected exactly one Matches function, found {len(hits)}')
    offset, size = hits.pop()
    return machine, offset, size


def patch(path):
    data = bytearray(Path(path).read_bytes())
    machine, offset, size = find_symbol(data, MATCHES_SYMBOL)
    if machine not in LAYOUTS:
        raise ValueError(f'unsupported ELF machine: {machine}')
    original, replacement = LAYOUTS[machine]

    if size < max(len(original), len(replacement)):
        raise ValueError(f'Matches too small ({size} bytes) to hold the patch')

    if data[offset:offset + len(replacement)] == replacement:
        print(f'  · 指纹补丁已存在 @0x{offset:x}')
        return
    if data[offset:offset + len(original)] != original:
        raise ValueError(f'unexpected prologue @0x{offset:x}: '
                         f'{bytes(data[offset:offset + len(original)]).hex()}; refusing to patch')

    data[offset:offset + len(replacement)] = replacement
    Path(path).write_bytes(bytes(data))
    print(f'  ✓ 指纹门禁已放宽 (machine={machine}) @0x{offset:x}')


if __name__ == '__main__':
    try:
        patch(sys.argv[1])
    except (ValueError, OSError, IndexError) as error:
        sys.exit(f'指纹补丁失败: {error}')
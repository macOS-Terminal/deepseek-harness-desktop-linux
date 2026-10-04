#!/usr/bin/env python3
"""Patch the supported Electron fingerprint gate, located by its ELF symbol.

Reject unknown layouts rather than guessing a nearby function. This bypass does
not establish ABI compatibility with arbitrary Electron releases.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from elf_payload import ELF

SYMBOL = b"MatchesERKNS2_19ElectronProfileSpecERKNS1_24NativeRuntimeFingerprintE"
LAYOUTS = {
    62: (bytes.fromhex("554889e54883ec1048"), bytes.fromhex("b801000000c3")),
    183: (bytes.fromhex("fd7bbea9fd030091"), bytes.fromhex("20008052c0035fd6")),
}

def patch(path):
    data = bytearray(Path(path).read_bytes())
    elf = ELF(data)
    if elf.machine not in LAYOUTS:
        raise ValueError(f"unsupported ELF machine: {elf.machine}")
    offset, size = elf.function(SYMBOL)
    original, replacement = LAYOUTS[elf.machine]
    if size < max(len(original), len(replacement)):
        raise ValueError("Matches function too small")
    if data[offset:offset + len(replacement)] == replacement:
        print(f"  ✓ 指纹补丁已存在 @0x{offset:x}")
        return
    if data[offset:offset + len(original)] != original:
        raise ValueError(f"unknown Matches prologue @0x{offset:x}; refusing to patch")
    data[offset:offset + len(replacement)] = replacement
    Path(path).write_bytes(data)
    print(f"  ✓ 指纹补丁 ELF machine={elf.machine} @0x{offset:x}")

if __name__ == "__main__":
    try:
        patch(sys.argv[1])
    except (ValueError, OSError, IndexError) as error:
        sys.exit(f"指纹补丁失败: {error}")

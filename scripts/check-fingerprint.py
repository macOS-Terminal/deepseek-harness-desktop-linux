#!/usr/bin/env python3
"""核对 node-addon-require-builtin 的 V8 指纹门禁是否被打成「恒真」。

patch-fingerprint.py 把匹配函数开头改成直接返回 1：
  x64   : b8 01 00 00 00   mov eax, 1
  arm64 : 20 00 80 52      mov w0, #1
按 ELF 符号定位该函数（符号名含 Matches / ElectronProfileSpec），读出开头字节核对。

用法: check-fingerprint.py <.node 文件> <x64|arm64>
"""
import re
import subprocess
import sys

EXPECT = {"x64": bytes.fromhex("b8010000"), "arm64": bytes.fromhex("20008052")}


def readelf(args):
    return subprocess.run(["readelf"] + args, capture_output=True, text=True, check=True).stdout


def section_map(path):
    """节序号 -> (名字, 虚拟地址, 文件偏移, 大小)。"""
    out = readelf(["-SW", path])
    secs = {}
    for line in out.splitlines():
        m = re.match(r"\s*\[\s*(\d+)\]\s+(\S+)\s+(\S+)\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)", line)
        if not m:
            continue
        idx = int(m.group(1))
        secs[idx] = (m.group(2), int(m.group(4), 16), int(m.group(5), 16), int(m.group(6), 16))
    return secs


def find_symbol(path):
    out = readelf(["-sW", path])
    cands = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 8 or not parts[0].rstrip(":").isdigit():
            continue
        # Num: Value Size Type Bind Vis Ndx Name
        value, ndx, name = parts[1], parts[6], parts[7]
        if "Matches" not in name:
            continue
        if not re.fullmatch(r"[0-9a-f]+", value):
            continue
        cands.append((name, int(value, 16), ndx))
    # 优先取带 ElectronProfileSpec 的那个唯一符号
    exact = [c for c in cands if "ElectronProfileSpec" in c[0]]
    return (exact or cands)[0] if (exact or cands) else None


def main(path, arch):
    want = EXPECT[arch]
    sym = find_symbol(path)
    if not sym:
        print("  ✗ 未找到 Matches 符号，无法核对")
        return 1
    name, value, ndx = sym
    if not ndx.isdigit():
        print(f"  ✗ 符号未落在具体节（Ndx={ndx}）")
        return 1
    secs = section_map(path)
    sname, saddr, soff, _size = secs[int(ndx)]
    delta = soff + (value - saddr)
    with open(path, "rb") as f:
        f.seek(delta)
        got = f.read(8)
    ok = got.startswith(want)
    print(f"  符号: {name}")
    print(f"  位置: {sname} 符号值 0x{value:x} -> 文件偏移 0x{delta:x}")
    print(f"  字节: {got.hex(' ')}   期望开头 {want.hex(' ')}")
    print(f"  {'✓ 指纹门禁已放宽（恒返回 1）' if ok else '✗ 未打指纹补丁'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))

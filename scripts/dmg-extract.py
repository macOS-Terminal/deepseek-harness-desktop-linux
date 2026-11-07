#!/usr/bin/env python3
"""把 UDIF dmg 解成原始磁盘镜像。

7z / dmg2img 都不支持 Apple LZFSE 块（0x80000008），本脚本直接解析 koly 尾部的
blkx 块表并逐块解码，产出可被 7z 读取的裸 HFS+ 镜像。

用法: dmg-extract.py <input.dmg> <output.img>
"""
import base64
import bz2
import ctypes
import lzma
import os
import plistlib
import struct
import sys
import zlib

CHUNK_RAW = 0x00000001
CHUNK_ZERO = 0x00000002
CHUNK_ADC = 0x80000004
CHUNK_ZLIB = 0x80000005
CHUNK_BZIP2 = 0x80000006
CHUNK_LZMA = 0x80000007
CHUNK_LZFSE = 0x80000008
CHUNK_END = 0xFFFFFFFF

XZ_MAGIC = b"\xfd7zXZ\x00"
LZFSE_MAGIC = b"bvx2"

_lzfse = ctypes.CDLL("/usr/lib/liblzfse.so")


def lzfse_decode(src: bytes, dst_size: int) -> bytes:
    buf = ctypes.create_string_buffer(dst_size)
    n = _lzfse.lzfse_decode_buffer(buf, ctypes.c_size_t(dst_size),
                                  src, ctypes.c_size_t(len(src)), None)
    if n == 0:
        raise RuntimeError(f"lzfse 解码失败 (src={len(src)}, dst={dst_size})")
    return buf.raw[:n]


def main(dmg_path: str, img_path: str) -> int:
    size = os.path.getsize(dmg_path)
    with open(dmg_path, "rb") as f:
        f.seek(size - 512)
        trailer = f.read(512)
        if trailer[:4] != b"koly":
            print("不是 UDIF dmg（缺少 koly 尾部签名）", file=sys.stderr)
            return 2
        xml_off, xml_len = struct.unpack(">QQ", trailer[216:232])
        f.seek(xml_off)
        plist = plistlib.loads(f.read(xml_len))
        blkx = plist["resource-fork"]["blkx"]

        # 选最大的那个分区块（HFS+ 数据分区），其余是 MBR/GPT 元数据
        target = max(blkx, key=lambda b: len(b["Data"]))
        name = target.get("Name", "?")
        mish = target["Data"]
        print(f"分区: {name} ({len(mish)} 字节块表)")

        n_chunks = (len(mish) - 0xCC) // 0x28
        written = 0
        stats = {}
        with open(img_path, "wb") as out:
            for i in range(n_chunks):
                off = 0xCC + i * 0x28
                ctype, _cmt, sector, count, coff, clen = struct.unpack(
                    ">IIQQQQ", mish[off:off + 0x28])
                if ctype == CHUNK_END:
                    break
                out.seek(sector * 512)
                dst_len = count * 512
                if ctype in (CHUNK_ZERO, 0x00000000):
                    out.write(b"\0" * dst_len)
                else:
                    f.seek(coff)
                    raw = f.read(clen)
                    if ctype == CHUNK_ZLIB:
                        data = zlib.decompress(raw)
                    elif ctype == CHUNK_BZIP2:
                        data = bz2.decompress(raw)
                    elif ctype == CHUNK_LZMA:
                        data = lzma.decompress(raw)
                    elif ctype == CHUNK_LZFSE:
                        # 实测该 dmg 把 xz 流也标成 0x80000008，按魔数区分
                        if raw[:6] == XZ_MAGIC:
                            data = lzma.decompress(raw)
                        elif raw[:4] == LZFSE_MAGIC:
                            data = lzfse_decode(raw, dst_len)
                        else:
                            raise RuntimeError(f"未知压缩魔数 {raw[:8].hex()} (chunk {i})")
                    elif ctype == CHUNK_RAW:
                        data = raw
                    else:
                        raise RuntimeError(f"不支持的块类型 {ctype:#x} (chunk {i})")
                    out.write(data)
                written += dst_len
                key = {CHUNK_ZERO: "zero", CHUNK_ZLIB: "zlib", CHUNK_BZIP2: "bzip2",
                       CHUNK_LZMA: "lzma", CHUNK_LZFSE: "lzfse", CHUNK_RAW: "raw"}.get(ctype, hex(ctype))
                stats[key] = stats.get(key, 0) + 1
            out.truncate(written)
    print(f"输出: {img_path}  {written} 字节  {stats}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))

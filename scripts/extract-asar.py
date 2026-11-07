#!/usr/bin/env python3
"""展开 Electron asar 归档。

格式: [0:4]=4, [4:8]=header pickle 长度, [8:12]=json 长度(含 padding), [12:16]=json 实际长度
     data_start = 8 + uint32([4:8])，各文件按 header 里的 offset/size 切片；
     unpacked:true 的条目从 <asar>.unpacked/ 取真实文件。

用法: extract-asar.py <app.asar> <目标目录>
"""
import json
import os
import struct
import sys


def main(asar: str, dest: str) -> int:
    with open(asar, "rb") as f:
        head = f.read(16)
        hdr_size = struct.unpack("<I", head[4:8])[0]
        str_len = struct.unpack("<I", head[12:16])[0]
        f.seek(16)
        header = json.loads(f.read(str_len).decode("utf-8"))
        data_start = 8 + hdr_size

        unpacked_root = asar + ".unpacked"
        n_files = n_unpacked = 0
        n_bytes = 0

        def walk(node, rel):
            nonlocal n_files, n_unpacked, n_bytes
            for name, meta in node.get("files", {}).items():
                path = os.path.join(rel, name) if rel else name
                out = os.path.join(dest, path)
                if "files" in meta:
                    os.makedirs(out, exist_ok=True)
                    walk(meta, path)
                    continue
                os.makedirs(os.path.dirname(out) or dest, exist_ok=True)
                if meta.get("unpacked"):
                    src = os.path.join(unpacked_root, path)
                    if not os.path.exists(src):
                        print(f"  ! 缺少 unpacked 文件: {path}", file=sys.stderr)
                        continue
                    with open(src, "rb") as s, open(out, "wb") as d:
                        while True:
                            b = s.read(1 << 20)
                            if not b:
                                break
                            d.write(b)
                    n_unpacked += 1
                else:
                    f.seek(data_start + int(meta["offset"]))
                    remain = int(meta["size"])
                    with open(out, "wb") as d:
                        while remain:
                            b = f.read(min(1 << 20, remain))
                            if not b:
                                break
                            d.write(b)
                            remain -= len(b)
                    n_files += 1
                n_bytes += int(meta.get("size", 0))
                if meta.get("executable"):
                    os.chmod(out, 0o755)
                if meta.get("link"):
                    pass

        walk(header, "")
    print(f"展开完成: 打包内文件 {n_files}, unpacked 文件 {n_unpacked}, 合计 {n_bytes} 字节 -> {dest}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))

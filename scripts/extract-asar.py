#!/usr/bin/env python3
"""展开 Electron 的 app.asar 归档为普通目录。

用法:
    extract-asar.py <app.asar> <输出目录> [--unpacked <app.asar.unpacked 目录>]

asar 文件头 16 字节的布局（小端）：
    [0:4]   = 4                    pickle 头部自身长度
    [4:8]   = 头块长度  -> data_start = 8 + uint32([4:8])
    [8:12]  = JSON 字符串长度（含 4 字节对齐填充）
    [12:16] = JSON 字符串真实长度
每个条目的 `offset` 是相对 data_start 的十进制字符串，`size` 是长度；
`unpacked: true` 的条目内容不在 asar 里，而在 app.asar.unpacked/ 的同名路径下。
"""
from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path, PurePosixPath


def read_header(fh):
    head = fh.read(16)
    if len(head) < 16:
        raise SystemExit('asar: 文件头不足 16 字节，不是 asar 归档')
    pickle_len, header_len, _json_padded, json_len = struct.unpack('<IIII', head)
    if pickle_len != 4:
        raise SystemExit(f'asar: pickle 头部长度异常 ({pickle_len})')
    data_start = 8 + header_len
    if header_len < 8 or json_len > header_len - 8:
        raise SystemExit("asar: JSON 长度超出文件头")
    raw = fh.read(json_len)
    if len(raw) != json_len:
        raise SystemExit('asar: JSON 目录被截断')
    return json.loads(raw.decode('utf8')), data_start


def walk(node, prefix, out):
    for name, entry in node.get('files', {}).items():
        if not name or name in ('.', '..') or '/' in name or '\\' in name:
            raise SystemExit(f'asar: 非法条目名称 {name!r}')
        path = f'{prefix}/{name}' if prefix else name
        if 'files' in entry:
            out.append(('dir', path, entry))
            walk(entry, path, out)
        else:
            out.append(('file', path, entry))


def main(argv):
    if len(argv) < 3:
        raise SystemExit(__doc__)
    asar, dest = argv[1], argv[2]
    unpacked = None
    if '--unpacked' in argv:
        unpacked = argv[argv.index('--unpacked') + 1]

    with open(asar, 'rb') as fh:
        tree, data_start = read_header(fh)

        entries: list[tuple[str, str, dict]] = []
        walk(tree, '', entries)

        files = dirs = unpacked_files = 0
        for kind, path, entry in entries:
            destination = Path(dest).resolve()
            target = str(destination / path)
            if not Path(target).resolve().is_relative_to(destination):
                raise SystemExit(f'asar: 条目路径越界 {path}')
            if kind == 'dir':
                os.makedirs(target, exist_ok=True)
                dirs += 1
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if entry.get('unpacked'):
                source = os.path.join(unpacked, path) if unpacked else None
                if source and os.path.exists(source):
                    _copy(source, target)
                    unpacked_files += 1
                else:
                    raise SystemExit(f'asar: unpacked 条目缺失: {path}')
                continue
            if 'link' in entry:
                link = PurePosixPath(entry['link'])
                if link.is_absolute() or '..' in link.parts:
                    raise SystemExit(f'asar: 非法链接 {path}')
                source = destination / str(link)
                os.symlink(os.path.relpath(source, os.path.dirname(target)), target)
                continue
            if int(entry['offset']) < 0 or int(entry['size']) < 0:
                raise SystemExit(f'asar: 非法文件范围 {path}')
            fh.seek(data_start + int(entry['offset']))
            data = fh.read(int(entry['size']))
            if len(data) != int(entry['size']):
                raise SystemExit(f'asar: {path} 数据被截断')
            with open(target, 'wb') as out:
                out.write(data)
            if entry.get('executable'):
                os.chmod(target, 0o755)
            files += 1

    print(f'  asar 展开: {files} 个文件 + {unpacked_files} 个外部载荷, {dirs} 个目录 -> {dest}')
    return 0


def _copy(source: str, target: str) -> None:
    import shutil

    if os.path.islink(source):
        link = os.readlink(source)
        if os.path.lexists(target):
            os.remove(target)
        os.symlink(link, target)
        return
    shutil.copy2(source, target)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))

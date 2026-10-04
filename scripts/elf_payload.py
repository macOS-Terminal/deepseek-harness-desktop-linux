"""Minimal ELF64 reader for supported Linux payloads (no external tooling)."""
import struct

MACHINES = {"x64": 62, "arm64": 183}

def machine(data):
    if data[:6] != b"\x7fELF\x02\x01" or len(data) < 64:
        raise ValueError("expected little-endian ELF64")
    return struct.unpack_from("<H", data, 18)[0]

class ELF:
    def __init__(self, data):
        self.data = data
        self.machine = machine(data)
        offset = struct.unpack_from("<Q", data, 40)[0]
        size, count = struct.unpack_from("<HH", data, 58)
        if count and (size != 64 or offset + count * size > len(data)):
            raise ValueError("invalid ELF section table")
        self.sections = [struct.unpack_from("<IIQQQQIIQQ", data, offset + i * size)
                         for i in range(count)]

    def function(self, fragment):
        hits = set()
        for section in self.sections:
            if section[1] not in (2, 11):
                continue
            _, _, _, _, offset, length, link, _, _, stride = section
            if stride != 24 or link >= len(self.sections) or offset + length > len(self.data):
                raise ValueError("invalid ELF symbol table")
            strings = self.sections[link]
            names = self.data[strings[4]:strings[4] + strings[5]]
            for pos in range(offset, offset + length, stride):
                name, info, _, index, address, size = struct.unpack_from("<IBBHQQ", self.data, pos)
                if info & 15 != 2 or index == 0 or index >= len(self.sections):
                    continue
                symbol = names[name:].split(b"\0", 1)[0]
                if fragment not in symbol:
                    continue
                target = self.sections[index]
                file_offset = target[4] + address - target[3]
                if not target[2] & 4 or not (target[4] <= file_offset < target[4] + target[5]):
                    raise ValueError("symbol is not executable file content")
                hits.add((file_offset, size))
        if len(hits) != 1:
            raise ValueError(f"expected exactly one Matches function, found {len(hits)}")
        return hits.pop()

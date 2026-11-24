"""Report ramoops and console storage declarations in Flip4 DTB/DTBO images."""
import argparse
import json
from pathlib import Path
import struct


def trees(image):
    magic = bytes.fromhex("d00dfeed")
    offset = image.find(magic)
    while offset != -1:
        _, size, _, _, _, version, *_ = struct.unpack_from(">10I", image, offset)
        if version < 17 or size < 40 or size > len(image) - offset:
            raise ValueError(f"invalid FDT header at byte {offset}")
        yield image[offset:offset + size]
        offset = image.find(magic, offset + size)


def nodes(tree):
    _, _, struct_offset, strings_offset, _, _, _, _, strings_size, struct_size = struct.unpack_from(">10I", tree)
    data = tree[struct_offset:struct_offset + struct_size]
    strings = tree[strings_offset:strings_offset + strings_size]
    parents = []
    offset = 0
    while offset < len(data):
        token, = struct.unpack_from(">I", data, offset)
        offset += 4
        if token == 1:
            end = data.index(0, offset)
            parents.append((data[offset:end].decode(), {}))
            offset = (end + 4) & ~3
        elif token == 2:
            yield "/".join(name for name, _ in parents), parents.pop()[1]
        elif token == 3:
            size, name_offset = struct.unpack_from(">II", data, offset)
            name = strings[name_offset:strings.index(0, name_offset)].decode()
            offset += 8
            parents[-1][1][name] = data[offset:offset + size]
            offset = (offset + size + 3) & ~3
        elif token == 9:
            return
        elif token != 4:
            raise ValueError(f"unexpected FDT token {token}")


def inspect(image):
    reports = []
    for tree in trees(image):
        entries = []
        for path, props in nodes(tree):
            compatible = props.get("compatible", b"").rstrip(b"\0").decode().split("\0")
            if not any("ramoops" in value or "pstore" in value for value in compatible):
                continue
            entry = {"path": path, "compatible": compatible, "status": props.get("status", b"okay").rstrip(b"\0").decode()}
            for prop in ("reg", "size", "alloc-ranges", "record-size", "console-size", "pmsg-size", "ftrace-size", "memory-region"):
                if prop in props:
                    entry[prop] = [f"0x{cell:08x}" for cell, in struct.iter_unpack(">I", props[prop])]
            entries.append(entry)
        reports.append(entries)
    if not reports:
        raise ValueError("no device trees found")
    return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path)
    args = parser.parse_args()
    print(json.dumps({path.name: inspect(path.read_bytes()) for path in args.images}, indent=2))

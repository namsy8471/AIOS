"""Report ramoops and console storage declarations in Flip4 DTB/DTBO images."""
import argparse
import json
from pathlib import Path
import struct

from flip4_fdt import nodes, trees


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

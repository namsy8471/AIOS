"""Set the reference touch drivers' bring-up mode and disable firmware names."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile

from flip4_board import DTB_INDEX, DTBO_INDEX, check_identity, overlay_at
from flip4_fdt import nodes, trees

POLICY = (
    ("/fragment@87/__overlay__/touchscreen@49", "/soc/i2c@a80000/touchscreen@49",
     "sec", b"tsp_stm/fst2ca78y_b4.bin\0"),
    ("/fragment@76/__overlay__/touchscreen@20", "/soc/i2c@984000/touchscreen@20",
     "zinitix", b"tsp_zinitix/ztw522_b4.bin\0"),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtb", type=Path)
    parser.add_argument("dtbo", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    table = args.dtbo.read_bytes()
    base = list(trees(args.dtb.read_bytes()))[DTB_INDEX]
    original = overlay_at(table, DTBO_INDEX)
    check_identity(base, original)
    offsets = {}
    properties = dict(nodes(original, offsets))
    candidate = bytearray(original)
    for fragment, _, prefix, firmware in POLICY:
        for key, expected, value in (
            (f"{prefix},bringup", bytes(4), b"\0\0\0\1"),
            (f"{prefix},firmware_name", firmware, bytes(len(firmware))),
        ):
            if properties[fragment][key] != expected:
                raise ValueError(f"Unexpected source property {fragment}/{key}")
            offset, size = offsets[fragment, key]
            candidate[offset:offset + size] = value
    _, _, _, entry_size, count, entries, _, _ = struct.unpack_from(">8I", table)
    _, start = struct.unpack_from(">2I", table, entries + DTBO_INDEX * entry_size)
    result = table[:start] + candidate + table[start + len(original):]
    if len(result) != len(table) or any(
        overlay_at(result, index) != overlay_at(table, index)
        for index in range(count) if index != DTBO_INDEX
    ):
        raise ValueError("touch policy changed other entries or the table layout")
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory)
        (stage / "base.dtb").write_bytes(base)
        (stage / "policy.dtbo").write_bytes(candidate)
        subprocess.run(["fdtoverlay", "-i", stage / "base.dtb", "-o", stage / "merged.dtb", stage / "policy.dtbo"],
                       check=True)
        merged = dict(nodes((stage / "merged.dtb").read_bytes()))
    for _, path, prefix, firmware in POLICY:
        if (merged[path][f"{prefix},bringup"] != b"\0\0\0\1"
                or merged[path][f"{prefix},firmware_name"] != bytes(len(firmware))):
            raise ValueError(f"touch policy did not reach {path}")
    args.output.write_bytes(result)
    print(json.dumps({
        "scope": "offline_reference_dtbo", "dtb_index": DTB_INDEX, "dtbo_index": DTBO_INDEX,
        "source_sha256": hashlib.sha256(table).hexdigest(), "policy_sha256": hashlib.sha256(result).hexdigest(),
        "touch_nodes": [path for _, path, _, _ in POLICY],
    }, indent=2))


if __name__ == "__main__":
    main()

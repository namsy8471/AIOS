"""Report the layout and component hashes of an Android boot header v2 image."""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def inspect(image):
    if len(image) < 1660 or image[:8] != b"ANDROID!":
        raise ValueError("expected an uncompressed Android boot or recovery image")
    kernel, kernel_addr, ramdisk, ramdisk_addr, second, second_addr, tags, page, version, _ = (
        struct.unpack_from("<10I", image, 8)
    )
    if version != 2:
        raise ValueError(f"expected Android header version 2, found {version}")
    overlay, overlay_offset, header_size, dtb, dtb_addr = struct.unpack_from("<IQIIQ", image, 1632)
    if header_size != 1660 or page < header_size or page & (page - 1) or not kernel:
        raise ValueError("invalid v2 header size, page size or kernel size")

    limit = len(image)
    footer = None
    if image[-64:-60] == b"AVBf":
        major, minor, original, vbmeta, vbmeta_size = struct.unpack_from(">IIQQQ", image, len(image) - 60)
        if not (page <= original <= vbmeta < vbmeta + vbmeta_size <= len(image) - 64):
            raise ValueError("invalid AVB footer offsets")
        limit = original
        footer = {"version": [major, minor], "original_image_size": original, "vbmeta_offset": vbmeta,
                  "vbmeta_size": vbmeta_size}

    cursor = page
    sections = {}
    for name, size, address in (
        ("kernel", kernel, kernel_addr), ("ramdisk", ramdisk, ramdisk_addr),
        ("second", second, second_addr), ("recovery_dtbo", overlay, None), ("dtb", dtb, dtb_addr),
    ):
        if not size:
            continue
        if name == "recovery_dtbo" and overlay_offset != cursor:
            raise ValueError("recovery DTBO offset disagrees with the preceding sections")
        end = cursor + size
        if end > limit:
            raise ValueError(f"{name} extends beyond the boot image payload")
        sections[name] = {"offset": cursor, "size": size, "load_address": address,
                          "sha256": hashlib.sha256(image[cursor:end]).hexdigest()}
        cursor = (end + page - 1) & ~(page - 1)

    return {"header_version": version, "page_size": page, "tags_address": tags,
            "image_size": len(image), "sha256": hashlib.sha256(image).hexdigest(),
            "sections": sections, "avb_footer": footer}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(inspect(args.image.read_bytes()), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")

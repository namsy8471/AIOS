"""Report boot and storage options from a raw ARM64 Image with embedded IKCONFIG."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zlib


OPTIONS = (
    "BLK_DEV_INITRD", "DEVTMPFS", "SCSI_UFSHCD", "SCSI_UFS_QCOM",
    "EXT4_FS", "F2FS_FS", "BTRFS_FS", "NAMESPACES", "USER_NS",
    "SECCOMP_FILTER", "SECURITY_SELINUX", "SECURITY_LANDLOCK",
    "PSTORE", "PSTORE_RAM", "PSTORE_CONSOLE", "PSTORE_PMSG",
)


def inspect(image):
    if image[56:60] != b"ARM\x64":
        raise ValueError("expected an uncompressed ARM64 kernel Image")
    start = image.find(b"IKCFG_ST\x1f\x8b")
    if start < 0:
        raise ValueError("no gzip-compressed IKCONFIG found")
    start += len(b"IKCFG_ST")
    end = image.find(b"IKCFG_ED", start)
    if end < 0:
        raise ValueError("missing IKCONFIG end marker")
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    config = decoder.decompress(image[start:end], 4 * 1024 * 1024)
    if not decoder.eof or decoder.unused_data:
        raise ValueError("incomplete or oversized embedded configuration")
    values = {}
    for line in config.decode().splitlines():
        if match := re.fullmatch(r"CONFIG_(\w+)=(.*)", line):
            values[match[1]] = match[2]
        elif match := re.fullmatch(r"# CONFIG_(\w+) is not set", line):
            values[match[1]] = "n"
    release = re.search(rb"Linux version ([^\s\x00]+)", image)
    return {
        "image_sha256": hashlib.sha256(image).hexdigest(),
        "kernel_release": release[1].decode() if release else None,
        "config_sha256": hashlib.sha256(config).hexdigest(),
        "options": {key: values.get(key) for key in OPTIONS},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(inspect(args.image.read_bytes()), indent=2))
    except (OSError, ValueError, zlib.error) as error:
        parser.exit(1, f"{error}\n")

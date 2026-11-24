"""Report ARM64 boot and driver options and compare an optional running kernel config."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import zlib


OPTIONS = (
    "BLK_DEV_INITRD", "DEVTMPFS", "SYSFS", "PROC_FS", "INPUT", "INPUT_EVDEV",
    "SCSI", "BLK_DEV_SD", "SCSI_UFSHCD", "SCSI_UFS_QCOM",
    "EXT4_FS", "F2FS_FS", "BTRFS_FS", "NAMESPACES", "USER_NS",
    "SECCOMP_FILTER", "SECURITY_SELINUX", "SECURITY_LANDLOCK",
    "PSTORE", "PSTORE_RAM", "PSTORE_CONSOLE", "PSTORE_PMSG",
    "MODULES", "MODVERSIONS", "TRIM_UNUSED_KSYMS", "MODULE_SIG",
    "DRM", "DRM_MSM", "DRM_VIRTIO_GPU", "VIRTIO_PCI",
)


def describe_config(config):
    values = {}
    for line in config.decode().splitlines():
        if match := re.fullmatch(r"CONFIG_(\w+)=(.*)", line):
            values[match[1]] = match[2]
        elif match := re.fullmatch(r"# CONFIG_(\w+) is not set", line):
            values[match[1]] = "n"
    return {
        "config_sha256": hashlib.sha256(config).hexdigest(),
        "options": {key: values.get(key) for key in OPTIONS},
    }


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
    release = re.search(rb"Linux version ([^\s\x00]+)", image)
    return {
        "image_sha256": hashlib.sha256(image).hexdigest(),
        "kernel_release": release[1].decode() if release else None,
        **describe_config(config),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--running-config", type=Path, help="a local copy of the running device's /proc/config.gz")
    args = parser.parse_args()
    try:
        report = inspect(args.image.read_bytes())
        if args.running_config:
            with gzip.open(args.running_config, "rb") as config_file:
                config = config_file.read(4 * 1024 * 1024 + 1)
            if len(config) > 4 * 1024 * 1024:
                raise ValueError("running configuration is oversized")
            running = describe_config(config)
            report["running"] = running
            report["option_differences"] = {
                key: {"image": value, "running": running["options"][key]}
                for key, value in report["options"].items() if value != running["options"][key]
            }
        print(json.dumps(report, indent=2))
    except (OSError, EOFError, ValueError, zlib.error) as error:
        parser.exit(1, f"{error}\n")

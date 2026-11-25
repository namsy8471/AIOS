"""Exercise the reference kernel's normal loader on recovery driver modules in QEMU."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
import sys
import tempfile


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from flip4_board import PROVIDERS


TOUCH_TARGETS = ("fst2ca78y_i2c.ko", "zinitix_ts.ko")
TARGETS = ("msm_drm.ko", *TOUCH_TARGETS, "ufs_qcom.ko")


def module_order(dependency_text, targets=TARGETS):
    def name(path):
        basename = PurePosixPath(path).name
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.ko", basename):
            raise ValueError(f"Invalid module name: {path}")
        return basename

    dependencies = {}
    for line in dependency_text.splitlines():
        module, separator, paths = line.partition(":")
        if not separator:
            raise ValueError(f"Invalid modules.dep line: {line}")
        dependencies[name(module)] = tuple(name(path) for path in paths.split())
    ordered = {}
    visiting = set()

    def visit(module):
        if module in ordered:
            return
        if module in visiting:
            raise ValueError(f"Cyclic module dependency: {module}")
        visiting.add(module)
        for dependency in dependencies[module]:
            visit(dependency)
        visiting.remove(module)
        ordered[module] = None

    for target in targets:
        visit(target)
    return list(ordered)


def module_abi(path):
    data = path.read_bytes()
    if data[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", data, 18)[0] != 183:
        raise ValueError(f"Expected ARM64 little-endian ELF: {path.name}")
    section_table = subprocess.check_output(["readelf", "-SW", path], text=True)
    sections = {}
    for name, offset, size in re.findall(
        r"^\s*\[\s*\d+\]\s+(\.modinfo|__versions)\s+PROGBITS\s+[0-9a-f]+\s+([0-9a-f]+)\s+([0-9a-f]+)\s",
        section_table, re.MULTILINE,
    ):
        start, length = int(offset, 16), int(size, 16)
        if start + length > len(data):
            raise ValueError(f"Truncated {name} in {path.name}")
        sections[name] = data[start:start + length]
    vermagic, = [entry.removeprefix(b"vermagic=").decode().strip()
                 for entry in sections[".modinfo"].split(b"\0") if entry.startswith(b"vermagic=")]
    required = {}
    for crc, name in struct.iter_unpack("<Q56s", sections.get("__versions", b"")):
        symbol = name.split(b"\0", 1)[0].decode()
        if not symbol or symbol in required or crc > 0xFFFFFFFF:
            raise ValueError(f"Invalid symbol version in {path.name}")
        required[symbol] = f"0x{crc:08x}"
    return {"sha256": hashlib.sha256(data).hexdigest(), "vermagic": vermagic, "required_crcs": required}


def symbol_exports(data):
    exports = {}
    for line in data.decode().splitlines():
        if not line.strip():
            continue
        crc, symbol, *_ = line.split()
        if not re.fullmatch(r"0x[0-9a-fA-F]{8}", crc):
            raise ValueError(f"Invalid Module.symvers CRC for {symbol}")
        if exports.setdefault(symbol, crc.lower()) != crc.lower():
            raise ValueError(f"Conflicting Module.symvers CRCs for {symbol}")
    if not exports:
        raise ValueError("Module.symvers has no symbol exports")
    return exports


def abi_report(kernel_hash, root, order, symvers):
    report = {"scope": "offline_arm64_reference_modules", "kernel_sha256": kernel_hash, "modules": {}}
    exports = None
    if symvers:
        source = symvers.read_bytes()
        exports = symbol_exports(source)
        report["module_symvers_sha256"] = hashlib.sha256(source).hexdigest()
    for module in order:
        abi = module_abi(root / "lib/modules" / module)
        if exports is not None:
            required = abi["required_crcs"]
            abi["missing_exports"] = sorted(required.keys() - exports.keys())
            abi["crc_mismatches"] = {
                name: {"required": crc, "exported": exports[name]}
                for name, crc in required.items() if name in exports and exports[name] != crc
            }
        report["modules"][module] = abi
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recovery", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--overlay", action="store_true", help="build the driver archive for a reference document boot")
    parser.add_argument("--board-overlay", action="store_true", help="include CAPE hardware providers in the driver overlay")
    parser.add_argument("--abi-only", action="store_true", help="report module ABI metadata without booting a guest")
    parser.add_argument("--module-symvers", type=Path, help="compare against exports from a specific target build")
    args = parser.parse_args()
    if args.abi_only and args.overlay:
        parser.error("--abi-only and --overlay are mutually exclusive")
    if args.module_symvers and not args.abi_only:
        parser.error("--module-symvers requires --abi-only")
    if args.board_overlay and not (args.overlay or args.abi_only):
        parser.error("--board-overlay requires --overlay or --abi-only")
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory)
        root = stage / "root"
        root.mkdir()
        subprocess.run(["unpack_bootimg", "--boot_img", args.recovery, "--out", stage / "image"], check=True)
        kernel = stage / "image/kernel"
        kernel_hash = hashlib.sha256(kernel.read_bytes()).hexdigest()
        archive = gzip.decompress((stage / "image/ramdisk").read_bytes())
        dependencies = subprocess.check_output(
            ["cpio", "-i", "--to-stdout", "--quiet", "lib/modules/modules.dep"], input=archive,
        )
        targets = (*PROVIDERS.values(), *TARGETS) if args.board_overlay else TARGETS
        dependency_text = dependencies.decode()
        order = module_order(dependency_text, targets)
        paths = [f"lib/modules/{name}" for name in order]
        subprocess.run(["cpio", "-id", "--quiet", "--no-absolute-filenames", "--no-preserve-owner", *paths],
                       input=archive, cwd=root, check=True)
        if any(not (root / path).is_file() or (root / path).is_symlink() for path in paths):
            raise ValueError("The recovery ramdisk did not provide each declared module as a file")
        if args.abi_only:
            report = abi_report(kernel_hash, root, order, args.module_symvers)
            (args.output / "abi.json").write_text(json.dumps(report, indent=2) + "\n")
            return
        (root / "module-order").write_text("\n".join(order) + "\n")
        if args.board_overlay:
            diagnostic_targets = (*PROVIDERS.values(), "msm_drm.ko", "ufs_qcom.ko")
            diagnostic_order = module_order(dependency_text, diagnostic_targets)
            if set(TOUCH_TARGETS).intersection(diagnostic_order):
                raise ValueError("A diagnostic module depends on a touch firmware update driver")
            (root / "module-order-without-touch").write_text("\n".join(diagnostic_order) + "\n")
        executable = root / ("usr/bin/flip4-driver-loader" if args.overlay else "init")
        executable.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([os.environ.get("CC", "cc"), "-static", "-O2", "-Wall", "-Wextra", "tests/flip4_module_init.c", "-o", executable], check=True)
        if not args.overlay:
            (root / "dev").mkdir()
            subprocess.run(["sudo", "mknod", "-m", "600", root / "dev/console", "c", "5", "1"], check=True)
        files = [str(path.relative_to(root)) for path in sorted(root.rglob("*"))]
        initramfs = args.output / "drivers.cpio.gz" if args.overlay else stage / "probe.cpio.gz"
        initramfs.write_bytes(gzip.compress(subprocess.check_output(
            ["cpio", "-o", "-H", "newc", "--owner=0:0", "--null", "--quiet"],
            input=("\0".join(files) + "\0").encode(), cwd=root,
        ), compresslevel=2))
        if args.board_overlay:
            files = subprocess.check_output(["cpio", "-it", "--quiet"], input=archive)
            (args.output / "recovery-files.txt").write_bytes(files)
        if args.overlay:
            (args.output / "order.txt").write_text("\n".join(order) + "\n")
            if args.board_overlay:
                (args.output / "order-without-touch.txt").write_text("\n".join(diagnostic_order) + "\n")
            return
        log = args.output / "console.log"
        with log.open("wb") as output:
            subprocess.run([
                "qemu-system-aarch64", "-machine", "virt,gic-version=3", "-cpu", "max", "-m", "1024M",
                "-nic", "none", "-display", "none", "-monitor", "none", "-serial", "stdio", "-no-reboot",
                "-kernel", kernel, "-initrd", initramfs,
                "-append", "earlycon=pl011,0x9000000 console=ttyAMA0 rdinit=/init panic=1",
            ], stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, timeout=90, check=True)

    lines = log.read_text(errors="replace").splitlines()
    results = [(module, int(error)) for module, error in
               re.findall(r"^AIOS_MODULE_RESULT (\S+) (\d+)$", "\n".join(lines), re.MULTILINE)]
    if [module for module, _ in results] != order or "AIOS_MODULE_PROBE_DONE" not in lines:
        raise RuntimeError(f"Incomplete module probe; see {log}")
    errors = dict(results)
    report = {
        "kernel_sha256": kernel_hash,
        "module_count": len(results),
        "target_errno": {module: errors[module] for module in TARGETS},
        "module_errno": errors,
        "symbol_errors": [line for line in lines if "Unknown symbol" in line or "disagrees about version" in line],
    }
    (args.output / "proof.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["target_errno"]))


if __name__ == "__main__":
    main()

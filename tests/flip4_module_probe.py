"""Exercise the reference kernel's normal loader on recovery driver modules in QEMU."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from flip4_board import PROVIDERS


TARGETS = ("msm_drm.ko", "fst2ca78y_i2c.ko", "zinitix_ts.ko", "ufs_qcom.ko")


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recovery", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--overlay", action="store_true", help="build the driver archive for a reference document boot")
    parser.add_argument("--board-overlay", action="store_true", help="include CAPE hardware providers in the driver overlay")
    args = parser.parse_args()
    if args.board_overlay and not args.overlay:
        parser.error("--board-overlay requires --overlay")
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
        order = module_order(dependencies.decode(), targets)
        paths = [f"lib/modules/{name}" for name in order]
        subprocess.run(["cpio", "-id", "--quiet", "--no-absolute-filenames", "--no-preserve-owner", *paths],
                       input=archive, cwd=root, check=True)
        if any(not (root / path).is_file() or (root / path).is_symlink() for path in paths):
            raise ValueError("The recovery ramdisk did not provide each declared module as a file")
        (root / "module-order").write_text("\n".join(order) + "\n")
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
        if args.overlay:
            (args.output / "order.txt").write_text("\n".join(order) + "\n")
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

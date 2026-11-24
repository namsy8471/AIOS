"""Verify the board diagnostic ramdisk using QEMU's virtual device tree."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def boot(directory, load_drivers):
    args = [
        "qemu-system-aarch64", "-machine", "virt,gic-version=3", "-cpu", "max", "-m", "1024M",
        "-nic", "none", "-display", "none", "-monitor", "none", "-serial", "stdio", "-no-reboot",
        "-kernel", directory / "payload/kernel", "-initrd", directory / "payload/ramdisk",
        "-append", "earlycon=pl011,0x9000000 console=ttyAMA0 rdinit=/init panic=1"
        + (" aios.qemu_flip4_probe=1" if load_drivers else ""),
    ]
    log_path = directory / ("console-drivers.log" if load_drivers else "console-default.log")
    records = {}
    module_results = []
    with log_path.open("wb", buffering=0) as log, subprocess.Popen(
        args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    ) as vm:
        try:
            for raw in vm.stdout:
                log.write(raw)
                line = raw.decode(errors="replace").strip()
                if match := re.fullmatch(r"AIOS_MODULE_RESULT (\S+) (\d+)", line):
                    module_results.append((match[1], int(match[2])))
                if line.startswith("AIOS_FLIP4_"):
                    name, value = line.split(" ", 1)
                    records[name.removeprefix("AIOS_FLIP4_")] = json.loads(value)
                if line.startswith("AIOS_FLIP4_DONE "):
                    break
            assert "ERROR" not in records and records["DONE"]["scope"] == "qemu_virt", records
            assert records["BOARD"]["scope"] == "qemu_virt"
            assert set(records["DEVICES"]) == {"drm", "input", "block"}
            assert "drm_connectors" in records["DISPLAY"]
            if load_drivers:
                assert records["MODULES"] == {"attempted": True, "exit_code": 0, "error": None}, records
                order = (directory / "order.txt").read_text().splitlines()
                assert len(order) == len(set(order)) > 0
                assert module_results == [(module, 0) for module in order], module_results
                assert vm.wait(timeout=15) == 0
            else:
                assert records["MODULES"] == {"attempted": False, "exit_code": None, "error": None}, records
                assert not module_results
        finally:
            if vm.poll() is None:
                vm.kill()
    return {"driver_count": len(module_results), "records": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    directory = args.directory
    layout = json.loads((directory / "layout.json").read_text())
    payload = {}
    for name in ("kernel", "ramdisk"):
        payload[name] = hashlib.sha256((directory / "payload" / name).read_bytes()).hexdigest()
        assert layout["sections"][name]["sha256"] == payload[name]
    print(json.dumps({
        "scope": "qemu_virt", "payload": payload,
        "default": boot(directory, load_drivers=False),
        "driver_opt_in": boot(directory, load_drivers=True),
    }, indent=2))


if __name__ == "__main__":
    main()

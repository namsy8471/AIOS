"""Verify the board diagnostic ramdisk using QEMU's virtual device tree."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def boot(directory, load_drivers, without_touch=False):
    args = [
        "qemu-system-aarch64", "-machine", "virt,gic-version=3", "-cpu", "max", "-m", "1024M",
        "-nic", "none", "-display", "none", "-monitor", "none", "-serial", "stdio", "-no-reboot",
        "-kernel", directory / "payload/kernel", "-initrd", directory / "payload/ramdisk",
        "-append", "earlycon=pl011,0x9000000 console=ttyAMA0 rdinit=/init panic=1"
        + (" aios.qemu_flip4_probe=1" if load_drivers else "")
        + (" aios.qemu_flip4_without_touch=1" if without_touch else ""),
    ]
    profile = "without-touch" if without_touch else "drivers" if load_drivers else "default"
    log_path = directory / f"console-{profile}.log"
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
                assert records["MODULES"] == {
                    "attempted": True, "exit_code": 0, "error": None,
                    "touch_modules_enabled": not without_touch,
                }, records
                order_file = "order-without-touch.txt" if without_touch else "order.txt"
                order = (directory / order_file).read_text().splitlines()
                for module in ("fst2ca78y_i2c.ko", "zinitix_ts.ko"):
                    assert (module in order) == (not without_touch)
                assert len(order) == len(set(order)) > 0
                assert module_results == [(module, 0) for module in order], module_results
                assert vm.wait(timeout=15) == 0
            else:
                assert records["MODULES"] == {
                    "attempted": False, "exit_code": None, "error": None, "touch_modules_enabled": False,
                }, records
                assert not module_results
        finally:
            if vm.poll() is None:
                vm.kill()
    return {"driver_count": len(module_results), "records": records}


def pstore_reboot(directory):
    dtb = directory / "qemu-ramoops.dtb"
    machine = "virt,gic-version=3"
    args = [
        "qemu-system-aarch64", "-cpu", "max", "-m", "1024M", "-nic", "none", "-display", "none",
        "-monitor", "none", "-serial", "stdio", "-kernel", directory / "payload/kernel",
        "-initrd", directory / "payload/ramdisk",
    ]
    subprocess.run([*args, "-machine", f"{machine},dumpdtb={dtb}"], check=True, stdout=subprocess.DEVNULL)
    node = "/reserved-memory/ramoops@70000000"
    for values in [
        ["-p", "-c", dtb, node],
        ["-t", "x", dtb, "/reserved-memory", "#address-cells", "2"],
        ["-t", "x", dtb, "/reserved-memory", "#size-cells", "2"],
        ["-t", "x", dtb, "/reserved-memory", "ranges"],
        ["-t", "s", dtb, node, "compatible", "ramoops"],
        ["-t", "x", dtb, node, "reg", "0", "70000000", "0", "200000"],
        ["-t", "x", dtb, node, "pmsg-size", "200000"],
    ]:
        subprocess.run(["fdtput", *values], check=True)
    log_path = directory / "console-pstore.log"
    with log_path.open("wb") as log:
        subprocess.run([
            *args, "-machine", machine, "-dtb", dtb, "-append",
            "earlycon=pl011,0x9000000 console=ttyAMA0 rdinit=/init panic=1 "
            "aios.qemu_flip4_probe=1 aios.qemu_flip4_pstore=1",
        ], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, timeout=50, check=True)
    lines = log_path.read_text(errors="replace").splitlines()

    def records(name):
        prefix = f"AIOS_FLIP4_{name} "
        return [json.loads(line.removeprefix(prefix)) for line in lines if line.startswith(prefix)]

    [first, second] = records("BOARD")
    [written] = records("PSTORE")
    [recovered] = records("RECOVERED")
    assert written == {"written": True, "error": None}
    assert first == second == recovered["board"]
    for name in ("modules", "display", "devices"):
        assert records(name.upper()) == [recovered[name]], name
    assert recovered["modules"] == {
        "attempted": True, "exit_code": 0, "error": None, "touch_modules_enabled": True,
    }
    return recovered


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
        "driver_without_touch": boot(directory, load_drivers=True, without_touch=True),
        "pstore_after_reboot": pstore_reboot(directory),
    }, indent=2))


if __name__ == "__main__":
    main()

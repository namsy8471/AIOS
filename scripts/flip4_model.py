"""Use the Flip4 reference kernel with a writable copy of the bundled ext4 disk."""
from pathlib import Path

from arm64_model import main

GUEST_RAM_MIB = 256

def launch(disk, guest_model=False, split_disk=False, *, boot_payload=None):
    kernel = boot_payload / "kernel" if boot_payload else Path(__file__).resolve().with_name("kernel")
    drive_path = str(disk.resolve()).replace(",", ",,")
    ram_mib = 1536 if guest_model else GUEST_RAM_MIB
    cpus = 4 if guest_model else 1
    root, mode = ("sda1", "ro") if split_disk else ("sda", "rw")
    cmdline = "earlycon=pl011,0x9000000 console=ttyAMA0 panic=1"
    boot = ["-append", f"{cmdline} root=/dev/{root} rootfstype=ext4 rootwait {mode} init=/init"]
    if boot_payload:
        mounts = "aios.qemu_document_disk=1"
        if guest_model:
            mounts += " aios.qemu_model_partition=1"
        boot = ["-initrd", str(boot_payload / "ramdisk"), "-append",
                f"{cmdline} rdinit=/init {mounts}"]
    return [
        "qemu-system-aarch64", "-machine", "virt,gic-version=3", "-cpu", "max",
        "-smp", str(cpus), "-m", f"{ram_mib}M", "-nic", "none",
        "-display", "none", "-monitor", "none",
        "-serial", "stdio", "-no-reboot", "-kernel", str(kernel),
        "-device", "qemu-xhci,id=xhci", "-drive", f"file={drive_path},if=none,id=docs,format=raw",
        "-device", "usb-storage,bus=xhci.0,drive=docs",
        *boot,
    ]


if __name__ == "__main__":
    main(launch)

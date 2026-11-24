"""Use the Flip4 reference kernel with a writable copy of the bundled ext4 disk."""
from pathlib import Path

from arm64_model import main

GUEST_RAM_MIB = 256

def launch(disk, guest_model=False):
    kernel = Path(__file__).resolve().with_name("kernel")
    drive_path = str(disk.resolve()).replace(",", ",,")
    ram_mib = 1536 if guest_model else GUEST_RAM_MIB
    return [
        "qemu-system-aarch64", "-machine", "virt,gic-version=3", "-cpu", "max",
        "-m", f"{ram_mib}M", "-nic", "none", "-display", "none", "-monitor", "none",
        "-serial", "stdio", "-no-reboot", "-kernel", str(kernel),
        "-device", "qemu-xhci,id=xhci", "-drive", f"file={drive_path},if=none,id=docs,format=raw",
        "-device", "usb-storage,bus=xhci.0,drive=docs",
        "-append", "earlycon=pl011,0x9000000 console=ttyAMA0 root=/dev/sda rootfstype=ext4 rootwait rw init=/init panic=1",
    ]


if __name__ == "__main__":
    main(launch)

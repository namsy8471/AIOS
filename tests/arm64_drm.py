"""Verify Linux probe results for a booted ARM64 DRM device and absolute pointer."""
import json
from pathlib import Path
import subprocess
import sys


bundle, initramfs, disk, output = map(Path, sys.argv[1:5])
sys.path.insert(0, str(bundle.resolve()))
from arm64_model import command, wait


args = [
    "qemu-system-aarch64", "-machine", "virt", "-cpu", "cortex-a53", "-m", "256M",
    "-nic", "none", "-display", "none", "-monitor", "none", "-serial", "stdio", "-no-reboot",
    "-kernel", str(bundle / "vmlinuz-virt"), "-initrd", str(initramfs),
    "-drive", f"file={disk},if=virtio,format=raw",
    "-device", "virtio-gpu-pci", "-device", "virtio-tablet-pci",
    "-append", "console=ttyAMA0 root=/dev/vda rootfstype=ext4 rw modules=virtio_gpu,virtio_input,evdev panic=1",
]
with (output / "console.log").open("wb", buffering=0) as log, subprocess.Popen(
    args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
) as vm:
    try:
        wait(vm, log, "AIOS_DOCUMENT_READY pid=1")
        reply = command(vm, log, "display-capabilities", "AIOS_")
        report = json.loads(reply.removeprefix("AIOS_DISPLAY "))
        # DRM's device symlink points to the PCI transport, while the kernel
        # log names the graphics driver that registered the DRM card.
        assert any(card["driver"] == "virtio-pci" for card in report["drm_cards"]), report
        assert "[drm] Initialized virtio_gpu " in Path(log.name).read_text(errors="replace")
        assert any(port["status"] == "connected" and port["modes"] for port in report["drm_connectors"]), report
        assert any("Tablet" in device["name"] for device in report["absolute_inputs"]), report
        vm.stdin.write(b"poweroff\n")
        vm.stdin.flush()
        assert vm.wait(timeout=20) == 0
        (output / "display.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    finally:
        if vm.poll() is None:
            vm.kill()

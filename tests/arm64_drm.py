"""Verify Linux probe results for a booted ARM64 DRM device and absolute pointer."""
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time


bundle, initramfs, disk, output = map(Path, sys.argv[1:5])
monitor = disk.with_suffix(".qmp")
sys.path.insert(0, str(bundle.resolve()))
from arm64_model import command, read_document, wait


args = [
    "qemu-system-aarch64", "-machine", "virt", "-cpu", "cortex-a53", "-m", "256M",
    "-nic", "none", "-display", "none", "-monitor", "none", "-serial", "stdio", "-no-reboot",
    "-qmp", f"unix:{monitor},server=on,wait=off",
    "-kernel", str(bundle / "vmlinuz-virt"), "-initrd", str(initramfs),
    "-drive", f"file={disk},if=virtio,format=raw",
    "-device", "virtio-gpu-pci", "-device", "virtio-tablet-pci",
    "-append", "console=ttyAMA0 root=/dev/vda rootfstype=ext4 rw modules=virtio_gpu,virtio_input,evdev panic=1",
]


def qmp(stream, name, arguments=None):
    request = {"execute": name}
    if arguments is not None:
        request["arguments"] = arguments
    stream.write(json.dumps(request).encode() + b"\n")
    while reply := stream.readline():
        message = json.loads(reply)
        if "error" in message:
            raise RuntimeError(message["error"])
        if "return" in message:
            return message["return"]
    raise RuntimeError("QEMU monitor disconnected")


def verify_frame(path, colors, row_fraction):
    magic, dimensions, depth, pixels = path.read_bytes().split(b"\n", 3)
    width, height = map(int, dimensions.split())
    assert magic == b"P6" and depth == b"255" and len(pixels) == 3 * width * height
    row = int(height * row_fraction) * width
    samples = [pixels[(row + x) * 3:(row + x) * 3 + 3] for x in (width // 6, width // 2, width * 5 // 6)]
    return samples == [bytes.fromhex(color) for color in colors]


def capture_frame(stream, screenshot, colors, row_fraction=0.5):
    for _ in range(10):
        qmp(stream, "screendump", {"filename": str(screenshot.resolve())})
        if verify_frame(screenshot, colors, row_fraction):
            return
        time.sleep(0.2)
    raise RuntimeError("QEMU scanout did not contain the expected diagnostic colors")


def tap(stream, x, y):
    qmp(stream, "input-send-event", {"events": [
        {"type": "abs", "data": {"axis": "x", "value": x}},
        {"type": "abs", "data": {"axis": "y", "value": y}},
        {"type": "btn", "data": {"button": "left", "down": True}},
    ]})
    qmp(stream, "input-send-event", {"events": [
        {"type": "btn", "data": {"button": "left", "down": False}},
    ]})


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
        frame = command(vm, log, "display-frame", "AIOS_")
        assert frame.startswith("AIOS_FRAME_READY "), frame
        screenshot = output / "scanout.ppm"
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(10)
            connection.connect(str(monitor))
            with connection.makefile("rwb", buffering=0) as stream:
                assert "QMP" in json.loads(stream.readline())
                qmp(stream, "qmp_capabilities")
                capture_frame(stream, screenshot, ("cc3322", "22aa55", "2244cc"))
                tap(stream, 24576, 16384)
                tapped = wait(vm, log, "AIOS_")
                assert tapped.startswith("AIOS_POINTER_TAP "), tapped
                x, y = map(int, tapped.split()[1:])
                width, height = map(int, frame.split()[1].split("x"))
                assert abs(x - width * 3 / 4) <= 2 and abs(y - height / 2) <= 2, (x, y)
                capture_frame(stream, output / "after-tap.ppm", ("cc3322", "22aa55", "f2c94c"))
                report["pointer_tap"] = {"x": x, "y": y}
                assert command(vm, log, "", "AIOS_") == "AIOS_FRAME_DONE"
                original = "작업 기록"
                before = hashlib.sha256(original.encode()).hexdigest()
                request = f"confirm-append {before} 우유"
                assert command(vm, log, request, "AIOS_").startswith("AIOS_CONFIRM_READY ")
                tap(stream, 8192, 24576)
                assert wait(vm, log, "AIOS_") == "AIOS_REJECT confirmation-canceled"
                assert read_document(vm, before)["text"] == original

                assert command(vm, log, request, "AIOS_").startswith("AIOS_CONFIRM_READY ")
                capture_frame(stream, output / "confirmation.ppm", ("38425a", "12192d", "204caf"), 0.79)
                tap(stream, 24576, 24576)
                expected = original + "\n우유"
                revision = hashlib.sha256(expected.encode()).hexdigest()
                assert wait(vm, log, "AIOS_") == f"AIOS_SAVED revision={revision}"
                assert read_document(vm, revision)["text"] == expected
                assert command(vm, log, request, "AIOS_") == "AIOS_REJECT invalid-edit"
                report["confirmed_note"] = {"text": expected, "revision": revision}
        report["scanout_verified"] = frame.removeprefix("AIOS_FRAME_READY ")
        vm.stdin.write(b"poweroff\n")
        vm.stdin.flush()
        assert vm.wait(timeout=20) == 0
        (output / "display.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    finally:
        if vm.poll() is None:
            vm.kill()

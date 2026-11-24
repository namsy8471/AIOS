"""Verify Linux probe results for a booted ARM64 DRM device and absolute pointer."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time


parser = argparse.ArgumentParser(description=__doc__)
for name in ("bundle", "initramfs", "disk", "output"):
    parser.add_argument(name, type=Path)
model_options = parser.add_mutually_exclusive_group()
model_options.add_argument("--model", action="store_true")
model_options.add_argument("--model-source", type=Path)
parser.add_argument("--multitouch", action="store_true")
options = parser.parse_args()
bundle, initramfs, disk, output = options.bundle, options.initramfs, options.disk, options.output
model_source = options.model_source
if model_source is not None and (not model_source.is_file() or (disk.exists() and disk.samefile(model_source))):
    parser.error("provide a separate model source image")
local_model = options.model or model_source is not None
multitouch = options.multitouch
monitor = disk.with_suffix(".qmp")
sys.path.insert(0, str(bundle.resolve()))
from arm64_model import command, read_document, wait
from arm64_touch import launch


args = launch(bundle, disk, display="none", model=local_model, multitouch=multitouch,
              monitor=f"unix:{monitor},server=on,wait=off", initramfs=initramfs, model_source=model_source)


def sha256(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


model_hash = sha256(model_source) if model_source else None


def model_proposal(vm, log, revision):
    instruction = "메모에 '우유'를 적어줘."
    start = log.tell()
    ready = command(vm, log, f"model-confirm-append {revision} {instruction}", "AIOS_")
    assert ready.startswith("AIOS_CONFIRM_READY "), ready
    with Path(log.name).open("rb") as transcript:
        transcript.seek(start)
        lines = transcript.read().splitlines()
    usage, = [json.loads(line.removeprefix(b"MODEL_USAGE ")) for line in lines
              if line.startswith(b"MODEL_USAGE ")]
    proposal, = [json.loads(line.removeprefix(b"MODEL_PROPOSAL ")) for line in lines
                 if line.startswith(b"MODEL_PROPOSAL ")]
    assert usage["inference_ms"] > 0 and usage["model_peak_rss_kib"] > 0, usage
    assert proposal == {"name": "append_line", "arguments": {
        "document": "note.txt", "revision": revision, "line": "우유",
    }}, proposal
    return usage, proposal


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


def preview_lines(path):
    _, dimensions, _, pixels = path.read_bytes().split(b"\n", 3)
    width, height = map(int, dimensions.split())
    lines = 0
    previous = False
    for y in range(height // 3, height // 2):
        row = 3 * y * width
        left, right = width * 15 // 100, width * 85 // 100
        drawn = any(pixels[i] >= 230 and pixels[i + 1] >= 230 and pixels[i + 2] >= 230
                    for i in range(row + left * 3, row + right * 3, 3))
        if drawn and not previous:
            lines += 1
        previous = drawn
    return lines


def contact(stream, slot, tracking, x=None, y=None):
    events = [
        {"type": "mtt", "data": {"type": "end" if tracking < 0 else "begin",
         "slot": slot, "tracking-id": tracking, "axis": "x", "value": 0}},
    ]
    if x is not None:
        events.extend({"type": "mtt", "data": {"type": "data", "slot": slot,
                       "tracking-id": tracking, "axis": axis, "value": value}}
                      for axis, value in (("x", x), ("y", y)))
    qmp(stream, "input-send-event", {"events": events})


def tap(stream, x, y):
    if multitouch:
        contact(stream, 0, 1, x, y)
        contact(stream, 0, -1)
        return
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
        expected_device = "multitouch" if multitouch else "tablet"
        assert any(expected_device in device["name"].lower() for device in report["absolute_inputs"]), report
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
                if multitouch:
                    assert (width, height) == (1080, 2640), (width, height)
                assert abs(x - width * 3 / 4) <= 2 and abs(y - height / 2) <= 2, (x, y)
                capture_frame(stream, output / "after-tap.ppm", ("cc3322", "22aa55", "f2c94c"))
                report["pointer_tap"] = {"x": x, "y": y}
                assert command(vm, log, "", "AIOS_") == "AIOS_FRAME_DONE"
                original = "작업 기록"
                before = hashlib.sha256(original.encode()).hexdigest()
                addition = "내일 아침에 우유와 사과를 사서 냉장고에 넣어 두기" if multitouch else "우유"
                request = f"confirm-append {before} {addition}"
                assert command(vm, log, request, "AIOS_").startswith("AIOS_CONFIRM_READY ")
                if multitouch:
                    preview = output / "long-preview.ppm"
                    capture_frame(stream, preview, ("38425a", "12192d", "204caf"), 0.79)
                    report["preview_visible_rows"] = preview_lines(preview)
                    assert report["preview_visible_rows"] >= 2, report
                tap(stream, 8192, 24576)
                assert wait(vm, log, "AIOS_") == "AIOS_REJECT confirmation-canceled"
                assert read_document(vm, before)["text"] == original

                if local_model:
                    addition = "우유"
                    canceled, canceled_proposal = model_proposal(vm, log, before)
                    tap(stream, 8192, 24576)
                    assert wait(vm, log, "AIOS_") == "AIOS_REJECT confirmation-canceled"
                    report["model_cancellation"] = {
                        "usage": canceled, "proposal": canceled_proposal,
                        "note": read_document(vm, before, log=log),
                    }
                    assert report["model_cancellation"]["note"] == {"text": original, "revision": before}
                    report["model_usage"], report["model_proposal"] = model_proposal(vm, log, before)
                else:
                    assert command(vm, log, request, "AIOS_").startswith("AIOS_CONFIRM_READY ")
                preview = output / "confirmation.ppm"
                capture_frame(stream, preview, ("38425a", "12192d", "204caf"), 0.79)
                if multitouch:
                    contact(stream, 0, 1, 24576, 24576)
                    contact(stream, 1, 2, 8192, 24576)
                    contact(stream, 0, -1)
                    contact(stream, 1, -1)
                    capture_frame(stream, output / "after-two-fingers.ppm", ("38425a", "12192d", "204caf"), 0.79)
                tap(stream, 24576, 24576)
                expected = original + "\n" + addition
                revision = hashlib.sha256(expected.encode()).hexdigest()
                assert wait(vm, log, "AIOS_") == f"AIOS_SAVED revision={revision}"
                assert read_document(vm, revision)["text"] == expected
                assert command(vm, log, request, "AIOS_") == "AIOS_REJECT invalid-edit"
                report["confirmed_note"] = {"text": expected, "revision": revision}
                report["input_protocol"] = "multitouch-type-b" if multitouch else "absolute-pointer"
        report["scanout_verified"] = frame.removeprefix("AIOS_FRAME_READY ")
        report["display_buffer_allocations"] = Path(log.name).read_bytes().count(b"AIOS display allocated ")
        assert report["display_buffer_allocations"] == 1, report
        vm.stdin.write(b"poweroff\n")
        vm.stdin.flush()
        assert vm.wait(timeout=20) == 0
    finally:
        if vm.poll() is None:
            vm.kill()

if local_model and multitouch:
    args = launch(bundle, disk, display="none", model=local_model, multitouch=multitouch, initramfs=initramfs,
                  model_source=model_source)
    with (output / "reboot.log").open("wb", buffering=0) as log, subprocess.Popen(
        args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    ) as vm:
        try:
            wait(vm, log, "AIOS_DOCUMENT_READY pid=1")
            report["reopened_note"] = read_document(vm, revision, log=log)
            assert report["reopened_note"] == report["confirmed_note"]
            vm.stdin.write(b"poweroff\n")
            vm.stdin.flush()
            assert vm.wait(timeout=20) == 0
        finally:
            if vm.poll() is None:
                vm.kill()

if model_source:
    assert sha256(model_source) == model_hash
    report["model_source_sha256"] = model_hash

(output / "display.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

"""Validate explicit Flip4 volume selection on an isolated QEMU disk."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("bundle", type=Path)
parser.add_argument("image", type=Path)
parser.add_argument("invalid_image", type=Path)
parser.add_argument("disk", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
sys.path.insert(0, str(args.bundle.resolve()))
from arm64_model import command, read_document, wait


def disk_hash(model_only=False):
    with args.disk.open("rb") as disk:
        if not model_only:
            return hashlib.file_digest(disk, "sha256").hexdigest()
        disk.seek(1 << 20)
        digest = hashlib.sha256()
        for _ in range(768):
            block = disk.read(1 << 20)
            assert len(block) == 1 << 20
            digest.update(block)
        return digest.hexdigest()


def launch(image):
    return subprocess.Popen([
        "qemu-system-aarch64", "-machine", "virt,gic-version=3", "-cpu", "max", "-smp", "4",
        "-m", "1536M", "-nic", "none", "-display", "none", "-monitor", "none", "-serial", "stdio",
        "-no-reboot", "-kernel", image / "payload/kernel", "-initrd", image / "payload/ramdisk",
        "-append", "console=ttyAMA0 rdinit=/init panic=1 aios.qemu_flip4_storage_test=1",
        "-device", "qemu-xhci,id=xhci", "-drive", f"file={args.disk.resolve()},if=none,id=storage,format=raw",
        "-device", "usb-storage,bus=xhci.0,drive=storage",
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


args.output.mkdir(parents=True, exist_ok=True)
before = disk_hash()
with (args.output / "rejected.log").open("wb", buffering=0) as log, launch(args.invalid_image) as vm:
    try:
        rejection = wait(vm, log, "AIOS_FLIP4_DOCUMENT_UNAVAILABLE")
        assert "does not match the configured ext4 volume" in rejection, rejection
    finally:
        if vm.poll() is None:
            vm.kill()
assert before == disk_hash(), "Rejected boot changed the disk"

model = disk_hash(model_only=True)
original, saved = "장보기", "장보기\n우유"
revisions = [hashlib.sha256(text.encode()).hexdigest() for text in (original, saved)]
for index, text in enumerate((original, saved)):
    with (args.output / f"console-{index + 1}.log").open("wb", buffering=0) as log, launch(args.image) as vm:
        try:
            wait(vm, log, "AIOS_MODEL_PARTITION_READ_ONLY")
            wait(vm, log, "AIOS_FLIP4_STORAGE_READY qemu_virt")
            wait(vm, log, "AIOS_DOCUMENT_READY pid=1")
            assert read_document(vm, revisions[index], log=log)["text"] == text
            if index == 0:
                result = command(vm, log, f"model-append {revisions[0]} 메모에 '우유'를 적어줘.", "AIOS_")
                assert result == f"AIOS_SAVED revision={revisions[1]}", result
            vm.stdin.write(b"poweroff\n")
            vm.stdin.flush()
            assert vm.wait(timeout=20) == 0
        finally:
            if vm.poll() is None:
                vm.kill()
    assert model == disk_hash(model_only=True), "Read-only model volume changed"
print(json.dumps({
    "scope": "qemu_virt_usb_storage", "rejected_disk_unchanged": True,
    "model_partition_sha256": model, "restored_text": saved, "revision": revisions[1],
}, ensure_ascii=False, indent=2))

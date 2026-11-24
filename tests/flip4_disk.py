"""Boot twice with the same USB-backed ext4 image and check its offline bytes."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from arm64_model import command, edit, read_document, wait


kernel, disk, output = map(Path, sys.argv[1:4])
args = [
    "qemu-system-aarch64", "-machine", "virt,gic-version=3", "-cpu", "max",
    "-m", "1024M", "-nic", "none", "-display", "none", "-monitor", "none",
    "-serial", "stdio", "-no-reboot", "-kernel", str(kernel),
    "-device", "qemu-xhci,id=xhci", "-drive", f"file={disk},if=none,id=docs,format=raw",
    "-device", "usb-storage,bus=xhci.0,drive=docs",
    "-append", "earlycon=pl011,0x9000000 console=ttyAMA0 root=/dev/sda rootfstype=ext4 rootwait rw init=/init panic=1",
]
expected = "장보기\n우유"
revision = hashlib.sha256(expected.encode()).hexdigest()
instruction = "장보기 메모 마지막에 '우유' 한 줄을 추가해 줘."
for boot in (1, 2):
    with (output / f"disk-{boot}.log").open("wb", buffering=0) as log, subprocess.Popen(
        args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    ) as vm:
        try:
            wait(vm, log, "AIOS_STREAM_POLICY open-denied")
            wait(vm, log, "AIOS_DOCUMENT_READY pid=1")
            if boot == 1:
                before = hashlib.sha256("장보기".encode()).hexdigest()
                assert read_document(vm, before)["text"] == "장보기"
                published, trace = edit(vm, log, 18080, instruction, before)
                assert published["revision"] == revision, trace
            assert read_document(vm, revision)["text"] == expected
            vm.stdin.write(b"poweroff\n")
            vm.stdin.flush()
            assert vm.wait(timeout=20) == 0
        finally:
            if vm.poll() is None:
                vm.kill()
for name, contents in [("note.txt", expected), ("sibling.txt", "private")]:
    assert subprocess.check_output(["debugfs", "-R", f"cat /work/{name}", disk]) == contents.encode()
report = {"instruction": instruction, "model_trace": trace, "after_reboot": expected, "revision": revision}
(output / "proof.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(expected, revision)

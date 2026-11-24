"""Verify orderly shutdown and a QEMU process loss on the Flip4 reference kernel."""
import hashlib
import json
from pathlib import Path
import signal
import subprocess
import sys

bundle, disk, output = map(Path, sys.argv[1:4])
sys.path.insert(0, str(bundle.resolve()))
from arm64_model import command, edit, read_document, wait
from flip4_model import GUEST_RAM_MIB, launch


args = launch(disk)
expected = "장보기\n우유"
revision = hashlib.sha256(expected.encode()).hexdigest()
after_cut = expected + "\n전원 중단 검증"
cut_revision = hashlib.sha256(after_cut.encode()).hexdigest()
instruction = "장보기 메모 마지막에 '우유' 한 줄을 추가해 줘."
memory = {}


def record_memory(label, vm, log):
    reply = command(vm, log, "memory", "AIOS_")
    assert reply.startswith("AIOS_MEMORY "), reply
    sample = json.loads(reply.removeprefix("AIOS_MEMORY "))
    assert 0 < sample["available_kib"] <= sample["total_kib"] <= GUEST_RAM_MIB * 1024, sample
    assert 0 < sample["init_rss_kib"] < sample["total_kib"], sample
    memory[label] = sample


for boot in (1, 2, 3):
    with (output / f"disk-{boot}.log").open("wb", buffering=0) as log, subprocess.Popen(
        args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    ) as vm:
        try:
            wait(vm, log, "AIOS_STREAM_POLICY open-denied")
            wait(vm, log, "AIOS_DOCUMENT_READY pid=1")
            record_memory(f"boot_{boot}", vm, log)
            if boot == 1:
                before = hashlib.sha256("장보기".encode()).hexdigest()
                assert read_document(vm, before)["text"] == "장보기"
                published, trace = edit(vm, log, 18080, instruction, before)
                assert published["revision"] == revision, trace
                record_memory("after_save", vm, log)
            if boot == 2:
                assert read_document(vm, revision)["text"] == expected
                reply = command(vm, log, f"append {revision} 전원 중단 검증", "AIOS_")
                assert reply == f"AIOS_SAVED revision={cut_revision}", reply
                # No further guest traffic before terminating the VM.
                vm.kill()
                assert vm.wait(timeout=20) == -signal.SIGKILL
                continue
            observed, text = (revision, expected) if boot == 1 else (cut_revision, after_cut)
            assert read_document(vm, observed)["text"] == text
            vm.stdin.write(b"poweroff\n")
            vm.stdin.flush()
            assert vm.wait(timeout=20) == 0
        finally:
            if vm.poll() is None:
                vm.kill()
for name, contents in [("note.txt", after_cut), ("sibling.txt", "private")]:
    assert subprocess.check_output(["debugfs", "-R", f"cat /work/{name}", disk]) == contents.encode()
report = {"instruction": instruction, "model_trace": trace, "after_reboot": expected, "revision": revision}
report.update(after_qemu_kill=after_cut, after_qemu_kill_revision=cut_revision)
report.update(guest_ram_mib=GUEST_RAM_MIB, memory=memory)
(output / "proof.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(expected, revision)

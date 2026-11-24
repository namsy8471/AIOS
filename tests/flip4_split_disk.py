"""Boot a read-only system partition and persist edits on its data partition."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys


bundle, disk = map(Path, sys.argv[1:3])
sys.path.insert(0, str(bundle.resolve()))
from arm64_model import command, read_document, wait
from flip4_model import launch


def system_hash():
    with disk.open("rb") as raw:
        raw.seek(1024 * 1024)
        return hashlib.sha256(raw.read(16 * 1024 * 1024)).hexdigest()


boot_payload = Path(sys.argv[3]) if len(sys.argv) > 3 else None
args = launch(disk, split_disk=True, boot_payload=boot_payload)
before = system_hash()
original = "장보기"
saved = original + "\n독립 저장"
revisions = [hashlib.sha256(text.encode()).hexdigest() for text in (original, saved)]
for index, (text, revision) in enumerate(zip((original, saved), revisions)):
    log_path = disk.with_name(f"console-{index + 1}.log")
    with log_path.open("wb", buffering=0) as log, subprocess.Popen(
        args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    ) as vm:
        try:
            wait(vm, log, "AIOS_DOCUMENT_READY pid=1")
            assert read_document(vm, revision, log=log)["text"] == text
            if index == 0:
                reply = command(vm, log, f"append {revision} 독립 저장", "AIOS_")
                assert reply == f"AIOS_SAVED revision={revisions[1]}", reply
                stale = command(vm, log, f"append {revision} 거절될 변경", "AIOS_")
                assert stale == "AIOS_REJECT invalid-edit", stale
            vm.stdin.write(b"poweroff\n")
            vm.stdin.flush()
            assert vm.wait(timeout=20) == 0
        finally:
            if vm.poll() is None:
                vm.kill()
    assert system_hash() == before
proof = {"system_sha256": before, "after_reboot": saved, "revision": revisions[1]}
if boot_payload:
    proof["boot_payload"] = {name: hashlib.sha256((boot_payload / name).read_bytes()).hexdigest()
                             for name in ("kernel", "ramdisk")}
print(json.dumps(proof, ensure_ascii=False))

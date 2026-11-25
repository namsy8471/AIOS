"""Boot a read-only system partition and persist edits on its data partition."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("bundle", type=Path)
parser.add_argument("disk", type=Path)
parser.add_argument("boot_payload", type=Path, nargs="?")
parser.add_argument("--guest-model", action="store_true")
parser.add_argument("--driver-order", type=Path)
options = parser.parse_args()
bundle, disk, boot_payload = options.bundle, options.disk, options.boot_payload
if (options.guest_model or options.driver_order) and boot_payload is None:
    parser.error("the selected profile requires the extracted reference boot payload")
drivers = options.driver_order.read_text().splitlines() if options.driver_order else []
if options.driver_order and not drivers:
    parser.error("the recovery driver list is empty")
sys.path.insert(0, str(bundle.resolve()))
from arm64_model import command, read_document, wait
from flip4_model import launch


def system_hash():
    digest = hashlib.sha256()
    with disk.open("rb") as raw:
        raw.seek(1 << 20)
        for _ in range(768 if options.guest_model else 16):
            block = raw.read(1 << 20)
            assert len(block) == 1 << 20, "system partition is incomplete"
            digest.update(block)
    return digest.hexdigest()


args = launch(disk, guest_model=options.guest_model, split_disk=True, boot_payload=boot_payload,
              recovery_drivers=bool(drivers))
before = system_hash()
original = "장보기"
addition = "우유" if options.guest_model else "독립 저장"
saved = original + "\n" + addition
revisions = [hashlib.sha256(text.encode()).hexdigest() for text in (original, saved)]
for index, (text, revision) in enumerate(zip((original, saved), revisions)):
    log_path = disk.with_name(f"console-{index + 1}.log")
    with log_path.open("wb", buffering=0) as log, subprocess.Popen(
        args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    ) as vm:
        try:
            wait(vm, log, "AIOS_DOCUMENT_READY pid=1")
            if drivers:
                boot_log = log_path.read_bytes().replace(b"\r", b"")
                # Kernel printk can start on the serial line before the result's newline.
                loaded = re.findall(
                    rb"^AIOS_MODULE_RESULT (\S+) 0(?=$|\[\s*\d+\.\d+\])", boot_log, re.MULTILINE
                )
                assert [name.decode() for name in loaded] == drivers, f"Incomplete driver load in {log_path}"
            if options.guest_model:
                assert b"AIOS_MODEL_PARTITION_READ_ONLY" in log_path.read_bytes(), "model partition was not mounted"
            assert read_document(vm, revision, log=log)["text"] == text
            if index == 0:
                if options.guest_model:
                    reply = command(vm, log, f"model-append {revision} 메모에 '{addition}'를 적어줘.", "AIOS_")
                else:
                    reply = command(vm, log, f"append {revision} {addition}", "AIOS_")
                assert reply == f"AIOS_SAVED revision={revisions[1]}", reply
                if options.guest_model:
                    record, = [line.removeprefix(b"MODEL_USAGE ") for line in log_path.read_bytes().splitlines()
                               if line.startswith(b"MODEL_USAGE ")]
                    usage = json.loads(record)
                    assert usage["inference_ms"] > 0 and usage["model_peak_rss_kib"] > 0, usage
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
if options.guest_model:
    proof["model_usage"] = usage
if drivers:
    proof["drivers_loaded_each_boot"] = drivers
if boot_payload:
    proof["boot_payload"] = {name: hashlib.sha256((boot_payload / name).read_bytes()).hexdigest()
                             for name in ("kernel", "ramdisk")}
print(json.dumps(proof, ensure_ascii=False))

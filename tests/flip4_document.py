"""Exercise the phone console through its serial port on the reference kernel."""
import hashlib
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from arm64_model import command, read_document, wait


def revision(text):
    return hashlib.sha256(text.encode()).hexdigest()


with open(sys.argv[1], "wb", buffering=0) as log, subprocess.Popen(
    sys.argv[2:], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
) as vm:
    try:
        wait(vm, log, "AIOS_STREAM_POLICY open-denied")
        wait(vm, log, "AIOS_DOCUMENT_READY pid=1")
        before = revision("장보기")
        after = revision("장보기\n우유")
        assert read_document(vm, before)["text"] == "장보기"
        assert command(vm, log, f"append {before} 우유", "AIOS_") == f"AIOS_SAVED revision={after}"
        assert command(vm, log, f"append {before} 우유", "AIOS_") == "AIOS_REJECT invalid-edit"
        reopened = read_document(vm, after)
        assert reopened["text"] == "장보기\n우유"
        print(reopened, flush=True)
        vm.stdin.write(b"poweroff\n")
        vm.stdin.flush()
        assert vm.wait(timeout=10) == 0
    finally:
        if vm.poll() is None:
            vm.kill()

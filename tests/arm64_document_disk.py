"""Verify ordinary shutdown and abrupt power loss using the packaged ARM64 launcher."""
import hashlib
from pathlib import Path
import subprocess
import signal
import sys


def revision(text):
    return hashlib.sha256(text.encode()).hexdigest()


def wait(vm, log, prefix):
    for raw in vm.stdout:
        log.write(raw)
        line = raw.decode(errors="replace").strip()
        if line.startswith(prefix):
            return line
        if "Kernel panic" in line:
            raise RuntimeError(line)
    raise RuntimeError(f"Guest stopped before {prefix}")


def command(vm, log, request, prefix):
    vm.stdin.write(request.encode() + b"\n")
    vm.stdin.flush()
    return wait(vm, log, prefix)


original = "작업 기록"
saved = original + "\n재부팅 검증"
durable = saved + "\n전원 중단 검증"
for boot, expected in enumerate((original, saved, durable), 1):
    with Path(f"build/arm64-disk-{boot}.log").open("wb") as log, subprocess.Popen([
        "bash", sys.argv[1], sys.argv[2],
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as vm:
        try:
            wait(vm, log, "AIOS_DOCUMENT_READY pid=1")
            result = command(vm, log, "inspect", "AIOS_DOCUMENT ")
            assert result == f"AIOS_DOCUMENT revision={revision(expected)} bytes={len(expected.encode())}", result
            if boot == 1:
                result = command(vm, log, f"append {revision(original)} 재부팅 검증", "AIOS_SAVED ")
                assert result == f"AIOS_SAVED revision={revision(saved)}", result
                command(vm, log, f"append {revision(original)} 중복", "AIOS_REJECT invalid-edit")
            if boot == 2:
                result = command(vm, log, f"append {revision(saved)} 전원 중단 검증", "AIOS_SAVED ")
                assert result == f"AIOS_SAVED revision={revision(durable)}", result
                vm.kill()
                assert vm.wait(timeout=20) == -signal.SIGKILL
            else:
                vm.stdin.write(b"poweroff\n")
                vm.stdin.flush()
                assert vm.wait(timeout=20) == 0
        except Exception:
            log.flush()
            print(Path(log.name).read_bytes()[-4000:].decode(errors='replace'), flush=True)
            raise
        finally:
            if vm.poll() is None:
                vm.terminate()
        print(f"Verified ARM64 disk boot {boot}", flush=True)

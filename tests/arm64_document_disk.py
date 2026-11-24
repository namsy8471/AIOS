"""Drive two independent ARM64 boots over the guest serial console."""
import hashlib
from pathlib import Path
import subprocess
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
for boot in (1, 2):
    with Path(f"build/arm64-disk-{boot}.log").open("wb") as log, subprocess.Popen([
        "timeout", "90s", "qemu-system-aarch64", "-machine", "virt", "-cpu", "cortex-a53",
        "-m", "128M", "-nic", "none", "-display", "none", "-monitor", "none", "-serial", "stdio",
        "-no-reboot", "-kernel", "/boot/vmlinuz-virt", "-initrd", "/boot/initramfs-virt",
        "-append", "console=ttyAMA0 root=/dev/vda rootfstype=ext4 rootflags=rw rw panic=1",
        "-drive", f"file={sys.argv[1]},if=virtio,format=raw,cache=none",
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as vm:
        try:
            wait(vm, log, "AIOS_DOCUMENT_READY pid=1")
            expected = original if boot == 1 else saved
            result = command(vm, log, "inspect", "AIOS_DOCUMENT ")
            assert result == f"AIOS_DOCUMENT revision={revision(expected)} bytes={len(expected.encode())}", result
            if boot == 1:
                result = command(vm, log, f"append {revision(original)} 재부팅 검증", "AIOS_SAVED ")
                assert result == f"AIOS_SAVED revision={revision(saved)}", result
                command(vm, log, f"append {revision(original)} 중복", "AIOS_REJECT invalid-edit")
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

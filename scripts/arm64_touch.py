"""Open the AIOS graphical memo and review appends on its display."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

from arm64_model import command, read_document, wait


def launch(bundle, disk, *, display, model=False, multitouch=False, monitor=None, initramfs=None):
    gpu = "virtio-gpu-pci,xres=1080,yres=2640" if multitouch else "virtio-gpu-pci"
    pointer = "virtio-multitouch-pci" if multitouch else "virtio-tablet-pci"
    drive = str(disk.resolve()).replace(",", ",,")
    args = [
        "qemu-system-aarch64", "-machine", "virt", "-cpu", "max" if model else "cortex-a53",
        "-smp", "4" if model else "1", "-m", "1536M" if model else "256M",
        "-nic", "none", "-display", display, "-monitor", "none", "-serial", "stdio", "-no-reboot",
        "-kernel", str(bundle / "vmlinuz-virt"), "-initrd", str(initramfs or bundle / "display-initramfs"),
        "-drive", f"file={drive},if=virtio,format=raw",
        "-device", gpu, "-device", pointer,
        "-append", "console=ttyAMA0 root=/dev/vda rootfstype=ext4 rootflags=rw rw modules=virtio_gpu,virtio_input,evdev panic=1",
    ]
    if monitor is not None:
        args.extend(["-qmp", monitor])
    return args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("disk", type=Path, help="working disk; the lightweight starter is copied on first use")
    parser.add_argument("--model", action="store_true", help="use an existing disk containing the local model")
    args = parser.parse_args()
    bundle = Path(__file__).resolve().parent
    starter = bundle / "display-starter.raw"
    if args.disk.exists():
        if not args.disk.is_file() or (starter.is_file() and args.disk.samefile(starter)):
            parser.error("provide a separate working disk")
    elif args.model:
        parser.error("--model requires a disk containing the model")
    else:
        with starter.open("rb") as source, args.disk.open("xb") as dest:
            shutil.copyfileobj(source, dest)

    operation = "model-confirm-append" if args.model else "confirm-append"
    with subprocess.Popen(launch(bundle, args.disk, display="sdl", model=args.model),
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as vm:
        try:
            wait(vm, None, "AIOS_DOCUMENT_READY pid=1")
            result = command(vm, None, "inspect", "AIOS_DOCUMENT ")
            revision = result.split()[1].split("=")[1]
            print(read_document(vm, revision)["text"], flush=True)
            prompt = "메모에 추가할 내용을 지시하세요." if args.model else "메모에 추가할 한 줄을 입력하세요."
            print(f"{prompt} 빈 줄을 입력하면 종료합니다.", flush=True)
            for instruction in sys.stdin:
                instruction = instruction.strip()
                if not instruction:
                    break
                if not instruction.isprintable() or len(instruction.encode()) > 512:
                    print("512바이트 이하의 한 줄을 입력해 주세요.", file=sys.stderr)
                    continue
                ready = command(vm, None, f"{operation} {revision} {instruction}", "AIOS_")
                if ready.startswith("AIOS_CONFIRM_READY "):
                    print("QEMU 창에서 저장 또는 취소를 선택하세요.", flush=True)
                    reply = wait(vm, None, "AIOS_")
                elif reply == "AIOS_REJECT confirmation-canceled":
                    print("편집을 취소했습니다.", flush=True)
                else:
                    reply = ready
                if reply.startswith("AIOS_SAVED revision="):
                    revision = reply.split("=", 1)[1]
                    print(read_document(vm, revision)["text"], flush=True)
                else:
                    print(reply, file=sys.stderr)
            vm.stdin.write(b"poweroff\n")
            vm.stdin.flush()
            if vm.wait(timeout=30) != 0:
                raise RuntimeError("Guest shutdown failed")
        finally:
            if vm.poll() is None:
                vm.kill()


if __name__ == "__main__":
    main()

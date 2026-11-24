"""Drive the ISO over two serial ports, then verify the powered-off volume."""
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time

run = subprocess.run
original = "첫 문서".encode()
line = "부팅한 AIOS에서 저장"
expected = original + b"\n" + line.encode()
with tempfile.TemporaryDirectory() as temp:
    base = Path(temp)
    disk, mount, port = (base / item for item in ("workspace.raw", "volume", "mcp"))
    mount.mkdir()
    with disk.open("wb") as f:
        f.truncate(256 << 20)
    run(["mkfs.btrfs", "-q", "-L", "AIOS-DATA", disk], check=True)
    note = mount / "documents/note.txt"
    run(["sudo", "mount", "-o", "loop", disk, mount], check=True)
    try:
        run(["sudo", "btrfs", "subvolume", "create", note.parent], check=True)
        run(["sudo", "tee", note], input=original, stdout=subprocess.DEVNULL, check=True)
    finally:
        run(["sudo", "umount", mount], check=True)

    ready = threading.Event()
    with subprocess.Popen([
        "qemu-system-x86_64", "-machine", "accel=kvm:tcg", "-m", "2048", "-smp", "2",
        "-boot", "d", "-cdrom", "build/runtime/aios-runtime.iso", "-nic", "none",
        "-drive", f"file={disk},if=virtio,format=raw", "-display", "none",
        "-monitor", "none", "-no-reboot", "-serial", "stdio",
        "-serial", f"unix:{port},server=on,wait=off",
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as vm:
        def capture():
            with open("build/runtime/console.log", "wb") as log:
                for data in vm.stdout:
                    log.write(data)
                    log.flush()
                    if b"AIOS_RUNTIME_READY" in data:
                        ready.set()
        output = threading.Thread(target=capture)
        output.start()
        try:
            deadline = time.monotonic() + 220
            while not ready.wait(0.5):
                if vm.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Guest did not start the broker")
            with socket.socket(socket.AF_UNIX) as sock:
                sock.settimeout(90)
                sock.connect(str(port))
                with sock.makefile("rwb", buffering=0) as stream:
                    def send(body):
                        message = dict(jsonrpc="2.0", **body)
                        sock.sendall(json.dumps(message).encode() + b"\n")
                    def rpc(number, method, params):
                        send(dict(id=number, method=method, params=params))
                        while True:
                            reply = json.loads(stream.readline())
                            if reply.get("id") == number:
                                return reply["result"]
                    rpc(1, "initialize", dict(protocolVersion="2025-03-26", capabilities={},
                                              clientInfo=dict(name="aios-test", version="1")))
                    send(dict(method="notifications/initialized"))
                    state = rpc(2, "tools/call", dict(name="inspect_document", arguments={}))
                    revision = hashlib.sha256(original).hexdigest()
                    assert state["structuredContent"]["revision"] == revision
                    request = dict(name="append_line", arguments=dict(document="note.txt",
                                   revision=revision, line=line))
                    result = rpc(3, "tools/call", request)
                    assert result.get("structuredContent", {}).get("revision") == hashlib.sha256(expected).hexdigest(), result
                    assert rpc(4, "tools/call", request)["isError"]
            vm.stdin.write(b"poweroff\n")
            vm.stdin.flush()
            assert vm.wait(timeout=45) == 0
        finally:
            if vm.poll() is None:
                vm.kill()
            vm.wait()
            output.join()
            print(Path("build/runtime/console.log").read_text(errors="replace")[-7500:])
    assert "AIOS_RUNTIME_STOPPED" in Path("build/runtime/console.log").read_text(errors="replace")
    run(["sudo", "mount", "-o", "loop,ro,nologreplay", disk, mount], check=True)
    try:
        assert note.read_bytes() == expected
    finally:
        run(["sudo", "umount", mount], check=True)
    print("Verified persisted UTF-8 bytes and stale request rejection")

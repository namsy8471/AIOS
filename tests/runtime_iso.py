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
original = "첫 문서\r\n둘째 줄".encode()
line = "부팅한 AIOS에서 저장"
expected = original + b"\r\n" + line.encode()
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
                    def rpc(number, method, params, review_action=None):
                        send(dict(id=number, method=method, params=params))
                        reviewed = False
                        while True:
                            reply = json.loads(stream.readline())
                            if reply.get("method") == "elicitation/create":
                                assert review_action and not reviewed
                                assert "note.txt" in reply["params"]["message"]
                                reviewed = True
                                # The editor has verified its saved bytes. A concurrent
                                # inspect must still see the last committed revision.
                                visible = rpc(number + 100, "tools/call",
                                              dict(name="inspect_document", arguments={}))
                                assert visible["structuredContent"]["revision"] == params["arguments"]["revision"]
                                decision = dict(action=review_action)
                                if review_action == "accept":
                                    decision["content"] = {"save": True}
                                send(dict(id=reply["id"], result=decision))
                                continue
                            if reply.get("id") == number:
                                assert reviewed == bool(review_action), reply
                                return reply["result"]
                    rpc(1, "initialize", dict(protocolVersion="2025-11-25", capabilities={"elicitation": {"form": {}}},
                                              clientInfo=dict(name="aios-test", version="1")))
                    send(dict(method="notifications/initialized"))
                    state = rpc(2, "tools/call", dict(name="inspect_document", arguments={}))
                    revision = hashlib.sha256(original).hexdigest()
                    assert state["structuredContent"]["revision"] == revision
                    request = dict(name="append_line", arguments=dict(document="note.txt",
                                   revision=revision, line=line, editor="gtk"))
                    result = rpc(3, "tools/call", request)
                    assert result.get("structuredContent", {}).get("revision") == hashlib.sha256(expected).hexdigest(), result
                    assert rpc(4, "tools/call", request)["isError"]
                    current = hashlib.sha256(expected).hexdigest()
                    qt = dict(document="note.txt", revision=current, editor="qt", review=True)
                    canceled = rpc(5, "tools/call", dict(name="append_line", arguments={
                        **qt, "line": "취소할 줄"}), "cancel")
                    assert canceled["isError"] and "discarded" in str(canceled), canceled
                    state = rpc(6, "tools/call", dict(name="inspect_document", arguments={}))
                    assert state["structuredContent"]["revision"] == current
                    appended = "Qt에서 확인하고 저장"
                    saved = rpc(7, "tools/call", dict(name="append_line", arguments={
                        **qt, "line": appended}), "accept")
                    expected += b"\r\n" + appended.encode()
                    assert saved.get("structuredContent", {}).get("revision") == hashlib.sha256(expected).hexdigest(), saved
                    direct = dict(document="note.txt", revision=hashlib.sha256(expected).hexdigest(),
                                  line="직접 편집 검토", review=True)
                    for index, decision in enumerate(("cancel", "accept"), 8):
                        result = rpc(index, "tools/call", dict(name="append_line", arguments=direct), decision)
                        if decision == "cancel":
                            assert result["isError"] and "discarded" in str(result), result
                        else:
                            expected += b"\r\n" + direct["line"].encode()
                            assert result["structuredContent"]["revision"] == hashlib.sha256(expected).hexdigest()
                    timings = {"direct": [], "gtk": []}
                    for pair in range(6):
                        for step, path in enumerate(("direct", "gtk") if pair % 2 == 0 else ("gtk", "direct")):
                            suffix = f"측정 {pair}"
                            args = dict(document="note.txt", revision=hashlib.sha256(expected).hexdigest(),
                                        line=suffix, editor=path)
                            start = time.perf_counter_ns()
                            result = rpc(20 + 2 * pair + step, "tools/call", dict(name="append_line", arguments=args))
                            timings[path].append((time.perf_counter_ns() - start) / 1e6)
                            expected += b"\r\n" + suffix.encode()
                            assert result["structuredContent"]["revision"] == hashlib.sha256(expected).hexdigest()
                    print("append_ms", json.dumps(timings))
                    replacement = dict(document="note.txt", revision=hashlib.sha256(expected).hexdigest(),
                                       old="직접 편집 검토", new="최종본")
                    saved = rpc(40, "tools/call", dict(name="replace_text", arguments=replacement))
                    expected = expected.replace(replacement["old"].encode(), replacement["new"].encode())
                    assert saved["structuredContent"]["revision"] == hashlib.sha256(expected).hexdigest()
                    Path("build/runtime/append-latency.json").write_text(json.dumps(timings))
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
    # Read the offline filesystem directly, including the documents subvolume.
    restored = base / "restored"
    restored.mkdir()
    run(["btrfs", "restore", "-s", disk, restored], check=True)
    assert (restored / "documents/note.txt").read_bytes() == expected
    print("Verified GTK and Qt commits, pending edit isolation, cancellation, stale rejection and offline CRLF bytes")

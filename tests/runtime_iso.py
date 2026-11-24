"""Drive the ISO over two serial ports, then verify the powered-off volume."""
import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import shutil
import subprocess
import tempfile
import sys
import threading
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from vsock_transport import connect, device


async def verify_reconnect(endpoint, revision):
    client = StdioServerParameters(command=sys.executable,
                                   args=["scripts/vsock_stdio.py", str(endpoint)])
    async with stdio_client(client) as streams, ClientSession(*streams) as session:
        await session.initialize()
        state = await session.call_tool("inspect_document", {})
        assert not state.isError and state.structuredContent["revision"] == revision


run = subprocess.run
original = "첫 문서\r\n둘째 줄".encode()
line = "부팅한 AIOS에서 저장"
sentinel = ".aios-session-00000000-0000-0000-0000-000000000000"
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
        run(["sudo", "mkdir", mount / sentinel], check=True)
        run(["sudo", "tee", mount / sentinel / "keep"], input=b"unmanaged", stdout=subprocess.DEVNULL, check=True)
        run(["sudo", "tee", note], input=original, stdout=subprocess.DEVNULL, check=True)
    finally:
        run(["sudo", "umount", mount], check=True)

    for boot in (1, 2, 3):
        log_path = Path("build/runtime") / ("console.log" if boot == 3 else f"crash-{boot}.log")
        ready = threading.Event()
        vsock = boot == 3
        with device(base, vsock) as transport, subprocess.Popen([
            "qemu-system-x86_64", "-machine", "accel=kvm:tcg", "-m", "2048", "-smp", "2",
            "-boot", "d", "-cdrom", "build/runtime/aios-runtime.iso", "-nic", "none",
            "-drive", f"file={disk},if=virtio,format=raw,cache=none", "-display", "none",
            "-monitor", "none", "-no-reboot", "-serial", "stdio",
            *(transport if vsock else ["-serial", f"unix:{port},server=on,wait=off"]),
        ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as vm:
            def capture():
                with open(log_path, "wb") as log:
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
                transport_name = "vsock" if vsock else "serial"
                assert f"AIOS_RUNTIME_READY transport={transport_name}" in log_path.read_text(errors="replace")
                with connect(base, vsock) as (sock, stream):
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
                    if boot == 1:
                        addition = "승인 후 전원 차단"
                        updated = rpc(3, "tools/call", dict(name="append_line", arguments=dict(
                            document="note.txt", revision=revision, line=addition)))
                        vm.kill()
                        original += b"\r\n" + addition.encode()
                        assert updated["structuredContent"]["revision"] == hashlib.sha256(original).hexdigest()
                        continue
                    if boot == 2:
                        send(dict(id=3, method="tools/call", params=dict(name="append_line", arguments=dict(
                            document="note.txt", revision=revision, line="미승인 변경", review=True))))
                        prompt = json.loads(stream.readline())
                        assert prompt.get("method") == "elicitation/create", prompt
                        vm.kill()
                        continue
                    assert "AIOS_RECOVERED_TRANSACTION" in log_path.read_text(errors="replace")
                    expected = original + b"\r\n" + line.encode()
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
                    batch = dict(document="note.txt", revision=hashlib.sha256(expected).hexdigest(),
                                 edits=[dict(op="append_line", line="검토 전"),
                                        dict(op="replace_text", old="검토 전", new="검토 완료"),
                                        dict(op="replace_text", old="최종본", new="공유본")])
                    bad = {**batch, "edits": [*batch["edits"], dict(op="replace_text", old="측정", new="x")]}
                    failed = rpc(41, "tools/call", dict(name="edit_document", arguments=bad))
                    assert failed["isError"] and "Edit 4" in str(failed)
                    current = rpc(42, "tools/call", dict(name="inspect_document", arguments={}))
                    assert current["structuredContent"]["revision"] == batch["revision"]
                    reviewed = dict(name="edit_document", arguments={**batch, "review": True})
                    canceled = rpc(43, "tools/call", reviewed, "cancel")
                    assert canceled["isError"] and "discarded" in str(canceled)
                    saved = rpc(44, "tools/call", reviewed, "accept")
                    expected = expected.replace("최종본".encode(), "공유본".encode()) + "\r\n검토 완료".encode()
                    assert saved["structuredContent"]["revision"] == hashlib.sha256(expected).hexdigest()
                    assert rpc(45, "tools/call", dict(name="edit_document", arguments=batch))["isError"]
                    history = rpc(46, "tools/call", dict(name="recent_activity", arguments={"limit": 100}))
                    entries = history["structuredContent"]["result"]
                    assert entries[0]["tool"] == "edit_document" and entries[0]["outcome"] == "rejected"
                    assert any(e["tool"] == "edit_document" and e["outcome"] == "succeeded"
                               and e["revision"] == hashlib.sha256(expected).hexdigest() for e in entries)
                    assert any(e["tool"] == "edit_document" and e["outcome"] == "discarded" for e in entries)
                    Path("build/runtime/append-latency.json").write_text(json.dumps(timings))
                # Reconnect to the same running VM with a fresh MCP handshake.
                asyncio.run(asyncio.wait_for(verify_reconnect(base / "host.sock",
                                                              hashlib.sha256(expected).hexdigest()), 45))
                print("Verified virtio-vsock reconnect through the stdio MCP client")
                vm.stdin.write(b"poweroff\n")
                vm.stdin.flush()
                assert vm.wait(timeout=45) == 0
            finally:
                if vm.poll() is None:
                    vm.kill()
                vm.wait()
                output.join()
                print(Path(log_path).read_text(errors="replace")[-7500:])
    assert "AIOS_RUNTIME_STOPPED" in Path("build/runtime/console.log").read_text(errors="replace")
    # Read the offline filesystem directly, including the documents subvolume.
    restored = base / "restored"
    restored.mkdir()
    run(["btrfs", "restore", "-s", disk, restored], check=True)
    assert [path.name for path in restored.glob(".aios-session-*")] == [sentinel]
    assert (restored / sentinel / "keep").read_bytes() == b"unmanaged"
    assert (restored / "documents/note.txt").read_bytes() == expected
    archive = restored / ".aios-activity/events.sqlite"
    db = sqlite3.connect(f"{archive.as_uri()}?mode=ro", uri=True)
    rows = db.execute("SELECT at_ns,grant_id,request,tool,outcome,revision,hash FROM events ORDER BY seq").fetchall()
    previous = ""
    requests = {}
    for *fields, stored in rows:
        data = json.dumps([previous, *fields], ensure_ascii=True, separators=(",", ":")).encode()
        assert hashlib.sha256(data).hexdigest() == stored
        previous = stored
        requests.setdefault(fields[2], []).append(fields[4])
    assert all(len(pair) == 2 and pair[0] == "started" for pair in requests.values())
    assert sum(pair[-1] == "outcome_unknown" for pair in requests.values()) == 1
    assert any(r[3:5] == ("append_line", "outcome_unknown") for r in rows)
    assert all(value.encode() not in archive.read_bytes() for value in ("승인 후 전원 차단", "미승인 변경", "검토 완료"))
    db.close()
    # Exercise startup verification against a damaged copy of the offline log.
    from importlib.util import module_from_spec, spec_from_file_location
    spec = spec_from_file_location("aios_activity", Path(__file__).resolve().parents[1] / "runtime/activity.py")
    activity = module_from_spec(spec)
    spec.loader.exec_module(activity)
    damaged = base / "damaged.sqlite"
    shutil.copyfile(archive, damaged)
    with sqlite3.connect(damaged) as modified:
        try:
            modified.execute("UPDATE events SET tool='modified' WHERE seq=1")
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("Ordinary SQL update modified the activity log")
        modified.execute("DROP TRIGGER prevent_update")
        modified.execute("UPDATE events SET tool='modified' WHERE seq=1")
    try:
        activity.Activity(damaged, "test-document")
    except ValueError as error:
        assert "hash chain" in str(error)
    else:
        raise AssertionError("Changed record passed startup verification")
    print("Verified persistent broker activity across three boots:", len(requests), "requests")
    print("Verified GTK and Qt commits, pending edit isolation, cancellation, stale rejection and offline CRLF bytes")

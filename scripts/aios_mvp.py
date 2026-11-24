"""Boot AIOS twice, edit a UTF-8 document through MCP, and verify its persisted bytes."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import lzma
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time


@contextmanager
def boot(qemu, iso, disk, console):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(1)
        port = listener.getsockname()[1]
        accelerator = "kvm:tcg" if sys.platform.startswith("linux") else "tcg"
        cmd = [qemu, "-machine", f"accel={accelerator}", "-m", "2048", "-smp", "2",
               "-display", "none", "-nic", "none", "-monitor", "none", "-no-reboot",
               "-boot", "d", "-cdrom", str(iso), "-drive",
               f"file={str(disk).replace(',', ',,')},if=virtio,format=raw", "-serial", "stdio",
               "-chardev", f"socket,id=mcp,host=127.0.0.1,port={port}", "-serial", "chardev:mcp"]
        with subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT) as vm:
            ready = threading.Event()
            def capture():
                with console.open("wb") as log:
                    for data in vm.stdout:
                        log.write(data)
                        if b"AIOS_RUNTIME_READY transport=serial" in data:
                            ready.set()
            thread = threading.Thread(target=capture)
            thread.start()
            deadline = time.monotonic() + 240
            try:
                while not ready.wait(0.2):
                    if vm.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError(f"AIOS failed to boot; see {console}")
                with listener.accept()[0] as channel:
                    channel.settimeout(90)
                    with channel.makefile("rwb", buffering=0) as stream:
                        sequence = 0
                        def call(method, params):
                            nonlocal sequence
                            sequence += 1
                            message = dict(jsonrpc="2.0", id=sequence, method=method, params=params)
                            channel.sendall(json.dumps(message).encode() + b"\n")
                            while True:
                                response = json.loads(stream.readline())
                                if response.get("id") == sequence:
                                    if "error" in response:
                                        raise RuntimeError(response["error"])
                                    return response["result"]
                        call("initialize", dict(protocolVersion="2025-11-25", capabilities={},
                                                clientInfo=dict(name="aios-mvp", version="1")))
                        channel.sendall(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
                        def tool(name, **arguments):
                            result = call("tools/call", dict(name=name, arguments=arguments))
                            if result.get("isError"):
                                raise RuntimeError(result["content"])
                            return result["structuredContent"]
                        yield tool, lambda: call("tools/list", {})["tools"]
                vm.stdin.write(b"poweroff\n")
                vm.stdin.flush()
                if vm.wait(timeout=45) != 0:
                    raise RuntimeError("QEMU failed during shutdown")
            finally:
                if vm.poll() is None:
                    vm.kill()
                vm.wait()
                thread.join()
            if b"AIOS_RUNTIME_STOPPED" not in console.read_bytes():
                raise RuntimeError("Clean data volume shutdown was not confirmed")


def read(tool):
    state = tool("inspect_document")
    page = tool("read_text", document=state["document"], revision=state["revision"])
    if page["next_offset"] is not None:
        raise ValueError("Expected the short MVP document")
    return state, page["text"]


def main():
    bundle = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qemu", default="qemu-system-x86_64")
    parser.add_argument("--output", type=Path, help="new directory for the disk, logs and proof")
    parser.add_argument("--model-port", type=int, help="local llama-server port for model-selected MCP calls")
    args = parser.parse_args()
    qemu = shutil.which(args.qemu)
    if not qemu:
        parser.error("QEMU x86_64 is required; specify --qemu with its executable path")
    iso, seed = bundle / "aios-runtime.iso", bundle / "starter.raw.xz"
    for path in (iso, seed):
        if not path.is_file():
            parser.error(f"Missing bundle file: {path.name}")
    if args.output:
        output = args.output.resolve()
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
    else:
        output = Path(tempfile.mkdtemp(prefix="aios-mvp-", dir=Path.cwd())).resolve()
    print(f"AIOS MVP output: {output}", flush=True)
    disk = output / "workspace.raw"
    with lzma.open(seed) as source, disk.open("xb") as target:
        shutil.copyfileobj(source, target)

    with boot(qemu, iso, disk, output / "first-boot.log") as (tool, catalog):
        before, original = read(tool)
        addition = "AIOS에서 저장했습니다."
        if args.model_port is not None:
            from model_mvp import run_model
            addition = "검토 완료 " + str(1000 + secrets.randbelow(9000))
            instruction = f"현재 문서의 기존 내용을 유지하고 새 줄에 '{addition}'라고 한 번만 추가해 줘."
            saved, trace = run_model(args.model_port, instruction, catalog(), tool)
        else:
            saved = tool("append_line", document=before["document"], revision=before["revision"], line=addition)
        expected = original + ("" if not original or original.endswith("\n") else "\n") + addition
        digest = hashlib.sha256(expected.encode()).hexdigest()
        if saved["revision"] != digest:
            raise RuntimeError("Save did not return the expected revision")
    with boot(qemu, iso, disk, output / "second-boot.log") as (tool, _):
        reopened, actual = read(tool)
        if actual != expected or reopened["revision"] != digest:
            raise RuntimeError("Rebooted guest returned different content")
    proof = dict(document=before["document"], before=original, after_reboot=actual,
                 revision_before=before["revision"], revision_after_reboot=digest, boots=2)
    if args.model_port is not None:
        proof.update(instruction=instruction, model_trace=trace)
    (output / "proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS: verified the saved document after a second ISO boot.", flush=True)


if __name__ == "__main__":
    main()

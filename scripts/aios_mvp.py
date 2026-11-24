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
def boot(qemu, iso, disk, console, usb_uefi=None):
    with socket.socket() as listener, socket.socket() as console_listener:
        for endpoint in (listener, console_listener):
            endpoint.bind(("127.0.0.1", 0))
            endpoint.listen(1)
            endpoint.settimeout(5)
        port = listener.getsockname()[1]
        console_port = console_listener.getsockname()[1]
        accelerator = "kvm:tcg" if sys.platform.startswith("linux") else "tcg"
        machine = f"accel={accelerator}"
        media = ["-boot", "d", "-cdrom", str(iso)]
        if usb_uefi:
            firmware, variables = usb_uefi
            machine = f"q35,{machine}"
            media = ["-drive", f"file={str(firmware).replace(',', ',,')},if=pflash,format=raw,readonly=on",
                     "-drive", f"file={str(variables).replace(',', ',,')},if=pflash,format=raw",
                     "-device", "qemu-xhci,id=xhci",
                     "-drive", f"file={str(iso).replace(',', ',,')},if=none,id=live,format=raw,readonly=on",
                     "-device", "usb-storage,bus=xhci.0,drive=live,bootindex=1"]
        cmd = [qemu, "-machine", machine, "-m", "2048", "-smp", "2",
               "-display", "none", "-nic", "none", "-monitor", "none", "-no-reboot",
               *media, "-drive",
               f"file={str(disk).replace(',', ',,')},if=virtio,format=raw",
               "-chardev", f"socket,id=console,host=127.0.0.1,port={console_port}", "-serial", "chardev:console",
               "-chardev", f"socket,id=mcp,host=127.0.0.1,port={port}", "-serial", "chardev:mcp"]
        with console.with_suffix(".qemu.log").open("wb") as qemu_log, subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=qemu_log, stderr=subprocess.STDOUT) as vm:
            ready = threading.Event()
            def capture():
                with console.open("wb") as log, console_channel.makefile("rb") as stream:
                    try:
                        for data in stream:
                            log.write(data)
                            if b"AIOS_RUNTIME_READY transport=serial" in data:
                                log.flush()
                                ready.set()
                    except ConnectionResetError:
                        # QEMU can reset the socket on exit. The caller checks the shutdown marker.
                        pass
            thread = console_channel = None
            deadline = time.monotonic() + 240
            try:
                try:
                    console_channel, _ = console_listener.accept()
                except TimeoutError as error:
                    raise RuntimeError(f"QEMU did not connect its console; see {qemu_log.name}") from error
                thread = threading.Thread(target=capture)
                thread.start()
                while not ready.wait(0.2):
                    if vm.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError(f"AIOS failed to boot; see {console}")
                with listener.accept()[0] as channel:
                    if usb_uefi:
                        # UEFI can mirror its console onto the MCP UART before Linux starts.
                        channel.setblocking(False)
                        try:
                            while channel.recv(65536):
                                pass
                        except BlockingIOError:
                            pass
                    channel.settimeout(90)
                    with channel.makefile("rwb", buffering=0) as stream:
                        sequence = 0
                        def call(method, params):
                            nonlocal sequence
                            sequence += 1
                            message = dict(jsonrpc="2.0", id=sequence, method=method, params=params)
                            channel.sendall(json.dumps(message).encode() + b"\n")
                            while True:
                                line = stream.readline()
                                if not line:
                                    raise RuntimeError(f"AIOS closed the MCP channel; see {console}")
                                response = json.loads(line)
                                if "method" in response:
                                    if "id" in response:
                                        answer = dict(jsonrpc="2.0", id=response["id"])
                                        if response["method"] == "elicitation/create":
                                            answer["result"] = {"action": "cancel"}
                                        elif response["method"] == "ping":
                                            answer["result"] = {}
                                        else:
                                            answer["error"] = {"code": -32601, "message": "Unsupported client method"}
                                        channel.sendall(json.dumps(answer).encode() + b"\n")
                                    continue
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
                console_channel.sendall(b"poweroff\n")
                if vm.wait(timeout=45) != 0:
                    raise RuntimeError("QEMU failed during shutdown")
            finally:
                if vm.poll() is None:
                    vm.kill()
                vm.wait()
                if thread is not None:
                    thread.join()
                    console_channel.close()
            if b"AIOS_RUNTIME_STOPPED" not in console.read_bytes():
                raise RuntimeError("Clean data volume shutdown was not confirmed")


def read(tool):
    state = tool("inspect_document")
    chunks = []
    offset = 0
    while True:
        page = tool("read_text", document=state["document"], revision=state["revision"], offset=offset)
        chunks.append(page["text"])
        if page["next_offset"] is None:
            return state, "".join(chunks)
        if page["next_offset"] != offset + len(page["text"]) or not page["text"]:
            raise ValueError("Document page did not advance correctly")
        offset = page["next_offset"]


def interactive_instructions():
    while True:
        try:
            instruction = input("AIOS> ").strip()
        except EOFError:
            return
        if not instruction:
            return
        yield instruction


def main():
    bundle = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qemu", default="qemu-system-x86_64")
    parser.add_argument("--usb-uefi", type=Path, nargs=2, metavar=("CODE", "VARS"),
                        help="boot the ISO from virtual USB with x86_64 UEFI firmware and a matching variables template")
    parser.add_argument("--output", type=Path, help="new directory for the disk, logs and proof")
    parser.add_argument("--model-port", type=int, help="local llama-server port for model-selected MCP calls")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--instruction", help="ask the local model to edit the open document")
    mode.add_argument("--interactive", action="store_true", help="enter instructions until a blank line or EOF")
    parser.add_argument("--resume", type=Path, help="continue from a completed MVP output directory")
    args = parser.parse_args()
    if args.instruction is not None and (not args.instruction.strip() or args.model_port is None):
        parser.error("--instruction requires a nonempty request and --model-port")
    if args.interactive and args.model_port is None:
        parser.error("--interactive requires --model-port")
    qemu = shutil.which(args.qemu)
    if not qemu:
        parser.error("QEMU x86_64 is required; specify --qemu with its executable path")
    iso, seed = bundle / "aios-runtime.iso", bundle / "starter.raw.xz"
    for path in (iso, seed, *(args.usb_uefi or ())):
        if not path.is_file():
            parser.error(f"Missing bundle file: {path.name}")
    if args.output:
        output = args.output.resolve()
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
    else:
        output = Path(tempfile.mkdtemp(prefix="aios-mvp-", dir=Path.cwd())).resolve()
    print(f"AIOS MVP output: {output}", flush=True)
    usb_uefi = None
    if args.usb_uefi:
        firmware, template = args.usb_uefi
        variables = output / "uefi-vars.fd"
        shutil.copyfile(template, variables)
        usb_uefi = (firmware, variables)
    disk = output / "workspace.raw"
    if args.resume is None:
        with lzma.open(seed) as source, disk.open("xb") as target:
            shutil.copyfileobj(source, target)
    else:
        prior = json.loads((args.resume / "proof.json").read_text(encoding="utf-8"))
        shutil.copyfile(args.resume / "workspace.raw", disk)

    with boot(qemu, iso, disk, output / "first-boot.log", usb_uefi) as (tool, catalog):
        addition = "AIOS에서 저장했습니다."
        instruction = args.instruction
        if args.model_port is not None:
            from model_mvp import run_model
            addition = "검토 완료 " + str(1000 + secrets.randbelow(9000))
            instruction = args.instruction or f"현재 문서의 기존 내용을 유지하고 새 줄에 '{addition}'라고 한 번만 추가해 줘."
        started = time.perf_counter_ns()
        before, original = read(tool)
        if args.resume is not None and (before["revision"] != prior["revision_after_reboot"]
                                        or original != prior["after_reboot"]):
            raise RuntimeError("Workspace differs from the completed session")
        state, text, digest = before, original, before["revision"]
        instructions = interactive_instructions() if args.interactive else [instruction]
        turns = []
        available = catalog() if args.model_port is not None else []
        if args.interactive:
            print(text, flush=True)
        for request in instructions:
            if args.interactive:
                started = time.perf_counter_ns()
            if args.model_port is not None:
                saved, trace = run_model(args.model_port, request, available, tool, state)
            else:
                saved = tool("append_line", document=state["document"], revision=digest, line=addition)
            revision_before = digest
            state, text = read(tool)
            if args.instruction is None and not args.interactive:
                expected = original + ("" if not original or original.endswith("\n") else "\n") + addition
                if text != expected:
                    raise RuntimeError("Saved document differs from the requested demo edit")
            digest = hashlib.sha256(text.encode()).hexdigest()
            if saved["revision"] != digest or state["revision"] != digest:
                raise RuntimeError("Saved document failed readback")
            verified_ns = time.perf_counter_ns() - started
            if args.interactive:
                turns.append(dict(instruction=request, revision_before=revision_before, revision_after=digest,
                                  model_trace=trace, instruction_to_verified_save_ns=verified_ns))
                print(text, flush=True)
    with boot(qemu, iso, disk, output / "second-boot.log", usb_uefi) as (tool, _):
        reopened, actual = read(tool)
        if actual != text or reopened["revision"] != digest:
            raise RuntimeError("Rebooted guest returned different content")
    proof = dict(document=before["document"], before=original, after_reboot=actual,
                 revision_before=before["revision"], revision_after_reboot=digest, boots=2)
    if usb_uefi:
        proof["boot_media"] = "uefi-usb"
    if args.interactive:
        proof["turns"] = turns
    elif args.model_port is not None:
        proof.update(instruction=instruction, model_trace=trace,
                     instruction_to_verified_save_ns=verified_ns)
    (output / "proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS: verified the saved document after a second ISO boot.", flush=True)


if __name__ == "__main__":
    main()

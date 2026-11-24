"""Send a Korean editing instruction to the running model and the ARM64 guest."""
import argparse
import hashlib
from functools import partial
import json
from pathlib import Path
import subprocess
import sys

from model_mvp import run_model


def wait(vm, log, prefix):
    for raw in vm.stdout:
        if log is not None:
            log.write(raw)
        line = raw.decode(errors="replace").strip()
        if line.startswith("MODEL_USAGE "):
            print(line.removeprefix("MODEL_USAGE "), file=sys.stderr, flush=True)
        if line.startswith(prefix):
            return line
        if "Kernel panic" in line:
            raise RuntimeError(line)
    raise RuntimeError(f"Guest stopped before {prefix}")


def command(vm, log, request, prefix):
    encoded = request.encode()
    if sys.platform == "win32":
        # The Windows stdio backend can overrun the emulated PL011 RX FIFO.
        # Wait for the guest terminal echo before submitting each next chunk.
        for offset in range(0, len(encoded), 8):
            chunk = encoded[offset:offset + 8]
            vm.stdin.write(chunk)
            vm.stdin.flush()
            echo = vm.stdout.read(len(chunk))
            if log is not None:
                log.write(echo)
            if echo != chunk:
                raise RuntimeError("Guest serial echo differs from the command")
    else:
        vm.stdin.write(encoded)
    vm.stdin.write(b"\n")
    vm.stdin.flush()
    return wait(vm, log, prefix)


def console_tool(vm, log, observations, name, document, revision, line=None, index=None):
    if name == "read_text" and document == "note.txt":
        reply = command(vm, log, f"read {revision} 0 512", "AIOS_")
        if not reply.startswith("AIOS_PAGE "):
            raise ValueError(reply)
        page = json.loads(reply.removeprefix("AIOS_PAGE "))
        if page["next_byte"] is None:
            observations[revision] = page["text"].split("\n")
        return page
    if name == "append_observed_line":
        lines = observations.get(revision, [])
        if type(index) is not int or not -len(lines) <= index < len(lines):
            raise ValueError("Read the complete document first and select an existing line index")
        name, line = "append_line", lines[index]
    if (name != "append_line" or document != "note.txt" or not isinstance(line, str) or not line.isprintable()
            or len(line.encode()) > 3900):
        raise ValueError("Expected a single printable console line")
    response = command(vm, log, f"append {revision} {line}", "AIOS_")
    if not response.startswith("AIOS_SAVED revision="):
        raise ValueError(response)
    return {"revision": response.removeprefix("AIOS_SAVED revision=")}



def edit(vm, log, port, instruction, revision):
    catalog = [
        {"name": "append_line", "inputSchema": {"properties": {"line": {"type": "string"}}}},
        {"name": "read_text", "inputSchema": {"properties": {}}},
        {"name": "append_observed_line", "inputSchema": {"properties": {"index": {"type": "integer"}}}},
    ]
    state = {"document": "note.txt", "revision": revision}
    return run_model(port, instruction, catalog, partial(console_tool, vm, log, {}), state)


def read_document(vm, revision):
    chunks = []
    offset = 0
    while offset is not None:
        response = command(vm, None, f"read {revision} {offset} 512", "AIOS_")
        if not response.startswith("AIOS_PAGE "):
            raise RuntimeError(response)
        page = json.loads(response.removeprefix("AIOS_PAGE "))
        if page["revision"] != revision or (page["next_byte"] is not None and
                (not page["text"] or page["next_byte"] != offset + len(page["text"].encode()))):
            raise RuntimeError("Invalid document page")
        chunks.append(page["text"])
        offset = page["next_byte"]
    text = "".join(chunks)
    if hashlib.sha256(text.encode()).hexdigest() != revision:
        raise RuntimeError("Readback differs from the guest revision")
    return {"revision": revision, "text": text}


def requests(args):
    if not args.interactive:
        yield args.instruction
        return
    if sys.stdin.isatty():
        print("한 줄씩 지시를 입력하세요. 빈 줄로 종료합니다.", file=sys.stderr)
    for line in sys.stdin:
        if not line.strip():
            return
        yield line.strip()


def main(launch=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("disk", type=Path, help="writable working copy of starter.raw")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--instruction", help="request a single document edit")
    action.add_argument("--interactive", action="store_true", help="edit repeatedly until a blank line or EOF")
    action.add_argument("--show", action="store_true", help="print the persisted document")
    parser.add_argument("--model-port", type=int, default=18080)
    engine = parser.add_mutually_exclusive_group()
    engine.add_argument("--offline", action="store_true", help="use built-in Korean memo commands in the guest")
    engine.add_argument("--guest-model", action="store_true", help="use built-in Korean commands with local model inference for additional phrasings")
    if launch:
        parser.add_argument("--split-disk", action="store_true", help="boot the disk with a separate read-only system partition")
    args = parser.parse_args()
    launcher = Path(__file__).resolve().with_name("arm64-console.sh")
    starters = [launcher.with_name(name) for name in ("starter.raw", "split-starter.raw", "split-model-starter.raw")]
    if not args.disk.is_file() or any(path.is_file() and args.disk.samefile(path) for path in starters):
        parser.error("provide a separate working disk")
    if args.instruction is not None and not args.instruction.strip():
        parser.error("empty instruction")

    vm_args = (
        launch(args.disk, guest_model=args.guest_model, split_disk=args.split_disk)
        if launch else ["bash", launcher, args.disk]
    )
    with subprocess.Popen(vm_args, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as vm:
        try:
            log = None
            wait(vm, log, "AIOS_DOCUMENT_READY pid=1")
            for instruction in requests(args):
                info = command(vm, log, "inspect", "AIOS_")
                if not info.startswith("AIOS_DOCUMENT revision="):
                    raise RuntimeError(info)
                revision = info.split()[1].split("=")[1]
                if instruction is not None and (args.offline or args.guest_model):
                    if not instruction.isprintable() or len(instruction.encode()) > 3900:
                        raise ValueError("Expected a single printable instruction under 3901 bytes")
                    operation = "model-append" if args.guest_model else "korean"
                    reply = command(vm, log, f"{operation} {revision} {instruction}", "AIOS_")
                    if not reply.startswith(("AIOS_SAVED revision=", "AIOS_READ revision=")):
                        raise ValueError(reply)
                    revision = reply.split("=", 1)[1]
                elif instruction is not None:
                    saved, _ = edit(vm, log, args.model_port, instruction, revision)
                    revision = saved["revision"]
                result = read_document(vm, revision)
                if args.interactive:
                    print(json.dumps(result, ensure_ascii=False), flush=True)
            vm.stdin.write(b"poweroff\n")
            vm.stdin.flush()
            if vm.wait(timeout=30) != 0:
                raise RuntimeError("Guest shutdown failed")
            if not args.interactive:
                print(json.dumps(result, ensure_ascii=False))
        finally:
            if vm.poll() is None:
                vm.kill()


if __name__ == "__main__":
    main()

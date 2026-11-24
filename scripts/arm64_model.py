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
        if line.startswith(prefix):
            return line
        if "Kernel panic" in line:
            raise RuntimeError(line)
    raise RuntimeError(f"Guest stopped before {prefix}")


def command(vm, log, request, prefix):
    vm.stdin.write(request.encode() + b"\n")
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("disk", type=Path, help="writable working copy of starter.raw")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--instruction", help="request a single document edit")
    action.add_argument("--show", action="store_true", help="print the persisted document")
    parser.add_argument("--model-port", type=int, default=18080)
    args = parser.parse_args()
    launcher = Path(__file__).resolve().with_name("arm64-console.sh")
    if not args.disk.is_file() or args.disk.samefile(launcher.with_name("starter.raw")):
        parser.error("provide a separate working disk")
    if args.instruction is not None and not args.instruction.strip():
        parser.error("empty instruction")

    with subprocess.Popen(["bash", launcher, args.disk], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as vm:
        try:
            log = None
            wait(vm, log, "AIOS_DOCUMENT_READY pid=1")
            info = command(vm, log, "inspect", "AIOS_DOCUMENT ")
            revision = info.split()[1].split("=")[1]
            if args.instruction is not None:
                saved, _ = edit(vm, log, args.model_port, args.instruction, revision)
                revision = saved["revision"]
            chunks = []
            offset = 0
            while offset is not None:
                response = command(vm, log, f"read {revision} {offset} 512", "AIOS_")
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
            vm.stdin.write(b"poweroff\n")
            vm.stdin.flush()
            if vm.wait(timeout=30) != 0:
                raise RuntimeError("Guest shutdown failed")
            print(json.dumps({"revision": revision, "text": text}, ensure_ascii=False))
        finally:
            if vm.poll() is None:
                vm.kill()


if __name__ == "__main__":
    main()

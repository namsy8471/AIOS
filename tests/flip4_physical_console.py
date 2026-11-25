"""Verify model-driven save and abrupt process loss on an authorized USB Flip4."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import uuid


def read_reply(process, prefix):
    for raw in process.stdout:
        line = raw.decode().strip()
        if line.startswith(prefix):
            return line.removeprefix(prefix)
        if line.startswith("AIOS_REJECT ") or line.startswith("AIOS_UNCONFIRMED "):
            raise RuntimeError(line)
    raise RuntimeError(f"Console stopped before {prefix}")


def send(process, request):
    process.stdin.write((request + "\n").encode())
    process.stdin.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("--adb", default="adb")
    args = parser.parse_args()
    adb = [args.adb, "-d"]
    identifier = uuid.uuid4().hex
    remote = f"/data/local/tmp/aios-power-cut-{identifier}"
    work = f"{remote}/work"
    executable = f"{remote}/aios"
    console = adb + ["shell", "-T", executable, "document-console", work, "--model-dir", remote]

    def shell(*command):
        subprocess.run(adb + ["shell", "-T", *command], check=True, timeout=20)

    def push(source, target):
        subprocess.run(adb + ["push", str(source), target], check=True, timeout=180)

    shell("mkdir", "-m", "700", remote)
    try:
        shell("mkdir", "-m", "700", work)
        with tempfile.TemporaryDirectory() as directory:
            note = Path(directory) / "note.txt"
            note.write_bytes("장보기".encode())
            before = hashlib.sha256(note.read_bytes()).hexdigest()
            push(note, f"{work}/note.txt")
        push(args.binary, executable)
        for name in ("llama-simple", "model.gguf"):
            push(args.model_dir / name, f"{remote}/{name}")
        shell("chmod", "700", executable, f"{remote}/llama-simple")

        with subprocess.Popen(console, stdin=subprocess.PIPE, stdout=subprocess.PIPE) as process:
            try:
                read_reply(process, "AIOS_STREAM_POLICY open-denied")
                pid = read_reply(process, "AIOS_DOCUMENT_READY pid=")
                if not pid.isascii() or not pid.isdecimal() or int(pid) <= 1:
                    raise RuntimeError("Invalid console PID")
                send(process, f"model-append {before} 메모에 '우유'를 적어줘.")
                usage = json.loads(read_reply(process, "MODEL_USAGE "))
                saved = read_reply(process, "AIOS_SAVED revision=")
                # Resolve the PID to the exact temporary executable before terminating it.
                shell(f'[ "$(readlink /proc/{pid}/exe)" = "{executable}" ] && kill -KILL {pid}')
                if process.wait(timeout=20) == 0:
                    raise RuntimeError("Expected a nonzero exit after SIGKILL")
            finally:
                if process.poll() is None:
                    process.kill()

        result = subprocess.run(
            console, input=f"append {before} 오래된 변경\nread {saved} 0 512\n".encode(),
            capture_output=True, check=True, timeout=20,
        )
        replies = result.stdout.decode().splitlines()
        rejected = [line for line in replies if line.startswith(("AIOS_REJECT ", "AIOS_SAVED "))]
        if rejected != ["AIOS_REJECT invalid-edit"]:
            raise RuntimeError(f"Reopened console accepted an old revision: {rejected}")
        page, = [
            json.loads(line.removeprefix("AIOS_PAGE "))
            for line in replies if line.startswith("AIOS_PAGE ")
        ]
        expected = "장보기\n우유"
        if page != {"text": expected, "revision": hashlib.sha256(expected.encode()).hexdigest(), "next_byte": None}:
            raise RuntimeError("Reopened document did not match the saved revision")
        digest = subprocess.check_output(adb + ["shell", "-T", "sha256sum", f"{work}/note.txt"], timeout=20)
        if digest.decode().split()[0] != page["revision"]:
            raise RuntimeError("On-device file differs from the reopened document")
        print(json.dumps({"model_usage": usage, "after_sigkill": page, "stale_revision_rejected": True},
                         ensure_ascii=False))
    finally:
        shell("rm", "-f", executable, f"{remote}/llama-simple", f"{remote}/model.gguf",
              f"{work}/note.txt", f"{work}/.aios-note-staging")
        shell("rmdir", work, remote)
        shell("test", "!", "-e", remote)


if __name__ == "__main__":
    main()

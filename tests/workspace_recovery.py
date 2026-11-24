"""Btrfs integration check. The CI job supplies a disposable mounted filesystem."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time


def tree_hash(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        if path.is_dir():
            digest.update(b"D")
        else:
            digest.update(b"F" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def entry(index):
    return Path(f"group-{index % 10}") / f"{index:05}.txt"


def failed_editor():
    for i in range(1000):
        path = entry(i)
        if i % 3 == 0:
            with path.with_suffix(".new").open("xb") as created:
                created.write(f"신규 {i}".encode())
        elif i % 3 == 1:
            path.unlink()
        else:
            path.write_text("changed", encoding="utf-8")
    # A detached autosave process would outlive a plain parent-process wait.
    if os.fork() == 0:
        os.setsid()
        time.sleep(0.5)
        Path(sys.argv[2]).write_text("escaped")
        os._exit(0)
    Path(sys.argv[3]).write_text(str(time.monotonic_ns()))
    sys.exit(23)


def verify(binary, mount):
    root = mount / "work"
    subprocess.run(["btrfs", "subvolume", "create", root], check=True)
    for i in range(10):
        (root / entry(i).parent).mkdir()
    for i in range(10_000):
        (root / entry(i)).write_text(f"원본 {i}", encoding="utf-8")
    subprocess.run(["btrfs", "filesystem", "sync", mount], check=True)
    before = tree_hash(root)
    marker = mount / "autosave"
    worker = mount / "workspace_recovery.py"
    shutil.copyfile(__file__, worker)
    command = [binary, "workspace-run", root, "--", sys.executable]
    abort_stamp = mount / "abort-time"
    failure = subprocess.run([*command, worker, "failed-editor", marker, abort_stamp],
                             capture_output=True, text=True)
    returned_ns = time.monotonic_ns()
    print(failure.stderr, flush=True)
    assert failure.returncode == 23, failure
    abort_to_return_ms = (returned_ns - int(abort_stamp.read_text())) / 1_000_000
    print(f"abort_to_return_ms={abort_to_return_ms:.3f}")
    assert 0 <= abort_to_return_ms < 1000
    for name, limit in [("checkpoint", 100_000), ("rollback", 1_000_000)]:
        match = re.search(rf"^{name}_us=(\d+)$", failure.stderr, re.MULTILINE)
        assert match and int(match[1]) < limit, failure.stderr
    time.sleep(0.6)
    assert not marker.exists()
    after = tree_hash(root)
    assert after == before
    print(f"tree_sha256_before={before} tree_sha256_after={after}", flush=True)
    ready = mount / "writer-ready"
    pending = subprocess.Popen([*command, "-c",
        "import sys,time; from pathlib import Path; "
        "Path(sys.argv[2]).write_text('pending'); Path(sys.argv[1]).touch(); "
        "time.sleep(30)", ready, entry(0)])
    try:
        until = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < until and pending.poll() is None:
            time.sleep(0.02)
        assert ready.exists(), "writer did not start"
        competing = subprocess.run([*command, "-c", "open('unexpected', 'w').close()"],
                                   capture_output=True, text=True, timeout=3)
        assert competing.returncode != 0 and "workspace parent unavailable" in competing.stderr
        pending.send_signal(signal.SIGINT)
        assert pending.wait(timeout=3) == 130
    finally:
        if pending.poll() is None:
            pending.terminate()
            pending.wait(timeout=5)
    assert tree_hash(root) == before
    # A new process opens the restored tree and commits a subsequent valid edit.
    subprocess.run([*command, "-c",
                    "import sys; from pathlib import Path; p=Path(sys.argv[1]); "
                    "assert p.read_text(encoding='utf-8')=='원본 0'; "
                    "p.write_bytes('검토 완료'.encode())", entry(0)], check=True)
    assert (root / entry(0)).read_bytes() == "검토 완료".encode()
    assert not list(mount.glob(".aios-session-*"))
    print("10,000-file hash restored; autosave stopped; next session committed")


if __name__ == "__main__":
    if sys.argv[1] == "failed-editor":
        failed_editor()
    else:
        verify(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())

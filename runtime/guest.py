"""Start one offline document session on the second emulated serial port."""
import errno
import fcntl
import os
import re
from pathlib import Path
import subprocess
import sys
import tty

def recover_sessions(root):
    # Boot runs before the broker starts. Use its parent-directory lock as well.
    fd = os.open(root, os.O_DIRECTORY | os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for entry in root.iterdir():
            if not re.fullmatch(r"\.aios-session-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", entry.name):
                continue
            if entry.is_symlink() or not entry.is_dir():
                continue
            try:
                marker = os.getxattr(entry, "trusted.aios.transaction", follow_symlinks=False)
            except OSError as err:
                if err.errno == errno.ENODATA:
                    continue
                raise
            if marker != b"v1":
                continue
            branch = entry / "documents"
            children = list(entry.iterdir())
            if children:
                if children != [branch] or branch.is_symlink() or not branch.is_dir():
                    raise RuntimeError("Unexpected contents in managed transaction directory")
                subprocess.run(["btrfs", "subvolume", "delete", branch], check=True)
            entry.rmdir()
            print("AIOS_RECOVERED_TRANSACTION", flush=True)
    finally:
        os.close(fd)


root = Path("/mnt/aios-data")
root.mkdir(parents=True, exist_ok=True)
subprocess.run(["mount", "-t", "btrfs", "-o", "nodev,nosuid,noexec",
                "LABEL=AIOS-DATA", str(root)], check=True)
try:
    with open("/dev/ttyS1", "r+b", buffering=0) as channel:
        tty.setraw(channel)
        workspace = root / "documents"
        if workspace.is_symlink() or not workspace.is_dir():
            raise ValueError("Expected a documents subvolume")
        recover_sessions(root)
        with subprocess.Popen([
            "/opt/aios/venv/bin/python", "/opt/aios/mcp_server.py",
            "--aios", "/usr/local/bin/aios", "--workspace", str(workspace),
            "--document", "note.txt",
        ], stdin=channel, stdout=channel, env={**os.environ, "AIOS_MANAGED_GUEST": "1"}) as server:
            try:
                print("AIOS_RUNTIME_READY", flush=True)
                for line in sys.stdin:
                    if line.strip() == "poweroff":
                        break
            finally:
                server.terminate()
                server.wait()
finally:
    os.sync()
    subprocess.run(["umount", str(root)], check=True)

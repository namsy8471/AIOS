"""Start one offline document session on the virtio-vsock or a serial channel."""
import errno
import fcntl
import os
import re
import select
import socket
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


def activity_database(root):
    directory = root / ".aios-activity"
    try:
        directory.mkdir(mode=0o700)
        parent = os.open(root, os.O_DIRECTORY | os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except FileExistsError:
        if directory.is_symlink() or not directory.is_dir():
            raise RuntimeError("Invalid activity directory")
    info = directory.stat()
    if info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise RuntimeError("Activity directory must be private to the broker")
    for entry in directory.iterdir():
        if (entry.name not in ("events.sqlite", "events.sqlite-journal") or entry.is_symlink()
                or not entry.is_file() or entry.stat().st_nlink != 1):
            raise RuntimeError("Unexpected activity database entry")
    return directory / "events.sqlite"


def serve(args):
    env = {**os.environ, "AIOS_MANAGED_GUEST": "1"}
    devices = Path("/sys/bus/virtio/devices").glob("*/device")
    vsock = any(int(device.read_text().strip(), 0) == 19 for device in devices)
    server = None
    try:
        if vsock:
            subprocess.run(["modprobe", "vmw_vsock_virtio_transport"], check=True)
            with socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM) as listener:
                listener.bind((socket.VMADDR_CID_ANY, 4050))
                listener.listen(1)
                print("AIOS_RUNTIME_READY transport=vsock", flush=True)
                while True:
                    if server is not None and server.poll() is not None:
                        server = None
                    readers = [sys.stdin] if server is not None else [sys.stdin, listener]
                    readable, _, _ = select.select(readers, [], [], 0.1 if server else None)
                    if sys.stdin in readable and sys.stdin.readline().strip() in ("", "poweroff"):
                        return
                    if listener in readable:
                        channel, peer = listener.accept()
                        with channel:
                            if peer[0] == socket.VMADDR_CID_HOST:
                                server = subprocess.Popen(args, stdin=channel, stdout=channel, env=env)
        else:
            with open("/dev/ttyS1", "r+b", buffering=0) as channel:
                tty.setraw(channel)
                server = subprocess.Popen(args, stdin=channel, stdout=channel, env=env)
                print("AIOS_RUNTIME_READY transport=serial", flush=True)
                for line in sys.stdin:
                    if line.strip() == "poweroff":
                        return
    finally:
        if server is not None:
            if server.poll() is None:
                server.terminate()
            server.wait()


root = Path("/mnt/aios-data")
root.mkdir(parents=True, exist_ok=True)
subprocess.run(["mount", "-t", "btrfs", "-o", "nodev,nosuid,noexec",
                "LABEL=AIOS-DATA", str(root)], check=True)
try:
    workspace = root / "documents"
    if workspace.is_symlink() or not workspace.is_dir():
        raise ValueError("Expected a documents subvolume")
    recover_sessions(root)
    serve(["/opt/aios/venv/bin/python", "/opt/aios/mcp_server.py",
           "--aios", "/usr/local/bin/aios", "--workspace", str(workspace),
           "--document", "note.txt", "--activity-db", str(activity_database(root))])

finally:
    os.sync()
    subprocess.run(["umount", str(root)], check=True)

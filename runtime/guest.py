"""Start one offline document session on the second emulated serial port."""
import os
from pathlib import Path
import subprocess
import sys
import tty

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
        with subprocess.Popen([
            "/opt/aios/venv/bin/python", "/opt/aios/mcp_server.py",
            "--aios", "/usr/local/bin/aios", "--workspace", str(workspace),
            "--document", "note.txt",
        ], stdin=channel, stdout=channel) as server:
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

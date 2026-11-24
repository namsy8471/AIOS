"""Isolate a QEMU vhost-user backend and connect to the guest's MCP port."""
from contextlib import contextmanager
from pathlib import Path
import socket
import subprocess
import time


@contextmanager
def device(directory, enabled):
    if not enabled:
        yield []
        return
    control = directory / "vhost.sock"
    with subprocess.Popen(["vhost-device-vsock", "--guest-cid", "4", "--socket", control,
                           "--uds-path", directory / "host.sock"]) as backend:
        try:
            deadline = time.monotonic() + 10
            while not control.is_socket():
                if backend.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("vhost-user backend did not start")
                time.sleep(0.05)
            yield ["-object", "memory-backend-memfd,id=vmram,size=2048M,share=on",
                   "-machine", "memory-backend=vmram", "-chardev", f"socket,id=vs,path={control}",
                   "-device", "vhost-user-vsock-pci,chardev=vs"]
        finally:
            if backend.poll() is None:
                backend.terminate()
            backend.wait(timeout=10)


@contextmanager
def connect(directory, enabled):
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(90)
        sock.connect(str(directory / ("host.sock" if enabled else "mcp")))
        with sock.makefile("rwb", buffering=0) as stream:
            if enabled:
                sock.sendall(b"CONNECT 4050\n")
                reply = stream.readline(100)
                if not reply.startswith(b"OK "):
                    raise RuntimeError(f"Guest MCP connection failed: {reply!r}")
            yield sock, stream

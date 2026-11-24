"""Verify the confined worker, its child, and the host's independent view."""
import errno
import os
from pathlib import Path
import socket
import subprocess
import sys


def check_worker(protected, port, host_fd):
    assert "AIOS_HOST_ONLY" not in os.environ
    for operation, expected in [
        (lambda: os.fstat(int(host_fd)), (errno.EBADF,)),
        (lambda: Path(protected).read_bytes(), (errno.ENOENT, errno.EACCES)),
        (lambda: Path(protected).write_bytes(b"changed"), (errno.ENOENT, errno.EACCES)),
        # /dev/null is present and normally writable; Landlock must deny the open.
        (lambda: os.close(os.open("/dev/null", os.O_WRONLY)), (errno.EACCES,)),
    ]:
        try:
            operation()
        except OSError as err:
            assert err.errno in expected, err
        else:
            raise AssertionError("operation unexpectedly allowed")
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=1):
            raise AssertionError("reached host listener")
    except OSError as err:
        assert err.errno in (errno.ECONNREFUSED, errno.ENETUNREACH, errno.EHOSTUNREACH)
    Path("result.tmp").write_text("검토 완료", encoding="utf-8")
    Path("result.tmp").replace("result.txt")


def verify(binary, mount):
    work = mount / "agent-documents"
    subprocess.run(["btrfs", "subvolume", "create", work], check=True)
    protected = mount / "private-note"
    protected.write_bytes(b"host original")
    (work / "check.py").write_bytes(Path(__file__).read_bytes())
    with socket.socket() as receiver:
        receiver.bind(("127.0.0.1", 0))
        receiver.listen()
        receiver.settimeout(0.2)
        command = [binary, "agent-run", work, "--", "/usr/bin/python3", "-I", "check.py",
                   "inside", str(protected), str(receiver.getsockname()[1])]
        with protected.open("r+b") as host_file:
            import fcntl
            high_fd = fcntl.fcntl(host_file, fcntl.F_DUPFD_CLOEXEC, 200)
            try:
                subprocess.run([*command, str(high_fd)], check=True, timeout=10,
                               pass_fds=(high_fd,), env={**os.environ, "AIOS_HOST_ONLY": "synthetic"})
            finally:
                os.close(high_fd)
        try:
            conn, _ = receiver.accept()
        except TimeoutError:
            pass
        else:
            conn.close()
            raise AssertionError("host received a connection")
    assert protected.read_bytes() == b"host original"
    assert (work / "result.txt").read_text(encoding="utf-8") == "검토 완료"
    print("Agent committed its document; protected file intact; host received zero connections")


if __name__ == "__main__":
    if sys.argv[1] == "inside":
        subprocess.run([sys.executable, "-I", __file__, "child", *sys.argv[2:]], check=True)
    elif sys.argv[1] == "child":
        check_worker(*sys.argv[2:])
    else:
        verify(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())

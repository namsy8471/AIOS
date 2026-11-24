"""Open the same document in two independent GTK sessions after cancellation."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


def edit(decision):
    document = Path("note.txt")
    expected = "시작\n검토 완료".encode()
    driver = Path(__file__).with_name("linux_editor_driver.py")
    with subprocess.Popen([sys.executable, driver, "gtk", document.resolve()],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as child:
        assert child.stdout.readline().strip() == "ready"
        def send(line, reply):
            print(line, file=child.stdin, flush=True)
            assert child.stdout.readline().strip() == reply
        send("append 검토 완료", "ok")
        send("save", "ok")
        until = time.monotonic() + 5
        while document.read_bytes() != expected and time.monotonic() < until:
            time.sleep(0.02)
        assert document.read_bytes() == expected
        if decision == "cancel":
            send("inject-modal", "injected")
            send("save", "blocked-dialog")
        child.stdin.close()
        assert child.wait(timeout=10) == 0
    return 23 if decision == "cancel" else 0


def verify(binary, mount):
    work = mount / "gtk-work"
    subprocess.run(["btrfs", "subvolume", "create", work], check=True)
    original = "시작".encode()
    (work / "note.txt").write_bytes(original)
    tools = mount / "gtk-tools"
    tools.mkdir()
    shutil.copyfile(Path(__file__).resolve().parents[1] / "runtime" / "atspi.py", tools / "atspi.py")
    for name in ["gtk_recovery.py", "linux_editor_driver.py", "editor_fixture.py"]:
        shutil.copyfile(Path(__file__).with_name(name), tools / name)
    for decision, status, expected in [("cancel", 23, original),
                                       ("commit", 0, "시작\n검토 완료".encode())]:
        with tempfile.TemporaryDirectory() as runtime:
            result = subprocess.run(
                [binary, "workspace-run", work, "--", "dbus-run-session", "--",
                 "xvfb-run", "-a", sys.executable, tools / "gtk_recovery.py", decision],
                env={**os.environ, "XDG_RUNTIME_DIR": runtime, "HOME": runtime,
                     "TMPDIR": runtime, "GSETTINGS_BACKEND": "memory"},
                timeout=45)
        assert result.returncode == status
        assert (work / "note.txt").read_bytes() == expected
    print("GTK saved inside its branch; cancellation preserved original; fresh editor committed")

    protected = mount / "host-note"
    protected.write_bytes(b"original host file")
    installed = mount / "aios"
    shutil.copy2(binary, installed)
    for script in tools.iterdir():
        shutil.copyfile(script, work / script.name)
    (work / "note.txt").write_bytes(original)
    for decision, status, expected in [("cancel", 23, original),
                                       ("commit", 0, "시작\n검토 완료".encode())]:
        result = subprocess.run([installed, "agent-gui-run", work, "--", sys.executable,
                                 "-I", "/work/gtk_recovery.py", decision, protected], timeout=45)
        assert result.returncode == status, result
        assert (work / "note.txt").read_bytes() == expected
        assert protected.read_bytes() == b"original host file"
    print("Private Wayland GTK editor committed and canceled saves; host file preserved")


if __name__ == "__main__":
    if sys.argv[1] in ("commit", "cancel"):
        if len(sys.argv) == 3:
            os.environ["AIOS_TEST_PROTECTED"] = sys.argv[2]
        sys.exit(edit(sys.argv[1]))
    verify(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())

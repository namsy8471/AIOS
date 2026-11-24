"""Measure observe, append, observe, invoke and independent persisted-byte confirmation."""
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

runtime = Path(__file__).resolve().parents[1] / "runtime"
sys.path.insert(0, str(runtime))
from editor_session import EditorSession


def measure(toolkit, base):
    document = base / f"{toolkit}.txt"
    expected = "시작"
    document.write_bytes(expected.encode())
    if os.name == "nt":
        cmd = ["powershell", "-NoProfile", "-STA", "-File", "tests/windows_editor.ps1",
               "-Toolkit", toolkit, "-Document", document]
    else:
        cmd = [sys.executable, "tests/linux_editor_driver.py", toolkit, document]
    adapter = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    def send(line):
        print(line, file=adapter.stdin, flush=True)
        return adapter.stdout.readline().rstrip("\r\n")

    samples = []
    try:
        assert adapter.stdout.readline().strip() == "ready"
        session = EditorSession(send)
        for i in range(20):
            start = time.perf_counter_ns()
            view = session.observe()
            body, = [n for n in view["elements"] if n["role"] == "textbox"]
            assert body["value"] == expected
            line = f"수정 {i}"
            session.act(view, body["element_id"], "append", line)
            expected += "\n" + line
            edited = session.observe()
            assert edited["generation_seq"] > view["generation_seq"]
            assert next(n for n in edited["elements"] if n["role"] == "textbox")["value"] == expected
            button, = [n for n in edited["elements"] if n["role"] == "button"]
            session.act(edited, button["element_id"], "invoke")
            deadline = time.monotonic() + 5
            while document.read_bytes() != expected.encode():
                if time.monotonic() >= deadline:
                    raise TimeoutError("Saved document mismatch")
                time.sleep(0.001)
            samples.append((time.perf_counter_ns() - start) / 1e6)
        for stale in (view, edited):
            try:
                session.act(stale, button["element_id"], "invoke")
            except ValueError:
                pass
            else:
                raise AssertionError("Consumed observation accepted")
        current = session.observe()
        assert send("inject-modal") == "injected"
        assert session.observe()["elements"] == []
        try:
            session.act(current, button["element_id"], "invoke")
        except ValueError:
            pass
        else:
            raise AssertionError("Modal allowed background action")
    finally:
        adapter.stdin.close()
        try:
            assert adapter.wait(timeout=10) == 0
        finally:
            if adapter.poll() is None:
                adapter.kill()
                adapter.wait()
    print("warm_edit_ms", json.dumps({"toolkit": toolkit, "count": len(samples),
                                     "median": statistics.median(samples),
                                     "p95": sorted(samples)[18], "samples": samples}))


with tempfile.TemporaryDirectory() as temp:
    for toolkit in sys.argv[1:]:
        measure(toolkit, Path(temp))

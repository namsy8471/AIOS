"""Measure editor change callback to verified AT-SPI text in one Linux clock domain."""
import json
import math
import select
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atspi import Atspi, control, editor_environment, observe_text, wait


def measure(toolkit):
    env = editor_environment()
    env.update(QT_QPA_PLATFORM="wayland", QT_LINUX_ACCESSIBILITY_ALWAYS_ON="1")
    fixture = Path(__file__).with_name("editor_fixture.py")
    Path("seed.txt").write_text("seed")
    editor = subprocess.Popen([sys.executable, "-I", fixture, toolkit, "seed.txt", "--clock"],
                              env=env, stdout=subprocess.PIPE, bufsize=0)
    samples = []
    try:
        window = wait(editor, "ready", "AIOS test editor")
        node = control(window, "Document", "EditableText")
        for index in range(100):
            value = f"관측 {index}"
            with observe_text(node, value) as await_change:
                assert Atspi.EditableText.set_text_contents(node, value)
                received = await_change()
            deadline = time.monotonic() + 5
            while select.select([editor.stdout], [], [], max(0, deadline - time.monotonic()))[0]:
                record = editor.stdout.readline()
                if not record:
                    raise EOFError("Editor exited before reporting a change")
                text, changed = json.loads(record)
                if text == value:
                    break
            else:
                raise TimeoutError("Editor did not report the matching sample")
            assert received >= changed
            samples.append({"index": index, "changed_ns": changed, "observed_ns": received})
    finally:
        editor.terminate()
        editor.wait(timeout=5)
    times = sorted((s["observed_ns"] - s["changed_ns"]) / 1e6 for s in samples)
    return {"toolkit": toolkit, "samples": samples, "count": len(times),
            "p95_ms": times[math.ceil(0.95 * len(times)) - 1], "max_ms": times[-1]}


if __name__ == "__main__":
    report = measure(sys.argv[1])
    Path(f"{sys.argv[1]}-latency.json").write_text(json.dumps(report, indent=2))

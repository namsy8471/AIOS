"""Observe the nested output independently from its Wayland server."""
import os
from pathlib import Path
import subprocess
import tempfile
import time

from PIL import ImageChops, ImageGrab


def wait_for(check, processes):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        for process in processes:
            if process.poll() is not None:
                raise RuntimeError(f"{process.args} exited with {process.returncode}")
        if result := check():
            return result
        time.sleep(0.05)
    raise TimeoutError("Expected compositor output did not appear")


def capture():
    return ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).convert("RGB")


with tempfile.TemporaryDirectory() as runtime:
    env = dict(os.environ, XDG_RUNTIME_DIR=runtime, LIBGL_ALWAYS_SOFTWARE="1")
    env.pop("WAYLAND_DISPLAY", None)
    with subprocess.Popen(["compositor/target/debug/aios-compositor"], env=env) as server:
        try:
            wait_for(lambda: (Path(runtime) / "aios-0").is_socket(), [server])
            # The renderer clears its window dark red before the first client.
            def background():
                image = capture()
                if any(r > 10 and g == b == 0 for _, (r, g, b) in image.getcolors(256) or []):
                    return image
            base = wait_for(background, [server])
            with subprocess.Popen(["weston-simple-shm"], env={**env, "WAYLAND_DISPLAY": "aios-0"}) as app:
                try:
                    def changed():
                        image = capture()
                        diff = ImageChops.difference(base, image).convert("L")
                        if sum(diff.histogram()[1:]) >= 10000:
                            return image
                    shown = wait_for(changed, [app, server])
                    print("Verified a rendered SHM client on the nested output", flush=True)
                finally:
                    app.terminate()
            wait_for(lambda: ImageChops.difference(base, capture()).getbbox() is None, [server])
            print("Verified background restored after client exit", flush=True)
        finally:
            server.terminate()

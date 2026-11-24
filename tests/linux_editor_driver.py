import signal
import subprocess
import sys
from pathlib import Path

# The fixture is also staged beside the adapter in the transaction tests.
runtime = Path(__file__).resolve().parents[1] / 'runtime'
if not Path(__file__).with_name('atspi.py').exists():
    sys.path.insert(0, str(runtime))
from atspi import command, editor_environment, wait


def main():
    fixture = Path(__file__).with_name("editor_fixture.py")
    editor = subprocess.Popen([sys.executable, str(fixture), *sys.argv[1:]],
                              env=editor_environment(),
                              stdin=subprocess.DEVNULL, stdout=sys.stderr)
    try:
        title = "AIOS test editor"
        wait(editor, "ready", title)
        print("ready", flush=True)
        for line in sys.stdin:
            if line.rstrip("\n") == "inject-modal":
                editor.send_signal(signal.SIGUSR1)
                wait(editor, "dialog", title)
                print("injected", flush=True)
            else:
                print(command(editor, line.rstrip("\n"), title), flush=True)
    finally:
        editor.terminate()
        editor.wait()


if __name__ == "__main__":
    main()

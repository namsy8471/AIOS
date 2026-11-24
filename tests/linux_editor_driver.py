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
        wait(editor, "ready")
        print("ready", flush=True)
        for line in sys.stdin:
            print(command(editor, line.rstrip("\n")), flush=True)
    finally:
        editor.terminate()
        editor.wait()


if __name__ == "__main__":
    main()

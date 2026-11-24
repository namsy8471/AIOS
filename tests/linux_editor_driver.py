"""Exercise only the target editor's accessibility interfaces."""
import signal
import subprocess
import sys
import time
from pathlib import Path

import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, GLib


def children(node):
    for i in range(node.get_child_count()):
        child = node.get_child_at_index(i)
        if child is not None:
            yield child


def walk(node):
    yield node
    for child in children(node):
        yield from walk(child)


def snapshot(pid):
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)
    for app in children(Atspi.get_desktop(0)):
        if app.get_process_id() != pid:
            continue
        windows = list(children(app))
        if any(w.get_state_set().contains(Atspi.StateType.MODAL)
               and w.get_state_set().contains(Atspi.StateType.SHOWING) for w in windows):
            return "modal", None
        for window in windows:
            if window.get_name() == "AIOS test editor":
                return "ready", window
    return "missing", None


def wait(editor, expected):
    deadline = time.monotonic() + 15
    while editor.poll() is None and time.monotonic() < deadline:
        state, window = snapshot(editor.pid)
        if state == expected:
            return window
        time.sleep(0.05)
    tree = [(app.get_name(), app.get_process_id(),
             [(w.get_name(), w.get_role_name()) for w in children(app)])
            for app in children(Atspi.get_desktop(0))]
    raise RuntimeError(f"PID {editor.pid} did not reach {expected}; desktop: {tree}")


def control(window, name, interface):
    matches = [n for n in walk(window) if n.get_name() == name and interface in n.get_interfaces()]
    if len(matches) != 1:
        raise ValueError(f"expected one {name} with {interface}, found {len(matches)}")
    return matches[0]


def command(editor, line):
    if line == "inject-modal":
        editor.send_signal(signal.SIGUSR1)
        wait(editor, "modal")
        return "injected"
    state, window = snapshot(editor.pid)
    if state != "ready":
        return "blocked-" + state
    if line.startswith("append "):
        node = control(window, "Document", "EditableText")
        old = Atspi.Text.get_text(node, 0, -1)
        if not Atspi.EditableText.set_text_contents(node, old + "\n" + line.removeprefix("append ")):
            raise RuntimeError("edit declined")
    elif line == "save":
        node = control(window, "Save", "Action")
        actions = [i for i in range(Atspi.Action.get_n_actions(node))
                   if Atspi.Action.get_action_name(node, i).lower() in ("click", "press")]
        if len(actions) != 1 or not Atspi.Action.do_action(node, actions[0]):
            raise RuntimeError("save declined")
    else:
        raise ValueError("unknown action")
    return "ok"


def main():
    fixture = Path(__file__).with_name("editor_fixture.py")
    Atspi.get_desktop(0)
    editor = subprocess.Popen([sys.executable, str(fixture), *sys.argv[1:]],
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

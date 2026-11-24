"""GTK fixture and independent AT-SPI observer for the Linux integration test."""
import signal
import subprocess
import sys
import time

import gi


def run_editor():
    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk

    window = Gtk.Window(title="AIOS test editor")
    window.add(Gtk.TextView())
    window.show_all()

    def open_dialog():
        dialog = Gtk.FileChooserDialog(
            title="Save document", transient_for=window,
            action=Gtk.FileChooserAction.SAVE, modal=True,
        )
        dialog.add_button("Save", Gtk.ResponseType.ACCEPT)
        dialog.run()
        dialog.destroy()
        return False

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, open_dialog)
    Gtk.main()


def observe(editor, expected):
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi, GLib

    def children(node):
        return [node.get_child_at_index(i) for i in range(node.get_child_count())]

    desktop = Atspi.get_desktop(0)
    context = GLib.MainContext.default()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if editor.poll() is not None:
            raise RuntimeError("GTK editor exited")
        while context.pending():
            context.iteration(False)
        for app in children(desktop):
            if app is None or app.get_process_id() != editor.pid:
                continue
            windows = children(app)
            if not any(w and w.get_name() == "AIOS test editor" for w in windows):
                continue
            modal = any(w and w.get_state_set().contains(Atspi.StateType.MODAL)
                        and w.get_state_set().contains(Atspi.StateType.SHOWING)
                        for w in windows)
            state = "modal" if modal else "ready"
            if state == expected:
                print(state, flush=True)
                return
        time.sleep(0.05)
    raise TimeoutError(f"GTK state never reached {expected}")


def run_observer():
    editor = subprocess.Popen([sys.executable, __file__, "editor"],
                              stdout=sys.stderr, stdin=subprocess.DEVNULL)
    try:
        observe(editor, "ready")
        if input() != "open":
            raise ValueError("expected dialog request")
        editor.send_signal(signal.SIGUSR1)
        observe(editor, "modal")
    finally:
        editor.terminate()
        editor.wait()


if __name__ == "__main__":
    if sys.argv[1:] == ["editor"]:
        run_editor()
    else:
        run_observer()

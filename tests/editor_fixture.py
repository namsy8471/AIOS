"""Small GTK and Qt editors that save only from their own button handlers."""
import json
import os
import signal
import sys
import time
from pathlib import Path


def report_change(read_text):
    changed = time.monotonic_ns()
    print(json.dumps([read_text(), changed]), flush=True)


def gtk_editor(path):
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib

    window = Gtk.Window(title="AIOS test editor")
    window.set_default_size(640, 400)
    body = Gtk.TextView()
    body.get_accessible().set_name("Document")
    buffer = body.get_buffer()
    buffer.set_text(path.read_text(encoding="utf-8"))
    if "--clock" in sys.argv[3:]:
        buffer.connect("changed", lambda *_: report_change(
            lambda: buffer.get_text(*buffer.get_bounds(), True)))
    save = Gtk.Button(label="Save")

    def persist(_):
        if protected := os.getenv("AIOS_TEST_PROTECTED"):
            from gi.repository import Gdk
            assert "Wayland" in Gdk.Display.get_default().__gtype__.name
            try:
                Path(protected).write_bytes(b"unexpected")
            except (FileNotFoundError, PermissionError):
                pass
            else:
                raise AssertionError("host path was writable from GTK")
        text = buffer.get_text(*buffer.get_bounds(), True)
        path.write_bytes(text.encode("utf-8"))

    save.connect("clicked", persist)
    layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.ALWAYS)
    scroll.add(body)
    layout.pack_start(scroll, True, True, 0)
    layout.pack_start(save, False, False, 0)
    window.add(layout)

    def open_dialog():
        dialog = Gtk.FileChooserDialog(title="Save document", transient_for=window,
                                       action=Gtk.FileChooserAction.SAVE, modal=True)
        dialog.add_button("Save", Gtk.ResponseType.ACCEPT)
        dialog.run()
        dialog.destroy()
        return False

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, open_dialog)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, lambda: save.set_margin_start(200))
    window.show_all()
    Gtk.main()


def qt_editor(path):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import (QApplication, QDialog, QPlainTextEdit,
                                 QPushButton, QVBoxLayout, QWidget)

    app = QApplication(["aios-qt-editor"])
    app.setApplicationName("AIOS Qt editor")
    window = QWidget()
    window.resize(640, 400)
    window.setWindowTitle("AIOS test editor")
    window.setAccessibleName("AIOS test editor")
    body = QPlainTextEdit(path.read_text(encoding="utf-8"))
    body.setAccessibleName("Document")
    if "--clock" in sys.argv[3:]:
        body.textChanged.connect(lambda: report_change(body.toPlainText))
    save = QPushButton("Save")
    save.clicked.connect(lambda: path.write_bytes(body.toPlainText().encode("utf-8")))
    layout = QVBoxLayout(window)
    layout.addWidget(body)
    layout.addWidget(save)
    dialog = QDialog(window)
    dialog.setWindowTitle("Save document")
    dialog.setModal(True)
    signal.signal(signal.SIGUSR1, lambda *_: dialog.show())
    signal.signal(signal.SIGUSR2, lambda *_: layout.setContentsMargins(layout.contentsMargins().left() + 200,
                  layout.contentsMargins().top(), layout.contentsMargins().right(), layout.contentsMargins().bottom()))
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(50)
    window.show()
    app.exec()


if __name__ == "__main__":
    {"gtk": gtk_editor, "qt": qt_editor}[sys.argv[1]](Path(sys.argv[2]))

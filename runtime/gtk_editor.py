"""Minimal AIOS UTF-8 document editor for the private Wayland desktop."""
import sys
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

document = Path(sys.argv[1])
window = Gtk.Window(title="AIOS document")
body = Gtk.TextView()
body.get_accessible().set_name("Document")
buffer = body.get_buffer()
buffer.set_text(document.read_bytes().decode("utf-8"))
save = Gtk.Button(label="Save")


def persist(_):
    document.write_bytes(buffer.get_text(*buffer.get_bounds(), True).encode("utf-8"))


save.connect("clicked", persist)
layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
layout.pack_start(body, True, True, 0)
layout.pack_start(save, False, False, 0)
window.add(layout)
window.show_all()
Gtk.main()

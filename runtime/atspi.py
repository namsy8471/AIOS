"""Resolve controls inside a single editor process through AT-SPI."""
from contextlib import contextmanager
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, Gio, GLib


def children(node):
    for i in range(node.get_child_count()):
        child = node.get_child_at_index(i)
        if child is not None:
            yield child


def walk(node):
    yield node
    for child in children(node):
        yield from walk(child)


def snapshot(pid, title):
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)
    for app in children(Atspi.get_desktop(0)):
        if app.get_process_id() != pid:
            continue
        windows = list(children(app))
        for window in windows:
            state = window.get_state_set()
            visible = state.contains(Atspi.StateType.SHOWING) or state.contains(Atspi.StateType.VISIBLE)
            dialog = window.get_role() in (Atspi.Role.DIALOG, Atspi.Role.ALERT)
            if visible and (dialog or state.contains(Atspi.StateType.MODAL)):
                return "dialog", None
        for window in windows:
            if window.get_name() == title:
                return "ready", window
    return "missing", None


def wait(editor, expected, title):
    deadline = time.monotonic() + 15
    while editor.poll() is None and time.monotonic() < deadline:
        state, window = snapshot(editor.pid, title)
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


@contextmanager
def observe_text(node, expected):
    """Wait for this control's text event and verify its new accessible value."""
    loop = GLib.MainLoop()
    observed = None

    def changed(event, *_):
        nonlocal observed
        if observed is None and event.source == node and Atspi.Text.get_text(node, 0, -1) == expected:
            observed = time.monotonic_ns()
            loop.quit()

    def await_change():
        if observed is None:
            timeout = GLib.timeout_source_new(5000)
            timeout.set_callback(lambda *_: loop.quit() or False)
            timeout.attach(loop.get_context())
            try:
                loop.run()
            finally:
                timeout.destroy()
        if observed is None:
            raise TimeoutError("Expected accessible text change was not observed")
        return observed

    listener = Atspi.EventListener.new(changed, None)
    event_type = "object:text-changed"
    if not listener.register(event_type):
        raise RuntimeError("Could not register text observer")
    try:
        yield await_change
    finally:
        listener.deregister(event_type)


def command(editor, line, title):
    state, window = snapshot(editor.pid, title)
    if line == "observe":
        elements = []
        if state == "ready":
            body = control(window, "Document", "EditableText")
            button = control(window, "Save", "Action")
            elements = [
                {"element_id": "body", "name": body.get_name(), "role": "textbox",
                 "value": Atspi.Text.get_text(body, 0, -1), "actions": ["append"]},
                {"element_id": "save", "name": button.get_name(), "role": "button",
                 "actions": ["invoke"]},
            ]
        return json.dumps({"state": state, "elements": elements})
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


def editor_environment():
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    address = bus.call_sync("org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus",
                            "GetAddress", None, GLib.VariantType.new("(s)"),
                            Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
    os.environ["AT_SPI_BUS_ADDRESS"] = address
    Atspi.get_desktop(0)
    # Let Qt discover GetAddress asynchronously after its accessibility bridge
    # has subscribed to the D-Bus connection's enabled notification.
    editor_env = os.environ.copy()
    editor_env.pop("AT_SPI_BUS_ADDRESS")
    return editor_env

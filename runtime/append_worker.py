# The trusted launcher embeds the document and AT-SPI modules ahead of this entry point.
editor_code, toolkit, filename, observed, line = sys.argv[1:]
path = Path(filename)
original = read_document(path)
if digest(original) != observed:
    sys.exit(42)
expected = append_bytes(original, line)
title = "AIOS document"
env = editor_environment()
if toolkit == "qt":
    env.update(QT_QPA_PLATFORM="wayland", QT_LINUX_ACCESSIBILITY_ALWAYS_ON="1")
editor = subprocess.Popen([sys.executable, "-I", "-c", editor_code, filename],
                          env=env, stdin=subprocess.DEVNULL)
try:
    window = wait(editor, "ready", title)
    node = control(window, "Document", "EditableText")
    visible = original.decode("utf-8")
    replacement = expected.decode("utf-8")
    if toolkit == "qt":
        visible = visible.replace("\r\n", "\n").replace("\r", "\n")
        replacement = replacement.replace("\r\n", "\n").replace("\r", "\n")
    if Atspi.Text.get_text(node, 0, -1) != visible:
        raise ValueError("Editor content differs from observed document")
    if not Atspi.EditableText.set_text_contents(node, replacement):
        raise RuntimeError("Editor declined text update")
    if command(editor, "save", title) != "ok":
        raise RuntimeError("Save blocked by changed UI state")
    deadline = time.monotonic() + 5
    while read_document(path) != expected:
        if time.monotonic() >= deadline:
            raise RuntimeError("Saved content could not be verified")
        time.sleep(0.03)
finally:
    editor.terminate()
    editor.wait(timeout=3)

# The trusted launcher embeds the document and AT-SPI modules ahead of this entry point.
editor_code, filename, observed, line = sys.argv[1:]
path = Path(filename)
original = read_document(path)
if digest(original) != observed:
    sys.exit(42)
expected = append_bytes(original, line)
title = "AIOS document"
editor = subprocess.Popen([sys.executable, "-I", "-c", editor_code, filename],
                          env=editor_environment(), stdin=subprocess.DEVNULL)
try:
    window = wait(editor, "ready", title)
    node = control(window, "Document", "EditableText")
    if Atspi.Text.get_text(node, 0, -1).encode() != original:
        raise ValueError("Editor content differs from observed document")
    if not Atspi.EditableText.set_text_contents(node, expected.decode("utf-8")):
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

"""Qt 6 editor for an append transaction on the private Wayland display."""
import sys
from PyQt6.QtWidgets import QApplication, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

document = Path(sys.argv[1])
original = read_document(document)
app = QApplication(["aios-qt-editor"])
window = QWidget()
window.setWindowTitle("AIOS document")
window.setAccessibleName("AIOS document")
body = QPlainTextEdit()
body.setPlainText(original.decode("utf-8"))
initial_view = body.toPlainText()
body.setAccessibleName("Document")
save = QPushButton("Save")


def persist():
    # Qt normalizes line endings in its view. Preserve the original bytes.
    prefix = initial_view
    if original and not original.endswith((b"\n", b"\r")):
        prefix += "\n"
    text = body.toPlainText()
    if text.startswith(prefix):
        document.write_bytes(append_bytes(original, text[len(prefix):]))


save.clicked.connect(persist)
layout = QVBoxLayout(window)
layout.addWidget(body)
layout.addWidget(save)
window.show()
app.exec()

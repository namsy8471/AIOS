"""Client for a running, process-scoped AIOS editor adapter over UTF-8 JSON lines."""
import json
from uuid import uuid4


class EditorSession:
    def __init__(self, send):
        self.send = send
        self.session_id = uuid4().hex
        self.generation = 0
        self.previous = None

    def observe(self):
        current = json.loads(self.send("observe"))
        if current != self.previous:
            self.generation += 1
            self.previous = current
        return {**current, "session_id": self.session_id, "generation_seq": self.generation}

    def act(self, view, element_id, action, text=None):
        current = self.observe()
        if current["state"] != "ready" or current != view:
            raise ValueError("Editor changed; observe again")
        node = next((n for n in current["elements"] if n["element_id"] == element_id), None)
        if node is None or action not in node["actions"]:
            raise ValueError("Unavailable action")
        if action == "append":
            if not isinstance(text, str) or not text or any(c in text for c in "\r\n\0"):
                raise ValueError("Expected one nonempty line")
            command = "append " + text
        elif action == "invoke" and text is None:
            command = "save"
        else:
            raise ValueError("Invalid action")
        # Consume this observation even if the action reply is lost.
        self.previous = None
        if self.send(command) != "ok":
            raise ValueError("Editor action blocked")

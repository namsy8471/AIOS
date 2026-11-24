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

    def act_batch(self, view, actions):
        """Run steps while the observed targets retain their original window geometry."""
        if view["state"] != "ready" or any("bbox" not in node for node in view["elements"]):
            raise ValueError("Batch needs a ready editor with observable target geometry")
        bounds = {node["element_id"]: node["bbox"] for node in view["elements"]}
        for element_id, action, text in actions:
            self.act(view, element_id, action, text)
            view = self.observe()
            if view["state"] != "ready" or {
                node["element_id"]: node.get("bbox") for node in view["elements"]
            } != bounds:
                raise ValueError("Editor layout changed during batch")
        return view

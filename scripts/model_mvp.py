"""Let a local model select MCP document tools using only its own observations."""
import json
import sys
from urllib.request import Request, urlopen


def run_model(port, instruction, catalog, tool):
    allowed = {item["name"]: item for item in catalog
               if item["name"] in {"inspect_document", "read_text", "append_line", "replace_text"}}
    definitions = [{"name": t["name"], "description": t["description"], "arguments": t["inputSchema"]}
                   for t in allowed.values()]
    system = ("You operate one AIOS document. Reply only with one JSON object containing tool "
              "and arguments. Use only available tools. Use returned document and revision values "
              "exactly. This is a non-interactive test: omit review, use the default direct edit. If you do not know the current revision, discover it. Do not invent "
              "arguments. Keep Korean text exactly as requested. Tool definitions: "
              + json.dumps(definitions, ensure_ascii=False))
    messages = [dict(role="system", content=system), dict(role="user", content=instruction)]
    revisions = {}
    trace = []
    for _ in range(6):
        payload = dict(messages=messages, temperature=0, max_tokens=256,
                       response_format={"type": "json_object"})
        request = Request(f"http://127.0.0.1:{port}/v1/chat/completions",
                          data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=120) as response:
            completion = json.load(response)
        raw = completion["choices"][0]["message"]["content"]
        print("Local model:", raw, file=sys.stderr, flush=True)
        messages.append(dict(role="assistant", content=raw))
        step = {"model": completion["model"], "reply": raw}
        trace.append(step)
        try:
            choice = json.loads(raw)
            name = choice["tool"]
            args = choice["arguments"].copy()
            if name not in allowed or not isinstance(args, dict):
                raise ValueError("Unknown tool or invalid arguments")
            # Short references keep the model from having to transcribe 64 hex digits.
            if args.get("review"):
                raise ValueError("Interactive review is unavailable in this test; omit review")
            if "revision" in args:
                args["revision"] = revisions[args["revision"]]
            if name in {"append_line", "replace_text"} and not revisions:
                raise ValueError("No document revision has been observed")
            step["mcp_call"] = {"name": name, "arguments": args}
            result = tool(name, **args)
            step["mcp_result"] = result
            view = result.copy()
            revision = view["revision"]
            handle = next((h for h, r in revisions.items() if r == revision), None)
            if handle is None:
                handle = f"r{len(revisions) + 1}"
                revisions[handle] = revision
            view["revision"] = handle
            if name in {"append_line", "replace_text"}:
                return result, trace
            feedback = json.dumps(view, ensure_ascii=False)
        except (ValueError, KeyError, AttributeError, TypeError, RuntimeError) as error:
            feedback = f"Tool error: {error}"
            step["error"] = feedback
        messages.append(dict(role="user", content="AIOS tool result: " + feedback))
    raise RuntimeError("Model did not finish within six calls: " + json.dumps(trace, ensure_ascii=False))

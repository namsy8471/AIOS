"""Let a local model choose operations on the open AIOS document."""
import json
import sys
import time
from urllib.request import Request, urlopen


def run_model(port, instruction, catalog, tool, state):
    fields = {"read_text": (), "append_line": ("line",), "replace_text": ("old", "new"),
              "edit_document": ("edits",)}
    choices = []
    definitions = {}
    for item in catalog:
        name = item["name"]
        if name not in fields:
            continue
        definitions.update(item["inputSchema"].get("$defs", {}))
        properties = {"tool": {"type": "string", "enum": [name]}}
        for key in fields[name]:
            properties[key] = item["inputSchema"]["properties"][key]
        choices.append(dict(type="object", properties=properties,
                            required=list(properties), additionalProperties=False))

    system = ("Choose the next operation on the open document. read_text reads its contents. "
              "append_line inserts a new line and adds the supplied line; line contains just "
              "the requested literal text without quotes or newline characters. replace_text "
              "replaces one exact occurrence of old with new. For multiple changes, send all "
              "requested edits in order in one edit_document call. Preserve the user's language.")
    messages = [
        dict(role="system", content=system),
        dict(role="user", content="맨 아래에 '회의 종료' 한 줄을 덧붙여 줘."),
        dict(role="assistant", content='{"tool":"append_line","line":"회의 종료"}'),
        dict(role="user", content="'오전'이라고 적힌 부분을 '오후'로 고쳐 줘."),
        dict(role="assistant", content='{"tool":"replace_text","old":"오전","new":"오후"}'),
        dict(role="user", content="'대기'를 '진행'으로 고치고 끝에 '담당자 확인'을 덧붙여 줘."),
        dict(role="assistant", content='{"tool":"edit_document","edits":['
             '{"op":"replace_text","old":"대기","new":"진행"},{"op":"append_line","line":"담당자 확인"}]}'),
        dict(role="user", content=instruction),
    ]
    trace = []
    for _ in range(6):
        payload = dict(messages=messages, temperature=0, max_tokens=256,
                       response_format={"type": "json_schema", "json_schema": {
                           "name": "document_action", "schema": {"oneOf": choices, "$defs": definitions}}})
        request = Request(f"http://127.0.0.1:{port}/v1/chat/completions",
                          data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        started = time.perf_counter_ns()
        with urlopen(request, timeout=120) as response:
            completion = json.load(response)
        model_ns = time.perf_counter_ns() - started
        raw = completion["choices"][0]["message"]["content"]
        print("Local model:", raw, file=sys.stderr, flush=True)
        messages.append(dict(role="assistant", content=raw))
        step = {"model": completion["model"], "reply": raw, "model_request_ns": model_ns}
        trace.append(step)
        try:
            choice = json.loads(raw)
            name = choice.pop("tool")
            if name not in fields or set(choice) != set(fields[name]):
                raise ValueError("Unknown operation or invalid arguments")
            args = dict(document=state["document"], revision=state["revision"], **choice)
            step["mcp_call"] = {"name": name, "arguments": args}
            started = time.perf_counter_ns()
            try:
                result = tool(name, **args)
            finally:
                step["tool_request_ns"] = time.perf_counter_ns() - started
            step["mcp_result"] = result
            if name != "read_text":
                return result, trace
            feedback = json.dumps(result, ensure_ascii=False)
        except (ValueError, KeyError, TypeError, RuntimeError) as error:
            feedback = f"Tool error: {error}"
            step["error"] = feedback
        messages.append(dict(role="user", content="AIOS tool result: " + feedback))
    raise RuntimeError("Model did not finish within six calls: " + json.dumps(trace, ensure_ascii=False))

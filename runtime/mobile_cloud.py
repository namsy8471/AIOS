"""Optional GPT and Claude inference on the Windows worker."""
import json
import os
from pathlib import Path
import subprocess
from urllib.request import Request, urlopen


class AccountRequired(Exception):
    pass


def cloud_draft(provider, instructions, text):
    if provider == "chatgpt":
        bridge = Path(__file__).with_name("chatgpt_oauth.mjs")
        try:
            result = subprocess.run(["node", str(bridge), "draft"],
                                    input=json.dumps({"instructions": instructions, "input": text}).encode(),
                                    capture_output=True, check=True, timeout=115)
        except (subprocess.CalledProcessError, FileNotFoundError) as error:
            raise AccountRequired("Connect ChatGPT and allow plan usage on the Windows PC") from error
        response = json.loads(result.stdout)
        return response["text"], response["model"]

    if provider != "claude":
        raise ValueError("unsupported cloud provider")
    model = os.environ.get("AIOS_CLAUDE_MODEL", "")
    if not model:
        raise AccountRequired("Connect Claude on the Windows PC and configure AIOS_CLAUDE_MODEL")
    env = os.environ.copy()
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(key, None)
    try:
        ant = os.environ.get("AIOS_ANT_CLI", "ant")
        authenticated = subprocess.run([ant, "auth", "print-credentials", "--profile", "aios", "--access-token"],
                                       env=env, capture_output=True, check=True, timeout=20)
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        raise AccountRequired("Sign in to Claude Console using the AIOS profile on the Windows PC") from error
    token = authenticated.stdout.decode("ascii").strip()
    if not token or any(c.isspace() for c in token):
        raise AccountRequired("No valid Claude access token")
    data = json.dumps({"model": model, "system": instructions, "max_tokens": 512,
                       "messages": [{"role": "user", "content": text}]}).encode()
    request = Request("https://api.anthropic.com/v1/messages", data=data,
                      headers={"Authorization": f"Bearer {token}", "anthropic-version": "2026-10-21",
                               "Content-Type": "application/json"})
    with urlopen(request, timeout=100) as response:
        message = json.load(response)
    return "\n".join(block["text"] for block in message["content"] if block["type"] == "text"), message["model"]

"""Test the public stdio endpoint using the official MCP client."""
import asyncio
import hashlib
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify(binary, mount):
    work = mount / "mcp-work"
    subprocess.run(["btrfs", "subvolume", "create", work], check=True)
    filename = "회의 기록.txt"
    document = work / filename
    original = "첫째 줄\r\n둘째 줄".encode()
    document.write_bytes(original)
    outside = mount / "other.txt"
    outside.write_bytes(b"original")
    server = Path(__file__).resolve().parents[1] / "runtime" / "mcp_server.py"
    params = StdioServerParameters(command=sys.executable,
                                   args=[str(server), "--aios", str(binary), "--workspace",
                                         str(work), "--document", filename])
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        await client.initialize()
        listing = await client.list_tools()
        assert {tool.name for tool in listing.tools} == {"inspect_document", "append_line"}
        inspected = await client.call_tool("inspect_document", {})
        assert not inspected.isError
        rev = inspected.structuredContent["revision"]
        assert rev == hashlib.sha256(original).hexdigest()
        request = {"document": filename, "revision": rev, "line": "검토 완료"}
        for change in [{"document": "../other.txt"}, {"line": "두\n줄"}]:
            denied = await client.call_tool("append_line", {**request, **change})
            assert denied.isError and document.read_bytes() == original
        saved = await client.call_tool("append_line", request)
        assert not saved.isError, saved.content
        expected = original + "\r\n검토 완료".encode()
        assert document.read_bytes() == expected
        assert saved.structuredContent["revision"] == hashlib.sha256(expected).hexdigest()
        replay = await client.call_tool("append_line", request)
        assert replay.isError and document.read_bytes() == expected
        assert outside.read_bytes() == b"original"
    print("MCP client verified GTK save, CRLF, scoped grant and stale revision rejection")


if __name__ == "__main__":
    asyncio.run(verify(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()))

"""AIOS stdio MCP server bound to one operator-selected document."""
import argparse
import asyncio
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

from document import append_bytes, digest, read_document


class DocumentRevision(BaseModel):
    document: str
    bytes: int
    revision: str


def create_server(binary, workspace, filename):
    if Path(filename).name != filename or filename in ("", ".", ".."):
        raise ValueError("Select one filename directly inside the managed workspace")
    document_path = workspace / filename
    read_document(document_path)
    runtime = Path(__file__).resolve().parent
    worker = "\n".join((runtime / f).read_text(encoding="utf-8")
                       for f in ("document.py", "atspi.py", "append_worker.py"))
    editor = (runtime / "gtk_editor.py").read_text(encoding="utf-8")
    mcp = FastMCP("AIOS documents", instructions=f"This session can edit only {filename!r}.")

    @mcp.tool()
    def inspect_document() -> DocumentRevision:
        """Return the authorized filename, UTF-8 byte count and current SHA-256 revision."""
        data = read_document(document_path)
        return DocumentRevision(document=filename, bytes=len(data), revision=digest(data))

    @mcp.tool()
    async def append_line(document: str, revision: str, line: str) -> DocumentRevision:
        """Append a line through GTK. Supply the document and revision from inspect_document."""
        if document != filename:
            raise ValueError("Document is outside this session's grant")
        original = read_document(document_path)
        if revision != digest(original):
            raise ValueError("Document revision changed; inspect again")
        expected = append_bytes(original, line)
        process = await asyncio.create_subprocess_exec(
            binary, "agent-gui-run", workspace, "--", "/usr/bin/python3", "-I",
            "-c", worker, editor, filename, revision, line,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL)
        try:
            code = await asyncio.wait_for(process.wait(), timeout=45)
        finally:
            if process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                await process.wait()
        if code == 42:
            raise ValueError("Document revision changed before editing; inspect again")
        if code != 0:
            raise RuntimeError("Session failed; inspect the document revision before retrying")
        return DocumentRevision(document=filename, bytes=len(expected), revision=digest(expected))

    return mcp


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aios", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--document", required=True)
    args = parser.parse_args()
    create_server(args.aios.resolve(strict=True), args.workspace.resolve(strict=True),
                  args.document).run(transport="stdio")

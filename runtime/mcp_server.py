"""AIOS stdio MCP server bound to one operator-selected document."""
import argparse
import asyncio
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from document import append_bytes, digest, read_document


class DocumentRevision(BaseModel):
    document: str
    bytes: int
    revision: str


class SaveDecision(BaseModel):
    save: bool


def create_server(binary, workspace, filename):
    if Path(filename).name != filename or filename in ("", ".", ".."):
        raise ValueError("Select one filename directly inside the managed workspace")
    document_path = workspace / filename
    read_document(document_path)
    runtime = Path(__file__).resolve().parent
    worker = "\n".join((runtime / f).read_text(encoding="utf-8")
                       for f in ("document.py", "atspi.py", "append_worker.py"))
    editors = {name: (runtime / f"{name}_editor.py").read_text(encoding="utf-8")
               for name in ("gtk", "qt")}
    editors["qt"] = (runtime / "document.py").read_text(encoding="utf-8") + "\n" + editors["qt"]
    mcp = FastMCP("AIOS documents", instructions=f"This session can edit only {filename!r}.")

    @mcp.tool()
    def inspect_document() -> DocumentRevision:
        """Return the authorized filename, UTF-8 byte count and current SHA-256 revision."""
        data = read_document(document_path)
        return DocumentRevision(document=filename, bytes=len(data), revision=digest(data))

    @mcp.tool()
    async def append_line(document: str, revision: str, line: str, ctx: Context,
                          editor: Literal["gtk", "qt"] = "gtk", review: bool = False) -> DocumentRevision:
        """Append via GTK or Qt. Set review to confirm the staged save before publishing."""
        if document != filename:
            raise ValueError("Document is outside this session's grant")
        original = read_document(document_path)
        if revision != digest(original):
            raise ValueError("Document revision changed; inspect again")
        expected = append_bytes(original, line)
        process = await asyncio.create_subprocess_exec(
            binary, "agent-gui-run", workspace, *(["--review"] if review else []), "--", "/usr/bin/python3", "-I",
            "-c", worker, editors[editor], editor, filename, revision, line,
            stdin=asyncio.subprocess.PIPE if review else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE if review else asyncio.subprocess.DEVNULL)
        try:
            if review and await asyncio.wait_for(process.stdout.readline(), 45) == b"AIOS_REVIEW_READY\n":
                decision = await asyncio.wait_for(ctx.elicit(
                    f"Save the staged {editor} edit to {filename}? Appended line: {line}",
                    SaveDecision), timeout=110)
                approved = decision.action == "accept" and decision.data.save
                process.stdin.write(b"Y" if approved else b"N")
                await process.stdin.drain()
                process.stdin.close()
            code = await asyncio.wait_for(process.wait(), timeout=45)
        finally:
            if process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                await process.wait()
        if code == 43:
            raise ValueError("Staged edit discarded")
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

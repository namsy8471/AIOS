"""AIOS stdio MCP server bound to one operator-selected document."""
import argparse
import asyncio
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, ConfigDict

from document import MAX_BYTES, append_bytes, digest, read_document


class DocumentRevision(BaseModel):
    document: str
    bytes: int
    revision: str


class DocumentPage(DocumentRevision):
    text: str
    next_offset: int | None


class AppendLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["append_line"]
    line: str


class ReplaceText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["replace_text"]
    old: str
    new: str


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
    mcp = FastMCP("AIOS documents", instructions=(
        f"This session can edit only {filename!r}. Use edit_document to group changes in one commit. Use read_text, replace_text and direct append_line for "
        "document work. Select gtk or qt only for tasks requiring an editor UI."))

    def checked_document(document, revision):
        if document != filename:
            raise ValueError("Document is outside this session's grant")
        data = read_document(document_path)
        if revision != digest(data):
            raise ValueError("Document revision changed; inspect again")
        return data

    def edit_args(revision, ranges, expected):
        args = ["--aios-edit", filename, revision]
        for offset, removed, inserted in ranges:
            args.extend((str(offset), str(removed), inserted))
        return [*args, digest(expected)]

    async def publish(profile, args, ctx, review, expected, prompt):
        process = await asyncio.create_subprocess_exec(
            binary, profile, workspace, *(["--review"] if review else []), "--", *args,
            stdin=asyncio.subprocess.PIPE if review else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE if review else asyncio.subprocess.DEVNULL)
        try:
            if review and await asyncio.wait_for(process.stdout.readline(), 45) == b"AIOS_REVIEW_READY\n":
                decision = await asyncio.wait_for(ctx.elicit(
                    prompt,
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

    @mcp.tool()
    def inspect_document() -> DocumentRevision:
        """Return the authorized filename, UTF-8 byte count and current SHA-256 revision."""
        data = read_document(document_path)
        return DocumentRevision(document=filename, bytes=len(data), revision=digest(data))

    @mcp.tool()
    def read_text(document: str, revision: str, offset: int = 0, limit: int = 4096) -> DocumentPage:
        """Read a revision in Unicode code points. Follow next_offset until it is null."""
        data = checked_document(document, revision)
        text = data.decode("utf-8")
        if not 0 <= offset <= len(text) or not 1 <= limit <= 8192:
            raise ValueError("Expected a valid character offset and a limit from 1 to 8192")
        end = min(len(text), offset + limit)
        return DocumentPage(document=filename, revision=revision, bytes=len(data),
                            text=text[offset:end], next_offset=end if end < len(text) else None)

    @mcp.tool()
    async def append_line(document: str, revision: str, line: str, ctx: Context,
                          editor: Literal["direct", "gtk", "qt"] = "direct", review: bool = False) -> DocumentRevision:
        """Append directly by default. Select gtk or qt for UI work, or review to confirm the save."""
        original = checked_document(document, revision)
        expected = append_bytes(original, line)
        if editor == "direct":
            profile = "agent-run"
            args = edit_args(revision, [(len(original), 0, expected[len(original):].decode())], expected)
        else:
            profile = "agent-gui-run"
            args = ["/usr/bin/python3", "-I", "-c", worker, editors[editor], editor, filename, revision, line]
        return await publish(profile, args, ctx, review, expected,
                             f"Save the staged {editor} edit to {filename}? Appended line: {line}")

    def replacement(data, old, new):
        before, after = old.encode(), new.encode()
        if not before or max(len(before), len(after)) > 8192 or b"\0" in after:
            raise ValueError("Expected a nonempty search and UTF-8 passages up to 8192 bytes")
        start = data.find(before)
        if start < 0 or data.find(before, start + 1) >= 0:
            raise ValueError("Expected exactly one matching passage")
        expected = data[:start] + after + data[start + len(before):]
        if len(expected) > MAX_BYTES:
            raise ValueError("Result exceeds 4 MiB")
        return expected, (start, len(before), new)

    @mcp.tool()
    async def replace_text(document: str, revision: str, old: str, new: str, ctx: Context,
                           review: bool = False) -> DocumentRevision:
        """Replace one exact, unique passage. Use an empty replacement to delete it."""
        data = checked_document(document, revision)
        expected, edit = replacement(data, old, new)
        args = edit_args(revision, [edit], expected)
        return await publish("agent-run", args, ctx, review, expected,
                             f"Save this replacement in {filename}? Before: {old} After: {new}")

    @mcp.tool()
    async def edit_document(document: str, revision: str, edits: list[AppendLine | ReplaceText],
                            ctx: Context, review: bool = False) -> DocumentRevision:
        """Apply 1-32 ordered edits to one revision and publish all changes together."""
        if not 1 <= len(edits) <= 32:
            raise ValueError("Expected between 1 and 32 edits")
        expected = checked_document(document, revision)
        ranges = []
        descriptions = []
        for index, operation in enumerate(edits, 1):
            try:
                if isinstance(operation, AppendLine):
                    start = len(expected)
                    expected = append_bytes(expected, operation.line)
                    edit = (start, 0, expected[start:].decode())
                    description = f"Append {operation.line!r}"
                else:
                    expected, edit = replacement(expected, operation.old, operation.new)
                    description = f"Replace {operation.old!r} with {operation.new!r}"
            except ValueError as error:
                raise ValueError(f"Edit {index}: {error}") from error
            ranges.append(edit)
            descriptions.append(f"{index}. {description}")
        prompt = f"Save these changes to {filename}?" + "\n" + "\n".join(descriptions)
        return await publish("agent-run", edit_args(revision, ranges, expected), ctx, review,
                             expected, prompt)

    return mcp


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aios", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--document", required=True)
    args = parser.parse_args()
    create_server(args.aios.resolve(strict=True), args.workspace.resolve(strict=True),
                  args.document).run(transport="stdio")

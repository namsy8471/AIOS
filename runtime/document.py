"""Encoding and capability checks shared by the broker and isolated worker."""
import hashlib
import os
import stat
from pathlib import Path

MAX_BYTES = 4 * 1024 * 1024


def read_document(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Expected a regular document with one directory entry")
        data = file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES or b"\0" in data:
        raise ValueError("Expected a UTF-8 text document of at most 4 MiB")
    data.decode("utf-8")
    return data


def digest(data):
    return hashlib.sha256(data).hexdigest()


def append_bytes(data, line):
    if not line or any(c in line for c in "\r\n\0") or len(line.encode()) > 8192:
        raise ValueError("Expected one nonempty line of at most 8192 UTF-8 bytes")
    separator = b""
    if data and not data.endswith((b"\n", b"\r")):
        separator = b"\r\n" if b"\r\n" in data else b"\n"
    result = data + separator + line.encode()
    if len(result) > MAX_BYTES:
        raise ValueError("Result exceeds 4 MiB")
    return result

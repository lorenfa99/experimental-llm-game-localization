from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True)
class Document:
    path: Path
    raw: bytes
    text: str
    encoding: str
    bom: str
    bom_bytes: bytes
    newline: str
    final_newline: bool
    lines: tuple[str, ...]


def _decode(data: bytes) -> tuple[str, str, bytes, str]:
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8", "UTF8", b"\xef\xbb\xbf", data[3:].decode("utf-8")
    if data.startswith(b"\xff\xfe"):
        return "utf-16-le", "UTF16LE", b"\xff\xfe", data[2:].decode("utf-16-le")
    if data.startswith(b"\xfe\xff"):
        return "utf-16-be", "UTF16BE", b"\xfe\xff", data[2:].decode("utf-16-be")
    try:
        return "utf-8", "NONE", b"", data.decode("utf-8")
    except UnicodeDecodeError:
        return "cp1252", "NONE", b"", data.decode("cp1252")


def _newline_metadata(text: str) -> tuple[str, bool]:
    crlf = text.count("\r\n")
    lf = text.count("\n")
    cr = text.count("\r")
    if crlf and lf == crlf and cr == crlf:
        style = "CRLF"
    elif lf and not crlf and not cr:
        style = "LF"
    elif cr and not lf:
        style = "CR"
    elif not lf and not cr:
        style = "NONE"
    else:
        style = "MIXED"
    return style, text.endswith(("\r", "\n"))


def _physical_lines(text: str, final_newline: bool) -> tuple[str, ...]:
    if not text:
        return ()
    parts = re.split(r"\r\n|\n|\r", text)
    if final_newline and parts and parts[-1] == "":
        parts.pop()
    return tuple(parts)


def read_document(path: str | Path) -> Document:
    resolved = Path(path).resolve()
    data = resolved.read_bytes()
    encoding, bom, bom_bytes, text = _decode(data)
    newline, final = _newline_metadata(text)
    return Document(
        path=resolved,
        raw=data,
        text=text,
        encoding=encoding,
        bom=bom,
        bom_bytes=bom_bytes,
        newline=newline,
        final_newline=final,
        lines=_physical_lines(text, final),
    )


def encode_like(lines: list[str] | tuple[str, ...], template: Document) -> bytes:
    newline = {"CRLF": "\r\n", "LF": "\n", "CR": "\r", "NONE": ""}.get(template.newline)
    if newline is None or (template.newline == "NONE" and len(lines) > 1):
        raise ValueError(f"Cannot write ambiguous newline style {template.newline!r}")
    text = newline.join(lines)
    if template.final_newline:
        text += newline
    return template.bom_bytes + text.encode(template.encoding)


def write_like(path: str | Path, lines: list[str] | tuple[str, ...], template: Document) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(encode_like(lines, template))


def file_sha256(path: str | Path) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()

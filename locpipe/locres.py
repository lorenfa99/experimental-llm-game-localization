"""Bounded UE .locres v0-v3 reader and metadata-preserving writer.

Identity is (namespace, key), NEVER source-language text or the UE source CRC. Existing
namespace/key hashes and source CRCs are preserved verbatim; no CityHash dependency.
Format reference: akintos/UnrealLocres, LocresLib/LocresFile.cs (see THIRD-PARTY.md).
"""
from __future__ import annotations

import io
import struct
from collections import Counter, OrderedDict
from dataclasses import dataclass, replace
from pathlib import Path

from .config import HarnessError

MAGIC = bytes.fromhex("0e147475674a03fc4a15909dc3377f1b")
MAX_COUNT = 2_000_000


class Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.stream = io.BytesIO(data)

    def take(self, n):
        if n < 0 or n > len(self.data):
            raise HarnessError("Invalid locres length")
        b = self.stream.read(n)
        if len(b) != n:
            raise HarnessError("Truncated locres")
        return b

    def num(self, fmt):
        return struct.unpack("<" + fmt, self.take(struct.calcsize("<" + fmt)))[0]

    def count(self):
        n = self.num("i")
        if not 0 <= n <= MAX_COUNT:
            raise HarnessError(f"Invalid locres count: {n}")
        return n

    def string(self):
        n = self.num("i")
        if not n:
            return ""
        b = self.take(abs(n) * (2 if n < 0 else 1))
        null = b"\0\0" if n < 0 else b"\0"
        if not b.endswith(null):
            raise HarnessError("Unterminated FString")
        try:
            return b[:-len(null)].decode("utf-16-le" if n < 0 else "utf-8")
        except UnicodeDecodeError as e:
            raise HarnessError(f"Invalid FString encoding: {e}") from e


def fstring(text: str) -> bytes:
    if "\0" in text:
        raise HarnessError("NUL is forbidden in a localized string")
    if text.isascii():
        data = text.encode("ascii") + b"\0"
        return struct.pack("<i", len(data)) + data
    data = text.encode("utf-16-le") + b"\0\0"
    return struct.pack("<i", -(len(data) // 2)) + data


@dataclass(frozen=True)
class Entry:
    namespace: str
    key: str
    source_hash: int
    text: str
    namespace_hash: int = 0
    key_hash: int = 0

    @property
    def identity(self):
        return self.namespace, self.key


@dataclass
class Locres:
    version: int
    entries: list[Entry]
    original: bytes | None = None

    @classmethod
    def load(cls, path: Path):
        return cls.parse(path.read_bytes())

    @classmethod
    def parse(cls, data: bytes):
        r = Reader(data)
        modern = data.startswith(MAGIC)
        if modern:
            r.take(16)
        version = r.num("B") if modern else 0
        if version not in (0, 1, 2, 3):
            raise HarnessError(f"Unsupported locres version {version}; refuse to guess")
        strings = []
        table_offset = None
        if version >= 1:
            table_offset = r.num("q")
            if not r.stream.tell() <= table_offset <= len(data) - 4:
                raise HarnessError("Locres string table offset outside file")
            pos = r.stream.tell()
            r.stream.seek(table_offset)
            for _ in range(r.count()):
                strings.append(r.string())
                if version >= 2:
                    r.count()  # reference count
            if r.stream.tell() != len(data):
                raise HarnessError("Unexpected trailing locres bytes")
            r.stream.seek(pos)
        expected = r.count() if version >= 2 else None
        entries = []
        seen = set()
        for _ in range(r.count()):
            ns_hash = r.num("I") if version >= 2 else 0
            namespace = r.string()
            for _ in range(r.count()):
                key_hash = r.num("I") if version >= 2 else 0
                key = r.string()
                source_hash = r.num("I")
                if version >= 1:
                    index = r.num("i")
                    if not 0 <= index < len(strings):
                        raise HarnessError("Locres string table index outside array")
                    text = strings[index]
                else:
                    text = r.string()
                if (namespace, key) in seen:
                    raise HarnessError(f"Duplicate locres identity: {namespace!r}/{key!r}")
                seen.add((namespace, key))
                entries.append(Entry(namespace, key, source_hash, text, ns_hash, key_hash))
        if expected is not None and expected != len(entries):
            raise HarnessError("Locres entry count does not match body")
        if r.stream.tell() != (table_offset if table_offset is not None else len(data)):
            raise HarnessError("Unexpected bytes between locres index and strings")
        return cls(version, entries, data)

    def encode(self, replacements: dict[tuple[str, str], str] | None = None, *, rebuild=False):
        replacements = replacements or {}
        unknown = replacements.keys() - {e.identity for e in self.entries}
        if unknown:
            raise HarnessError(f"Unknown locres identities: {sorted(unknown)!r}")
        if not replacements and self.original is not None and not rebuild:
            return self.original
        entries = [replace(e, text=replacements.get(e.identity, e.text)) for e in self.entries]
        groups = OrderedDict()
        for e in entries:
            groups.setdefault(e.namespace, []).append(e)
        strings = list(dict.fromkeys(e.text for e in entries))
        indexes = {text: i for i, text in enumerate(strings)}
        refs = Counter(e.text for e in entries)
        out = io.BytesIO()
        if self.version:
            out.write(MAGIC + bytes([self.version]) + b"\0" * 8)
        if self.version >= 2:
            out.write(struct.pack("<i", len(entries)))
        out.write(struct.pack("<i", len(groups)))
        for ns, values in groups.items():
            if self.version >= 2:
                out.write(struct.pack("<I", values[0].namespace_hash))
            out.write(fstring(ns) + struct.pack("<i", len(values)))
            for e in values:
                if self.version >= 2:
                    out.write(struct.pack("<I", e.key_hash))
                out.write(fstring(e.key) + struct.pack("<I", e.source_hash))
                out.write(struct.pack("<i", indexes[e.text]) if self.version else fstring(e.text))
        if self.version:
            table_offset = out.tell()
            out.write(struct.pack("<i", len(strings)))
            for s in strings:
                out.write(fstring(s))
                if self.version >= 2:
                    out.write(struct.pack("<i", refs[s]))
            result = bytearray(out.getvalue())
            struct.pack_into("<q", result, 17, table_offset)
            return bytes(result)
        return out.getvalue()

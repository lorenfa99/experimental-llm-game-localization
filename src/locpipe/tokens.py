from __future__ import annotations

import re
from functools import lru_cache


NUMBER_RE = re.compile(r"(?<![\w])\d+(?:[.,]\d+)*(?:st|nd|rd|th|°|º|ª)?%?", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(
    r"\{[^{}\r\n]+\}|(?<!%)%[a-z](?!%)|\\[nrt]|"
    r"</[A-Za-z][A-Za-z0-9_-]*>|<[A-Za-z][A-Za-z0-9_-]*=[^<>\r\n]+>"
)


@lru_cache(maxsize=32)
def _marker_re(markers: tuple[str, ...]) -> re.Pattern[str]:
    ordered = sorted(markers, key=lambda value: (-len(value), value))
    return re.compile("|".join(re.escape(value) for value in ordered))


def marker_sequence(text: str, markers: tuple[str, ...]) -> list[str]:
    return [match.group() for match in _marker_re(markers).finditer(text)]


def number_sequence(text: str) -> list[str]:
    tokens: list[str] = []
    for match in NUMBER_RE.finditer(text):
        token = match.group()
        percent = token.endswith("%")
        if percent:
            token = token[:-1]
        token = re.sub(r"(?:st|nd|rd|th|°|º|ª)$", "", token, flags=re.IGNORECASE)
        tokens.append(token + ("%" if percent else ""))
    return tokens


def placeholder_sequence(text: str) -> list[str]:
    return [match.group() for match in PLACEHOLDER_RE.finditer(text)]

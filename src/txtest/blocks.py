"""Select regions delimited by standalone [type value] and [endtype] markers."""

from __future__ import annotations

import re
from dataclasses import dataclass


_KIND = r"[A-Za-z][A-Za-z0-9_-]*"
_VALUE = r"[^\s\[\]:]+"
_SELECTOR = re.compile(rf"({_KIND}):({_VALUE})")
_MARKER = re.compile(rf" {{0,3}}\[({_KIND})(?:[ \t]+([^\]]*))?\][ \t]*")
_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
_HTML_LITERAL = re.compile(r" {0,3}(?:<!--|<(pre|code|script|style|textarea)\b)", re.IGNORECASE)


@dataclass(frozen=True)
class _Block:
    kind: str
    line: int
    visible: bool


def filter_blocks(text: str, selectors: tuple[str, ...]) -> str:
    """Keep shared text and selected block bodies in their original order."""
    if not selectors:
        return text

    selected: dict[str, set[str]] = {}
    for selector in selectors:
        match = _SELECTOR.fullmatch(selector)
        if match is None:
            raise ValueError(f"Invalid --block value {selector!r}. Use TYPE:VALUE, such as language:cpp.")
        kind, value = match.groups()
        selected.setdefault(kind, set()).add(value)

    output: list[str] = []
    blocks: list[_Block] = []
    fence = ""
    html_end = ""
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        raw = line.rstrip("\r\n")
        visible = not blocks or blocks[-1].visible

        if html_end:
            if html_end in raw.lower():
                html_end = ""
        elif fence:
            closing_fence = _FENCE.fullmatch(raw)
            if closing_fence and closing_fence[1].startswith(fence) and not closing_fence[2].strip():
                fence = ""
        elif opening := _FENCE.fullmatch(raw):
            delimiter, info = opening.groups()
            if delimiter[0] == "~" or "`" not in info:
                fence = delimiter
        elif literal := _HTML_LITERAL.match(raw):
            tag = literal[1]
            closing = f"</{tag.lower()}>" if tag else "-->"
            if closing not in raw.lower():
                html_end = closing
        elif marker := _MARKER.fullmatch(raw):
            kind, value = marker.groups()
            if value is None and kind.startswith("end") and kind[3:] in selected:
                if not blocks or blocks[-1].kind != kind[3:]:
                    raise ValueError(f"Line {number}: unexpected [{kind}].")
                blocks.pop()
                continue
            if kind in selected:
                value = (value or "").strip()
                if not re.fullmatch(_VALUE, value):
                    raise ValueError(f"Line {number}: use [{kind} VALUE] with a single value.")
                blocks.append(_Block(kind, number, visible and value in selected[kind]))
                continue

        if visible:
            output.append(line)

    if blocks:
        block = blocks[-1]
        raise ValueError(f"Line {block.line}: missing [end{block.kind}].")
    return "".join(output)

import re
from dataclasses import dataclass
from typing import List


@dataclass
class Chunk:
    text: str
    start_line: int
    end_line: int
    index: int


_PY_UNIT_RE = re.compile(r"^(def |class |@)")
_GO_UNIT_RE = re.compile(r"^(func |type |package )")
_MD_UNIT_RE = re.compile(r"^#{1,6} ")

_EXTENSION_SPLITTERS = {
    ".py": "structural",
    ".go": "structural_go",
    ".md": "headers",
}


def _split_units(content: str, extension: str) -> List[str]:
    """Splits content into structural units (functions/classes, headers, or
    blank-line-separated paragraphs), preserving exact text — units
    concatenated back together reconstruct the original content."""
    mode = _EXTENSION_SPLITTERS.get(extension, "paragraphs")
    lines = content.splitlines(keepends=True)

    if not lines:
        return []

    if mode == "structural":
        boundary_re = _PY_UNIT_RE
    elif mode == "structural_go":
        boundary_re = _GO_UNIT_RE
    elif mode == "headers":
        boundary_re = _MD_UNIT_RE
    else:
        boundary_re = None

    if boundary_re is not None:
        units: List[str] = []
        current: List[str] = []
        for line in lines:
            if boundary_re.match(line) and current:
                units.append("".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            units.append("".join(current))
        return units

    # paragraphs: split on blank lines, keep the blank line(s) attached to
    # the paragraph that precedes them so concatenation is lossless.
    units = []
    current = []
    for line in lines:
        current.append(line)
        if line.strip() == "":
            units.append("".join(current))
            current = []
    if current:
        units.append("".join(current))
    return units


def _char_window_split(text: str, max_chars: int) -> List[str]:
    """Final fallback: splits arbitrary text (e.g. a single huge line) into
    fixed-size character windows. Always makes progress regardless of
    line structure."""
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)] or [text]


def _line_window_split(unit: str, max_chars: int) -> List[str]:
    """Splits an oversized unit by packing consecutive lines up to max_chars.
    Falls back to character windows for any single line that alone exceeds
    max_chars (e.g. a minified file with one giant line)."""
    lines = unit.splitlines(keepends=True)
    windows: List[str] = []
    current = ""
    for line in lines:
        if len(line) > max_chars:
            if current:
                windows.append(current)
                current = ""
            windows.extend(_char_window_split(line, max_chars))
            continue
        if current and len(current) + len(line) > max_chars:
            windows.append(current)
            current = line
        else:
            current += line
    if current:
        windows.append(current)
    return windows or _char_window_split(unit, max_chars)


def chunk_file(path: str, content: str, max_chars: int = 3000) -> List[Chunk]:
    """
    Splits file content into chunks bounded by max_chars, preferring
    structural boundaries (functions/classes for .py, func/type/package for
    .go, headers for .md, blank-line paragraphs otherwise) over blind windows.

    Packs consecutive units together while they fit under max_chars. A
    single unit that alone exceeds max_chars falls back to line windows,
    and a single line that alone exceeds max_chars falls back to character
    windows — so no chunk ever exceeds max_chars, regardless of input.
    """
    if not content:
        return []

    extension = path[path.rfind("."):] if "." in path else ""
    units = _split_units(content, extension)

    # Expand any oversized unit into sub-windows before packing, so packing
    # only ever deals with pieces that individually fit.
    pieces: List[str] = []
    for unit in units:
        if len(unit) > max_chars:
            pieces.extend(_line_window_split(unit, max_chars))
        else:
            pieces.append(unit)

    chunks: List[Chunk] = []
    current_text = ""
    current_start_line = 1
    line_cursor = 1
    chunk_index = 0

    def flush(end_line: int):
        nonlocal current_text, current_start_line, chunk_index
        if current_text:
            chunks.append(Chunk(
                text=current_text,
                start_line=current_start_line,
                end_line=end_line,
                index=chunk_index,
            ))
            chunk_index += 1
        current_text = ""

    for piece in pieces:
        piece_lines = piece.count("\n") + (1 if piece and not piece.endswith("\n") else 0)
        piece_end_line = line_cursor + max(piece_lines - 1, 0)

        if current_text and len(current_text) + len(piece) > max_chars:
            flush(line_cursor - 1)
            current_start_line = line_cursor

        if not current_text:
            current_start_line = line_cursor

        current_text += piece
        line_cursor = piece_end_line + 1

    flush(line_cursor - 1)

    return chunks

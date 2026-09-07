"""
Chunking strategies.

`chunk_fixed` is the notebook's original character-window splitter, kept
byte-for-byte so the ported pipeline still matches `untitled13.py`. The other
two strategies were added for the Week 3 retrieval evaluation:

- fixed      character window over whitespace-collapsed text (notebook default)
- recursive  split on paragraph -> line -> sentence -> word boundaries
- heading    markdown section-aware; keeps tables intact and prefixes every
             chunk with its heading path

Size semantics differ by strategy and this matters when reading eval results:
`fixed` treats `chunk_size` as a hard cap, while `recursive` and `heading`
treat it as a target and may exceed it by up to `overlap` characters (overlap
is applied after packing) or by the length of one indivisible table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List

RECURSIVE_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


@dataclass
class TextPiece:
    """One chunk of text plus the document section it came from."""

    text: str
    section: str = ""
    extras: dict = field(default_factory=dict)


def chunk_fixed_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """The notebook's splitter. Collapses all whitespace, then slides a window."""
    text = " ".join(text.split())
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
        if start <= 0:
            break
    return chunks


def chunk_fixed(text: str, chunk_size: int = 500, overlap: int = 50) -> List[TextPiece]:
    return [TextPiece(text=piece) for piece in chunk_fixed_text(text, chunk_size, overlap)]


def _atoms(text: str, separators: List[str]) -> List[str]:
    """Split on the first separator that is present, keeping the separator attached."""
    if not separators:
        return list(text)
    sep = separators[0]
    if sep == "":
        return list(text)
    if sep not in text:
        return _atoms(text, separators[1:])
    parts = text.split(sep)
    out = []
    for index, part in enumerate(parts):
        piece = part + (sep if index < len(parts) - 1 else "")
        if piece:
            out.append(piece)
    return out


def _pack(atoms: List[str], chunk_size: int, separators: List[str]) -> List[str]:
    """Greedily fill chunks up to chunk_size, recursing into oversized atoms."""
    chunks: List[str] = []
    current = ""
    for atom in atoms:
        if len(atom) > chunk_size:
            if current.strip():
                chunks.append(current)
            current = ""
            chunks.extend(_pack(_atoms(atom, separators[1:] or [""]), chunk_size, separators[1:] or [""]))
            continue
        if len(current) + len(atom) <= chunk_size:
            current += atom
        else:
            if current.strip():
                chunks.append(current)
            current = atom
    if current.strip():
        chunks.append(current)
    return chunks


def _apply_overlap(chunks: List[str], overlap: int) -> List[str]:
    """Prepend the tail of each chunk to the next one."""
    if overlap <= 0 or len(chunks) < 2:
        return chunks
    out = [chunks[0]]
    for previous, current in zip(chunks, chunks[1:]):
        out.append(previous[-overlap:] + current)
    return out


def chunk_recursive(text: str, chunk_size: int = 500, overlap: int = 50) -> List[TextPiece]:
    text = text.strip()
    if not text:
        return []
    packed = _pack(_atoms(text, RECURSIVE_SEPARATORS), chunk_size, RECURSIVE_SEPARATORS)
    return [TextPiece(text=piece.strip()) for piece in _apply_overlap(packed, overlap) if piece.strip()]


def _is_table_line(line: str) -> bool:
    return line.strip().startswith("|")


def _blocks(body: str) -> List[str]:
    """Paragraph-level blocks, with each contiguous table treated as one atom."""
    out: List[str] = []
    buffer: List[str] = []
    table: List[str] = []

    def flush_buffer():
        if buffer:
            joined = "\n".join(buffer).strip()
            if joined:
                out.append(joined)
            buffer.clear()

    def flush_table():
        if table:
            out.append("\n".join(table).strip())
            table.clear()

    for line in body.splitlines():
        if _is_table_line(line):
            flush_buffer()
            table.append(line)
            continue
        flush_table()
        if not line.strip():
            flush_buffer()
        else:
            buffer.append(line)
    flush_table()
    flush_buffer()
    return out


def chunk_by_heading(text: str, chunk_size: int = 500, overlap: int = 50) -> List[TextPiece]:
    """
    Section-aware markdown chunking.

    Sections are cut at `#` headings. A section that fits becomes one chunk. A
    section that does not is packed from paragraph blocks, where a markdown
    table is one indivisible block, so a table row is never separated from its
    header row. Every chunk is prefixed with its heading path so the embedding
    carries the section context even when the chunk itself is a bare table.
    """
    lines = text.splitlines()
    sections: List[tuple[str, List[str]]] = []
    path: List[str] = []
    current_heading = ""
    current_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            if current_lines or current_heading:
                sections.append((current_heading, current_lines))
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped.lstrip("#").strip()
            path = path[: level - 1]
            path.append(title)
            current_heading = " > ".join(path)
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines or current_heading:
        sections.append((current_heading, current_lines))

    pieces: List[TextPiece] = []
    for heading, section_lines in sections:
        body = "\n".join(section_lines).strip()
        if not body:
            continue
        prefix = f"{heading}\n" if heading else ""
        budget = max(chunk_size - len(prefix), 100)

        if len(body) <= budget:
            pieces.append(TextPiece(text=prefix + body, section=heading))
            continue

        packed: List[str] = []
        current = ""
        for block in _blocks(body):
            if len(block) > budget:
                if current.strip():
                    packed.append(current.strip())
                    current = ""
                sub = _pack(_atoms(block, RECURSIVE_SEPARATORS), budget, RECURSIVE_SEPARATORS)
                packed.extend(piece.strip() for piece in sub if piece.strip())
                continue
            candidate = f"{current}\n\n{block}" if current else block
            if len(candidate) <= budget:
                current = candidate
            else:
                if current.strip():
                    packed.append(current.strip())
                current = block
        if current.strip():
            packed.append(current.strip())

        for piece in _apply_overlap(packed, overlap):
            pieces.append(TextPiece(text=prefix + piece, section=heading))

    if not pieces:
        return chunk_recursive(text, chunk_size, overlap)
    return pieces


STRATEGIES: dict[str, Callable[[str, int, int], List[TextPiece]]] = {
    "fixed": chunk_fixed,
    "recursive": chunk_recursive,
    "heading": chunk_by_heading,
}

DEFAULT_STRATEGY = "fixed"


def chunk_document(
    text: str,
    strategy: str = DEFAULT_STRATEGY,
    chunk_size: int = 500,
    overlap: int = 50,
) -> List[TextPiece]:
    try:
        splitter = STRATEGIES[strategy]
    except KeyError:
        raise ValueError(
            f"Unknown chunking strategy '{strategy}'. Available: {', '.join(sorted(STRATEGIES))}"
        ) from None
    return splitter(text, chunk_size, overlap)

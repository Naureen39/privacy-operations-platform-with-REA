"""Split documents into passages by heading and paragraph, keeping section and page metadata.

A chunk never crosses a heading. Paragraphs under one heading are packed together up to
`max_chars`; a paragraph that is longer than that is split at sentence boundaries. A small
trailing piece is merged back so no passage is a lone fragment.
"""

import io
import json
import re
from dataclasses import dataclass

DEFAULT_MAX_CHARS = 900
MIN_CHARS = 120
TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
HTML_SUFFIXES = {".html", ".htm"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | HTML_SUFFIXES | {".pdf", ".json"}

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_NUMBERED_HEADING = re.compile(r"^(\d+(\.\d+)*\.?)\s+[A-Z][^.!?]{1,80}$")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")
_ITALIC_NOTE = re.compile(r"_[^_].*[^_]_")


@dataclass(frozen=True)
class Chunk:
    index: int
    heading: str | None
    page: int | None
    text: str

    @property
    def token_count(self) -> int:
        return max(1, len(self.text.split()))

    @property
    def embedding_text(self) -> str:
        return f"{self.heading}: {self.text}" if self.heading else self.text


@dataclass(frozen=True)
class Block:
    """One paragraph (or list) with the heading it sits under and the page it came from."""

    heading: str | None
    page: int | None
    text: str


def chunk_blocks(blocks: list[Block], max_chars: int = DEFAULT_MAX_CHARS) -> list[Chunk]:
    chunks: list[Chunk] = []
    group: list[Block] = []

    def flush() -> None:
        if not group:
            return
        for text in _pack([b.text for b in group], max_chars):
            chunks.append(Chunk(len(chunks), group[0].heading, group[0].page, text))
        group.clear()

    for block in blocks:
        if group and block.heading != group[0].heading:
            flush()
        group.append(block)
    flush()
    return chunks


def _pack(paragraphs: list[str], max_chars: int) -> list[str]:
    pieces: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            pieces.append(paragraph)
        else:
            pieces.extend(_split_sentences(paragraph, max_chars))
    packed: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) + 2 > max_chars:
            packed.append(current)
            current = piece
        else:
            current = f"{current}\n\n{piece}" if current else piece
    if current:
        small = len(current) < MIN_CHARS
        if packed and small and len(packed[-1]) + len(current) + 2 <= max_chars * 1.3:
            packed[-1] = f"{packed[-1]}\n\n{current}"
        else:
            packed.append(current)
    return packed


def _split_sentences(text: str, max_chars: int) -> list[str]:
    out: list[str] = []
    current = ""
    for sentence in _SENTENCE.split(text):
        if len(sentence) > max_chars:  # no sentence boundary to use: cut at a space
            words: list[str] = []
            for word in sentence.split():
                if sum(len(w) + 1 for w in words) + len(word) > max_chars:
                    if current:
                        out.append(current)
                        current = ""
                    out.append(" ".join(words))
                    words = []
                words.append(word)
            sentence = " ".join(words)
        if current and len(current) + len(sentence) + 1 > max_chars:
            out.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}" if current else sentence
    if current:
        out.append(current)
    return out


def _paragraphs(lines: list[str]) -> list[str]:
    """Blank lines separate paragraphs; consecutive list items stay together."""
    result: list[str] = []
    current: list[str] = []
    for line in lines:
        if line.strip():
            current.append(line.strip())
        elif current:
            result.append("\n".join(current))
            current = []
    if current:
        result.append("\n".join(current))
    return result


def markdown_blocks(text: str) -> tuple[str | None, list[Block]]:
    """Return the document title (the first level 1 heading) and the blocks under each heading.
    Nested headings are kept as a path, for example "Retention > Backups"."""
    title: str | None = None
    path: list[tuple[int, str]] = []
    blocks: list[Block] = []
    buffer: list[str] = []

    def heading() -> str | None:
        return " > ".join(h for _, h in path) or None

    def flush() -> None:
        for paragraph in _paragraphs(buffer):
            if _ITALIC_NOTE.fullmatch(paragraph):  # provenance note, not content
                continue
            blocks.append(Block(heading(), None, paragraph))
        buffer.clear()

    in_code = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
        match = None if in_code else _HEADING.match(line)
        if match:
            flush()
            level, name = len(match.group(1)), match.group(2).strip()
            if level == 1 and title is None:
                title = name
                continue
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, name))
        else:
            buffer.append(line)
    flush()
    return title, blocks


def _flush_pdf(buffer: list[str], blocks: list[Block], heading: str | None, page: int) -> None:
    blocks.extend(Block(heading, page, p) for p in _paragraphs(buffer))
    buffer.clear()


def pdf_blocks(content: bytes) -> tuple[str | None, list[Block]]:
    import pdfplumber

    blocks: list[Block] = []
    heading: str | None = None
    title: str | None = None
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            buffer: list[str] = []
            for line in (page.extract_text() or "").splitlines():
                stripped = line.strip()
                if stripped and _NUMBERED_HEADING.match(stripped):
                    _flush_pdf(buffer, blocks, heading, number)
                    heading = stripped
                else:
                    if stripped and title is None:
                        title = stripped
                    buffer.append(stripped)
            _flush_pdf(buffer, blocks, heading, number)
    return title, blocks


def html_blocks(content: str) -> tuple[str | None, list[Block]]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else None
    blocks: list[Block] = []
    path: list[tuple[int, str]] = []
    root = soup.body or soup
    for element in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre"]):
        text = " ".join(element.get_text(" ", strip=True).split())
        if not text:
            continue
        if len(element.name) == 2 and element.name.startswith("h"):
            level = int(element.name[1])
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, text))
        elif element.name == "li" and element.find_parent("li") is not None:
            continue  # already part of the parent item
        else:
            blocks.append(Block(" > ".join(h for _, h in path) or None, None, text))
    return title, blocks


def questionnaire_blocks(content: str) -> tuple[str | None, list[Block]]:
    data = json.loads(content)
    answers = data.get("answers", data) if isinstance(data, dict) else {}
    blocks: list[Block] = []
    for key, value in answers.items():
        label = key.replace("_", " ")
        blocks.append(Block(label, None, f"{label}: {_flatten(value)}"))
    return "Questionnaire answers", blocks


def _flatten(value: object) -> str:
    if isinstance(value, dict):
        return "; ".join(f"{k.replace('_', ' ')} {_flatten(v)}" for k, v in value.items())
    if isinstance(value, list):
        return ", ".join(_flatten(v) for v in value) or "none"
    if value in (None, ""):
        return "not answered"
    return str(value)


class UnreadableDocumentError(ValueError):
    """The content could not be turned into text."""


def extract_blocks(filename: str, content: bytes) -> tuple[str | None, list[Block]]:
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnreadableDocumentError(f"Unsupported file type: {suffix or 'none'}")
    try:
        if suffix == ".pdf":
            if not content.startswith(b"%PDF-"):
                raise UnreadableDocumentError("The file is not a PDF")
            return pdf_blocks(content)
        text = content.decode("utf-8-sig")
        if suffix == ".json":
            return questionnaire_blocks(text)
        if suffix in HTML_SUFFIXES:
            return html_blocks(text)
        return markdown_blocks(text)
    except UnreadableDocumentError:
        raise
    except Exception as exc:
        raise UnreadableDocumentError(
            f"The document could not be read ({type(exc).__name__})"
        ) from exc


def chunk_document(
    filename: str, content: bytes, max_chars: int = DEFAULT_MAX_CHARS
) -> tuple[str | None, list[Chunk]]:
    title, blocks = extract_blocks(filename, content)
    return title, chunk_blocks(blocks, max_chars)

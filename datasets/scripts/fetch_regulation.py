"""Download the official GDPR text and split it into article and paragraph chunks.

    uv run python datasets/scripts/fetch_regulation.py            # download
    uv run python datasets/scripts/fetch_regulation.py --from-file path/to/saved.xhtml

Source: Regulation (EU) 2016/679, Official Journal L 119, 4.5.2016. EUR-Lex itself answers
automated clients with a bot challenge, so the script reads the same official XHTML
manifestation from the Publications Office resolver, which serves EUR-Lex content.

Output: datasets/regulation/gdpr_articles.json. The file records the SHA-256 of the source
document and no download time, so the same source always yields the same output.
"""

import argparse
import re
import sys
import time
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup, Tag

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS_DIR, sha256_text, strip_long_dashes, write_json  # noqa: E402

CELEX = "32016R0679"
SOURCE_URL = f"https://publications.europa.eu/resource/celex/{CELEX}"
ELI_URL = "https://eur-lex.europa.eu/eli/reg/2016/679/oj"
OUTPUT = DATASETS_DIR / "regulation" / "gdpr_articles.json"
MAX_CHUNK_CHARS = 1500
MANDATORY_ARTICLES = {5, 6, 9, 12, 13, 15, 28, 30, 35}
CHAPTER_V = range(44, 51)


def download() -> str:
    request = urllib.request.Request(  # noqa: S310  (fixed https URL)
        SOURCE_URL,
        headers={"Accept": "application/xhtml+xml", "Accept-Language": "en"},
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310
                return response.read().decode("utf-8")
        except OSError as exc:
            last_error = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"could not download {SOURCE_URL}: {last_error}")


def clean(text: str) -> str:
    text = text.replace("\xa0", " ")
    for fancy, plain in (("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"')):
        text = text.replace(fancy, plain)
    return strip_long_dashes(" ".join(text.split()))


def split_long(text: str) -> list[str]:
    """Split text longer than MAX_CHUNK_CHARS at list item or sentence boundaries."""
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    pieces = re.split(r"(?<=[;.:]) (?=\(?[a-z0-9]{1,3}\)|[A-Z])", text)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) + 1 > MAX_CHUNK_CHARS:
            chunks.append(current)
            current = piece
        else:
            current = f"{current} {piece}".strip()
    if current:
        chunks.append(current)
    return chunks


def chapter_of(node: Tag) -> str | None:
    chapter = node.find_parent("div", id=re.compile(r"^cpt_[IVX]+$"))
    if not isinstance(chapter, Tag):
        return None
    number = chapter.find("p", class_="oj-ti-section-1")
    title = chapter.find("div", id=re.compile(r"^cpt_[IVX]+\.tit_1$"))
    parts = [
        clean(number.get_text(" ")) if number else "",
        clean(title.get_text(" ")) if title else "",
    ]
    return " - ".join(p for p in parts if p) or None


def parse(document: str) -> list[dict[str, object]]:
    soup = BeautifulSoup(document, "html.parser")
    chunks: list[dict[str, object]] = []
    for article in soup.find_all("div", id=re.compile(r"^art_\d+$")):
        if not isinstance(article, Tag):
            continue
        number = int(str(article["id"]).split("_")[1])
        title_node = article.find("div", id=re.compile(rf"^art_{number}\.tit_1$"))
        title = clean(title_node.get_text(" ")) if title_node else ""
        chapter = chapter_of(article)
        paragraphs = [
            div
            for div in article.find_all("div", id=re.compile(r"^\d{3}\.\d{3}$"))
            if isinstance(div, Tag)
        ]
        if paragraphs:
            items = [
                (str(int(str(d["id"]).split(".")[1])), clean(d.get_text(" "))) for d in paragraphs
            ]
        else:
            body = " ".join(
                clean(p.get_text(" "))
                for p in article.find_all("p")
                if "oj-ti-art" not in (p.get("class") or [])
                and "oj-sti-art" not in (p.get("class") or [])
            )
            items = [("1", body)]
        for paragraph, text in items:
            # Drop the leading "1." that duplicates the paragraph label.
            text = re.sub(r"^\d+\.\s+", "", text)
            if not text:
                continue
            for part, piece in enumerate(split_long(text), start=1):
                chunks.append(
                    {
                        "id": f"gdpr-art{number}-p{paragraph}" + (f"-{part}" if part > 1 else ""),
                        "regulation": "GDPR",
                        "chapter": chapter,
                        "article": number,
                        "paragraph": paragraph,
                        "part": part,
                        "title": title,
                        "text": piece,
                    }
                )
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from-file", type=Path, help="parse a previously saved XHTML file")
    args = parser.parse_args()

    document = args.from_file.read_text(encoding="utf-8") if args.from_file else download()
    chunks = parse(document)

    articles = {int(c["article"]) for c in chunks}  # type: ignore[call-overload]
    required = MANDATORY_ARTICLES | set(CHAPTER_V)
    missing = sorted(required - articles)
    if len(articles) != 99 or missing:
        sys.exit(f"unexpected result: {len(articles)} articles, missing mandatory {missing}")

    write_json(
        OUTPUT,
        {
            "source": {
                "title": "Regulation (EU) 2016/679 (General Data Protection Regulation)",
                "celex": CELEX,
                "eli": ELI_URL,
                "retrieved_from": SOURCE_URL,
                "source_sha256": sha256_text(document),
                "note": "Typographic long dashes in the source are replaced by a spaced hyphen.",
            },
            "articles": len(articles),
            "chunks": chunks,
        },
    )
    print(f"wrote {OUTPUT} ({len(articles)} articles, {len(chunks)} chunks)")


if __name__ == "__main__":
    main()

"""Chunking, query building and rank fusion (no database, no model)."""

import json
import uuid

import pytest

from app.knowledge.chunking import (
    Block,
    UnreadableDocumentError,
    chunk_blocks,
    chunk_document,
    html_blocks,
    markdown_blocks,
)
from app.knowledge.evaluation import GoldQuestion, load_gold, matches
from app.knowledge.retrieval import (
    Passage,
    document_label,
    query_terms,
    reciprocal_rank_fusion,
    regulation_label,
    tsquery_string,
)

POLICY = """# Privacy notice: Shop

_Reference document. Draft for review by a qualified privacy professional. Not legal advice._

## Who we are

Shop is run by Northbridge.

## How long we keep it

Orders are kept for 24 months.

Support tickets are kept for 12 months.

## Security

### Backups

Backups are encrypted.
"""


def test_markdown_chunks_follow_headings_and_never_cross_them() -> None:
    title, chunks = chunk_document("policy.md", POLICY.encode())
    assert title == "Privacy notice: Shop"
    assert [c.heading for c in chunks] == [
        "Who we are",
        "How long we keep it",
        "Security > Backups",
    ]
    assert (
        chunks[1].text
        == "Orders are kept for 24 months.\n\nSupport tickets are kept for 12 months."
    )
    assert [c.index for c in chunks] == [0, 1, 2]
    assert not any("Draft for review" in c.text for c in chunks)  # provenance note is not content


def test_long_sections_are_split_at_sentences_within_the_limit() -> None:
    sentence = "We keep the records of each order for the period the law requires. "
    text = "## Retention\n\n" + sentence * 40
    _, chunks = chunk_document("p.md", text.encode(), max_chars=400)
    assert len(chunks) > 3
    assert all(len(c.text) <= 400 for c in chunks)
    assert all(c.heading == "Retention" for c in chunks)
    assert "".join(c.text.replace(" ", "") for c in chunks) == (sentence * 40).replace(" ", "")


def test_a_small_tail_is_merged_instead_of_left_alone() -> None:
    blocks = [Block("H", None, "a" * 500), Block("H", None, "b" * 350), Block("H", None, "tail.")]
    chunks = chunk_blocks(blocks, max_chars=900)
    assert [len(c.text.split("\n\n")) for c in chunks] == [3]


def test_an_unbroken_word_run_is_still_cut() -> None:
    _, chunks = chunk_document("p.md", ("## H\n\n" + "word " * 500).encode(), max_chars=300)
    assert all(len(c.text) <= 300 for c in chunks) and len(chunks) > 5


def test_heading_inside_code_fence_is_not_a_heading() -> None:
    _, blocks = markdown_blocks("## Real\n\n```\n## not a heading\n```\n")
    assert [b.heading for b in blocks] == ["Real"]


def test_embedding_text_carries_the_heading() -> None:
    _, chunks = chunk_document("policy.md", POLICY.encode())
    assert chunks[0].embedding_text == "Who we are: Shop is run by Northbridge."
    assert chunks[0].token_count == 5


def test_html_headings_and_text_without_scripts() -> None:
    html = (
        "<html><head><title>Privacy</title><script>var secret=1</script></head><body>"
        "<h1>Policy</h1><h2>Cookies</h2><p>We use one session cookie.</p>"
        "<ul><li>First item</li><li>Second item</li></ul></body></html>"
    )
    title, blocks = html_blocks(html)
    assert title == "Privacy"
    assert all("secret" not in b.text for b in blocks)
    assert blocks[0] == Block("Policy > Cookies", None, "We use one session cookie.")
    assert [b.text for b in blocks[1:]] == ["First item", "Second item"]


def test_questionnaire_answers_become_one_passage_each() -> None:
    content = json.dumps(
        {
            "answers": {
                "last_review_date": "2026-03-12",
                "processors_with_agreement": ["Stripe", "Google Fonts"],
                "retention": {"tickets": "12 months"},
                "notes": "",
            }
        }
    )
    _, chunks = chunk_document("questionnaire.json", content.encode())
    by_heading = {c.heading: c.text for c in chunks}
    assert by_heading["last review date"] == "last review date: 2026-03-12"
    assert by_heading["processors with agreement"].endswith("Stripe, Google Fonts")
    assert by_heading["retention"] == "retention: tickets 12 months"
    assert by_heading["notes"].endswith("not answered")


def make_pdf(pages: list[list[str]]) -> bytes:
    """A minimal valid PDF with one page per list of text lines."""
    objects: list[bytes] = []
    page_ids = [4 + 2 * i for i in range(len(pages))]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{i} 0 R" for i in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, lines in enumerate(pages):
        content_id = page_ids[i] + 1
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode()
        )
        ops = ["BT", "/F1 11 Tf", "14 TL", "50 740 Td"]
        for line in lines:
            ops.append(f"({line}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode()
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


def test_pdf_chunks_keep_the_page_and_the_numbered_heading() -> None:
    pdf = make_pdf(
        [
            ["Data processing agreement", "1. Subject matter", "The processor provides payroll."],
            [
                "2. Security",
                "The processor encrypts all data.",
                "3. Sub-processors",
                "None are used.",
            ],
        ]
    )
    title, chunks = chunk_document("agreement.pdf", pdf)
    assert title == "Data processing agreement"
    found = {(c.heading, c.page): c.text for c in chunks}
    assert found[("1. Subject matter", 1)] == "The processor provides payroll."
    assert found[("2. Security", 2)] == "The processor encrypts all data."
    assert found[("3. Sub-processors", 2)] == "None are used."


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("notes.exe", b"MZ"),
        ("noext", b"text"),
        ("fake.pdf", b"not a pdf"),
        ("broken.json", b"{not json"),
        ("binary.md", b"\xff\xfe\x00\x00"),
        ("empty.md", b""),
    ],
)
def test_unreadable_documents_are_rejected_cleanly(filename: str, content: bytes) -> None:
    with pytest.raises(UnreadableDocumentError):
        _, chunks = chunk_document(filename, content)
        if not chunks:
            raise UnreadableDocumentError("no text")


def test_query_terms_drop_stopwords_and_keep_distinct_words() -> None:
    assert query_terms("What is the retention period of the retention data?") == [
        "retention",
        "period",
        "data",
    ]


def test_tsquery_string_cannot_carry_operators() -> None:
    nasty = "breach' | !(a & b) <-> :* ; DROP TABLE x; --"
    q = tsquery_string(nasty)
    assert set(q) <= set("abcdefghijklmnopqrstuvwxyz0123456789 |")
    assert q == "breach | drop | table"


def test_reciprocal_rank_fusion_rewards_agreement() -> None:
    scores = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "d"]], k=60)
    assert scores["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["c"] == pytest.approx(1 / 63)
    assert scores["a"] > scores["c"] and set(scores) == {"a", "b", "c", "d"}


def test_an_item_ranked_first_in_one_list_beats_one_ranked_third_in_both() -> None:
    scores = reciprocal_rank_fusion([["x", "p", "q"], ["y", "r", "q"]], k=60)
    assert scores["q"] == pytest.approx(2 / 63) and scores["q"] > scores["x"]


def test_labels() -> None:
    assert regulation_label(30, "1", "Records of processing activities") == (
        "GDPR Article 30(1), Records of processing activities"
    )
    assert regulation_label(5, None, None) == "GDPR Article 5"
    assert document_label("Privacy notice: Shop", "How long we keep it", None) == (
        "Privacy notice: Shop, How long we keep it"
    )
    assert document_label("Agreement", None, 2) == "Agreement, page 2"


def _passage(source: str, **metadata: object) -> Passage:
    return Passage(
        id=uuid.uuid4(),
        source=source,  # type: ignore[arg-type]
        citation="x",
        label="x",
        text="x",
        score=0.0,
        metadata=dict(metadata),
    )


def test_gold_predicates_match_the_right_source_only() -> None:
    reg = _passage("regulation", article=30, paragraph="1")
    doc = _passage("document", source_uri="a.md", heading=None)
    assert matches(reg, {"article": 30}) and not matches(reg, {"article": 31})
    assert matches(reg, {"article": 30, "paragraph": "1"})
    assert not matches(doc, {"article": 30})
    assert matches(doc, {"source_uri": "a.md", "heading": None})
    assert not matches(reg, {"source_uri": "a.md"})


def test_the_gold_set_has_forty_well_formed_questions() -> None:
    gold = load_gold()
    assert len(gold) == 40
    assert len({q.id for q in gold}) == 40 and len({q.question for q in gold}) == 40
    assert all(isinstance(q, GoldQuestion) and q.relevant for q in gold)
    regulation = [q for q in gold if q.id.startswith("R")]
    assert len(regulation) == 24
    assert all("article" in p for q in regulation for p in q.relevant)
    assert {p["article"] for q in regulation for p in q.relevant} >= {5, 6, 9, 30, 32, 33, 35}

"""Upload validation: size cap, extension allowlist per evidence kind, magic byte checks.

Uploaded files are stored encrypted and are only ever read as data. Nothing in this
code base executes them. Executable formats are rejected outright, whatever the
extension claims.
"""

import json
import re
from pathlib import PurePath

from app.db.enums import EvidenceKind

ALLOWED_EXTENSIONS: dict[EvidenceKind, frozenset[str]] = {
    EvidenceKind.HAR: frozenset({".har", ".json"}),
    EvidenceKind.WEBSITE: frozenset({".html", ".htm", ".json"}),
    EvidenceKind.JAVASCRIPT_BUNDLE: frozenset({".js", ".mjs"}),
    EvidenceKind.SQLITE_SNAPSHOT: frozenset({".sqlite", ".sqlite3", ".db"}),
    EvidenceKind.QUESTIONNAIRE: frozenset({".json"}),
    EvidenceKind.PRIVACY_POLICY: frozenset({".pdf", ".md", ".txt", ".html"}),
    EvidenceKind.VENDOR_AGREEMENT: frozenset({".pdf", ".md", ".txt"}),
}

EXECUTABLE_SIGNATURES: tuple[bytes, ...] = (
    b"MZ",  # Windows PE
    b"\x7fELF",
    b"\xfe\xed\xfa\xce",  # Mach-O
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",  # Mach-O universal or Java class
)
SQLITE_MAGIC = b"SQLite format 3\x00"
PDF_MAGIC = b"%PDF-"


class UploadRejectedError(ValueError):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def safe_filename(name: str) -> str:
    base = PurePath(name.replace("\\", "/")).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".")[:120]
    return cleaned or "upload"


def validate_upload(filename: str, kind: EvidenceKind, content: bytes, max_bytes: int) -> str:
    """Returns the sanitised filename or raises UploadRejectedError."""
    if len(content) > max_bytes:
        raise UploadRejectedError("File exceeds the size limit", 413)
    if not content:
        raise UploadRejectedError("File is empty")
    name = safe_filename(filename)
    extension = PurePath(name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS[kind]:
        raise UploadRejectedError(f"Extension {extension or '(none)'} is not allowed for {kind}")
    if content.startswith(EXECUTABLE_SIGNATURES):
        raise UploadRejectedError("Executable files are not accepted")

    if extension == ".pdf":
        if not content.startswith(PDF_MAGIC):
            raise UploadRejectedError("File content is not a PDF")
    elif extension in (".sqlite", ".sqlite3", ".db"):
        if not content.startswith(SQLITE_MAGIC):
            raise UploadRejectedError("File content is not a SQLite database")
    elif extension in (".har", ".json"):
        try:
            document = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise UploadRejectedError("File content is not valid JSON") from exc
        if kind is EvidenceKind.HAR and not (isinstance(document, dict) and "log" in document):
            raise UploadRejectedError("File content is not a HAR capture")
    else:
        if b"\x00" in content[:8192]:
            raise UploadRejectedError("File content is not text")
        try:
            content[:65536].decode("utf-8")
        except UnicodeDecodeError as exc:
            if exc.start < 65536 - 4:  # a character cut at the boundary is acceptable
                raise UploadRejectedError("File content is not valid UTF-8 text") from exc
    return name

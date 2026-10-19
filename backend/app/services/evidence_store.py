"""Encrypted evidence storage on the local file system.

Files are written as AES-256-GCM blobs under `<base>/<org>/<system>/<evidence id>.enc`.
The evidence id is bound as associated data, so a blob copied onto another record
fails authentication. The database stores the path relative to the base directory.
"""

import uuid
from pathlib import Path

from app.core import crypto


class EvidenceStore:
    def __init__(self, base_dir: Path, key: bytes) -> None:
        self.base_dir = base_dir.resolve()
        self._key = key

    def _resolve(self, relative: str) -> Path:
        path = (self.base_dir / relative).resolve()
        if not path.is_relative_to(self.base_dir):
            raise ValueError("path escapes the evidence directory")
        return path

    def save(
        self,
        org_id: uuid.UUID,
        system_id: uuid.UUID,
        evidence_id: uuid.UUID,
        plaintext: bytes,
    ) -> str:
        relative = f"{org_id}/{system_id}/{evidence_id}.enc"
        path = self._resolve(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(crypto.encrypt(self._key, plaintext, str(evidence_id).encode()))
        return relative

    def read(self, relative: str, evidence_id: uuid.UUID) -> bytes:
        return crypto.decrypt(
            self._key, self._resolve(relative).read_bytes(), str(evidence_id).encode()
        )

    def delete(self, relative: str) -> bool:
        path = self._resolve(relative)
        if path.is_file():
            path.unlink()
            return True
        return False

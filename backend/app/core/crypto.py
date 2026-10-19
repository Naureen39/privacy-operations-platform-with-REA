"""AES-256-GCM encryption for evidence stored at rest."""

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_BYTES = 12


class DecryptionError(Exception):
    pass


def encrypt(key: bytes, plaintext: bytes, associated_data: bytes) -> bytes:
    """Returns nonce + ciphertext + tag. The associated data binds the blob to its record."""
    nonce = os.urandom(NONCE_BYTES)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, associated_data)


def decrypt(key: bytes, blob: bytes, associated_data: bytes) -> bytes:
    if len(blob) < NONCE_BYTES + 16:
        raise DecryptionError("blob too short")
    try:
        return AESGCM(key).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], associated_data)
    except InvalidTag as exc:
        raise DecryptionError("authentication failed") from exc

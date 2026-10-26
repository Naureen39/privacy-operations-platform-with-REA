"""Subject identifiers: normalised, then HMAC hashed with a secret key and the organisation. The raw
value exists only inside the request that carries it; it is never stored, logged or sent to a model.
"""

import hashlib
import hmac
import re

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import Settings

IDENTIFIER_TYPES = ("email", "phone")
# Taxonomy categories whose database columns can identify a person for each identifier type.
ID_CATEGORIES = {"email": ("contact_email",), "phone": ("contact_phone",)}
_EMAIL = re.compile(r"^[a-z0-9._%+'-]+@[a-z0-9-]+(\.[a-z0-9-]+)+$")


class InvalidIdentifierError(ValueError):
    """The identifier is not valid for its type. The message never contains the value."""


def normalise(identifier_type: str, raw: str) -> str:
    if identifier_type == "email":
        value = raw.strip().lower()
        if len(value) > 254 or not _EMAIL.match(value):
            raise InvalidIdentifierError("The e-mail address is not valid")
        return value
    if identifier_type == "phone":
        digits = re.sub(r"[^0-9]", "", raw)
        if not 7 <= len(digits) <= 15:
            raise InvalidIdentifierError("The telephone number is not valid")
        return digits
    raise InvalidIdentifierError("Unsupported identifier type")


def subject_key(settings: Settings) -> bytes:
    if settings.subject_hash_key is not None:
        return hashlib.sha256(settings.subject_hash_key.get_secret_value().encode()).digest()
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"processledger/subject-hash/v1"
    ).derive(settings.encryption_key_bytes())


def subject_hash(key: bytes, org_id: object, identifier_type: str, raw: str) -> str:
    """The organisation is part of the message, so the same person gets a different hash in each
    organisation and hashes cannot be used to link tenants."""
    message = f"{org_id}:{identifier_type}:{normalise(identifier_type, raw)}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def matches(key: bytes, org_id: object, identifier_type: str, raw: str, stored: str) -> bool:
    return hmac.compare_digest(subject_hash(key, org_id, identifier_type, raw), stored)

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core import crypto
from app.core.security import (
    TokenError,
    WeakPasswordError,
    create_access_token,
    decode_access_token,
    hash_password,
    hash_token,
    new_opaque_token,
    verify_password,
)
from app.core.uploads import UploadRejectedError, safe_filename, validate_upload
from app.core.urlguard import UrlRejectedError, validate_observation_url
from app.db.enums import EvidenceKind, Role

SECRET = "s" * 40
UID, OID = uuid.uuid4(), uuid.uuid4()


class TestPasswords:
    def test_argon2id_hash_verifies(self) -> None:
        hashed = hash_password("Correct-Horse-Battery-1")
        assert hashed.startswith("$argon2id$")
        assert verify_password(hashed, "Correct-Horse-Battery-1")
        assert not verify_password(hashed, "wrong-password-123")

    def test_minimum_length_is_enforced(self) -> None:
        with pytest.raises(WeakPasswordError):
            hash_password("short-pass1")  # 11 characters
        hash_password("exactly-12-ch")

    def test_garbage_hash_does_not_raise(self) -> None:
        assert not verify_password("not-a-hash", "whatever-password")


class TestTokens:
    def test_round_trip(self) -> None:
        token = create_access_token(SECRET, UID, OID, Role.ANALYST, 15)
        claims = decode_access_token(SECRET, token)
        assert (claims.user_id, claims.org_id, claims.role) == (UID, OID, "analyst")

    def test_expires_after_fifteen_minutes(self) -> None:
        past = datetime.now(UTC) - timedelta(minutes=16)
        token = create_access_token(SECRET, UID, OID, Role.ADMIN, 15, now=past)
        with pytest.raises(TokenError):
            decode_access_token(SECRET, token)

    def test_wrong_secret_and_tampering_rejected(self) -> None:
        token = create_access_token(SECRET, UID, OID, Role.ADMIN, 15)
        with pytest.raises(TokenError):
            decode_access_token("o" * 40, token)
        with pytest.raises(TokenError):
            decode_access_token(SECRET, token[:-3] + "abc")

    def test_unsigned_token_rejected(self) -> None:
        payload = {
            "sub": str(UID),
            "org": str(OID),
            "typ": "access",
            "iat": 1,
            "exp": 4102444800,
        }
        with pytest.raises(TokenError):
            decode_access_token(SECRET, jwt.encode(payload, None, algorithm="none"))

    def test_refresh_type_token_rejected_as_access(self) -> None:
        payload = {
            "sub": str(UID),
            "org": str(OID),
            "typ": "refresh",
            "iat": 1,
            "exp": 4102444800,
        }
        with pytest.raises(TokenError):
            decode_access_token(SECRET, jwt.encode(payload, SECRET, algorithm="HS256"))

    def test_opaque_tokens_are_unique_and_hashed(self) -> None:
        a, b = new_opaque_token(), new_opaque_token()
        assert a != b and len(a) >= 64
        assert hash_token(a) != a and len(hash_token(a)) == 64


class TestCrypto:
    KEY = b"k" * 32

    def test_round_trip_and_randomised_nonce(self) -> None:
        one = crypto.encrypt(self.KEY, b"secret evidence", b"id-1")
        two = crypto.encrypt(self.KEY, b"secret evidence", b"id-1")
        assert one != two and b"secret evidence" not in one
        assert crypto.decrypt(self.KEY, one, b"id-1") == b"secret evidence"

    def test_wrong_record_key_or_tamper_fails(self) -> None:
        blob = crypto.encrypt(self.KEY, b"data", b"id-1")
        with pytest.raises(crypto.DecryptionError):
            crypto.decrypt(self.KEY, blob, b"id-2")
        with pytest.raises(crypto.DecryptionError):
            crypto.decrypt(b"z" * 32, blob, b"id-1")
        with pytest.raises(crypto.DecryptionError):
            crypto.decrypt(self.KEY, blob[:-1] + bytes([blob[-1] ^ 1]), b"id-1")


HAR = b'{"log": {"entries": []}}'
SQLITE = b"SQLite format 3\x00" + b"\x00" * 100
LIMIT = 1000


class TestUploads:
    def test_accepts_valid_files(self) -> None:
        assert validate_upload("cap.har", EvidenceKind.HAR, HAR, LIMIT) == "cap.har"
        assert validate_upload("db.sqlite", EvidenceKind.SQLITE_SNAPSHOT, SQLITE, LIMIT)
        assert validate_upload("p.pdf", EvidenceKind.PRIVACY_POLICY, b"%PDF-1.7\n...", LIMIT)
        assert validate_upload("p.md", EvidenceKind.PRIVACY_POLICY, b"# Policy\ntext", LIMIT)
        assert validate_upload("app.js", EvidenceKind.JAVASCRIPT_BUNDLE, b"var a = 1;", LIMIT)

    @pytest.mark.parametrize(
        ("name", "kind", "content"),
        [
            ("cap.exe", EvidenceKind.HAR, HAR),
            ("cap", EvidenceKind.HAR, HAR),
            ("a.har", EvidenceKind.SQLITE_SNAPSHOT, SQLITE),
            ("cap.har", EvidenceKind.HAR, b"MZ\x90\x00" + HAR),
            ("lib.js", EvidenceKind.JAVASCRIPT_BUNDLE, b"\x7fELF\x02\x01"),
            ("tool.json", EvidenceKind.QUESTIONNAIRE, b"MZ" + b"\x00" * 50),
            ("cap.har", EvidenceKind.HAR, b"not json"),
            ("cap.har", EvidenceKind.HAR, b'{"other": 1}'),
            ("db.sqlite", EvidenceKind.SQLITE_SNAPSHOT, b"plain text pretending"),
            ("p.pdf", EvidenceKind.PRIVACY_POLICY, b"<html>not a pdf</html>"),
            ("p.txt", EvidenceKind.PRIVACY_POLICY, b"text\x00with nul"),
            ("p.txt", EvidenceKind.PRIVACY_POLICY, b""),
        ],
    )
    def test_rejects(self, name: str, kind: EvidenceKind, content: bytes) -> None:
        with pytest.raises(UploadRejectedError):
            validate_upload(name, kind, content, LIMIT)

    def test_size_cap(self) -> None:
        with pytest.raises(UploadRejectedError) as info:
            validate_upload("p.txt", EvidenceKind.PRIVACY_POLICY, b"a" * (LIMIT + 1), LIMIT)
        assert info.value.status_code == 413

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("../../etc/passwd", "passwd"),
            ("..\\..\\windows\\system32\\cap.har", "cap.har"),
            ("a b;c.har", "a_b_c.har"),
            (".hidden.har", "hidden.har"),
            ("", "upload"),
        ],
    )
    def test_filename_sanitised(self, raw: str, expected: str) -> None:
        assert safe_filename(raw) == expected


Resolver = Callable[[str, int], Sequence[str]]
ALLOWED = ["shop.northbridge.test", "*.northbridge.test"]


def resolver_for(*addresses: str) -> Resolver:
    return lambda host, port: list(addresses)


def accept(url: str, *addresses: str, networks: tuple[str, ...] = ()):  # type: ignore[no-untyped-def]
    return validate_observation_url(
        url,
        allowed_hosts=ALLOWED,
        allowed_networks=networks,
        resolver=resolver_for(*addresses),
    )


class TestUrlGuard:
    def test_public_address_accepted(self) -> None:
        resolved = accept("https://shop.northbridge.test/checkout", "93.184.216.34")
        assert resolved.addresses == ("93.184.216.34",) and resolved.port == 443

    def test_wildcard_host_and_demo_network(self) -> None:
        resolved = accept("http://cms.northbridge.test", "172.28.0.7", networks=("172.28.0.0/16",))
        assert resolved.addresses == ("172.28.0.7",)

    @pytest.mark.parametrize(
        "address",
        [
            "127.0.0.1",
            "127.1.2.3",
            "::1",
            "169.254.169.254",
            "fe80::1",
            "10.1.2.3",
            "192.168.0.10",
            "172.16.5.5",
            "0.0.0.0",  # noqa: S104
            "224.0.0.1",
            "::ffff:127.0.0.1",
            "::ffff:10.0.0.1",
            "fc00::1",
        ],
    )
    def test_unsafe_addresses_rejected(self, address: str) -> None:
        with pytest.raises(UrlRejectedError):
            accept("https://shop.northbridge.test", address)

    def test_private_address_outside_demo_network_rejected(self) -> None:
        with pytest.raises(UrlRejectedError):
            accept("https://shop.northbridge.test", "10.9.9.9", networks=("172.28.0.0/16",))

    def test_loopback_rejected_even_inside_an_allowed_network(self) -> None:
        with pytest.raises(UrlRejectedError):
            accept("https://shop.northbridge.test", "127.0.0.1", networks=("127.0.0.0/8",))

    def test_one_bad_address_among_good_ones_rejects(self) -> None:
        with pytest.raises(UrlRejectedError):
            accept("https://shop.northbridge.test", "93.184.216.34", "169.254.169.254")

    @pytest.mark.parametrize(
        "url",
        [
            "ftp://shop.northbridge.test/",
            "file:///etc/passwd",
            "gopher://shop.northbridge.test",
            "https://evil.example/",
            "https://northbridge.test.evil.example/",
            "https://shop.northbridge.test@evil.example/",
            "https://user:pw@shop.northbridge.test/",
            "https://shop.northbridge.test:8443/",
            "https://shop.northbridge.test:notaport/",
            "https:///nohost",
            "https://localhost/",
            "http://169.254.169.254/latest/meta-data",
            "https://" + "a" * 3000 + ".northbridge.test",
        ],
    )
    def test_bad_urls_rejected_before_resolution(self, url: str) -> None:
        def explode(host: str, port: int) -> Sequence[str]:
            raise AssertionError("must not resolve")

        with pytest.raises(UrlRejectedError):
            validate_observation_url(url, allowed_hosts=ALLOWED, resolver=explode)

    def test_apex_not_matched_by_wildcard(self) -> None:
        with pytest.raises(UrlRejectedError):
            validate_observation_url(
                "https://northbridge.test",
                allowed_hosts=["*.northbridge.test"],
                resolver=resolver_for("93.184.216.34"),
            )

    def test_unresolvable_host_rejected(self) -> None:
        def fail(host: str, port: int) -> Sequence[str]:
            raise OSError("no such host")

        with pytest.raises(UrlRejectedError):
            validate_observation_url(
                "https://shop.northbridge.test", allowed_hosts=ALLOWED, resolver=fail
            )

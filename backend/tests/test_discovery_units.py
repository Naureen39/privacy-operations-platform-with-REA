import json
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.db.enums import EvidenceKind, Extractor
from app.discovery import masking
from app.discovery.executor import Executor, ReaClients
from app.discovery.extractors import har, javascript, sqlite, website
from app.discovery.patterns import (
    detect_pattern,
    dominant_pattern,
    luhn_valid,
    mask_shape,
    masked_samples,
)
from app.discovery.rea_adapter import ReaAdapter, ReaError, ReaRequest, ReaUnavailableError


# --- patterns and masks ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("rhys.begum222@webpost.example", "email"),
        ("198.18.7.222", "ip_address"),
        ("999.1.1.1", None),
        ("3fa85f64-5717-4562-b3fc-2c963f66afa6", "uuid"),
        ("IE48DCMD55940781618495", "iban"),
        ("IE48DCMD55940781618496", None),  # fails the mod 97 check
        ("4242424242424242", "payment_card"),
        ("4242424242424241", "integer"),  # fails the Luhn check, so only a number
        ("+44 7700 900123", "phone"),
        ("2026-03-23", "date"),
        ("2026-03-23T05:22:50Z", "datetime"),
        ("$2y$10$c79e2066c904c5f6259fe4c49b546d50224e47a08dff986b9d4588", "password_hash"),
        ("9e62bebfc797b9abc32625c6bc6aa0ea3926bb01a13dd2218dafd9a0c5eb8f4e", "sha256_hash"),
        ("5d1aa0cbdb7a3aba", "hex_token"),
        ("https://example.test/x", "url"),
        ("51.50853", "coordinate"),
        ("hello", None),
        ("", None),
        (True, "boolean"),
        (7, "integer"),
    ],
)
def test_pattern_detection(value: Any, expected: str | None) -> None:
    assert detect_pattern(value) == expected


def test_luhn() -> None:
    assert luhn_valid("4242424242424242") and not luhn_valid("1234567890123456")


def test_dominant_pattern_needs_a_clear_majority() -> None:
    assert dominant_pattern(["a@b.example", "c@d.example", "x"])[0] == "email"
    assert dominant_pattern(["a@b.example", "plain", "other", "words"])[0] is None
    assert dominant_pattern([None, "", "  "]) == (None, 0)


def test_masks_keep_shape_but_not_content() -> None:
    assert mask_shape("rhys.begum222@webpost.example") == "xxxx.xxxxx999@xxxxxxx.xxxxxxx"
    assert mask_shape("a" * 100).endswith("...") and len(mask_shape("a" * 100)) == 43
    assert masked_samples(["ab1", "cd2", "ef3", "gh4"], 3) == ["xx9"]  # same shape collapses


# --- raw output masking ------------------------------------------------------------------------
ENTRY: dict[str, Any] = {
    "request": {
        "method": "POST",
        "url": "https://shop.example.test/?wc-ajax=checkout&ref=jane.doe%40mail.example",
        "queryString": [
            {"name": "wc-ajax", "value": "checkout"},
            {"name": "ref", "value": "jane.doe@mail.example"},
        ],
        "headers": [
            {"name": "cookie", "value": "session=abc123"},
            {
                "name": "referer",
                "value": "https://shop.example.test/checkout/?email=jane.doe@mail.example",
            },
            {"name": "content-type", "value": "application/json"},
        ],
        "cookies": [{"name": "session", "value": "abc123"}],
        "postData": {
            "mimeType": "application/json",
            "text": json.dumps(
                {"contact": {"email": "jane.doe@mail.example", "name": "Jane Doe"}, "ok": True}
            ),
            "params": [{"name": "email", "value": "jane.doe@mail.example"}],
        },
    },
    "response": {
        "status": 200,
        "headers": [
            {"name": "set-cookie", "value": "s=1"},
            {"name": "location", "value": "https://x.test/?a=jane.doe@mail.example"},
        ],
        "cookies": [{"name": "s", "value": "1"}],
        "content": {
            "mimeType": "application/json",
            "text": json.dumps({"email": "jane.doe@mail.example", "id": 7}),
        },
    },
}


def test_masked_entry_contains_no_values() -> None:
    masked = masking.mask_har_entry(ENTRY)
    dumped = json.dumps(masked)
    for secret in ("jane.doe", "mail.example", "abc123", "Jane Doe"):
        assert secret not in dumped, secret
    # Names and structure survive.
    assert [q["name"] for q in masked["request"]["queryString"]] == ["wc-ajax", "ref"]
    assert masked["request"]["url"].endswith("wc-ajax=&ref=")
    assert set(json.loads(masked["request"]["postData"]["text"])["contact"]) == {"email", "name"}
    assert ENTRY["request"]["cookies"][0]["value"] == "abc123"  # the original is untouched


def test_non_json_bodies_are_dropped_and_oversized_raw_is_summarised() -> None:
    entry = json.loads(json.dumps(ENTRY))
    entry["response"]["content"] = {"mimeType": "text/html", "text": "<p>jane.doe@mail.example</p>"}
    assert masking.mask_har_entry(entry)["response"]["content"]["text"].startswith("[omitted ")
    huge = {"records": ["x" * 1000] * 9000, "name": "x"}
    summary, truncated = masking.finalize_raw(huge)
    assert truncated and summary["truncated"] is True and summary["summary"]["records"] == 9000


def test_strip_query_values() -> None:
    assert (
        masking.strip_query_values("https://u:p@h.test/p?a=1&b=2#frag") == "https://h.test/p?a=&b="
    )
    assert masking.strip_query_values("https://h.test/p") == "https://h.test/p"


# --- extractors on small crafted inputs ----------------------------------------------------------
def make_entry(
    url: str,
    method: str = "GET",
    post: dict | None = None,
    response: dict | None = None,
    cookies: list | None = None,
) -> dict:
    entry: dict[str, Any] = {
        "request": {"method": method, "url": url, "queryString": [], "headers": []},
        "response": response or {"status": 200, "content": {"mimeType": "text/html"}},
    }
    if "?" in url:
        from urllib.parse import parse_qsl, urlsplit

        entry["request"]["queryString"] = [
            {"name": k, "value": v} for k, v in parse_qsl(urlsplit(url).query)
        ]
    if post:
        entry["request"]["postData"] = post
    if cookies:
        entry["response"]["cookies"] = cookies
    return entry


def test_har_extraction_separates_own_and_third_party() -> None:
    entries = [
        make_entry("https://own.test/page"),
        make_entry(
            "https://own.test/api/order",
            "POST",
            {
                "mimeType": "application/json",
                "text": json.dumps(
                    {"customer": {"email": "a@b.example"}, "items": [{"sku": "x1"}, {"sku": "x2"}]}
                ),
            },
            {
                "status": 200,
                "content": {"mimeType": "application/json", "text": json.dumps({"order_id": 4})},
            },
            [{"name": "sid", "httpOnly": True, "secure": True}],
        ),
        make_entry("https://tracker.test/c?uid=a%40b.example&ev=buy", "GET"),
        make_entry("https://tracker.test/c?uid=c%40d.example", "GET"),
    ]
    elements, recipients, own = har.extract_entries(entries)
    assert own == "own.test"
    keys = {(e.location_kind, e.name) for e in elements}
    assert ("request_json_key", "customer.email") in keys and (
        "request_json_key",
        "items.sku",
    ) in keys
    assert ("response_json_key", "order_id") in keys and ("cookie", "sid") in keys
    assert {("third_party_param", "uid"), ("third_party_param", "ev")} <= keys
    assert [r.host for r in recipients] == ["tracker.test"]
    assert recipients[0].context["request_count"] == 2 and recipients[0].context["parameters"] == [
        "ev",
        "uid",
    ]
    uid = next(e for e in elements if e.name == "uid")
    assert uid.pattern_class == "email" and uid.context["masked_samples"] == ["x@x.xxxxxxx"]
    assert "a@b.example" not in json.dumps([e.context for e in elements])


def test_har_form_params_and_own_host_override() -> None:
    entries = [
        make_entry("https://cdn.test/lib.js"),
        make_entry(
            "https://own.test/f",
            "POST",
            {
                "mimeType": "application/x-www-form-urlencoded",
                "params": [{"name": "email", "value": "a@b.example"}],
            },
        ),
    ]
    elements, recipients, own = har.extract_entries(entries, own_host="own.test")
    assert own == "own.test" and [r.host for r in recipients] == ["cdn.test"]
    assert ("request_form_param", "email") in {(e.location_kind, e.name) for e in elements}


def test_sqlite_fallback_skips_integer_keys_and_masks_samples(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "d.sqlite"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE people (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, dob TEXT, ip TEXT, note TEXT)"
    )
    db.executemany(
        "INSERT INTO people (email, dob, ip, note) VALUES (?,?,?,?)",
        [(f"u{i}@x.example", "1990-01-0%d" % (i + 1), f"198.18.0.{i + 1}", None) for i in range(5)],
    )
    db.commit()
    db.close()
    tables = sqlite.tables_from_file(path, row_sample=3)
    assert tables[0].name == "people" and len(tables[0].sample_rows) == 3
    candidates = {c.name: c for c in sqlite.extract_tables(tables)}
    assert set(candidates) == {"email", "dob", "ip", "note"}  # the integer key is skipped
    assert (
        candidates["email"].pattern_class == "email"
        and candidates["ip"].pattern_class == "ip_address"
    )
    assert candidates["dob"].pattern_class == "date" and candidates["note"].pattern_class is None
    assert candidates["email"].context["masked_samples"] == ["x9@x.xxxxxxx"]
    assert all(
        c.path == "db:people" and c.location_kind == "db_column" for c in candidates.values()
    )


def test_javascript_fallback_finds_packages_routes_ipc_and_hosts() -> None:
    source = """
    const { ipcMain } = require("electron"); import axios from "axios"; import "./local.js";
    const Sentry = require("@sentry/electron"); const x = require("./relative");
    ipcMain.handle("clock:in", () => 1); ipcRenderer.invoke("profile:get");
    const routes = [{ path: "/home" }, { path: "/clock" }];
    Sentry.init({ dsn: 'https://key@o1.ingest.sentry.io/1?secret=zzz' });
    fetch("https://api.own.test/v1/x"); const db = new Database("hub.db");
    """
    technologies, recipients = javascript.extract_fallback(source, own_host="api.own.test")
    by_kind: dict[str, set[str]] = {}
    for t in technologies:
        by_kind.setdefault(t.kind, set()).add(t.name)
    assert by_kind["package"] == {"electron", "axios", "@sentry/electron"}
    assert by_kind["route"] == {"/home", "/clock"} and by_kind["ipc_channel"] == {
        "clock:in",
        "profile:get",
    }
    assert by_kind["storage"] == {"hub.db"}
    assert [r.host for r in recipients] == ["o1.ingest.sentry.io"]
    dumped = json.dumps([r.context for r in recipients]) + json.dumps(
        [t.name for t in technologies]
    )
    assert "secret=zzz" not in dumped and "key@" not in dumped


def test_website_parse_reads_inputs_labels_and_hosts() -> None:
    html = """<html><body>
    <form id="f1" action="/send" method="post">
      <label for="a">Email address</label><input id="a" name="billing_email" type="email" autocomplete="email" required>
      <label>Phone <input name="phone" type="tel"></label>
      <input type="checkbox" name="optin" checked> <input type="hidden" name="src" value="web">
      <textarea name="note" placeholder="Tell us"></textarea><button type="submit" name="go">Go</button>
    </form>
    <script src="https://cdn.third.test/sdk.js"></script><script src="https://own.test/app.js"></script>
    <script src="app://local/x.js"></script><iframe src="https://frame.third.test/e"></iframe>
    <link rel="stylesheet" href="https://fonts.third.test/css"><link rel="canonical" href="https://other.test/">
    <a href="https://not-a-recipient.test/">link</a></body></html>"""
    parsed = website.parse_html(html, own_host="own.test")
    fields = {e.name: e for e in parsed.elements}
    assert set(fields) == {
        "billing_email",
        "phone",
        "optin",
        "src",
        "note",
    }  # the submit button is skipped
    assert (
        fields["billing_email"].context["label"] == "Email address"
        and fields["billing_email"].context["autocomplete"] == "email"
    )
    assert (
        fields["billing_email"].context["required"] is True
        and fields["billing_email"].path == "form:f1"
    )
    assert (
        fields["phone"].context["label"].startswith("Phone")
        and fields["optin"].context["checked_by_default"] is True
    )
    assert fields["note"].context["label"] == "Tell us" and fields["note"].data_type == "textarea"
    assert [r.host for r in parsed.recipients] == [
        "cdn.third.test",
        "fonts.third.test",
        "frame.third.test",
    ]
    assert "https://cdn.third.test" in parsed.origins


def test_website_rea_projection() -> None:
    result = {
        "page_origin": "http://127.0.0.1:5000",
        "evidence": {"normalized_result": {
            "resources": [{"url": "https://cdn.third.test/a.js"}, {"url": "http://127.0.0.1:5000/x"}],
            "metadata": {"dom_urls": [{"url": "https://fonts.third.test/css"}, {"url": None}]},
            "network": {"requests": [{"url": "https://pixel.third.test/p.gif?e=1"}]},
            "scripts": {"items": [{"url": "https://cdn.third.test/a.js"}]},
            "accessibility": {"nodes": [{"role": "textbox", "name": "Email", "states": [{"name": "required", "value": True}]}, {"role": "generic", "name": "x"}]},
            "target": {"title": "T"},
        }},
    }  # fmt: skip
    recipients, summary = website.observed_hosts_rea(result, own_host="own.test")
    assert [r.host for r in recipients] == [
        "cdn.third.test",
        "fonts.third.test",
        "pixel.third.test",
    ]
    assert "e=1" not in json.dumps([r.context for r in recipients])
    assert summary["controls"] == [{"role": "textbox", "label": "Email", "required": True}]


# --- adapter and executor behaviour -----------------------------------------------------------
class FakeTransport:
    def __init__(self, envelope: dict[str, Any] | Exception, healthy: bool = True) -> None:
        self.envelope = envelope
        self.healthy = healthy
        self.requests: list[ReaRequest] = []

    def call(self, request: ReaRequest, timeout_seconds: float) -> dict[str, Any]:
        self.requests.append(request)
        if isinstance(self.envelope, Exception):
            raise self.envelope
        return self.envelope

    def health(self) -> dict[str, Any]:
        if not self.healthy:
            raise ReaUnavailableError("runner_unreachable", "down")
        return {"ok": True, "commands": ["inspect-web-network-capture"]}


def test_adapter_returns_structured_errors() -> None:
    adapter = ReaAdapter(
        FakeTransport(
            {
                "ok": False,
                "error": {
                    "code": "rea_error",
                    "message": "bad input",
                    "details": {"rea_code": "invalid_request"},
                },
            }
        )
    )
    with pytest.raises(ReaError) as info:
        adapter.run("inspect-web-network-capture", path="x/y.har")
    assert info.value.code == "rea_error" and info.value.details == {"rea_code": "invalid_request"}
    assert str(info.value) == "rea_error: bad input"

    ok = ReaAdapter(
        FakeTransport({"ok": True, "rea_version": "6.7.0", "duration_ms": 12, "result": {"a": 1}})
    )
    response = ok.run("inspect-web-network-capture", path="x/y.har")
    assert (response.rea_version, response.duration_ms, response.result) == ("6.7.0", 12, {"a": 1})
    assert response.canonical_command.startswith("rea inspect-web-network-capture")
    assert ok.available() and not ReaAdapter(FakeTransport({}, healthy=False)).available()


def test_executor_falls_back_and_records_the_failed_rea_attempt(tmp_path: Path) -> None:
    transport = FakeTransport(ReaUnavailableError("timeout", "no answer", retryable=True))
    adapter = ReaAdapter(transport)
    executor = Executor(Settings(rea_input_dir=str(tmp_path)), ReaClients(adapter, adapter))
    har_bytes = json.dumps(
        {
            "log": {
                "creator": {"name": "t"},
                "entries": [make_entry("https://own.test/a"), make_entry("https://x.test/b?q=1")],
            }
        }
    ).encode()
    runs = executor.process(EvidenceKind.HAR, "c.har", har_bytes, None)
    assert [(r.extractor, r.status) for r in runs] == [
        (Extractor.REA, "error"),
        (Extractor.FALLBACK, "ok"),
    ]
    assert "timeout" in (runs[0].error or "")
    assert [r.host for r in runs[1].recipients] == ["x.test"]
    assert runs[1].command.startswith("fallback:") and runs[1].rea_version is None
    assert not any(tmp_path.iterdir()), "staged plaintext must be removed"


def test_executor_without_rea_uses_the_fallback_only(tmp_path: Path) -> None:
    executor = Executor(Settings(rea_input_dir=str(tmp_path), rea_enabled=False), None)
    runs = executor.process(
        EvidenceKind.JAVASCRIPT_BUNDLE, "a.js", b'require("axios"); fetch("https://h.test/x")', None
    )
    assert [(r.extractor, r.status) for r in runs] == [(Extractor.FALLBACK, "ok")]
    bad = executor.process(EvidenceKind.HAR, "c.har", b"not json", None)
    assert bad[0].status == "error" and bad[0].extractor is Extractor.FALLBACK
    assert executor.observe_url("https://x.test", None)[0].status == "error"  # no browser, no fetch


def test_website_runs_the_parser_and_the_browser_observation(tmp_path: Path) -> None:
    rea_result = {
        "ok": True,
        "rea_version": "6.7.0",
        "duration_ms": 5,
        "result": {
            "page_origin": "http://127.0.0.1:1",
            "allowed_origins": [],
            "evidence": {
                "normalized_result": {
                    "resources": [{"url": "https://cdn.third.test/a.js"}],
                    "metadata": {"dom_urls": []},
                    "network": {"requests": []},
                    "scripts": {"items": []},
                    "accessibility": {"nodes": []},
                    "target": {},
                }
            },
        },
    }
    transport = FakeTransport(rea_result)
    adapter = ReaAdapter(transport)
    executor = Executor(Settings(rea_input_dir=str(tmp_path)), ReaClients(adapter, adapter))
    html = b'<form id="f"><input name="email"></form><script src="https://cdn.third.test/a.js"></script>'
    runs = executor.process(EvidenceKind.WEBSITE, "p.html", html, "own.test")
    assert [(r.extractor, r.status) for r in runs] == [
        (Extractor.FALLBACK, "ok"),
        (Extractor.REA, "ok"),
    ]
    assert runs[0].elements[0].name == "email" and runs[1].elements == []
    assert transport.requests[0].options["allowed_origins"] == ["https://cdn.third.test"]
    assert runs[1].rea_version == "6.7.0" and runs[1].command.startswith("rea inspect-web-page")


# --- HTTP transport against a real wrapper server ------------------------------------------------
def test_http_transport_talks_to_the_wrapper_service(tmp_path: Path) -> None:
    import socket
    import subprocess
    import sys
    import time

    from app.discovery.rea_adapter import HttpTransport
    from tests.rea_support import RUNNER_DIR, rea_unavailable_reason

    if rea_unavailable_reason():
        pytest.skip(rea_unavailable_reason() or "")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    import os

    keep = ("PATH", "HOME", "USERPROFILE", "TMPDIR", "TEMP", "TMP", "SystemRoot", "LANG")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env.update(
        {"REA_INPUT_DIR": str(tmp_path), "REA_RUNNER_ROLE": "offline", "REA_RUNNER_TOKEN": "t0k3n"}
    )
    server = subprocess.Popen(
        [
            "node",
            str(RUNNER_DIR / "wrapper.mjs"),
            "serve",
            "--port",
            str(port),
            "--host",
            "127.0.0.1",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
    )  # noqa: S603, S607
    try:
        (tmp_path / "t").mkdir()
        entry = {
            "startedDateTime": "2026-01-01T00:00:00.000Z", "time": 5, "cache": {}, "timings": {"send": 1, "wait": 1, "receive": 1},
            "request": {"method": "GET", "url": "https://own.test/p", "httpVersion": "HTTP/2.0", "headers": [], "queryString": [], "cookies": [], "headersSize": -1, "bodySize": 0},
            "response": {"status": 200, "statusText": "OK", "httpVersion": "HTTP/2.0", "headers": [], "cookies": [], "content": {"size": 2, "mimeType": "text/html", "text": "ok"}, "redirectURL": "", "headersSize": -1, "bodySize": 2},
        }  # fmt: skip
        (tmp_path / "t" / "a.har").write_text(
            json.dumps(
                {
                    "log": {
                        "version": "1.2",
                        "creator": {"name": "t", "version": "1"},
                        "entries": [entry],
                    }
                }
            )
        )
        base = f"http://127.0.0.1:{port}"
        for _ in range(60):
            try:
                if HttpTransport(base, "t0k3n").health().get("ok"):
                    break
            except ReaError:
                time.sleep(0.25)
        adapter = ReaAdapter(HttpTransport(base, "t0k3n"), timeout_seconds=60)
        assert adapter.available() and "inspect-sqlite-database" in adapter.commands()
        response = adapter.run("inspect-web-network-capture", path="t/a.har")
        assert (
            response.rea_version == "6.7.0"
            and response.result["normalized_result"]["total_records"] == 1
        )
        with pytest.raises(ReaError) as info:
            adapter.run("inspect-web-network-capture", path="t/missing.har")
        assert info.value.code == "not_found"
        with pytest.raises(ReaUnavailableError) as refused:
            ReaAdapter(HttpTransport(base, "wrong")).run(
                "inspect-web-network-capture", path="t/a.har"
            )
        assert refused.value.code == "runner_refused"
        assert not ReaAdapter(HttpTransport("http://127.0.0.1:1", None)).available()
    finally:
        server.terminate()
        server.wait(timeout=10)
    _ = sys


def test_sqlite_extraction_records_the_record_months_of_timestamp_columns(tmp_path: Path) -> None:
    import sqlite3

    from app.discovery.extractors.sqlite import extract_tables, tables_from_file

    path = tmp_path / "snap.sqlite"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE conversations (id INTEGER PRIMARY KEY, created_at TEXT, closed_at TEXT, birth_date TEXT, note TEXT)"
    )
    rows = [
        (i, f"2022-03-{i % 28 + 1:02d}T10:00:00", None, "1980-01-01", "x") for i in range(1, 40)
    ]
    rows += [(100, "2026-09-02T08:00:00", "2026-09-03", "1990-05-05", "y")]
    db.executemany("INSERT INTO conversations VALUES (?, ?, ?, ?, ?)", rows)
    db.commit()
    db.close()
    tables = tables_from_file(path, row_sample=5)  # the sample sees only the first rows
    by_name = {c.name: c for c in extract_tables(tables)}
    created = by_name["created_at"].context["record_months"]
    assert created == {"oldest": "2022-03", "newest": "2026-09", "basis": "whole table"}
    assert by_name["closed_at"].context["record_months"]["oldest"] == "2026-09"
    assert "record_months" not in by_name["birth_date"].context  # birth dates are never summarised
    assert "record_months" not in by_name["note"].context

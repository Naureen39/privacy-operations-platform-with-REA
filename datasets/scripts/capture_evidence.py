"""Record a network capture (HAR 1.2), a website snapshot and a bundle for each system.

A simulated browser loads each system's pages from the system's own application, follows the
resources the page references, submits the forms for a few synthetic visitors, and fires the
requests the page's scripts would send to third parties. Responses from the system itself are
the application's real output. Responses from third parties are stubs, because the estate
never contacts the internet.

    uv run python datasets/scripts/capture_evidence.py     (normally run through build_estate.py)

This is the deterministic capture path. capture_evidence.ts is the optional Playwright
equivalent for recording the same flows against the open source stacks started with
compose_estate.yml.
"""

import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from estate_apps import SIM_HEADER, Store, build_app, unflatten
from generators import Person, resolve
from js_bundles import bundle_filename, render_bundle

sys.path.insert(0, str(Path(__file__).resolve().parent))
from datetime import datetime, timedelta  # noqa: E402

from common import BASE_TIME, rng_for, write_json, write_text  # noqa: E402

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
CAPTURE_PEOPLE = 3
STUB_BODIES = {
    ".js": ("application/javascript", "/* third-party script */"),
    ".css": ("text/css", "/* third-party styles */"),
    ".gif": ("image/gif", "GIF89a"),
}


def _headers(items: Any) -> list[dict[str, str]]:
    return [{"name": k, "value": v} for k, v in items if k.lower() != SIM_HEADER]


def _cookies_from_set_cookie(values: list[str]) -> list[dict[str, Any]]:
    cookies = []
    for raw in values:
        parts = [p.strip() for p in raw.split(";")]
        name, _, value = parts[0].partition("=")
        flags = {
            p.split("=")[0].lower(): (p.split("=", 1)[1] if "=" in p else True) for p in parts[1:]
        }
        cookies.append(
            {
                "name": name, "value": value, "path": flags.get("path", "/"),
                "httpOnly": "httponly" in flags, "secure": "secure" in flags,
                "sameSite": str(flags.get("samesite", "")).capitalize() or None,
                "maxAge": int(str(flags["max-age"])) if "max-age" in flags else None,
            }
        )  # fmt: skip
    return cookies


class HarRecorder:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self.start = datetime.fromisoformat(BASE_TIME.replace("Z", "+00:00"))

    def _stamp(self) -> tuple[str, int]:
        index = len(self.entries)
        moment = self.start + timedelta(milliseconds=350 * index)
        return (
            moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z",
            40 + (index * 7) % 90,
        )

    def _entry(
        self, method: str, url: str, req_headers: list[dict[str, str]], body: str | None, mime: str | None,
        status: int, resp_headers: list[dict[str, str]], resp_text: str, resp_mime: str,
        set_cookies: list[str], page_ref: str | None = None,
    ) -> None:  # fmt: skip
        started, wait = self._stamp()
        split = urlsplit(url)
        post_data: dict[str, Any] | None = None
        if body is not None:
            post_data = {"mimeType": mime or "application/octet-stream", "text": body}
            if mime and "x-www-form-urlencoded" in mime:
                post_data["params"] = [
                    {"name": k, "value": v} for k, v in parse_qsl(body, keep_blank_values=True)
                ]
        request = {
            "method": method, "url": url, "httpVersion": "HTTP/2.0", "headers": req_headers,
            "queryString": [{"name": k, "value": v} for k, v in parse_qsl(split.query, keep_blank_values=True)],
            "cookies": [
                {"name": c.split("=", 1)[0].strip(), "value": c.split("=", 1)[1].strip()}
                for h in req_headers if h["name"].lower() == "cookie" for c in h["value"].split(";") if "=" in c
            ],
            "headersSize": -1, "bodySize": len(body.encode()) if body else 0,
        }  # fmt: skip
        if post_data:
            request["postData"] = post_data
        self.entries.append(
            {
                "startedDateTime": started, "time": wait + 3, "request": request,
                "response": {
                    "status": status, "statusText": "OK" if status < 400 else "Error", "httpVersion": "HTTP/2.0",
                    "headers": resp_headers, "cookies": _cookies_from_set_cookie(set_cookies),
                    "content": {"size": len(resp_text.encode()), "mimeType": resp_mime, "text": resp_text},
                    "redirectURL": "", "headersSize": -1, "bodySize": len(resp_text.encode()),
                },
                "cache": {}, "timings": {"send": 1, "wait": wait, "receive": 2},
                "_resourceType": "document" if resp_mime.startswith("text/html") else "xhr",
            }
        )  # fmt: skip

    def add_response(self, response: Any) -> None:
        request = response.request
        body = request.content.decode("utf-8") if request.content else None
        resp_mime = response.headers.get("content-type", "application/octet-stream").split(";")[0]
        text = (
            response.text
            if resp_mime.startswith(("text/", "application/json", "application/javascript"))
            else "GIF89a"
        )
        self._entry(
            request.method, str(request.url), _headers(request.headers.items()), body,
            request.headers.get("content-type"), response.status_code,
            _headers(response.headers.items()), text, resp_mime, response.headers.get_list("set-cookie"),
        )  # fmt: skip

    def add_third_party(
        self,
        method: str,
        url: str,
        referer: str,
        body: str | None,
        content_type: str | None,
        response_text: str,
    ) -> None:
        split = urlsplit(url)
        headers = [
            {"name": "host", "value": split.netloc}, {"name": "user-agent", "value": BROWSER_UA},
            {"name": "accept", "value": "*/*"}, {"name": "referer", "value": referer},
        ]  # fmt: skip
        if content_type:
            headers.append({"name": "content-type", "value": content_type})
        suffix = Path(split.path).suffix
        mime, default_text = STUB_BODIES.get(suffix, ("application/json", ""))
        text = response_text or default_text
        if text.startswith("GIF89a"):
            mime = "image/gif"
        elif text.startswith("<html"):
            mime = "text/html"
        elif text.startswith(("{", "[")):
            mime = "application/json"
        self._entry(
            method, url, headers, body, content_type, 200,
            [{"name": "content-type", "value": mime}], text, mime, [],
        )  # fmt: skip

    def to_har(self) -> dict[str, Any]:
        return {
            "log": {
                "version": "1.2",
                "creator": {"name": "processledger-dataset-capture", "version": "1.0"},
                "pages": [], "entries": self.entries,
            }
        }  # fmt: skip


def _beacon_url_and_body(
    beacon: dict[str, Any], person: Person, rng: Any
) -> tuple[str, str | None, str | None]:
    query = {k: resolve(v, person, rng) for k, v in beacon["query"].items()}
    url = f"https://{beacon['host']}{beacon['path']}"
    if query:
        url += "?" + urlencode({k: str(v) for k, v in query.items()}, quote_via=quote)
    body_values = {k: resolve(v, person, rng) for k, v in beacon["body"].items()}
    if beacon["body_type"] == "form":
        return (
            url,
            urlencode({k: str(v) for k, v in body_values.items()}),
            "application/x-www-form-urlencoded",
        )
    if beacon["body_type"] == "json":
        return url, json.dumps(unflatten(body_values), sort_keys=True), "application/json"
    return url, None, None


def _build_payload(endpoint: dict[str, Any], person: Person, rng: Any) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field in endpoint["fields"]:
        value = resolve(field["src"], person, rng)
        if value is None:
            continue
        if field["type"] == "checkbox":
            if value in (1, "1", True):
                values[field["name"]] = "on"
            continue
        values[field["name"]] = value
    return values


def capture_system(
    spec: dict[str, Any],
    store: Store,
    people_by_id: dict[str, Person],
    capture_pids: list[str],
    out_dir: Path,
) -> dict[str, Any]:
    bundle = render_bundle(spec)
    assets: dict[str, tuple[str, str]] = {}
    for page in spec["pages"]:
        for url in page["scripts"]:
            split = urlsplit(url)
            if split.scheme in ("http", "https") and split.netloc == spec["host"]:
                assets[split.path] = ("application/javascript", bundle)
    app = build_app(spec, store, people_by_id, assets)
    client = TestClient(
        app, base_url=f"https://{spec['host']}", headers={"user-agent": BROWSER_UA, "accept": "*/*"}
    )
    recorder = HarRecorder()
    sent: set[tuple[str, str]] = set()
    first = people_by_id[capture_pids[0]]
    page_url = f"https://{spec['host']}{spec['pages'][0]['path']}"
    snapshot_html = ""

    for index, page in enumerate(spec["pages"]):
        response = client.get(page["path"], headers={SIM_HEADER: first["person_id"]})
        recorder.add_response(response)
        if index == 0:
            snapshot_html = response.text
        soup = BeautifulSoup(response.text, "html.parser")
        refs = [t.get("src") for t in soup.find_all(["script", "img", "iframe"])]
        refs += [t.get("href") for t in soup.find_all("link", rel="stylesheet")]
        for ref in filter(None, refs):
            split = urlsplit(ref)
            if split.scheme not in ("http", "https"):
                continue
            if split.netloc == spec["host"]:
                recorder.add_response(
                    client.get(split.path or "/", headers={SIM_HEADER: first["person_id"]})
                )
            else:
                recorder.add_third_party("GET", ref, page_url, None, None, "")

    for beacon in (b for b in spec["beacons"] if b["when"] == "load"):
        url, body, ctype = _beacon_url_and_body(
            beacon, first, rng_for("beacon", spec["id"], beacon["id"], "load")
        )
        recorder.add_third_party(beacon["method"], url, page_url, body, ctype, beacon["response"])

    for pid in capture_pids:
        person = people_by_id[pid]
        for endpoint in spec["endpoints"]:
            rng = rng_for("capture", spec["id"], endpoint["id"], pid)
            payload = _build_payload(endpoint, person, rng)
            sent.update((endpoint["id"], name) for name in payload)
            headers = {SIM_HEADER: pid, "referer": page_url}
            if endpoint["enctype"] == "json":
                response = client.request(
                    endpoint["method"], endpoint["path"], json=unflatten(payload), headers=headers
                )
            elif endpoint["enctype"] == "form":
                response = client.request(
                    endpoint["method"], endpoint["path"], data=payload, headers=headers
                )
            else:
                response = client.request(
                    endpoint["method"], endpoint["path"], params=payload, headers=headers
                )
            recorder.add_response(response)
        for beacon in (b for b in spec["beacons"] if b["when"] == "submit"):
            url, body, ctype = _beacon_url_and_body(
                beacon, person, rng_for("beacon", spec["id"], beacon["id"], pid)
            )
            recorder.add_third_party(
                beacon["method"], url, page_url, body, ctype, beacon["response"]
            )

    evidence = out_dir / "evidence"
    write_json(evidence / "capture.har", recorder.to_har())
    write_text(evidence / "website_snapshot.html", snapshot_html)
    write_text(evidence / bundle_filename(spec), bundle)
    return {
        "entries": len(recorder.entries),
        "hosts": sorted({urlsplit(e["request"]["url"]).netloc for e in recorder.entries}),
        "sent_fields": sorted(sent),
    }

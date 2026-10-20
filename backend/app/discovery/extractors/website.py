"""Website extraction.

Two complementary sources, recorded separately:

* The fallback parser reads the saved page: form inputs with their names, types, labels and
  autocomplete hints, and the hosts of scripts, styles, images and frames. REA's page
  inspection deliberately keeps DOM node names and attribute names but not attribute values,
  so input names and autocomplete hints are outside what the pinned release returns. That
  gap is why this parser always runs for a website.
* REA (`observe-website`: a headless browser observed over the DevTools protocol) confirms
  which hosts the page really loads from, including resources that scripts add at run time,
  and reports the accessible label and state of each control.
"""

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag

from app.discovery.candidates import ElementCandidate, RecipientCandidate

RESOURCE_TAGS = {
    "script": "src",
    "img": "src",
    "iframe": "src",
    "source": "src",
    "link": "href",
    "form": "action",
}
SKIPPED_INPUT_TYPES = {"submit", "button", "reset", "image"}


@dataclass
class HtmlParse:
    elements: list[ElementCandidate] = field(default_factory=list)
    recipients: list[RecipientCandidate] = field(default_factory=list)
    origins: set[str] = field(default_factory=set)
    controls: int = 0


def _attr(tag: Tag, name: str) -> str | None:
    """A single string for an attribute (BeautifulSoup returns a list for multi valued ones)."""
    value = tag.get(name)
    if isinstance(value, list):
        return " ".join(value)
    return value


def _label_for(soup: BeautifulSoup, control: Tag) -> str | None:
    ident = _attr(control, "id")
    if ident:
        label = soup.find("label", attrs={"for": ident})
        if label:
            return " ".join(label.get_text(" ").split())
    parent = control.find_parent("label")
    if parent:
        return " ".join(parent.get_text(" ").split())
    return _attr(control, "aria-label") or _attr(control, "placeholder") or None


def parse_html(html: str, own_host: str | None = None) -> HtmlParse:
    soup = BeautifulSoup(html, "html.parser")
    parsed = HtmlParse()
    own = (own_host or "").lower()

    for control in soup.find_all(["input", "textarea", "select"]):
        if not isinstance(control, Tag) or not control.get("name"):
            continue
        default_type = control.name if control.name in {"textarea", "select"} else "text"
        input_type = (_attr(control, "type") or default_type).lower()
        if input_type in SKIPPED_INPUT_TYPES:
            continue
        form = control.find_parent("form")
        form_ref = (
            (_attr(form, "id") or _attr(form, "action") or "form")
            if isinstance(form, Tag)
            else "page"
        )
        parsed.controls += 1
        parsed.elements.append(
            ElementCandidate(
                name=str(control["name"]),
                path=f"form:{form_ref}",
                location_kind="form_field",
                data_type=input_type,
                context={
                    "label": _label_for(soup, control),
                    "autocomplete": _attr(control, "autocomplete"),
                    "input_type": input_type,
                    "required": control.has_attr("required"),
                    "checked_by_default": control.has_attr("checked"),
                    "form_action": _attr(form, "action") if isinstance(form, Tag) else None,
                    "form_method": (
                        (_attr(form, "method") or "get").lower() if isinstance(form, Tag) else None
                    ),
                },
            )
        )

    found: dict[str, dict[str, Any]] = {}
    for tag_name, attribute in RESOURCE_TAGS.items():
        for tag in soup.find_all(tag_name):
            if not isinstance(tag, Tag) or not tag.get(attribute):
                continue
            if tag_name == "link" and not {
                "stylesheet",
                "preload",
                "preconnect",
                "dns-prefetch",
                "icon",
            } & set(tag.get("rel") or []):
                continue
            url = urlsplit(str(tag[attribute]))
            if url.scheme not in ("http", "https") or not url.hostname:
                continue
            host = url.hostname.lower()
            if host == own:
                continue
            entry = found.setdefault(host, {"types": set(), "urls": [], "origins": set()})
            entry["types"].add(tag_name)
            safe = f"{url.scheme}://{host}{url.path}"
            if safe not in entry["urls"] and len(entry["urls"]) < 5:
                entry["urls"].append(safe)
            entry["origins"].add(f"{url.scheme}://{url.netloc.split('@')[-1]}")
    for host, info in sorted(found.items()):
        parsed.origins |= info["origins"]
        parsed.recipients.append(
            RecipientCandidate(
                host=host,
                context={
                    "observed_via": ["html"],
                    "resource_types": sorted(info["types"]),
                    "urls": info["urls"],
                },
            )
        )
    return parsed


def observed_hosts_rea(
    result: dict[str, Any], own_host: str | None = None
) -> tuple[list[RecipientCandidate], dict[str, Any]]:
    """Hosts REA saw the page load or reference, plus the controls it reports (labels and states)."""
    normalized = result["evidence"]["normalized_result"]
    page_host = (urlsplit(result["page_origin"]).hostname or "").lower()
    own = (own_host or "").lower()
    seen: dict[str, dict[str, set[str]]] = {}

    def note(url: str | None, via: str) -> None:
        if not url:
            return
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme not in ("http", "https") or not host or host in {page_host, own}:
            return
        seen.setdefault(host, {"via": set(), "urls": set()})
        seen[host]["via"].add(via)
        seen[host]["urls"].add(f"{parts.scheme}://{host}{parts.path}")

    for resource in normalized.get("resources", []):
        note(resource.get("url"), "resource")
    for item in normalized.get("metadata", {}).get("dom_urls", []):
        note(item.get("url"), "dom_url")
    for request in normalized.get("network", {}).get("requests", []):
        note(request.get("url"), "network_request")
    for script in normalized.get("scripts", {}).get("items", []):
        note(script.get("url"), "script")

    recipients = [
        RecipientCandidate(
            host=host,
            context={
                "observed_via": ["browser_observation"],
                "observed_as": sorted(info["via"]),
                "urls": sorted(info["urls"])[:5],
            },
        )
        for host, info in sorted(seen.items())
    ]
    controls = [
        {
            "role": node["role"],
            "label": node.get("name"),
            "required": any(
                s["name"] == "required" and s["value"] is True for s in node.get("states", [])
            ),
        }
        for node in normalized.get("accessibility", {}).get("nodes", [])
        if node.get("role") in {"textbox", "checkbox", "combobox", "radio", "spinbutton", "button"}
        and node.get("name")
    ]
    return recipients, {"controls": controls, "title": normalized.get("target", {}).get("title")}

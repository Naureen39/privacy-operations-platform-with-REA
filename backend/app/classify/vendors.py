"""Mapping an outbound host to a vendor, its role, country and category (vendor_registry.yaml).

The first matching entry in file order wins, so specific patterns come before general ones. A
host of the organisation itself is internal. Anything else is unknown and becomes a review item.
"""

from dataclasses import dataclass

from app.classify.knowledge import Knowledge


@dataclass(frozen=True)
class VendorResolution:
    host: str
    vendor: str | None
    role: str | None
    country: str | None
    category: str | None
    internal: bool
    pattern: str | None

    @property
    def known(self) -> bool:
        return self.internal or self.vendor is not None


def _matches(host: str, pattern: str) -> bool:
    return host == pattern or host.endswith("." + pattern)


def resolve_host(host: str, knowledge: Knowledge) -> VendorResolution:
    name = host.lower().rstrip(".")
    for suffix in knowledge.first_party:
        if _matches(name, suffix):
            return VendorResolution(name, None, "controller", None, "internal", True, suffix)
    for entry in knowledge.vendors:
        if _matches(name, entry.pattern):
            return VendorResolution(
                name, entry.vendor, entry.role, entry.country, entry.category, False, entry.pattern
            )
    return VendorResolution(name, None, None, None, None, False, None)

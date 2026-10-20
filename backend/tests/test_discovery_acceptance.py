"""Phase 4 acceptance: on the reference estate, discovery recovers at least 90 percent of the
true data elements and at least 95 percent of the true recipient hosts, with either extractor.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.db.enums import EvidenceKind, Extractor
from app.discovery.candidates import ElementCandidate, Extraction, TechnologyCandidate
from app.discovery.executor import Executor, build_rea_clients
from tests.discovery_scoring import ESTATE, SYSTEM_IDS, Score, aggregate, score_system
from tests.rea_support import rea_unavailable_reason

FILES = [
    (EvidenceKind.HAR, "capture.har"),
    (EvidenceKind.WEBSITE, "website_snapshot.html"),
    (EvidenceKind.JAVASCRIPT_BUNDLE, None),
    (EvidenceKind.SQLITE_SNAPSHOT, "snapshot.sqlite"),
]


@dataclass
class EstateRun:
    scores: dict[str, Score] = field(default_factory=dict)
    extractions: dict[str, list[Extraction]] = field(default_factory=dict)
    seconds: dict[str, float] = field(default_factory=dict)

    @property
    def total(self) -> Score:
        return aggregate(list(self.scores.values()))


def run_estate(settings: Settings) -> EstateRun:
    executor = Executor(settings, build_rea_clients(settings))
    run = EstateRun()
    for system_id in SYSTEM_IDS:
        started = time.monotonic()
        evidence = ESTATE / system_id / "evidence"
        own_host: str | None = None
        elements: list[ElementCandidate] = []
        hosts: set[str] = set()
        extractions: list[Extraction] = []
        for kind, name in FILES:
            filename = name or (
                "main.bundle.js" if system_id == "staff_desktop" else "app.bundle.js"
            )
            for extraction in executor.process(
                kind, filename, (evidence / filename).read_bytes(), own_host
            ):
                extractions.append(extraction)
                if extraction.status != "ok":
                    continue
                elements += extraction.elements
                hosts |= {r.host for r in extraction.recipients}
                for note in extraction.notes:
                    if note.startswith("own_host=") and note != "own_host=None":
                        own_host = note.split("=", 1)[1]
        run.scores[system_id] = score_system(system_id, elements, hosts)
        run.extractions[system_id] = extractions
        run.seconds[system_id] = time.monotonic() - started
    return run


def assert_acceptance(run: EstateRun) -> None:
    for system_id, score in run.scores.items():
        assert score.element_recall >= 0.9, (system_id, score.missed_elements)
        assert score.host_recall >= 0.95, (system_id, score.missed_hosts)
    total = run.total
    assert total.elements_total == 72 and total.hosts_total == 19  # the reference estate
    assert total.element_recall >= 0.9 and total.host_recall >= 0.95
    assert total.location_recall >= 0.9


@pytest.fixture(scope="module")
def fallback_run(tmp_path_factory: pytest.TempPathFactory) -> EstateRun:
    settings = Settings(rea_enabled=False, rea_input_dir=str(tmp_path_factory.mktemp("stage_fb")))
    return run_estate(settings)


@pytest.fixture(scope="module")
def rea_run(tmp_path_factory: pytest.TempPathFactory) -> EstateRun:
    reason = rea_unavailable_reason()
    if reason:
        pytest.skip(reason)
    settings = Settings(
        rea_enabled=True,
        rea_input_dir=str(tmp_path_factory.mktemp("stage_rea")),
        rea_observation_ms=1000,
    )
    return run_estate(settings)


def test_fallback_parsers_meet_the_acceptance_thresholds(fallback_run: EstateRun) -> None:
    assert_acceptance(fallback_run)
    assert all(
        x.status == "ok" and x.extractor is Extractor.FALLBACK
        for xs in fallback_run.extractions.values()
        for x in xs
    )


def test_rea_meets_the_acceptance_thresholds(rea_run: EstateRun) -> None:
    assert_acceptance(rea_run)


def test_rea_is_the_extractor_for_files_and_every_run_records_its_command(
    rea_run: EstateRun,
) -> None:
    for system_id, extractions in rea_run.extractions.items():
        by_kind: dict[EvidenceKind, list[Extraction]] = {}
        for x in extractions:
            by_kind.setdefault(x.evidence_kind, []).append(x)
        for kind in (
            EvidenceKind.HAR,
            EvidenceKind.SQLITE_SNAPSHOT,
            EvidenceKind.JAVASCRIPT_BUNDLE,
        ):
            runs = by_kind[kind]
            assert [(r.extractor, r.status) for r in runs] == [(Extractor.REA, "ok")], (
                system_id,
                kind,
                [r.error for r in runs],
            )
        # Websites: the parser supplies input names, REA's browser observation confirms the hosts.
        assert [(r.extractor, r.status) for r in by_kind[EvidenceKind.WEBSITE]] == [
            (Extractor.FALLBACK, "ok"),
            (Extractor.REA, "ok"),
        ]
        for x in extractions:
            assert x.command and x.duration_ms >= 0
            assert x.raw_output and x.raw_sha256 and len(x.raw_sha256) == 64
            if x.extractor is Extractor.REA:
                assert x.rea_version == "6.7.0" and x.command.startswith("rea ")
            else:
                assert x.rea_version is None and x.command.startswith("fallback:")


def _keys(run: EstateRun, system_id: str, kind: EvidenceKind) -> set[tuple[str, ...]]:
    keys: set[tuple[str, ...]] = set()
    for x in run.extractions[system_id]:
        if (
            x.evidence_kind is kind
            and x.status == "ok"
            and not (kind is EvidenceKind.WEBSITE and x.extractor is Extractor.REA)
        ):
            keys |= {(c.location_kind, c.path, c.name) for c in x.elements}
    return keys


def _tech(run: EstateRun, system_id: str) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for x in run.extractions[system_id]:
        if x.evidence_kind is EvidenceKind.JAVASCRIPT_BUNDLE and x.status == "ok":
            found |= {(t.kind, t.name) for t in x.technologies}
    return found


def _hosts(run: EstateRun, system_id: str, kind: EvidenceKind) -> set[str]:
    return {
        r.host
        for x in run.extractions[system_id]
        if x.evidence_kind is kind and x.status == "ok"
        for r in x.recipients
    }


@pytest.mark.parametrize("system_id", SYSTEM_IDS)
def test_rea_and_fallback_find_the_same_facts(
    rea_run: EstateRun, fallback_run: EstateRun, system_id: str
) -> None:
    """The two extractors agree on network captures, SQLite schemas and bundles."""
    for kind in (EvidenceKind.HAR, EvidenceKind.SQLITE_SNAPSHOT):
        assert _keys(rea_run, system_id, kind) == _keys(fallback_run, system_id, kind), kind
    assert _hosts(rea_run, system_id, EvidenceKind.HAR) == _hosts(
        fallback_run, system_id, EvidenceKind.HAR
    )
    rea_tech, fallback_tech = _tech(rea_run, system_id), _tech(fallback_run, system_id)
    # Packages, routes, IPC channels and storage match exactly. A URL REA does not report as a literal
    # (here the Sentry DSN inside an options object) can only be missing from REA's endpoint list;
    # the hosts, compared below, still agree.
    structural = {t for t in rea_tech | fallback_tech if t[0] != "endpoint"}
    assert (
        {t for t in rea_tech if t[0] != "endpoint"}
        == {t for t in fallback_tech if t[0] != "endpoint"}
        == structural
    )
    assert {t for t in rea_tech if t[0] == "endpoint"} <= {
        t for t in fallback_tech if t[0] == "endpoint"
    }
    assert _hosts(rea_run, system_id, EvidenceKind.JAVASCRIPT_BUNDLE) == _hosts(
        fallback_run, system_id, EvidenceKind.JAVASCRIPT_BUNDLE
    )
    # REA's browser observation reports hosts the static page references.
    static_hosts = _hosts(fallback_run, system_id, EvidenceKind.WEBSITE)
    observed = {
        r.host
        for x in rea_run.extractions[system_id]
        if x.evidence_kind is EvidenceKind.WEBSITE and x.extractor is Extractor.REA
        for r in x.recipients
    }
    assert observed <= static_hosts | {"fonts.gstatic.com"}, (observed, static_hosts)
    if static_hosts:  # the browser reports the hosts the saved page references
        assert observed, (system_id, static_hosts)


def test_electron_bundle_yields_ipc_channels_and_the_database(rea_run: EstateRun) -> None:
    technologies = _tech(rea_run, "staff_desktop")
    assert {
        ("ipc_channel", c) for c in ("clock:in", "clock:out", "timesheet:submit", "profile:get")
    } <= technologies
    assert ("storage", "staff-hub.db") in technologies
    assert {
        ("package", p)
        for p in ("electron", "better-sqlite3", "electron-store", "axios", "@sentry/electron")
    } <= technologies
    assert ("route", "/clock") in technologies


def test_no_extraction_carries_sample_values(rea_run: EstateRun, fallback_run: EstateRun) -> None:
    import csv

    with (ESTATE.parent / "people" / "synthetic_people.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        emails = [row["email"] for row in csv.DictReader(handle)]
    needles = set(emails)
    for run in (rea_run, fallback_run):
        for extractions in run.extractions.values():
            for x in extractions:
                text = (
                    repr([e.context for e in x.elements])
                    + repr([r.context for r in x.recipients])
                    + repr(x.raw_output)
                )
                assert not any(needle in text for needle in list(needles)[:2000]), x.command


def test_candidates_are_typed_and_named() -> None:
    sample = ElementCandidate("n", "p", "db_column")
    assert sample.context == {} and TechnologyCandidate("x", "package").version is None


def test_discovery_stays_within_a_time_budget(rea_run: EstateRun) -> None:
    """Onboarding one system must finish in under 3 minutes; discovery is a small part of it."""
    assert max(rea_run.seconds.values()) < 60, rea_run.seconds


def test_report_for_the_record(
    rea_run: EstateRun, fallback_run: EstateRun, capsys: pytest.CaptureFixture[str]
) -> None:
    with capsys.disabled():
        print()
        for label, run in (("REA", rea_run), ("fallback", fallback_run)):
            t = run.total
            print(
                f"[discovery {label}] elements {t.elements_found}/{t.elements_total} "
                f"({t.element_recall:.1%}), locations {t.location_recall:.1%}, hosts {t.hosts_found}/{t.hosts_total} "
                f"({t.host_recall:.1%}), candidate precision {t.element_precision:.1%}, slowest system {max(run.seconds.values()):.1f}s"
            )
    assert Path(ESTATE).is_dir()
    _ = Any

"""Load sanity: a 50 MB network capture is analysed without going over a set memory limit.

    cd backend
    uv run python ../scripts/load_check.py                 # 50 MB, limit 1536 MB
    uv run python ../scripts/load_check.py --size-mb 20 --limit-mb 1024

A synthetic capture of the requested size is written, then analysed in a fresh process by the
fallback parser and, when the pinned REA release can run here, by REA. The parent samples the
resident memory of the worker and all its children (REA runs in a Node child process) every 50 ms
and reports the peak and the time. Exit status 1 when the limit is exceeded or a run fails.
"""

import argparse
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"


def write_capture(path: Path, size_bytes: int) -> int:
    """A valid HAR 1.2 file of about `size_bytes`: many requests to a few hosts with query values and
    large response bodies, the shape of a long browsing session."""
    hosts = [
        "shop.example.test",
        "cdn.example.test",
        "pixel.ads-example.test",
        "api.pay-example.test",
        "stats.example.test",
    ]
    body = "x" * 4000
    entries = 0
    with path.open("w", encoding="utf-8") as out:
        out.write(
            '{"log":{"version":"1.2","creator":{"name":"load-check","version":"1"},"entries":['
        )
        written = 0
        while written < size_bytes:
            host = hosts[entries % len(hosts)]
            entry = {
                "startedDateTime": "2026-10-01T10:00:00.000Z",
                "time": 12,
                "request": {
                    "method": "GET" if entries % 3 else "POST",
                    "url": f"https://{host}/path/{entries}?session={entries}&utm_source=load",
                    "httpVersion": "HTTP/1.1",
                    "headers": [
                        {"name": "Accept", "value": "*/*"},
                        {"name": "Cookie", "value": f"sid={entries}"},
                    ],
                    "queryString": [{"name": "session", "value": str(entries)}],
                    "cookies": [],
                    "headersSize": -1,
                    "bodySize": 0,
                    "postData": (
                        {
                            "mimeType": "application/json",
                            "text": json.dumps(
                                {"email": f"person{entries}@example.test", "id": entries}
                            ),
                        }
                        if entries % 3 == 0
                        else None
                    ),
                },
                "response": {
                    "status": 200,
                    "statusText": "OK",
                    "httpVersion": "HTTP/1.1",
                    "headers": [{"name": "Content-Type", "value": "text/plain"}],
                    "cookies": [],
                    "content": {"size": len(body), "mimeType": "text/plain", "text": body},
                    "redirectURL": "",
                    "headersSize": -1,
                    "bodySize": len(body),
                },
                "cache": {},
                "timings": {"send": 0, "wait": 10, "receive": 2},
            }
            if entry["request"]["postData"] is None:
                del entry["request"]["postData"]
            text = json.dumps(entry, separators=(",", ":"))
            out.write(("," if entries else "") + text)
            written += len(text) + 1
            entries += 1
        out.write("]}}")
    return entries


WORKER = """
import json, sys, time
sys.path.insert(0, {backend!r})
from pathlib import Path
from app.core.config import Settings
from app.db.enums import EvidenceKind
from app.discovery.executor import Executor, build_rea_clients

mode, path = sys.argv[1], Path(sys.argv[2])
settings = Settings(rea_enabled=(mode == "rea"), rea_input_dir=sys.argv[3], rea_timeout_seconds=600)
executor = Executor(settings, build_rea_clients(settings))
started = time.monotonic()
runs = executor.process(EvidenceKind.HAR, path.name, path.read_bytes(), None)
print(json.dumps({{
    "seconds": round(time.monotonic() - started, 1),
    "runs": [{{"extractor": r.extractor.value, "status": r.status, "elements": len(r.elements), "recipients": len(r.recipients), "error": r.error}} for r in runs],
}}))
"""


def measure(mode: str, capture: Path, stage: str) -> dict[str, object]:
    code = WORKER.format(backend=str(BACKEND))
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", code, mode, str(capture), stage],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=BACKEND,
    )  # fmt: skip
    peak = 0
    started = time.monotonic()
    stop = threading.Event()

    def sample() -> None:
        nonlocal peak
        root = psutil.Process(proc.pid)
        while not stop.is_set():
            try:
                total = root.memory_info().rss + sum(
                    c.memory_info().rss for c in root.children(recursive=True)
                )
                peak = max(peak, total)
            except psutil.Error:
                pass
            time.sleep(0.05)

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    out, err = proc.communicate()
    stop.set()
    thread.join()
    result: dict[str, object] = {
        "mode": mode,
        "peak_mb": round(peak / 1048576),
        "wall_seconds": round(time.monotonic() - started, 1),
        "exit": proc.returncode,
    }
    if proc.returncode == 0:
        result.update(json.loads(out.strip().splitlines()[-1]))
    else:
        result["error"] = err.strip().splitlines()[-1][:300] if err.strip() else "failed"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--size-mb", type=int, default=50)
    parser.add_argument("--limit-mb", type=int, default=1536)
    parser.add_argument("--out", default=str(BACKEND / ".eval" / "load.json"))
    args = parser.parse_args()

    sys.path.insert(0, str(BACKEND))
    from tests.rea_support import rea_unavailable_reason  # noqa: PLC0415

    modes = ["fallback"] + ([] if rea_unavailable_reason() else ["rea"])
    with tempfile.TemporaryDirectory() as tmp:
        capture = Path(tmp) / "capture.har"
        entries = write_capture(capture, args.size_mb * 1_000_000)
        size = capture.stat().st_size
        print(f"capture: {size / 1e6:.1f} MB, {entries} requests")
        results = [measure(mode, capture, str(Path(tmp) / f"stage_{mode}")) for mode in modes]
    report = {
        "capture_mb": round(size / 1e6, 1),
        "requests": entries,
        "limit_mb": args.limit_mb,
        "runs": results,
        "rea_skipped": rea_unavailable_reason(),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    for r in results:
        print(r)
    failed = [r for r in results if r["exit"] != 0 or int(str(r["peak_mb"])) > args.limit_mb]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

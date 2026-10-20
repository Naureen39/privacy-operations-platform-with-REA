"""A small web application and database store for each estate system, built from its spec.

The application serves the system's pages (with real HTML forms), accepts submissions, writes
rows to the system's SQLite database and sets cookies, exactly as described in the spec. The
capture step drives these applications to record authentic request and response pairs.

Requests identify the simulated visitor through the `x-sim-person` header. That header is a
test harness detail: it is never written to the recorded network capture.
"""

import hashlib
import html
import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from common import BASE_TIME, rng_for
from generators import GENERATORS, Person

SIM_HEADER = "x-sim-person"
GIF = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"


def visible_columns(table: dict[str, Any]) -> list[dict[str, Any]]:
    return list(table["columns"])


def create_table_sql(table: dict[str, Any], with_pid: bool) -> str:
    parts = []
    for column in visible_columns(table):
        if column["src"] == "auto":
            parts.append(f'"{column["n"]}" INTEGER PRIMARY KEY AUTOINCREMENT')
        else:
            parts.append(f'"{column["n"]}" {column["t"]}')
    if with_pid:
        parts.append('"_pid" TEXT')
    return f'CREATE TABLE "{table["name"]}" ({", ".join(parts)})'


class Store:
    """The system's live database. Rows carry a hidden `_pid` so a snapshot can be sampled."""

    def __init__(self, path: Path, spec: dict[str, Any]) -> None:
        self.path = path
        self.spec = spec
        self.tables = {t["name"]: t for t in spec["tables"]}
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        self.db = sqlite3.connect(path, check_same_thread=False)
        for table in spec["tables"]:
            self.db.execute(create_table_sql(table, with_pid=True))
        self.db.commit()

    def insert(self, table: str, values: dict[str, Any], pid: str | None) -> int:
        columns = [c for c in visible_columns(self.tables[table]) if c["src"] != "auto"]
        names = [c["n"] for c in columns]
        row = []
        for c in columns:
            value = values.get(c["n"])
            if c["t"] == "INTEGER" and value in (None, ""):
                value = 0
            elif c["t"] == "INTEGER" and isinstance(value, str):
                value = (
                    1
                    if value.lower() in ("1", "on", "true", "yes")
                    else int(value) if value.isdigit() else 0
                )
            elif c["t"] == "REAL" and isinstance(value, str):
                value = float(value)
            row.append(value)
        quoted = ", ".join(f'"{n}"' for n in [*names, "_pid"])
        marks = ", ".join("?" for _ in [*names, "_pid"])
        cursor = self.db.execute(f'INSERT INTO "{table}" ({quoted}) VALUES ({marks})', [*row, pid])
        return int(cursor.lastrowid or 0)

    def commit(self) -> None:
        self.db.commit()

    def pids(self) -> set[str]:
        found: set[str] = set()
        for name in self.tables:
            found.update(
                r[0]
                for r in self.db.execute(
                    f'SELECT DISTINCT _pid FROM "{name}" WHERE _pid IS NOT NULL'
                )
            )
        return found

    def export(self, out_path: Path, pids: set[str]) -> dict[str, int]:
        """Write a snapshot with the rows of the given people and without the hidden column."""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists():
            out_path.unlink()
        snapshot = sqlite3.connect(out_path)
        counts: dict[str, int] = {}
        ordered = sorted(pids)
        for table in self.spec["tables"]:
            name = table["name"]
            snapshot.execute(create_table_sql(table, with_pid=False))
            names = [c["n"] for c in visible_columns(table)]
            quoted = ", ".join(f'"{n}"' for n in names)
            marks = ", ".join("?" for _ in names)
            total = 0
            for chunk_start in range(0, len(ordered), 500):
                chunk = ordered[chunk_start : chunk_start + 500]
                query = f'SELECT {quoted} FROM "{name}" WHERE _pid IN ({",".join("?" for _ in chunk)}) ORDER BY rowid'
                rows = self.db.execute(query, chunk).fetchall()
                snapshot.executemany(f'INSERT INTO "{name}" ({quoted}) VALUES ({marks})', rows)
                total += len(rows)
            counts[name] = total
        snapshot.execute("PRAGMA user_version = 1")
        snapshot.commit()
        snapshot.close()
        return counts

    def close(self) -> None:
        self.db.commit()
        self.db.close()


def _flatten(prefix: str, value: Any, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            _flatten(f"{prefix}.{key}" if prefix else key, inner, out)
    else:
        out[prefix] = value


def unflatten(fields: dict[str, Any]) -> dict[str, Any]:
    nested: dict[str, Any] = {}
    for key, value in fields.items():
        node = nested
        parts = key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return nested


def render_field(field: dict[str, Any]) -> str:
    name = html.escape(field["name"], quote=True)
    ident = "f_" + name.replace(".", "_")
    label = html.escape(field["label"])
    attrs = f' name="{name}" id="{ident}"'
    if field["autocomplete"]:
        attrs += f' autocomplete="{html.escape(field["autocomplete"], quote=True)}"'
    if field["required"]:
        attrs += " required"
    if field["type"] == "textarea":
        control = f"<textarea{attrs}></textarea>"
    elif field["type"] == "hidden":
        return f'<input type="hidden"{attrs} value="">'
    else:
        if field["checked"]:
            attrs += " checked"
        control = f'<input type="{field["type"]}"{attrs}>'
    return f'<p><label for="{ident}">{label}</label> {control}</p>'


def render_page(spec: dict[str, Any], page: dict[str, Any]) -> str:
    esc = html.escape
    out = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        f'<head><meta charset="utf-8"><title>{esc(page["title"])}</title>',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
    ]
    out += [f'<link rel="stylesheet" href="{esc(url, quote=True)}">' for url in page["styles"]]
    out.append("</head>")
    out.append(f'<body><main><h1>{esc(page["heading"])}</h1><p>{esc(page["intro"])}</p>')
    for endpoint in spec["endpoints"]:
        if endpoint["page"] != page["path"] or endpoint["enctype"] == "query":
            continue
        action = esc(endpoint["path"], quote=True)
        fmt = ' data-format="json"' if endpoint["enctype"] == "json" else ""
        out.append(f'<form id="{endpoint["id"]}" method="post" action="{action}"{fmt}>')
        out += [render_field(f) for f in endpoint["fields"]]
        out.append(f'<button type="submit">{esc(endpoint["submit_label"])}</button></form>')
    out += [
        f'<iframe src="{esc(url, quote=True)}" title="embedded content"></iframe>'
        for url in page["iframes"]
    ]
    out += [f'<img src="{esc(url, quote=True)}" alt="">' for url in page["images"]]
    out.append("</main>")
    out += [f'<script src="{esc(url, quote=True)}"></script>' for url in page["scripts"]]
    out.append("</body></html>")
    return "\n".join(out)


class SimClock:
    """Deterministic clock: every call advances five seconds from the capture start."""

    def __init__(self) -> None:
        from datetime import datetime, timedelta

        self.current = datetime.fromisoformat(BASE_TIME.replace("Z", "+00:00"))
        self._step = timedelta(seconds=5)

    def now(self) -> str:
        self.current += self._step
        return self.current.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_app(
    spec: dict[str, Any],
    store: Store,
    people: dict[str, Person],
    assets: dict[str, tuple[str, str]],
) -> FastAPI:
    app = FastAPI(title=spec["name"], docs_url=None, redoc_url=None, openapi_url=None)
    clock = SimClock()
    counter = {"n": 0}

    def person_of(request: Request) -> Person:
        return people[request.headers[SIM_HEADER]]

    def cookie_value(name: str, ip: str) -> str:
        return hashlib.sha256(f"{spec['id']}:{name}:{ip}".encode()).hexdigest()[:24]

    def make_page_handler(page: dict[str, Any]) -> Any:
        async def handler(request: Request) -> Response:
            person = person_of(request)
            response = HTMLResponse(render_page(spec, page))
            for cookie in page["cookies"]:
                response.set_cookie(
                    cookie["name"], cookie_value(cookie["name"], person["ip_address"]),
                    max_age=cookie["max_age"], httponly=cookie["http_only"], secure=True, samesite="lax", path="/",
                )  # fmt: skip
            return response

        return handler

    def resolve_write(expr: str, fields: dict[str, Any], person: Person, rng: Any) -> Any:
        if expr == "ip":
            return person["ip_address"]
        if expr == "now":
            return clock.now()
        kind, _, rest = expr.partition(":")
        if kind == "field":
            return fields.get(rest)
        if kind == "person":
            return person[rest]
        if kind == "gen":
            return GENERATORS[rest](person, rng)
        if kind == "const":
            return rest
        raise ValueError(expr)

    def build_response(template: Any, fields: dict[str, Any], person: Person, last_id: int) -> Any:
        if isinstance(template, dict):
            return {k: build_response(v, fields, person, last_id) for k, v in template.items()}
        if isinstance(template, str) and template.startswith("$"):
            if template == "$last_id":
                return last_id
            kind, _, rest = template[1:].partition(":")
            return fields.get(rest) if kind == "field" else person[rest]
        return template

    def make_endpoint_handler(endpoint: dict[str, Any]) -> Any:
        async def handler(request: Request) -> Response:
            person = person_of(request)
            fields: dict[str, Any] = {}
            if endpoint["enctype"] == "json":
                _flatten("", await request.json(), fields)
            elif endpoint["enctype"] == "form":
                fields = {k: v for k, v in (await request.form()).items()}
            else:
                fields = dict(request.query_params)
            missing = [
                f["name"] for f in endpoint["fields"] if f["required"] and not fields.get(f["name"])
            ]
            if missing:
                return JSONResponse({"error": "missing fields", "fields": missing}, status_code=422)
            counter["n"] += 1
            rng = rng_for("app", spec["id"], counter["n"])
            last_id = 0
            for write in endpoint["writes"]:
                values = {
                    col: resolve_write(expr, fields, person, rng)
                    for col, expr in write["map"].items()
                }
                last_id = store.insert(write["table"], values, person["person_id"])
            if endpoint["response"] == {}:
                return Response(GIF, media_type="image/gif")
            body = build_response(endpoint["response"], fields, person, last_id)
            return JSONResponse(body)

        return handler

    for page in spec["pages"]:
        app.add_api_route(
            page["path"], make_page_handler(page), methods=["GET"], include_in_schema=False
        )
    for endpoint in spec["endpoints"]:
        route = endpoint["path"].split("?")[0]
        app.add_api_route(
            route,
            make_endpoint_handler(endpoint),
            methods=[endpoint["method"]],
            include_in_schema=False,
        )

    async def asset(request: Request, path: str) -> Response:
        full = "/" + path
        if full in assets:
            content_type, body = assets[full]
            return Response(body, media_type=content_type)
        if full.endswith(".css"):
            return Response("/* styles */", media_type="text/css")
        return Response("not found", status_code=404)

    app.add_api_route("/{path:path}", asset, methods=["GET"], include_in_schema=False)
    return app


def dumps(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False)

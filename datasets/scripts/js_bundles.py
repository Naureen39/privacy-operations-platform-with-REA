"""Generate the JavaScript bundle of each system from its spec.

The bundles are small, readable stand-ins for built front-end code. They contain what a static
analysis of a real bundle would find: imported packages, routes, endpoint URLs, SDK
initialisation, IPC channels (Electron) and the database schema statements.
"""

import re
from typing import Any

from estate_apps import create_table_sql


def bundle_filename(spec: dict[str, Any]) -> str:
    return "main.bundle.js" if spec["js"]["kind"] == "electron" else "app.bundle.js"


def _identifier(package: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", package.split("/")[-1]).strip("_") or "pkg"


# How an Electron main process usually binds the packages it uses.
ELECTRON_BINDINGS = {
    "electron": "{ app, BrowserWindow, ipcMain, contextBridge, ipcRenderer }",
    "better-sqlite3": "Database",
    "electron-store": "Store",
    "@sentry/electron": "Sentry",
}


def _module_map(modules: list[str]) -> str:
    lines = [
        f'  "./node_modules/{m}/index.js": function (module, exports) {{ /* {m} */ }},'
        for m in modules
    ]
    return "\n".join(lines)


def _web_bundle(spec: dict[str, Any]) -> str:
    js = spec["js"]
    requires = "\n".join(f'  var {_identifier(m)} = require("{m}");' for m in js["modules"])
    routes = ",\n".join(f'    {{ path: "{r}", component: "page" }}' for r in js["routes"])
    endpoints = "\n".join(f'  var ENDPOINT_{i} = "{u}";' for i, u in enumerate(js["endpoints"]))
    sends = "\n".join(
        f'  function send_{i}(payload) {{ return fetch(ENDPOINT_{i}, {{ method: "POST", body: JSON.stringify(payload) }}); }}'
        for i in range(len(js["endpoints"]))
    )
    init = "\n".join(f"  {line}" for line in js["init"])
    return f"""/*! {js['title']} - generated for the Northbridge demonstration estate */
(function (modules) {{
  var cache = {{}};
  function __require(id) {{
    if (cache[id]) return cache[id].exports;
    var module = (cache[id] = {{ exports: {{}} }});
    modules[id](module, module.exports, __require);
    return module.exports;
  }}
  __require("./src/index.js");
}})({{
{_module_map(js['modules'])}
  "./src/index.js": function (module, exports, __require) {{
{requires}
  var ROUTES = [
{routes}
  ];
{endpoints}
{sends}
{init}
  }}
}});
"""


def _electron_bundle(spec: dict[str, Any]) -> str:
    js = spec["js"]
    requires = "\n".join(
        f'const {ELECTRON_BINDINGS.get(m, _identifier(m))} = require("{m}");' for m in js["modules"]
    )
    requires += '\nconst path = require("path");'
    handlers = "\n".join(
        f'ipcMain.handle("{channel}", async (event, payload) => {{ /* handler for {channel} */ }});'
        for channel in js["ipc"]
    )
    bridge = ", ".join(f'"{c}": (p) => ipcRenderer.invoke("{c}", p)' for c in js["ipc"])
    routes = "\n".join(f'  {{ path: "{r}" }},' for r in js["routes"])
    endpoints = "\n".join(f'const API_{i} = "{u}";' for i, u in enumerate(js["endpoints"]))
    schema = "\n".join(f"db.exec(`{create_table_sql(t, with_pid=False)}`);" for t in spec["tables"])
    init = "\n".join(js["init"])
    return f"""/*! {js['title']} - generated for the Northbridge demonstration estate */
// ==== main process (main.js) ====
{requires}
const db = new Database("staff-hub.db");
{schema}
{endpoints}
{init}
{handlers}
app.whenReady().then(() => {{
  const win = new BrowserWindow({{
    webPreferences: {{ preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false }},
  }});
  win.loadFile("renderer/index.html");
}});

// ==== preload (preload.js) ====
contextBridge.exposeInMainWorld("staffHub", {{ {bridge} }});

// ==== renderer routes ====
const routes = [
{routes}
];
"""


def render_bundle(spec: dict[str, Any]) -> str:
    return _electron_bundle(spec) if spec["js"]["kind"] == "electron" else _web_bundle(spec)

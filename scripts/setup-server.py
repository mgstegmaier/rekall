#!/usr/bin/env python3
"""Rekall's local settings page. Standard library only. Today it covers the optional Microsoft
Graph ingest.

Run `python3 scripts/setup-server.py` and open http://localhost:8086, as often as you like: it
reads rekall.toml and .env fresh on every load. The page shows:
- each secret Rekall reads, present or missing (never the value), and whether `claude` is on PATH;
- Graph sign-in status (a token refresh plus /me) and a Sign in button;
- your Teams chats with a checkbox each, the mail folders, and the on/off switch;
- Save, which rewrites only the [graph] section of rekall.toml.

Sign-in uses the same Entra app and auth-code flow as cos-desk's msgraph-auth.py: it needs
MSGRAPH_CLIENT_ID, MSGRAPH_CLIENT_SECRET and MSGRAPH_TENANT_ID, and the app must list
http://localhost:8086 as a "Mobile and desktop applications" redirect URI. The new refresh token
goes into .env (mode 600). Doppler users: start it under `doppler run -- python3 scripts/setup-server.py`.

Local only, with Radar's /setup guards: binds 127.0.0.1, rejects any Host but localhost:8086 or
127.0.0.1:8086, every POST needs a matching Origin and `X-Rekall-Setup: 1`, and the OAuth callback
checks a one-time state value.
"""
import http.server
import importlib.util
import json
import os
import re
import secrets
import shutil
import sys
import tomllib
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

_spec = importlib.util.spec_from_file_location("graph_ingest", Path(__file__).parent / "graph-ingest.py")
gi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gi)
fp = gi.fp

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path(os.environ.get("REKALL_CONFIG", ROOT / "rekall.toml"))
ENV_FILE = ROOT / ".env"
PORT = 8086  # the redirect URI registered on the Entra app, shared with cos-desk's msgraph-auth.py
REDIRECT = f"http://localhost:{PORT}"
SIGNIN_SCOPE = "offline_access User.Read Mail.Read Chat.ReadBasic Chat.Read"
HOSTS = {f"localhost:{PORT}", f"127.0.0.1:{PORT}"}
SECRETS = ["FATHOM_API_KEY", "WORK_EMAIL", "MSGRAPH_CLIENT_ID", "MSGRAPH_CLIENT_SECRET",
           "MSGRAPH_TENANT_ID", "MSGRAPH_REFRESH_TOKEN"]
STATES = set()  # one-time OAuth state values


def load_env_file():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and re.fullmatch(r"[A-Z_][A-Z0-9_]*", k.strip()) and v.strip():
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def set_env_var(key, value):
    """Set KEY=value in .env, keeping every other line. Creates the file (mode 600) if missing."""
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
    out, done = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == key:
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(out) + "\n")
    ENV_FILE.chmod(0o600)
    os.environ[key] = value


def graph_section(enabled, folders, chats):
    q = lambda v: json.dumps(v, ensure_ascii=False)  # a JSON string is a TOML basic string; raw UTF-8, since TOML rejects surrogate escapes
    rows = "".join(f"  {{ id = {q(c['id'])}, name = {q(c['name'])} }},\n" for c in chats)
    return ("[graph]\n# Written by scripts/setup-server.py. Only the chats listed here are read.\n"
            f"enabled = {'true' if enabled else 'false'}\n"
            f"mail_folders = [{', '.join(q(f) for f in folders)}]\n"
            + (f"chats = [\n{rows}]\n" if chats else "chats = []\n"))


def replace_section(text, name, new):
    """text with its [name] section (header to the next [table] line) swapped for new, or new appended.
    To add another setting to this page: render its section, then call this with its table name."""
    lines, out, skipping = text.split("\n"), [], False
    for line in lines:
        if re.match(r"^\s*\[", line):
            skipping = line.strip() == f"[{name}]"
            if skipping:
                continue
        if not skipping:
            out.append(line)
    body = "\n".join(out).rstrip("\n")
    return body + "\n\n" + new


def save_config(data):
    folders = [f for f in data.get("folders", []) if re.fullmatch(r"[A-Za-z0-9_=-]{1,200}", f)] or ["inbox", "sentitems"]
    chats = [{"id": str(c["id"]), "name": str(c.get("name") or "Teams chat")[:120]} for c in data.get("chats", [])
             if re.fullmatch(r"19:[^\s\"\\]{1,300}", str(c.get("id", "")))]
    text = replace_section(CONFIG.read_text(encoding="utf-8"), "graph", graph_section(bool(data.get("enabled")), folders, chats))
    parsed = tomllib.loads(text)["graph"]  # refuse to write a file that doesn't parse back
    assert [c["id"] for c in parsed["chats"]] == [c["id"] for c in chats]
    tmp = CONFIG.with_suffix(".toml.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(CONFIG)
    return parsed


def graph_status():
    if not all(os.environ.get(k) for k in SECRETS[2:]):
        return {"ok": False, "error": "One or more MSGRAPH_* secrets are missing."}
    try:
        tok = gi.graph_token()
        me = gi.graph_get("/me?$select=displayName,mail,userPrincipalName", tok)
        return {"ok": True, "user": me.get("displayName"), "mail": me.get("mail") or me.get("userPrincipalName")}
    except fp.urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")
        expired = "AADSTS700082" in body
        return {"ok": False, "error": "The refresh token expired. Sign in again." if expired else f"Graph refused: HTTP {e.code}"}
    except Exception as e:  # network down, proxy CA, etc.
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}


def list_chats():
    tok = gi.graph_token()
    me = gi.graph_get("/me?$select=id", tok).get("id")
    q = urlencode({"$expand": "members", "$select": "id,topic,chatType,lastUpdatedDateTime", "$top": 50})
    out = []
    for c in gi.graph_pages(f"/me/chats?{q}", tok, max_pages=6):
        others = [m.get("displayName") for m in c.get("members") or [] if m.get("userId") != me and m.get("displayName")]
        out.append({"id": c["id"], "name": c.get("topic") or ", ".join(others[:4]) or "(unnamed chat)",
                    "type": c.get("chatType"), "updated": c.get("lastUpdatedDateTime") or ""})
    return sorted(out, key=lambda c: c["updated"], reverse=True)


def status():
    cfg = tomllib.loads(CONFIG.read_text(encoding="utf-8")).get("graph", {})
    return {"secrets": [{"name": k, "present": bool(os.environ.get(k))} for k in SECRETS],
            "claude": bool(shutil.which("claude")), "graph": graph_status(),
            "config": {"enabled": bool(cfg.get("enabled")), "folders": cfg.get("mail_folders", ["inbox", "sentitems"]),
                       "chats": cfg.get("chats", [])},
            "config_path": str(CONFIG)}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # keep OAuth codes out of the terminal
        sys.stderr.write(f"{self.command} {urlparse(self.path).path} {args[1] if len(args) > 1 else ''}\n")

    def send(self, code, body, ctype="application/json", headers=None):
        data = body if isinstance(body, bytes) else (json.dumps(body) if ctype == "application/json" else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def host_ok(self):
        if self.headers.get("Host") not in HOSTS:
            self.send(403, {"error": "local only"})
            return False
        return True

    def do_GET(self):
        if not self.host_ok():
            return
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/" and "code" in q:
            return self.callback(q)
        if url.path == "/" and "error" in q:
            return self.send(400, f"Sign-in failed: {q.get('error_description', q['error'])[0][:300]}", "text/plain")
        if url.path == "/":
            return self.send(200, PAGE, "text/html")
        if url.path == "/signin":
            missing = [k for k in SECRETS[2:5] if not os.environ.get(k)]
            if missing:
                return self.send(400, f"Missing {', '.join(missing)}. Add them to .env first.", "text/plain")
            state = secrets.token_urlsafe(24)
            STATES.add(state)
            auth = (f"https://login.microsoftonline.com/{os.environ['MSGRAPH_TENANT_ID']}/oauth2/v2.0/authorize?"
                    + urlencode({"client_id": os.environ["MSGRAPH_CLIENT_ID"], "response_type": "code",
                                 "redirect_uri": REDIRECT, "response_mode": "query", "scope": SIGNIN_SCOPE,
                                 "state": state, "prompt": "select_account"}))
            return self.send(302, b"", "text/plain", {"Location": auth})
        if url.path == "/api/status":
            return self.send(200, status())
        if url.path == "/api/chats":
            try:
                return self.send(200, {"chats": list_chats()})
            except Exception as e:
                return self.send(502, {"error": f"{type(e).__name__}: {e}"[:200]})
        self.send(404, {"error": "not found"})

    def callback(self, q):
        state = q.get("state", [""])[0]
        if state not in STATES:
            return self.send(400, "Unknown sign-in state. Start again from the setup page.", "text/plain")
        STATES.discard(state)
        body = urlencode({"client_id": os.environ["MSGRAPH_CLIENT_ID"], "client_secret": os.environ["MSGRAPH_CLIENT_SECRET"],
                          "code": q["code"][0], "redirect_uri": REDIRECT, "grant_type": "authorization_code",
                          "scope": SIGNIN_SCOPE}).encode()
        req = fp.urllib.request.Request(
            f"https://login.microsoftonline.com/{os.environ['MSGRAPH_TENANT_ID']}/oauth2/v2.0/token", data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with fp.urllib.request.urlopen(req, timeout=30, context=fp.SSL_CTX) as resp:
                tokens = json.loads(resp.read().decode())
        except fp.urllib.error.HTTPError as e:
            return self.send(400, f"Token exchange failed: HTTP {e.code} {e.read().decode(errors='ignore')[:300]}", "text/plain")
        if not tokens.get("refresh_token"):
            return self.send(400, "Microsoft returned no refresh token (offline_access missing?).", "text/plain")
        set_env_var("MSGRAPH_REFRESH_TOKEN", tokens["refresh_token"])
        self.send(302, b"", "text/plain", {"Location": "/"})

    def do_POST(self):
        if not self.host_ok():
            return
        origin = self.headers.get("Origin")
        if origin not in {f"http://{h}" for h in HOSTS} or self.headers.get("X-Rekall-Setup") != "1":
            return self.send(403, {"error": "bad origin or missing X-Rekall-Setup header"})
        n = int(self.headers.get("Content-Length") or 0)
        if n > 64_000:
            return self.send(413, {"error": "too large"})
        if urlparse(self.path).path != "/api/config":
            return self.send(404, {"error": "not found"})
        try:
            return self.send(200, {"saved": save_config(json.loads(self.rfile.read(n) or b"{}"))})
        except Exception as e:
            return self.send(400, {"error": f"{type(e).__name__}: {e}"[:200]})


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rekall settings</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@500;600&family=Lora:ital,wght@0,400;0,500;1,400&display=swap" rel="stylesheet">
<style>
/* All Mammal palette (rekall's opt-in brand for this page). Dark follows the viewer's OS. */
:root {
  color-scheme: light;
  --ground: #faf9f5; --surface: #ffffff; --surface-2: #e8e6dc; --ink: #141413; --ink-muted: #5f5e5a;
  --stone: #b0aea5; --accent: #d97757; --accent-text: #b8542e; --olive: #788c5d; --line: rgba(20, 20, 19, 0.12);
  --font-heading: "Styrene A", "Styrene B", Poppins, Arial, sans-serif;
  --font-body: "Tiempos Text", Lora, Georgia, serif;
  --font-mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  --space-xs: 4px; --space-sm: 8px; --space-md: 12px; --space-lg: 16px; --space-xl: 24px; --space-2xl: 32px; --space-3xl: 48px;
  --radius-sm: 8px; --radius: 12px;
  --tint: 22%;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --ground: #141413; --surface: #1f1e1b; --surface-2: #2a2926; --ink: #faf9f5; --ink-muted: #b0aea5;
    --stone: #5f5e5a; --accent-text: #e08a6b; --line: rgba(250, 249, 245, 0.14); --tint: 38%;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --ground: #141413; --surface: #1f1e1b; --surface-2: #2a2926; --ink: #faf9f5; --ink-muted: #b0aea5;
  --stone: #5f5e5a; --accent-text: #e08a6b; --line: rgba(250, 249, 245, 0.14); --tint: 38%;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--ground); color: var(--ink); font: 400 1rem/1.6 var(--font-body); }
main { max-width: 44rem; margin: 0 auto; padding: var(--space-3xl) var(--space-lg) var(--space-3xl); }
.masthead { font: 500 0.75rem/1 var(--font-heading); letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-muted); margin: 0 0 var(--space-xl); }
.masthead b { color: var(--ink); font-weight: 600; }
h1 { font: 500 2rem/1.15 var(--font-heading); margin: 0 0 var(--space-sm); text-wrap: balance; }
.lead { color: var(--ink-muted); margin: 0 0 var(--space-2xl); max-width: 36rem; }
section { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: var(--space-xl); margin-bottom: var(--space-lg); }
h2 { font: 500 1.125rem/1.3 var(--font-heading); margin: 0 0 var(--space-xs); }
.hint { color: var(--ink-muted); font-size: 0.9375rem; margin: 0 0 var(--space-lg); }
code { font: 0.875em var(--font-mono); background: var(--surface-2); padding: 1px 5px; border-radius: 4px; }
table { width: 100%; border-collapse: collapse; }
th { text-align: left; font: 600 0.6875rem/1 var(--font-heading); letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-muted); padding: 0 0 var(--space-sm); border-bottom: 1px solid var(--stone); }
td { padding: var(--space-sm) 0; border-bottom: 1px solid var(--line); vertical-align: middle; }
tr:last-child td { border-bottom: none; }
td:last-child, th:last-child { text-align: right; }
.tag { display: inline-block; font: 600 0.75rem/1 var(--font-heading); color: var(--ink); padding: 5px 10px; border-radius: 999px; }
.tag.ok { background: color-mix(in srgb, var(--olive) var(--tint), var(--surface)); }
.tag.bad { background: color-mix(in srgb, var(--accent) var(--tint), var(--surface)); }
.account { display: flex; align-items: center; justify-content: space-between; gap: var(--space-lg); flex-wrap: wrap; }
.account p { margin: 0; }
.account .who { font-family: var(--font-heading); font-weight: 500; }
.account .sub { color: var(--ink-muted); font-size: 0.9375rem; }
.btn { font: 500 0.9375rem/1 var(--font-heading); padding: 10px 18px; border-radius: var(--radius-sm); border: 1px solid transparent; cursor: pointer; text-decoration: none; display: inline-block; transition: background-color 150ms ease-out, border-color 150ms ease-out; }
.btn-secondary { background: transparent; color: var(--ink); border-color: var(--ink); }
.btn-secondary:hover { background: var(--surface-2); }
.btn-accent { background: var(--accent); color: #141413; }
.btn-accent:hover { background: color-mix(in srgb, var(--accent) 88%, #141413); }
.btn:focus-visible, input:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.chat-tools { display: flex; gap: var(--space-md); align-items: center; flex-wrap: wrap; margin-bottom: var(--space-md); }
.chat-tools input { flex: 1 1 14rem; }
input[type=text], input[type=search] { font: 400 1rem var(--font-body); color: var(--ink); background: var(--surface); border: 1px solid var(--stone); border-radius: var(--radius-sm); padding: 9px 12px; width: 100%; }
input::placeholder { color: var(--stone); }
#chats { max-height: 22rem; overflow-y: auto; background: var(--surface-2); border-radius: var(--radius-sm); padding: var(--space-xs) var(--space-lg); }
#chats:empty { display: none; }
#chats label { display: flex; align-items: baseline; gap: var(--space-md); padding: var(--space-sm) 0; border-bottom: 1px solid var(--line); cursor: pointer; }
#chats label:last-child { border-bottom: none; }
#chats .type { color: var(--ink-muted); font: 500 0.75rem var(--font-heading); margin-left: auto; white-space: nowrap; }
input[type=checkbox] { accent-color: var(--accent); width: 16px; height: 16px; flex: none; position: relative; top: 2px; }
.count { color: var(--ink-muted); font-size: 0.9375rem; margin: var(--space-md) 0 0; }
.switch { display: flex; gap: var(--space-md); align-items: flex-start; cursor: pointer; }
.switch .hint { display: block; margin: var(--space-xs) 0 0; }
.switch strong { font: 500 1rem/1.4 var(--font-heading); display: block; }
.savebar { display: flex; align-items: center; gap: var(--space-lg); flex-wrap: wrap; margin-top: var(--space-xl); padding-top: var(--space-xl); border-top: 1px solid var(--line); }
#msg { margin: 0; color: var(--ink-muted); font-size: 0.9375rem; }
.callout { border-left: 3px solid var(--accent); background: var(--surface-2); border-radius: 0 var(--radius-sm) var(--radius-sm) 0; padding: var(--space-md) var(--space-lg); margin-top: var(--space-xl); font-size: 0.9375rem; }
.callout p { margin: 0; }
.callout code { background: var(--surface); }
.callout .cmd { display: block; margin-top: var(--space-sm); padding: var(--space-sm) var(--space-md); overflow-x: auto; white-space: nowrap; }
footer { font: 500 0.75rem/1.5 var(--font-heading); letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-muted); margin-top: var(--space-2xl); }
@media (prefers-reduced-motion: reduce) { .btn { transition: none; } }
@media (max-width: 480px) { main { padding-top: var(--space-2xl); } section { padding: var(--space-lg); } }
</style></head><body><main>
<p class="masthead">Rekall · <b>settings</b> · this machine only</p>
<h1>Settings</h1>
<p class="lead">Rekall can read your mail and the Teams chats you pick, and add new project facts and decisions to the wiki pages they name. It never sends mail or posts to Teams. Come back to this page any time to change what it reads.</p>

<section aria-labelledby="h-secrets">
  <h2 id="h-secrets">Secrets</h2>
  <p class="hint">Read from <code>.env</code> in the rekall folder or the environment. Values are never shown here.</p>
  <table><thead><tr><th scope="col">Name</th><th scope="col">Status</th></tr></thead><tbody id="secrets"></tbody></table>
</section>

<section aria-labelledby="h-account">
  <h2 id="h-account">Microsoft account</h2>
  <p class="hint">Sign-in uses your Entra app. The new token goes into <code>.env</code>.</p>
  <div class="account"><div id="graph"><p class="sub">Checking...</p></div><a class="btn btn-secondary" href="/signin" id="signin">Sign in with Microsoft</a></div>
</section>

<section aria-labelledby="h-chats">
  <h2 id="h-chats">Teams chats</h2>
  <p class="hint">Only the chats you tick are read. Every other chat is ignored.</p>
  <div class="chat-tools">
    <button class="btn btn-secondary" id="load" type="button">Load my chats</button>
    <input type="search" id="filter" placeholder="Filter by name" aria-label="Filter chats by name" hidden>
  </div>
  <div id="chats"></div>
  <p class="count" id="count"></p>
</section>

<section aria-labelledby="h-mail">
  <h2 id="h-mail">Mail folders</h2>
  <p class="hint">Comma separated: a well-known name like <code>inbox</code> or <code>sentitems</code>, or a folder id.</p>
  <input type="text" id="folders" aria-labelledby="h-mail">
</section>

<section aria-labelledby="h-save">
  <h2 id="h-save">Mail and Teams ingest</h2>
  <label class="switch"><input type="checkbox" id="enabled"><span><strong>Turn on the ingest</strong><span class="hint">Saving writes the choices above to the <code>[graph]</code> section of <code id="cfg">rekall.toml</code>. Nothing else in the file changes.</span></span></label>
  <div class="savebar"><button class="btn btn-accent" id="save" type="button">Save</button><p id="msg" role="status"></p></div>
  <div class="callout"><p>Check what it would write, without touching the vault:</p><code class="cmd">bash scripts/run-graph-ingest.sh --dry-run --hours 24</code></div>
</section>

<footer>Runs on 127.0.0.1 and stops when you press Ctrl-C in the terminal.</footer>
</main>
<script>
let saved = [];
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const tag = (ok, yes, no) => `<span class="tag ${ok ? "ok" : "bad"}">${ok ? yes : no}</span>`;
async function refresh() {
  const s = await (await fetch("/api/status")).json();
  $("secrets").innerHTML = s.secrets.map(x => `<tr><td><code>${x.name}</code></td><td>${tag(x.present, "Present", "Missing")}</td></tr>`).join("")
    + `<tr><td><code>claude</code> on PATH</td><td>${tag(s.claude, "Found", "Missing")}</td></tr>`;
  $("graph").innerHTML = s.graph.ok
    ? `<p class="who">${esc(s.graph.user)}</p><p class="sub">${esc(s.graph.mail)}</p>`
    : `<p class="who">Not signed in</p><p class="sub">${esc(s.graph.error)}</p>`;
  $("signin").textContent = s.graph.ok ? "Switch account" : "Sign in with Microsoft";
  $("enabled").checked = s.config.enabled;
  $("folders").value = s.config.folders.join(", ");
  $("cfg").textContent = s.config_path.split("/").pop();
  saved = s.config.chats;
  renderChats(saved, saved.map(c => c.id));
}
function count() {
  const n = document.querySelectorAll("#chats input:checked").length;
  $("count").textContent = $("chats").children.length ? `${n} ${n === 1 ? "chat" : "chats"} selected` : "";
}
function renderChats(list, picked) {
  $("chats").innerHTML = list.map(c => `<label data-name="${esc(c.name.toLowerCase())}"><input type="checkbox" value="${esc(c.id)}" data-name="${esc(c.name)}" ${picked.includes(c.id) ? "checked" : ""}>
    <span>${esc(c.name)}</span>${c.type ? `<span class="type">${c.type === "oneOnOne" ? "1:1" : c.type === "group" ? "Group" : esc(c.type)}</span>` : ""}</label>`).join("");
  count();
}
$("chats").addEventListener("change", count);
$("filter").addEventListener("input", e => {
  const q = e.target.value.toLowerCase();
  for (const l of $("chats").children) l.hidden = q && !l.dataset.name.includes(q);
});
$("load").onclick = async () => {
  $("load").textContent = "Loading...";
  const r = await (await fetch("/api/chats")).json();
  $("load").textContent = "Reload chats";
  if (r.error) { $("count").textContent = r.error; return; }
  const picked = [...document.querySelectorAll("#chats input:checked")].map(i => i.value);
  const ids = new Set(r.chats.map(c => c.id));
  renderChats(r.chats.concat(saved.filter(c => !ids.has(c.id))), picked);
  $("filter").hidden = false;
};
$("save").onclick = async () => {
  const chats = [...document.querySelectorAll("#chats input:checked")].map(i => ({id: i.value, name: i.dataset.name}));
  const folders = $("folders").value.split(",").map(s => s.trim()).filter(Boolean);
  const r = await (await fetch("/api/config", {method: "POST", headers: {"Content-Type": "application/json", "X-Rekall-Setup": "1"},
    body: JSON.stringify({enabled: $("enabled").checked, folders, chats})})).json();
  $("msg").textContent = r.error ? r.error : `Saved. Ingest ${r.saved.enabled ? "on" : "off"}, ${r.saved.chats.length} chats, folders: ${r.saved.mail_folders.join(", ")}.`;
  if (!r.error) saved = r.saved.chats;
};
refresh();
</script></body></html>
"""


def main():
    load_env_file()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Rekall setup: open {REDIRECT}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

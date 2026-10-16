#!/usr/bin/env python3
"""Local setup page for the optional Microsoft Graph ingest. Standard library only.

Run `python3 scripts/setup-server.py` and open http://localhost:8086. The page shows:
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


def replace_graph_section(text, new):
    """text with its [graph] section (header to the next [table] line) swapped for new, or new appended."""
    lines, out, skipping = text.split("\n"), [], False
    for line in lines:
        if re.match(r"^\s*\[", line):
            skipping = line.strip() == "[graph]"
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
    text = replace_graph_section(CONFIG.read_text(encoding="utf-8"), graph_section(bool(data.get("enabled")), folders, chats))
    parsed = tomllib.loads(text)["graph"]  # refuse to write a file that doesn't parse back
    assert [c["id"] for c in parsed["chats"]] == [c["id"] for c in chats]
    tmp = CONFIG.with_suffix(".toml.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(CONFIG)
    return parsed


def graph_status():
    if not all(os.environ.get(k) for k in SECRETS[2:]):
        return {"ok": False, "error": "Not signed in: one or more MSGRAPH_* secrets are missing."}
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
<title>Rekall setup</title>
<style>
:root { --bg: #fafaf8; --fg: #1d1d1b; --muted: #6b6b66; --line: #deded8; --ok: #2f7a3e; --bad: #b3261e; --accent: #1f5fae; }
@media (prefers-color-scheme: dark) { :root { --bg: #161615; --fg: #ececea; --muted: #a0a09a; --line: #34342f; --ok: #6cc47f; --bad: #f2867d; --accent: #8ab4f0; } }
body { background: var(--bg); color: var(--fg); font: 16px/1.5 system-ui, sans-serif; margin: 0; padding: 32px 16px; }
main { max-width: 680px; margin: 0 auto; }
h1 { font-size: 1.5rem; margin: 0 0 4px; } h2 { font-size: 1.1rem; margin: 32px 0 8px; }
p.lead, .muted { color: var(--muted); }
ul.checks { list-style: none; padding: 0; margin: 0; }
ul.checks li { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--line); }
code { font: 0.9em ui-monospace, monospace; }
.ok { color: var(--ok); } .bad { color: var(--bad); }
button, a.button { font: inherit; padding: 6px 14px; border: 1px solid var(--accent); border-radius: 6px; background: none; color: var(--accent); cursor: pointer; text-decoration: none; display: inline-block; }
button.primary { background: var(--accent); color: var(--bg); }
#chats { max-height: 360px; overflow-y: auto; border: 1px solid var(--line); border-radius: 6px; padding: 4px 12px; margin-top: 8px; }
#chats label { display: flex; gap: 10px; padding: 6px 0; border-bottom: 1px solid var(--line); }
#chats label:last-child { border-bottom: none; }
input[type=text] { font: inherit; width: 100%; box-sizing: border-box; padding: 6px 8px; border: 1px solid var(--line); border-radius: 6px; background: transparent; color: inherit; }
#msg { margin-top: 12px; min-height: 1.5em; }
</style></head><body><main>
<h1>Rekall setup</h1>
<p class="lead">Optional: read your mail and the Teams chats you pick, and write new project facts and decisions into matching wiki project pages. Nothing here sends mail or posts to Teams.</p>

<h2>Secrets</h2>
<p class="muted">Read from <code>.env</code> in the rekall folder or the environment. Values are never shown.</p>
<ul class="checks" id="secrets"></ul>

<h2>Microsoft sign-in</h2>
<p id="graph" class="muted">Checking...</p>
<a class="button" href="/signin">Sign in with Microsoft</a>

<h2>Teams chats to include</h2>
<p class="muted">Only the chats you tick are read. Every other chat is ignored.</p>
<button id="load">Load my chats</button>
<div id="chats" hidden></div>

<h2>Mail folders</h2>
<input type="text" id="folders" aria-label="Mail folders, comma separated">
<p class="muted">Comma separated. <code>inbox</code> and <code>sentitems</code> are the defaults.</p>

<h2>Save</h2>
<label><input type="checkbox" id="enabled"> Turn on the Graph ingest</label>
<p><button class="primary" id="save">Save to rekall.toml</button></p>
<p id="msg"></p>
<p class="muted">Then check it: <code>bash scripts/run-graph-ingest.sh --dry-run --hours 24</code></p>
</main>
<script>
let saved = [];
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
async function refresh() {
  const s = await (await fetch("/api/status")).json();
  $("secrets").innerHTML = s.secrets.map(x => `<li><code>${x.name}</code><span class="${x.present ? "ok" : "bad"}">${x.present ? "present" : "missing"}</span></li>`).join("")
    + `<li><code>claude</code> on PATH<span class="${s.claude ? "ok" : "bad"}">${s.claude ? "found" : "missing"}</span></li>`;
  $("graph").innerHTML = s.graph.ok ? `<span class="ok">Signed in as ${esc(s.graph.user)} (${esc(s.graph.mail)})</span>` : `<span class="bad">${esc(s.graph.error)}</span>`;
  $("enabled").checked = s.config.enabled;
  $("folders").value = s.config.folders.join(", ");
  saved = s.config.chats;
  renderChats(saved, saved.map(c => c.id));
}
function renderChats(list, picked) {
  if (!list.length) return;
  $("chats").hidden = false;
  $("chats").innerHTML = list.map(c => `<label><input type="checkbox" value="${esc(c.id)}" data-name="${esc(c.name)}" ${picked.includes(c.id) ? "checked" : ""}>
    <span>${esc(c.name)}${c.type ? ` <span class="muted">${esc(c.type)}</span>` : ""}</span></label>`).join("");
}
$("load").onclick = async () => {
  $("msg").textContent = "Loading chats...";
  const r = await (await fetch("/api/chats")).json();
  if (r.error) { $("msg").textContent = r.error; return; }
  const ids = new Set(r.chats.map(c => c.id));
  renderChats(r.chats.concat(saved.filter(c => !ids.has(c.id))), saved.map(c => c.id));
  $("msg").textContent = `${r.chats.length} chats loaded.`;
};
$("save").onclick = async () => {
  const chats = [...document.querySelectorAll("#chats input:checked")].map(i => ({id: i.value, name: i.dataset.name}));
  const folders = $("folders").value.split(",").map(s => s.trim()).filter(Boolean);
  const r = await (await fetch("/api/config", {method: "POST", headers: {"Content-Type": "application/json", "X-Rekall-Setup": "1"},
    body: JSON.stringify({enabled: $("enabled").checked, folders, chats})})).json();
  $("msg").textContent = r.error ? r.error : `Saved: ingest ${r.saved.enabled ? "on" : "off"}, ${r.saved.chats.length} chats, folders ${r.saved.mail_folders.join(", ")}.`;
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

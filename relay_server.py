#!/usr/bin/env python3
"""
Prism — public relay server
───────────────────────────
Deploy this ONE file anywhere that runs Python (Render, Railway, Fly.io, any
VPS) and Prism terminals anywhere in the world can catch prompts typed on its
website — no shared Wi-Fi needed.

    person with the idea           this relay              friend's terminal
    opens https://<relay>/  ──►  assigns 4-digit code
    tells friend the code                                  /remote 4821  (pairs)
    types the prompt        ──►  queued under code  ◄───   polls /next, runs it

Run locally:   python3 relay_server.py            (port 8080)
On a host:     the PORT env var is respected automatically.

Standalone on purpose: no imports from Prism, no third-party dependencies —
just the Python standard library — so this single file IS the deployment.

Security: pairing returns a secret token; only the paired terminal (holding
the token) can read prompts or post statuses. Codes expire if unpaired for
15 minutes; whole sessions expire after 24 h idle.
"""
from __future__ import annotations
import json
import os
import random
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

UNPAIRED_TTL = 15 * 60        # empty code dies if nobody pairs within 15 min
QUEUED_TTL = 2 * 60 * 60      # …but if prompts are waiting, keep it 2 h
IDLE_TTL = 24 * 60 * 60       # paired session dies after 24 h of silence

_LOCK = threading.Lock()
_SESSIONS: dict[str, dict] = {}   # code -> {paired, token, queue[], created, seen}
_PROMPTS: dict[str, dict] = {}    # pid  -> {code, prompt, status}


def _new_code() -> str:
    while True:
        code = f"{random.randint(0, 9999):04d}"
        if code not in _SESSIONS:
            return code


def _purge():
    """Drop expired sessions (call with _LOCK held)."""
    now = time.time()
    dead = []
    for c, s in _SESSIONS.items():
        if s["paired"]:
            if now - s["seen"] > IDLE_TTL:
                dead.append(c)
        else:
            ttl = QUEUED_TTL if s["queue"] else UNPAIRED_TTL
            if now - s["created"] > ttl:
                dead.append(c)
    for c in dead:
        for pid in list(_PROMPTS):
            if _PROMPTS[pid]["code"] == c:
                del _PROMPTS[pid]
        del _SESSIONS[c]


# ── the website ───────────────────────────────────────────────────────────────
_PAGE = """<!doctype html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prism Remote</title>
<style>
  :root { --pink:#EF4B77; --teal:#4CD9B4; --orange:#FF8A4B; --bg:#101014; --card:#1a1a22; }
  * { box-sizing:border-box; margin:0; }
  body { background:var(--bg); color:#eee; font:16px/1.5 -apple-system, "Segoe UI", sans-serif;
         min-height:100vh; display:flex; align-items:center; justify-content:center; padding:16px; }
  .card { background:var(--card); border:1px solid #2a2a35; border-radius:14px;
          padding:28px; width:100%; max-width:520px; }
  h1 { color:var(--pink); font-size:22px; margin-bottom:4px; }
  h1 span { color:var(--teal); }
  .sub { color:#888; font-size:13px; margin-bottom:22px; }
  .code { font:700 44px/1 ui-monospace, monospace; letter-spacing:14px; color:var(--teal);
          text-align:center; padding:18px 0 10px; }
  .hint { text-align:center; color:#aaa; font-size:14px; margin-bottom:6px; }
  .hint code { background:#26262f; color:var(--orange); padding:2px 8px; border-radius:6px;
               font-family:ui-monospace, monospace; }
  .dot { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:7px;
         background:var(--orange); }
  .dot.on { background:var(--teal); }
  .status { font-size:13px; color:#999; text-align:center; margin-top:14px; }
  textarea { width:100%; min-height:110px; background:#14141a; color:#eee; border:1px solid #33333f;
             border-radius:10px; padding:12px; font:15px/1.5 inherit; resize:vertical; }
  textarea:focus { outline:none; border-color:var(--pink); }
  button { width:100%; margin-top:12px; padding:13px; border:none; border-radius:10px;
           background:var(--pink); color:#fff; font:600 16px inherit; cursor:pointer; }
  button:disabled { opacity:.4; cursor:default; }
  .jobs { margin-top:20px; }
  .job { background:#14141a; border:1px solid #26262f; border-radius:9px; padding:10px 12px;
         margin-top:8px; font-size:13.5px; display:flex; justify-content:space-between; gap:10px; }
  .job .txt { color:#bbb; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .badge { flex:none; font-size:11.5px; padding:2px 9px; border-radius:99px; align-self:center; }
  .queued  { background:#3a2f18; color:var(--orange); }
  .running { background:#1a2b3f; color:#4C9AFF; }
  .done    { background:#15332b; color:var(--teal); }
  .error   { background:#3a1822; color:var(--pink); }
</style></head><body>
<div class="card">
  <h1>&#9672; Prism <span>Remote</span></h1>
  <div class="sub">type an idea here &rarr; it runs in a paired Prism terminal, anywhere</div>

  <div id="pairing">
    <div class="code" id="code">&middot;&middot;&middot;&middot;</div>
    <div class="hint">tell this code to whoever runs Prism &mdash; they type
        <code>/remote <span id="code2">····</span></code></div>
    <div class="status"><span class="dot" id="dot"></span><span id="ptxt">no terminal paired yet &mdash; prompts you send will wait in the queue</span></div>
  </div>

  <div id="composer">
    <textarea id="prompt" placeholder="Describe your idea &mdash; it will run through their Prism agents&hellip;"></textarea>
    <button id="send">Run in their terminal</button>
    <div class="jobs" id="jobs"></div>
  </div>
</div>
<script>
let code = null;
const $ = id => document.getElementById(id);

async function init() {
  const r = await fetch('/session', {method:'POST'});
  code = (await r.json()).code;
  $('code').textContent = code;
  $('code2').textContent = code;
  setInterval(pollPair, 2500);
}
async function pollPair() {
  const r = await fetch('/poll?code=' + code);
  if ((await r.json()).paired) {
    $('dot').classList.add('on');
    $('ptxt').textContent = 'paired with a Prism terminal';
    $('composer').style.display = 'block';
  }
}
async function send() {
  const text = $('prompt').value.trim();
  if (!text) return;
  $('send').disabled = true;
  const r = await fetch('/prompt', {method:'POST', body: JSON.stringify({code, prompt: text})});
  const d = await r.json();
  $('send').disabled = false;
  if (d.error) { alert(d.error); return; }
  $('prompt').value = '';
  addJob(d.id, text);
}
function addJob(id, text) {
  const el = document.createElement('div');
  el.className = 'job';
  el.innerHTML = '<span class="txt"></span><span class="badge queued">queued</span>';
  el.querySelector('.txt').textContent = text;
  $('jobs').prepend(el);
  const badge = el.querySelector('.badge');
  const t = setInterval(async () => {
    const r = await fetch('/result?id=' + id);
    const s = (await r.json()).status || 'queued';
    const cls = s.startsWith('error') ? 'error' : s;
    badge.className = 'badge ' + cls;
    badge.textContent = s;
    if (s === 'done' || s.startsWith('error')) clearInterval(t);
  }, 3000);
}
$('send').onclick = send;
init();
</script>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── website-facing ────────────────────────────────────────────────────────
    def do_GET(self):
        p = urlparse(self.path)
        q = parse_qs(p.query)
        if p.path == "/":
            body = _PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif p.path == "/poll":
            code = q.get("code", [""])[0]
            with _LOCK:
                s = _SESSIONS.get(code)
            self._json({"paired": bool(s and s["paired"])})
        elif p.path == "/result":
            pid = q.get("id", [""])[0]
            with _LOCK:
                pr = _PROMPTS.get(pid)
            self._json({"status": pr["status"] if pr else "unknown"})
        # ── terminal-facing: poll for the next queued prompt ──────────────────
        elif p.path == "/next":
            code = q.get("code", [""])[0]
            token = q.get("token", [""])[0]
            with _LOCK:
                s = _SESSIONS.get(code)
                if not s or not s["paired"] or s["token"] != token:
                    self._json({"error": "bad code/token"}, 403)
                    return
                s["seen"] = time.time()
                if not s["queue"]:
                    self._json({})
                    return
                pid = s["queue"].pop(0)
                _PROMPTS[pid]["status"] = "running"
                self._json({"id": pid, "prompt": _PROMPTS[pid]["prompt"]})
        elif p.path == "/health":
            self._json({"ok": True, "sessions": len(_SESSIONS)})
        else:
            self.send_error(404)

    def do_POST(self):
        p = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}") if length else {}
        except Exception:
            data = {}
        if p.path == "/session":
            with _LOCK:
                _purge()
                code = _new_code()
                now = time.time()
                _SESSIONS[code] = {"paired": False, "token": "", "queue": [],
                                   "created": now, "seen": now}
            self._json({"code": code})
        elif p.path == "/prompt":
            code = str(data.get("code", ""))
            prompt = str(data.get("prompt", "")).strip()
            with _LOCK:
                s = _SESSIONS.get(code)
                if not s:
                    self._json({"error": "This code has expired — reload the page."}, 404)
                    return
                # Not paired yet? Fine — the prompt WAITS in the queue and pops
                # up the moment a terminal pairs with this code.
                if not prompt:
                    self._json({"error": "Empty prompt."}, 400)
                    return
                pid = uuid.uuid4().hex[:12]
                _PROMPTS[pid] = {"code": code, "prompt": prompt, "status": "queued"}
                s["queue"].append(pid)
                s["seen"] = time.time()
            self._json({"id": pid})
        # ── terminal-facing ───────────────────────────────────────────────────
        elif p.path == "/pair":
            code = str(data.get("code", ""))
            with _LOCK:
                _purge()
                s = _SESSIONS.get(code)
                if not s:
                    self._json({"error": "unknown code"}, 404)
                    return
                # Re-pairing invalidates any previous terminal's token.
                s["paired"] = True
                s["token"] = uuid.uuid4().hex
                s["seen"] = time.time()
                self._json({"token": s["token"]})
        elif p.path == "/status":
            pid = str(data.get("id", ""))
            token = str(data.get("token", ""))
            status = str(data.get("status", ""))[:120]
            with _LOCK:
                pr = _PROMPTS.get(pid)
                s = _SESSIONS.get(pr["code"]) if pr else None
                if not pr or not s or s["token"] != token:
                    self._json({"error": "bad id/token"}, 403)
                    return
                pr["status"] = status or pr["status"]
            self._json({"ok": True})
        else:
            self.send_error(404)


def main():
    port = int(os.environ.get("PORT", 8080))
    server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    print(f"◈ Prism relay listening on :{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

"""
Prism — remote bridge
─────────────────────
`/remote` hosts a tiny website on your local network (stdlib http.server — no
new dependencies). Any device on the same Wi-Fi opens it and gets a random
4-digit pairing code. Once you approve that code in the terminal with
`/remote <code>`, prompts submitted on the page are queued here and run as if
they were typed at the prism › prompt.

Security model: pairing is explicit (nothing runs until you type the code into
the terminal), and the server only listens on your LAN.
"""
from __future__ import annotations
import json
import random
import socket
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE_PORT = 7777

_LOCK = threading.Lock()
_SESSIONS: dict[str, dict] = {}   # code -> {"paired": bool, "queue": [pid, …]}
_PROMPTS: dict[str, dict] = {}    # pid  -> {"code", "prompt", "status"}
_SERVER: ThreadingHTTPServer | None = None
_THREAD: threading.Thread | None = None
_PORT: int | None = None


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))   # no packets sent — just picks the LAN iface
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _new_code() -> str:
    while True:
        code = f"{random.randint(0, 9999):04d}"
        if code not in _SESSIONS:
            return code


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
  <div class="sub">send a prompt from this device &rarr; it runs in your Prism terminal</div>

  <div id="pairing">
    <div class="code" id="code">&middot;&middot;&middot;&middot;</div>
    <div class="hint">in your Prism terminal, type <code>/remote <span id="code2">····</span></code></div>
    <div class="status"><span class="dot" id="dot"></span><span id="ptxt">not paired yet &mdash; prompts you send will wait in the queue</span></div>
  </div>

  <div id="composer">
    <textarea id="prompt" placeholder="Describe a task for your Prism agents&hellip;"></textarea>
    <button id="send">Run in terminal</button>
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
  setInterval(pollPair, 2000);
}
async function pollPair() {
  const r = await fetch('/poll?code=' + code);
  if ((await r.json()).paired) {
    $('dot').classList.add('on');
    $('ptxt').textContent = 'paired';
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


# ── HTTP handler ──────────────────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):   # keep the REPL clean
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = urlparse(self.path)
        if p.path == "/":
            body = _PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif p.path == "/poll":
            code = parse_qs(p.query).get("code", [""])[0]
            with _LOCK:
                s = _SESSIONS.get(code)
            self._json({"paired": bool(s and s["paired"])})
        elif p.path == "/result":
            pid = parse_qs(p.query).get("id", [""])[0]
            with _LOCK:
                pr = _PROMPTS.get(pid)
            self._json({"status": pr["status"] if pr else "unknown"})
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
                code = _new_code()
                _SESSIONS[code] = {"paired": False, "queue": []}
            self._json({"code": code})
        elif p.path == "/prompt":
            code = str(data.get("code", ""))
            prompt = str(data.get("prompt", "")).strip()
            with _LOCK:
                s = _SESSIONS.get(code)
                if not s:
                    self._json({"error": "Unknown code — reload the page."}, 404)
                    return
                # Not paired yet? Fine — the prompt WAITS in the queue and pops
                # up the moment the terminal pairs with this code.
                if not prompt:
                    self._json({"error": "Empty prompt."}, 400)
                    return
                pid = uuid.uuid4().hex[:12]
                _PROMPTS[pid] = {"code": code, "prompt": prompt, "status": "queued"}
                s["queue"].append(pid)
            self._json({"id": pid})
        else:
            self.send_error(404)


# ── public API (used by prism.py) ─────────────────────────────────────────────
def is_running() -> bool:
    return _SERVER is not None


def url() -> str | None:
    return f"http://{_lan_ip()}:{_PORT}" if _PORT else None


def start(port: int = BASE_PORT) -> str:
    """Start the bridge (idempotent). Returns the LAN URL to open."""
    global _SERVER, _THREAD, _PORT
    if _SERVER:
        return url()
    last_err = None
    for p in range(port, port + 10):          # skip ports already in use
        try:
            _SERVER = ThreadingHTTPServer(("0.0.0.0", p), _Handler)
            _PORT = p
            break
        except OSError as e:
            last_err = e
    if not _SERVER:
        raise RuntimeError(f"No free port in {port}–{port+9}: {last_err}")
    _THREAD = threading.Thread(target=_SERVER.serve_forever, daemon=True)
    _THREAD.start()
    return url()


def stop():
    global _SERVER, _THREAD, _PORT
    if _SERVER:
        _SERVER.shutdown()
        _SERVER = None
        _THREAD = None
        _PORT = None
    with _LOCK:
        _SESSIONS.clear()
        _PROMPTS.clear()


def pair(code: str) -> bool:
    """Approve a session code shown on the website. Returns False if unknown."""
    with _LOCK:
        s = _SESSIONS.get(code)
        if not s:
            return False
        s["paired"] = True
        return True


def next_prompt(code: str):
    """Pop the oldest queued prompt for a paired session → (pid, text) or None."""
    with _LOCK:
        s = _SESSIONS.get(code)
        if not s or not s["queue"]:
            return None
        pid = s["queue"].pop(0)
        _PROMPTS[pid]["status"] = "running"
        return pid, _PROMPTS[pid]["prompt"]


def set_status(pid: str, status: str):
    with _LOCK:
        if pid in _PROMPTS:
            _PROMPTS[pid]["status"] = status


# ── relay client (for a hosted relay_server.py — works across the internet) ───
# The terminal is a *client* here: it pairs against the public relay, then
# polls it for prompts. Mirrors the local bridge's API shape.

def relay_pair(base: str, code: str) -> str | None:
    """Pair with a session code on a hosted relay. Returns the secret token,
    or None if the code is unknown/expired."""
    import requests
    try:
        r = requests.post(base.rstrip("/") + "/pair", json={"code": code}, timeout=15)
        return r.json().get("token") if r.ok else None
    except Exception:
        return None


def relay_next(base: str, code: str, token: str):
    """Poll the relay for the next queued prompt → (pid, text) or None.
    Raises on network errors so the caller can back off and retry."""
    import requests
    r = requests.get(base.rstrip("/") + "/next",
                     params={"code": code, "token": token}, timeout=15)
    d = r.json()
    if r.ok and d.get("id"):
        return d["id"], d["prompt"]
    return None


def relay_set_status(base: str, pid: str, token: str, status: str):
    import requests
    try:
        requests.post(base.rstrip("/") + "/status",
                      json={"id": pid, "token": token, "status": status}, timeout=15)
    except Exception:
        pass   # status is cosmetic — never let it kill the run

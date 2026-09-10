"""
Prism — email blasts (/email)
─────────────────────────────
Mail-merge through the pipeline: the user attaches a CSV of recipients and a
source document (e.g. a brochure PDF). The pipeline analyses the document,
the drafting agent is locked to output ONLY the email (strict SUBJECT/BODY
format — nothing else survives into the send), and then Prism itself sends
the email to every address in the CSV through the user's own account (SMTP,
stdlib smtplib — no new dependencies).

The CSV is never shown to any AI: recipients are parsed locally, so the
address list never leaves this machine.
"""
from __future__ import annotations
import csv
import io
import re
import ssl
import random
import time
import smtplib
from email.message import EmailMessage
from . import ui

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_NAME_HEADERS = ("name", "first name", "firstname", "first_name", "full name",
                 "full_name", "fullname", "contact", "person")

# Known providers → (smtp host, port). 465 = SSL, 587 = STARTTLS.
_SMTP_HOSTS = {
    "gmail.com": ("smtp.gmail.com", 465),
    "googlemail.com": ("smtp.gmail.com", 465),
    "outlook.com": ("smtp-mail.outlook.com", 587),
    "hotmail.com": ("smtp-mail.outlook.com", 587),
    "live.com": ("smtp-mail.outlook.com", 587),
    "yahoo.com": ("smtp.mail.yahoo.com", 465),
    "icloud.com": ("smtp.mail.me.com", 587),
    "me.com": ("smtp.mail.me.com", 587),
    "zoho.com": ("smtp.zoho.com", 465),
}

# Pause between sends — keeps providers from flagging the account for bursts.
# The GUI reads the customer's own figure out of cfg["email"]["send"] (see
# email_config.send_policy in prism_gui); this is what a bare call gets.
SEND_DELAY = 2.0


def pause_after_send(delay: float, jitter: float = 0.0) -> float:
    """How long to wait before the next message: the fixed gap plus a random
    slice of `jitter`. A list sent with an identical pause every time is a
    metronome a provider can hear; a little randomness reads as a person."""
    delay = max(0.0, float(delay or 0.0))
    jitter = max(0.0, float(jitter or 0.0))
    return delay + (random.uniform(0.0, jitter) if jitter else 0.0)


def _sleep_until(deadline: float, should_stop=None, on_wait=None) -> bool:
    """Wait for wall-clock `deadline` (time.time()), in quarter-second
    slices so a cancel lands promptly. on_wait(seconds_left) is called once a
    second for a screen to count down on. Returns False if stopped."""
    last_told = None
    while True:
        left = deadline - time.time()
        if left <= 0:
            return True
        if should_stop and should_stop():
            return False
        told = int(left)
        if on_wait and told != last_told:
            on_wait(told)
            last_told = told
        time.sleep(min(0.25, left))


# ── recipients (parsed locally — the CSV never reaches any AI) ────────────────

def split_attachments(attachments: list[dict]):
    """(csv attachments, everything else). CSVs hold recipients; the rest is
    source material for the pipeline."""
    csvs = [a for a in attachments if a["name"].lower().endswith(".csv")]
    others = [a for a in attachments if a not in csvs]
    return csvs, others


def parse_recipients(path: str) -> list[dict]:
    """Extract [{'email', 'name'}, …] from any reasonable CSV: with or without
    a header row, whatever column the addresses live in. Deduped, in order."""
    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
        rows = [r for r in csv.reader(f) if any(c.strip() for c in r)]
    if not rows:
        return []

    width = max(len(r) for r in rows)
    cell = lambda r, i: r[i].strip() if i < len(r) else ""

    # The email column is the one with the most address-looking cells.
    email_col, best = None, 0
    for i in range(width):
        hits = sum(1 for r in rows if _EMAIL_RE.search(cell(r, i)))
        if hits > best:
            email_col, best = i, hits
    if email_col is None:
        return []

    # Header row = first row whose email cell isn't an address.
    has_header = not _EMAIL_RE.search(cell(rows[0], email_col))
    header = [c.strip().lower() for c in rows[0]] if has_header else []
    data = rows[1:] if has_header else rows

    # Name column: a name-ish header if there is one, else the first other
    # column that holds mostly letters (not numbers/URLs).
    name_col = None
    for i, h in enumerate(header):
        if h in _NAME_HEADERS:
            name_col = i
            break
    if name_col is None:
        for i in range(width):
            if i == email_col:
                continue
            alpha = sum(1 for r in data
                        if cell(r, i) and re.fullmatch(r"[A-Za-z .'-]+", cell(r, i)))
            if data and alpha >= max(1, len(data) // 2):
                name_col = i
                break

    out, seen = [], set()
    for r in data:
        m = _EMAIL_RE.search(cell(r, email_col))
        if not m:
            continue
        email = m.group(0).lower()
        if email in seen:
            continue
        seen.add(email)
        out.append({"email": email,
                    "name": cell(r, name_col) if name_col is not None else ""})
    return out


def recipients_from_text(text: str):
    """Addresses typed straight into the /email prompt ("… send to a@x.com and
    b@y.com") become recipients. Returns (recipients, text with the addresses
    removed) — like the CSV, addresses are never shown to any AI."""
    recs, seen = [], set()
    for e in _EMAIL_RE.findall(text):
        e = e.lower()
        if e not in seen:
            seen.add(e)
            recs.append({"email": e, "name": ""})
    cleaned = _EMAIL_RE.sub("", text)
    cleaned = re.sub(r"\s*(?:,|;|\band\b)?\s*(?:,|;|\band\b)\s*(?=$|[,;.])", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;&")
    return recs, cleaned


# ── discovered recipients (a research agent found them, not the user) ────────

# Tools that are lead databases rather than chat models. They are told to
# FILTER, not to "search the web and write about it", because the whole reason
# to route a discovery run through one is that its addresses were verified by
# somebody other than a language model.
LEAD_DATABASES = {"Apollo"}


def prefers_lead_database(agent_name: str) -> bool:
    """True when this agent looks up real contact records instead of writing
    prose about companies. Callers use it to pick a finder for outreach runs
    and to decide which research prompt to send."""
    return (agent_name or "").strip() in LEAD_DATABASES


def apollo_filter_prompt(goal: str) -> str:
    """What Groq is asked BEFORE Apollo ever opens: turn the outreach goal
    into Apollo's own filters. Apollo is a database, not a chatbot — it
    takes short comma-separated values, one line per field, and rejects
    anything long — so the filters are decided locally first and the block
    below is all Apollo's stage prompt needs to carry."""
    return (
        "Turn this outreach goal into search filters for Apollo.io's People "
        f"database.\nGOAL: {goal}\n\n"
        "Apollo does not read sentences — every filter is a short "
        "comma-separated value. Answer with EXACTLY this block and nothing "
        "else, no bullets, no bold, no commentary:\n\n"
        "HANDOFF FOR APOLLO\n"
        "TITLES: 2-6 job titles of the person worth reaching\n"
        "INDUSTRIES: 2-6 industry keywords describing the company\n"
        "LOCATIONS: cities, states or countries from the goal\n"
        "HEADCOUNT: one or more of 1-10, 11-20, 21-50, 51-100, 101-200, "
        "201-500, 501-1000, 1001-2000, 2001-5000, 5001-10000, 10001+\n"
        "KEYWORDS: up to 12 plain words further describing the company\n\n"
        "Every line under 150 characters. Write 'any' for a field you "
        "genuinely cannot narrow — never leave one out.")


def discovery_prompts(goal: str, finder: str = "",
                      filter_block: str = "") -> tuple[str, str]:
    """(research prompt, structuring prompt) for finding recipients that match
    a description — "the best-suited agencies in Vadodara", not one named
    org. Two stages because a research agent free-writes prose; asking it to
    also format strict CSV in the same breath tends to lose rows. Splitting
    the jobs is exactly the 'let stages cycle back through agents' pattern —
    the structuring stage often reuses whichever agent already ran.

    `finder` is the agent that will run the first stage. A lead database is
    driven differently from a chat model — it is asked to build a filter and
    read its own results grid, not to recall companies — so the first prompt
    changes shape entirely. The structuring stage is identical either way,
    which is the point: whatever comes back becomes the same CSV.

    `filter_block` is a ready 'HANDOFF FOR APOLLO' block (built locally by
    Groq via apollo_filter_prompt). When given, it IS the research prompt's
    payload: _run_apollo parses those exact lines into Apollo's search URL,
    and the prose shrinks to one reading instruction — Apollo never gets a
    paragraph, because a paragraph typed at Apollo returns nothing.
    """
    if prefers_lead_database(finder):
        if filter_block.strip():
            research = (
                "Read the filtered People table and list every contact with "
                "a verified work email as: Name — Website — Email — Reason, "
                "one per line. Write exactly 'unknown' for anything locked "
                "or guessed; never reconstruct an address.\n\n"
                + filter_block.strip())
        else:
            research = (
                "Your ONLY task is to build a prospect list for this request: "
                f"{goal}. Use the search filters — job title, company industry, "
                "employee headcount, and location — to narrow to companies that "
                "genuinely match, then read the results table. For each contact "
                "with a verified work email, list: Company name, Website, Email, "
                "and a one-line reason it fits. One per line, in the form: "
                "Name — Website — Email — Reason. Only include rows where the "
                "email is actually shown and marked verified; write exactly "
                "'unknown' for anything locked, hidden behind credits, or shown "
                "as a guess. Never reconstruct an address from a pattern. Do not "
                "pad the list to hit a number."
            )
        return research, _DISCOVERY_STRUCTURE

    research = (
        "Your ONLY task is: based on the brief above, find real, currently "
        f"operating businesses that match this request: {goal}. Search the "
        "web for actual candidates — do not invent any. For each one you are "
        "reasonably confident is real, list: Name, Website, a public contact "
        "email ONLY if you actually found one (write exactly 'unknown' if you "
        "did not — never guess or construct one from a pattern), and a "
        "one-line reason it fits. One candidate per line, in the form: "
        "Name — Website — Email — Reason. List every genuine candidate you "
        "can find; do not pad the list to hit a number."
    )
    return research, _DISCOVERY_STRUCTURE


# One structuring prompt for every finder. Whatever shape the first stage
# replied in — scraped prose or a filtered results table — this turns it into
# the same CSV, so parse_structured_csv_text() below never has to care which
# tool found the rows.
_DISCOVERY_STRUCTURE = (
    "Take the candidate list from the previous stage and convert it to a "
    "strict CSV. Reply with NOTHING except the CSV — no commentary, no "
    "markdown fences. First line exactly: name,website,email,reason. "
    "Then one row per candidate that has a real email address — DROP any "
    "candidate whose email is 'unknown', blank, or that you are not "
    "confident is real. Quote any field that contains a comma. If no "
    "candidate has a confirmed email, reply with just the header row."
)


def parse_structured_csv_text(text: str) -> list[dict]:
    """Pull [{'name','email','website','reason'}, …] out of the structuring
    stage's reply. It's told to answer with ONLY a
    'name,website,email,reason' CSV, but a scrape can still carry a stray
    fence or a leaked comment around it — keep only well-formed rows that
    contain an actual email address, so prose that slipped through can't
    masquerade as a recipient."""
    if not text:
        return []
    t = re.sub(r"^```[a-z]*\n|\n```$", "", text.strip())
    out = []
    for row in csv.reader(io.StringIO(t)):
        cells = [c.strip() for c in row]
        email = next((c for c in cells if _EMAIL_RE.fullmatch(c)), None)
        if not email:
            continue
        rest = [c for c in cells if c != email]
        out.append({
            "email": email.lower(),
            "name": rest[0] if rest else "",
            "website": rest[1] if len(rest) > 1 else "",
            "reason": rest[2] if len(rest) > 2 else "",
        })
    seen, dedup = set(), []
    for r in out:
        if r["email"] not in seen:
            seen.add(r["email"])
            dedup.append(r)
    return dedup


def write_recipients_csv(rows: list[dict], path: str) -> None:
    """Persist discovered recipients to a real CSV on disk — a durable record
    the user can open, edit or hand to someone else, and (since it's a plain
    recipients CSV) re-attach to a future /email run via parse_recipients()."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "website", "email", "reason"])
        for r in rows:
            w.writerow([r.get("name", ""), r.get("website", ""),
                       r.get("email", ""), r.get("reason", "")])


# ── the draft (what the AI produced) ──────────────────────────────────────────

# Fingerprints of the instructions Prism itself typed into the tool. A scrape
# that contains any of them is our own prompt read back off the page — several
# tools render the user's message with the same CSS classes as the reply — and
# it parses as a perfectly valid draft whose subject is "<one subject line>".
_PROMPT_MARKERS = (
    "your only task is",
    "reply with nothing except",
    "<one subject line>",
    "<the full email body>",
    "strict pipeline rules",
    "every character you output will be sent",
)


def is_prompt_echo(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _PROMPT_MARKERS)


def parse_draft(text: str):
    """Pull (subject, body) out of the drafting agent's answer. The agent is
    ordered to reply in exactly 'SUBJECT: …' / 'BODY: …' — but scrapes can
    carry stray fences or a leaked handoff, so be forgiving on the way in."""
    if not text or not text.strip():
        return None
    t = text.strip()
    t = re.sub(r"^```[a-z]*\n|\n```$", "", t)                    # markdown fences
    t = re.split(r"\n\s*HANDOFF\b", t, flags=re.IGNORECASE)[0]   # leaked handoff

    # Take the LAST SUBJECT: on the page, not the first. When the capture also
    # holds the prompt (or the tool restated the format before answering), the
    # earlier ones are the template and the real draft is the final block.
    # Tools love to bold the labels: **SUBJECT:** … / **BODY:** …
    for m in reversed(list(re.finditer(r"^[ \t]*\**\s*SUBJECT\s*\**\s*:\s*\**(.+)$",
                                       t, re.IGNORECASE | re.MULTILINE))):
        subject = m.group(1).strip().strip("*").strip()
        # A placeholder straight out of our own instructions is never a draft.
        if not subject or subject.startswith("<") or is_prompt_echo(subject):
            continue
        rest = t[m.end():]
        b = re.search(r"^[ \t]*\**\s*BODY\s*\**\s*:\s*\**[ \t]*\n?", rest,
                      re.IGNORECASE | re.MULTILINE)
        body = rest[b.end():].strip() if b else rest.strip()
        if body and not body.startswith("<") and not is_prompt_echo(body):
            return subject, body
    return None


# ── account setup ─────────────────────────────────────────────────────────────

def smtp_for(address: str):
    domain = address.rsplit("@", 1)[-1].lower()
    return _SMTP_HOSTS.get(domain)


# Google shows app passwords as four groups of four — "abcd efgh ijkl mnop" —
# and people paste them exactly as shown, spaces and all. Gmail's SMTP then
# rejects the login with the same 535 it gives a wrong password, which is the
# single most common reason sending "just doesn't work".
_APP_PASSWORD = re.compile(r"^([A-Za-z0-9]{4}[ \t ]){3}[A-Za-z0-9]{4}$")


def clean_password(password: str) -> str:
    """Trim a pasted password. Outer whitespace always goes; inner spaces go
    only when the string is exactly an app password's shape, because a real
    passphrase is allowed to contain spaces and we must not corrupt it."""
    p = (password or "").strip().replace(" ", " ")
    if _APP_PASSWORD.match(p):
        return re.sub(r"\s+", "", p)
    return p


def explain_error(error: str, address: str = "", port: int | str = "") -> str:
    """Turn an smtplib failure into the sentence that actually unblocks the
    user. The raw text ('(535, b\\'5.7.8 Username and Password not accepted\\')')
    says nothing about app passwords, which is what it almost always means."""
    e = (error or "").lower()
    domain = address.rsplit("@", 1)[-1].lower() if "@" in address else ""
    other_port = 465 if str(port) == "587" else 587
    if "535" in e or "auth" in e or "username and password" in e:
        if domain in ("gmail.com", "googlemail.com"):
            return ("Google rejected the sign-in. Gmail needs a 16-character "
                    "APP PASSWORD (not your Google password), created at "
                    "myaccount.google.com/apppasswords with 2-Step "
                    "Verification switched on.")
        if domain in ("outlook.com", "hotmail.com", "live.com"):
            return ("Microsoft rejected the sign-in. Personal Outlook accounts "
                    "no longer allow SMTP passwords — you need an app password "
                    "from account.microsoft.com/security, or a different "
                    "sending account.")
        if domain in ("yahoo.com",):
            return ("Yahoo rejected the sign-in. Generate an app password "
                    "under Account Security → App passwords.")
        return ("The server rejected that address/password. Most providers "
                "require an app password for SMTP rather than your normal one.")
    if "certificate" in e or "ssl" in e:
        return ("TLS handshake failed — check the port: 465 is SSL, 587 is "
                "STARTTLS. Using the wrong one for your host fails like this.")
    if ("getaddrinfo" in e or "name or service" in e or "resolve" in e
           or "name resolution" in e):
        return "Couldn't resolve the SMTP host — check it for typos."
    if "timed out" in e or "timeout" in e:
        # Which port to suggest depends on which one just failed — telling
        # someone already on 587 to "try 587" fixes nothing and reads as a
        # canned non-answer.
        return (f"The mail server didn't answer on port {port or '?'}. This "
               f"usually means a network is blocking outbound mail — some "
               f"ISPs and office firewalls block it entirely. Try port "
               f"{other_port} instead in Setup, or send from a different "
               f"network (e.g. a phone hotspot) to check whether it's the "
               f"network rather than the account.")
    return error


def is_configured(cfg: dict) -> bool:
    ec = cfg.get("email") or {}
    return bool(ec.get("address") and ec.get("password") and ec.get("host"))


def verify(cfg: dict) -> str:
    """Open a session and log in, then hang up. Returns "" on success or a
    human error. Credentials are otherwise only ever tested by a real blast,
    which is the worst moment to discover that Gmail wants an app password."""
    ec = (cfg or {}).get("email") or {}
    if not is_configured(cfg or {}):
        return "No sending account is set up yet."
    try:
        server = _connect(ec, timeout=30)
    except Exception as e:
        return explain_error(str(e), ec.get("address", ""), ec.get("port", ""))
    try:
        server.quit()
    except Exception:
        pass
    return ""


# ── sending ───────────────────────────────────────────────────────────────────

def _connect(ec: dict, timeout: int = 60):
    if int(ec["port"]) == 465:
        server = smtplib.SMTP_SSL(ec["host"], 465, timeout=timeout,
                                  context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(ec["host"], int(ec["port"]), timeout=timeout)
        server.starttls(context=ssl.create_default_context())
    # Cleaned here as well as at save time, so an account stored by an older
    # build (spaced app password → permanent 535) starts working by itself.
    server.login(ec["address"].strip(), clean_password(ec["password"]))
    return server


def _send_timeout(files: list[dict]) -> int:
    """Socket timeout scaled to the attachment payload. Uploading a big PDF
    can take minutes on a slow uplink — with a short timeout the socket dies
    mid-transfer and smtplib reports the misleading 'Server not connected'.
    Budget: worst-case ~20 KB/s on the base64-inflated (×1.4) size."""
    total = 0
    for f in files:
        try:
            import os
            total += os.path.getsize(f["path"])
        except Exception:
            pass
    return max(60, min(900, int(total * 1.4 / 20_000)))


def _build_message(ec, recipient, subject, body, files):
    name = (recipient.get("name") or "").strip() or "there"
    msg = EmailMessage()
    msg["From"] = ec["address"]
    msg["To"] = recipient["email"]
    msg["Subject"] = subject.replace("{name}", name)
    msg.set_content(body.replace("{name}", name))
    for f in files:
        with open(f["path"], "rb") as fh:
            data = fh.read()
        maintype, _, subtype = (f.get("mime") or "application/octet-stream").partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream",
                           filename=f["name"])
    return msg


# ── save a copy to the Sent folder (IMAP APPEND) ──────────────────────────────
# A plain SMTP send reaches the recipient but never writes to the sender's OWN
# mailbox, so a Prism-sent mail is invisible in Outlook/webmail's "Sent". A real
# mail client fixes this with a second step — it APPENDS the message to the
# account's Sent folder over IMAP — and so do we, after each send, reusing the
# engine's tested IMAP host-discovery (inbox.guess_hosts / inbox._connect).
#
# Best-effort by contract: a mailbox that refuses the append, has IMAP switched
# off, or whose Sent folder can't be found NEVER breaks the send. The copy is a
# convenience; the delivery is the job.

# Providers whose SMTP already files sent mail into Sent for you — a second copy
# would just duplicate it, so skip the append entirely.
_SMTP_AUTOSAVES_SENT = ("gmail.com", "googlemail.com")

# Folder names to try when the server doesn't advertise the RFC-6154 \Sent
# special-use flag, best-known first.
_SENT_NAMES = ("Sent", "Sent Items", "Sent Mail", "INBOX.Sent", "[Gmail]/Sent Mail")

_LIST_LINE = re.compile(
    r'^\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL|\S+)\s+'
    r'(?P<name>"(?:[^"\\]|\\.)*"|\S+)\s*$')


def _unquote_mailbox(raw: str) -> str:
    raw = (raw or "").strip()
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        raw = raw[1:-1].replace('\\"', '"').replace('\\\\', '\\')
    return raw


def sent_folder_from_list(lines) -> str:
    """The account's Sent folder name from raw IMAP LIST output. Prefers the
    RFC-6154 \\Sent special-use flag; otherwise the first well-known name the
    server actually lists. '' when nothing matches (the caller then skips)."""
    names = []
    for raw in lines or []:
        line = (raw.decode(errors="ignore")
                if isinstance(raw, (bytes, bytearray)) else str(raw)).strip()
        m = _LIST_LINE.match(line)
        if not m:
            continue
        name = _unquote_mailbox(m.group("name"))
        names.append(name)
        if re.search(r"\\Sent\b", m.group("flags"), re.IGNORECASE):
            return name
    lower = {n.lower(): n for n in names}
    for cand in _SENT_NAMES:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return ""


# Known SMTP host → the IMAP host that goes with it. We ALWAYS know the SMTP
# host (we just sent through it), so deriving IMAP from it needs no DNS — which
# is what makes the Sent copy work even when dnspython isn't installed and
# inbox.guess_hosts() can't resolve a hosted provider (GoDaddy being the case in
# point: smtpout.secureserver.net has no imap.<domain>, only imap.secureserver.net).
_SMTP_TO_IMAP = {
    "smtpout.secureserver.net": "imap.secureserver.net",   # GoDaddy Workspace
    "smtp-mail.outlook.com": "outlook.office365.com",
    "smtp.office365.com": "outlook.office365.com",
    "smtp.mail.yahoo.com": "imap.mail.yahoo.com",
    "smtp.zoho.com": "imap.zoho.com",
    "smtp.zoho.in": "imap.zoho.in",
    "smtp.mail.me.com": "imap.mail.me.com",
    "smtp.gmail.com": "imap.gmail.com",
}


def _imap_from_smtp(smtp_host: str) -> str:
    """The IMAP host implied by an SMTP host: a known mapping, else the common
    'smtp…'→'imap…' rewrite (covers cPanel/hosted mail), else ''."""
    h = (smtp_host or "").strip().lower()
    if not h:
        return ""
    if h in _SMTP_TO_IMAP:
        return _SMTP_TO_IMAP[h]
    if h.startswith("smtp"):
        return re.sub(r"^smtp[a-z-]*", "imap", h)
    if h.startswith("mail."):
        return h                        # mail.<domain> often serves both
    return ""


class _SentSaver:
    """Opens ONE IMAP connection for a whole send run and drops each sent
    message into the account's Sent folder. Every method swallows its own
    errors — saving a copy must never break sending."""

    def __init__(self, cfg: dict):
        self._conn = None
        self._folder = ""
        self.active = False
        self.note = ""
        self._cfg = cfg or {}
        ec = self._cfg.get("email") or {}
        addr = (ec.get("address") or "").strip()
        domain = addr.rsplit("@", 1)[-1].lower() if "@" in addr else ""
        if not ec.get("save_to_sent", True) or not addr or not ec.get("password"):
            return
        if domain in _SMTP_AUTOSAVES_SENT:
            self.note = "your provider files sent mail into Sent automatically"
            return
        try:                                            # construction must never
            self._open()                                # break the send that
        except Exception:                               # noqa: BLE001  follows it
            self.active = False

    def _candidate_hosts(self):
        from . import inbox
        ec = self._cfg["email"]
        addr = ec["address"].strip()
        dom = addr.rsplit("@", 1)[-1].lower()
        hosts = []
        # A mailbox already set up for READING is a known-good IMAP server — use
        # it first when it's the same provider as the sending address.
        ic = self._cfg.get("inbox") or {}
        if ic.get("host") and (ic.get("address") or "").rsplit("@", 1)[-1].lower() == dom:
            hosts.append(ic["host"])
        # Derived from the SMTP host — no DNS, so it works without dnspython.
        derived = _imap_from_smtp(ec.get("host"))
        if derived and derived not in hosts:
            hosts.append(derived)
        for h in inbox.guess_hosts(addr):
            if h and h not in hosts:
                hosts.append(h)
        return hosts

    def _open(self):
        from . import inbox
        ec = self._cfg["email"]
        for host in self._candidate_hosts():
            ic = {"address": ec["address"], "password": ec["password"],
                  "host": host, "port": 993}
            try:
                conn = inbox._connect(ic, timeout=20)
            except Exception:                           # noqa: BLE001
                continue                                # wrong host / refused → next
            try:
                typ, data = conn.list()
                folder = sent_folder_from_list(data) if typ == "OK" else ""
            except Exception:                           # noqa: BLE001
                folder = ""
            if folder:
                self._conn, self._folder, self.active = conn, folder, True
                return
            try:
                conn.logout()
            except Exception:                           # noqa: BLE001
                pass
        self.note = "couldn't reach the Sent folder — copies were not saved there"

    def save(self, msg) -> None:
        if not self.active:
            return
        import imaplib
        box = '"%s"' % self._folder.replace("\\", "\\\\").replace('"', '\\"')
        try:
            self._conn.append(box, r"(\Seen)",
                              imaplib.Time2Internaldate(time.time()),
                              msg.as_bytes())
        except Exception:                               # noqa: BLE001
            pass                                        # a lost copy is not a lost send

    def close(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.logout()
        except Exception:                               # noqa: BLE001
            pass
        self._conn = None


def send_bulk(cfg: dict, recipients: list[dict], subject: str, body: str,
              files: list[dict], delay: float = SEND_DELAY,
              session_max: int = 20, on_progress=None, should_stop=None, *,
              jitter: float = 0.0, limit: int = 0, start_at: float = 0.0,
              on_wait=None):
    """Send the draft to every recipient, one message each (so {name} can be
    personalised and one bad address can't sink the rest).
    Returns (sent emails, [(email, error), …]).

    on_progress(i, total, email, ok, error) is called after every attempt, and
    should_stop() is polled between them — a blast of 200 addresses takes
    minutes at SEND_DELAY, and the GUI needs both a live count and a way out.
    Neither is used by the CLI, which has ui.* and Ctrl-C for the same jobs.

    Pace and limits — the three knobs a list send needs so it does not read
    as spam to the provider or to the people on it:
      delay + jitter   the gap between two messages: `delay` seconds plus a
                       random 0..`jitter` on top (pause_after_send)
      limit            send to at most this many this run; 0 = everyone.
                       The rest are not attempted and are reported as such
      start_at         a wall-clock time (time.time()) to begin at; the
                       login happens only once it arrives, so a send set for
                       the morning does not hold an SMTP session open all
                       night. on_wait(seconds_left) ticks once a second
                       meanwhile; a stop during the wait sends nothing."""
    ec = cfg["email"]
    if limit and limit > 0 and len(recipients) > limit:
        ui.info(f"   ⏳  sending to {limit} of {len(recipients)} this run — "
                f"{len(recipients) - limit} left for the next")
        recipients = list(recipients)[:limit]
    if start_at and start_at > time.time():
        ui.info(f"   🕒  waiting until {time.strftime('%H:%M', time.localtime(start_at))} "
                "to begin")
        if not _sleep_until(start_at, should_stop, on_wait):
            ui.warn("stopped before the scheduled time — nothing sent")
            return [], []
    timeout = _send_timeout(files)
    if timeout > 60:
        ui.info(f"   📦  large attachment(s) — allowing up to {timeout}s per send")
    server = _connect(ec, timeout)
    saver = _SentSaver(cfg)             # best-effort IMAP copy → account's Sent
    if saver.active:
        ui.info("   🗂   a copy of each message is saved to your Sent folder")
    elif saver.note and "automatically" not in saver.note:
        ui.info(f"   🗂   {saver.note}")
    sent, failed = [], []
    in_session = 0                      # messages sent on the current connection
    every = max(1, session_max)

    def report(i, r, ok, error=""):
        if on_progress:
            on_progress(i, len(recipients), r["email"], ok, error)

    def _fresh():
        # Drop and reopen the SMTP session. Providers (GoDaddy especially) cap
        # "messages per session" and defer the rest with a 452 "too many
        # messages sent in a single session" — a fresh session resets that
        # counter, so a large blast doesn't stall on the last few.
        nonlocal server
        try:
            server.quit()
        except Exception:                               # noqa: BLE001
            pass
        server = _connect(ec, timeout)

    def _attempt(msg):
        try:
            server.send_message(msg)
            return True, ""
        except Exception as e:                          # noqa: BLE001
            return False, str(e)

    def _session_limit(err: str) -> bool:
        e = (err or "").lower()
        return any(x in e for x in ("serverdisconnected", "too many",
                                    "single session", "452", "try again",
                                    "temporarily"))

    try:
        for i, r in enumerate(recipients, 1):
            if should_stop and should_stop():
                ui.warn(f"stopped after {len(sent)} send(s) — "
                        f"{len(recipients) - i + 1} not attempted")
                break
            if in_session >= every:          # proactively cycle before the cap
                _fresh()
                in_session = 0
            msg = _build_message(ec, r, subject, body, files)
            ok, err = _attempt(msg)
            if not ok and _session_limit(err):   # session/rate limit → fresh session, retry once
                _fresh()
                in_session = 0
                ok, err = _attempt(msg)
            if ok:
                sent.append(r["email"])
                in_session += 1
                saver.save(msg)          # mirror into Sent (best-effort, silent)
                ui.info(f"   ✉️   {i}/{len(recipients)}  {r['email']}")
                report(i, r, True)
            else:
                failed.append((r["email"], err))
                ui.err(f"   ✗   {r['email']}: {err}")
                report(i, r, False, err)
            if i < len(recipients):
                # Split the pause so a cancel lands in ~a quarter second
                # instead of after the full provider-friendly delay.
                pause = pause_after_send(delay, jitter)
                waited = 0.0
                while waited < pause:
                    if should_stop and should_stop():
                        break
                    time.sleep(min(0.25, pause - waited))
                    waited += 0.25
    finally:
        try:
            server.quit()
        except Exception:
            pass
        saver.close()
    return sent, failed


# ── the pipeline prompts (kept here so the wording lives with the feature) ────

def draft_question(instruction: str) -> str:
    return (
        f"Your ONLY task is: write ONE email. Goal of the email: {instruction}. "
        "Reply with NOTHING except the final email, in EXACTLY this format:\n\n"
        "SUBJECT: <one subject line>\n"
        "BODY:\n"
        "<the full email body>\n\n"
        "Strict rules: no introduction, no explanation, no notes, no options or "
        "alternatives, no markdown code fences, and no placeholders except "
        "{name}. Address the reader as {name} — it will be replaced with each "
        "recipient's real name before sending. Every character you output will "
        "be sent to real recipients exactly as written."
    )

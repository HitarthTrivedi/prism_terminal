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
import re
import ssl
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
SEND_DELAY = 2.0


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


# ── the draft (what the AI produced) ──────────────────────────────────────────

def parse_draft(text: str):
    """Pull (subject, body) out of the drafting agent's answer. The agent is
    ordered to reply in exactly 'SUBJECT: …' / 'BODY: …' — but scrapes can
    carry stray fences or a leaked handoff, so be forgiving on the way in."""
    if not text or not text.strip():
        return None
    t = text.strip()
    t = re.sub(r"^```[a-z]*\n|\n```$", "", t)                    # markdown fences
    t = re.split(r"\n\s*HANDOFF\b", t, flags=re.IGNORECASE)[0]   # leaked handoff

    m = re.search(r"^\s*SUBJECT:\s*(.+)$", t, re.IGNORECASE | re.MULTILINE)
    if not m:
        return None
    subject = m.group(1).strip()

    b = re.search(r"^\s*BODY:\s*", t[m.end():], re.IGNORECASE | re.MULTILINE)
    body = t[m.end() + b.end():].strip() if b else t[m.end():].strip()
    return (subject, body) if body else None


# ── account setup ─────────────────────────────────────────────────────────────

def smtp_for(address: str):
    domain = address.rsplit("@", 1)[-1].lower()
    return _SMTP_HOSTS.get(domain)


def is_configured(cfg: dict) -> bool:
    ec = cfg.get("email") or {}
    return bool(ec.get("address") and ec.get("password") and ec.get("host"))


# ── sending ───────────────────────────────────────────────────────────────────

def _connect(ec: dict, timeout: int = 60):
    if int(ec["port"]) == 465:
        server = smtplib.SMTP_SSL(ec["host"], 465, timeout=timeout,
                                  context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(ec["host"], int(ec["port"]), timeout=timeout)
        server.starttls(context=ssl.create_default_context())
    server.login(ec["address"], ec["password"])
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


def send_bulk(cfg: dict, recipients: list[dict], subject: str, body: str,
              files: list[dict], delay: float = SEND_DELAY):
    """Send the draft to every recipient, one message each (so {name} can be
    personalised and one bad address can't sink the rest).
    Returns (sent emails, [(email, error), …])."""
    ec = cfg["email"]
    timeout = _send_timeout(files)
    if timeout > 60:
        ui.info(f"   📦  large attachment(s) — allowing up to {timeout}s per send")
    server = _connect(ec, timeout)
    sent, failed = [], []
    try:
        for i, r in enumerate(recipients, 1):
            msg = _build_message(ec, r, subject, body, files)
            try:
                server.send_message(msg)
                sent.append(r["email"])
                ui.info(f"   ✉️   {i}/{len(recipients)}  {r['email']}")
            except smtplib.SMTPServerDisconnected:
                # Provider dropped the connection mid-run — reconnect once.
                try:
                    server = _connect(ec, timeout)
                    server.send_message(msg)
                    sent.append(r["email"])
                    ui.info(f"   ✉️   {i}/{len(recipients)}  {r['email']}  (reconnected)")
                except Exception as e:
                    failed.append((r["email"], str(e)))
                    ui.err(f"   ✗   {r['email']}: {e}")
            except Exception as e:
                failed.append((r["email"], str(e)))
                ui.err(f"   ✗   {r['email']}: {e}")
            if i < len(recipients):
                time.sleep(delay)
    finally:
        try:
            server.quit()
        except Exception:
            pass
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

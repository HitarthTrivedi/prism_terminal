"""Faults a program can see in a cold email.

Length, the opener, the placeholder that escaped, and the number nobody
can stand behind. `context` may carry `claims` (the approved-claims text)
and `offer`; a figure absent from both is reported, which is the same
rule prospector/reach.py already enforces — here it reaches every cold
email, not only the ones that go through the prospector.
"""
from __future__ import annotations

import re

SUBJECT = re.compile(r"^\s*SUBJECT\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
BODY = re.compile(r"^\s*BODY\s*:\s*$", re.IGNORECASE | re.MULTILINE)
DEAD_OPENER = re.compile(
    r"i hope (?:this|you)\s|hope you'?re (?:doing )?well|hope this (?:email|"
    r"message) finds you|reach(?:ing)? out|touch base|circle back|"
    r"i came across your|just (?:wanted|checking)|my name is \w+ and i",
    re.IGNORECASE)
BANNED = re.compile(r"\bsynerg\w+|\bgame[- ]chang\w+|\bleverag\w+|"
                    r"\bcutting[- ]edge\b|\bworld[- ]class\b|\bbest[- ]in[- ]"
                    r"class\b|\brevolution(?:ary|ise|ize)\w*|\bseamless\w*|"
                    r"\bone[- ]stop\b|\bleading provider\b|\bdo the needful\b",
                    re.IGNORECASE)
PLACEHOLDER = re.compile(r"\[[^\]]{1,40}\]|\{\{?[a-z_ ]{1,30}\}?\}|<[a-z_ ]{2,25}>|"
                         r"\bTBD\b|\bXX+\b|\byour company\b", re.IGNORECASE)
NAME_TOKEN = re.compile(r"^\{\{?\s*(?:first_?)?name\s*\}?\}$|^\[(?:first ?)?name\]$",
                        re.IGNORECASE)
NUMBER = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*(?:%|percent|x\b|times\b)|"
                    r"(?:₹|\$|€|£|\bRs\.?)\s?\d[\d,]*|\b\d+\s*(?:crore|lakh|"
                    r"million|billion)\b", re.IGNORECASE)
LINK = re.compile(r"https?://\S+|www\.\S+")
ASK = re.compile(r"\?|\bwould you\b|\bare you (?:open|free|available)\b|"
                 r"\bworth a\b|\bcan i\b|\bshall i\b|\blet me know\b|"
                 r"\b(?:fifteen|15|twenty|20|ten|10)[- ]minute", re.IGNORECASE)
ATTACH = re.compile(r"\battach(?:ed|ing|ment)\b|\bplease find\b|\benclosed\b",
                    re.IGNORECASE)

MAX_WORDS = 120
SUBJECT_MIN, SUBJECT_MAX = 3, 8


def _body(text: str) -> str:
    m = BODY.search(text)
    if m:
        return text[m.end():].strip()
    s = SUBJECT.search(text)
    return text[s.end():].strip() if s else text.strip()


def faults(text: str, context: dict) -> list:
    text = text or ""
    out = []
    body = _body(text)
    words = body.split()

    subject = SUBJECT.search(text)
    if not subject:
        out.append("No SUBJECT line. Give one, four to seven words, lower "
                   "case.")
    else:
        subj = subject.group(1).strip()
        n = len(subj.split())
        if n < SUBJECT_MIN or n > SUBJECT_MAX:
            out.append(f"The subject is {n} words ('{subj[:50]}'). Four to "
                       "seven words, saying what the email is about.")
        if re.match(r"^\s*re\s*:", subj, re.IGNORECASE):
            out.append("The subject pretends to be a reply. A first email is "
                       "not a 'Re:'.")

    if len(words) > MAX_WORDS:
        out.append(f"The body is {len(words)} words. The limit is "
                   f"{MAX_WORDS} — a long first email is deleted unread.")

    first = next((ln.strip() for ln in body.splitlines()
                  if len(ln.split()) >= 4), "")
    if DEAD_OPENER.search(first):
        out.append(f"The opening line is a stock phrase: '{first[:60]}…'. "
                   "Open with something specific and checkable about this "
                   "recipient.")

    banned = sorted({m.group(0).strip().lower() for m in BANNED.finditer(text)})
    if banned:
        out.append("Sales filler used: " + ", ".join(banned[:6]) + ".")

    held = [m.group(0) for m in PLACEHOLDER.finditer(body)
            if not NAME_TOKEN.match(m.group(0).strip())]
    if held:
        out.append("Placeholder(s) other than the name left in: "
                   + ", ".join(sorted(set(held))[:6])
                   + ". Rewrite the sentence rather than sending a gap.")

    allowed = " ".join(str(context.get(k, "")) for k in
                       ("claims", "offer", "signals", "source",
                        "prompt")).lower()
    unbacked = []
    for m in NUMBER.finditer(body):
        fig = m.group(0).strip()
        digits = re.sub(r"[^\d.]", "", fig)
        if digits and digits in allowed:
            continue
        unbacked.append(fig)
    if unbacked:
        out.append("Figure(s) used that are not in the approved claims or the "
                   "offer: " + ", ".join(sorted(set(unbacked))[:6])
                   + ". Drop them, or use only a claim that was approved.")

    if not ASK.search(body):
        out.append("There is no ask. End with one small, specific request.")

    links = LINK.findall(body)
    if len(links) > 1:
        out.append(f"{len(links)} links in a first email. One at most.")
    if ATTACH.search(body):
        out.append("The email refers to an attachment. A first email to a "
                   "stranger sends none.")
    return out

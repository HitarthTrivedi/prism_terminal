"""Faults a program can see in a research answer.

Written for the text Prism captures, not for markdown. A heading arrives
as a short bare line, a table row as its cells joined by spaces, and a
Perplexity citation as a bare site name on the line under the claim
('nhb.gov', '+1'). The first version was written for markdown and,
replayed over the owner's own Perplexity replies, called 121 sourced
figures unsourced and missed headings named 'Executive Summary' and
'Bibliography'.

What a checker can genuinely test is whether the numbers are attributable
and whether the answer admits what it could not find. It cannot judge
whether a source is any good.
"""
from __future__ import annotations

import re

from core import skills as SK

SUMMARY = r"summar|overview|key findings|at a glance|highlights|bottom line"
SOURCES = (r"\bsources?\b|references|bibliograph|citations|works cited|"
           r"further reading")
UNCERTAIN = (r"uncertain|limitation|caveat|\bgaps?\b|open questions|unknowns|"
             r"what (?:we|i) (?:could not|couldn't|don't) know|confidence|"
             r"data quality")
UNCERTAIN_SAID = re.compile(
    r"no (?:published|public|reliable|official) (?:figure|data|source)|"
    r"could not (?:find|verify|confirm|establish)|not (?:publicly )?available|"
    r"(?:figures|estimates|sources) (?:vary|differ|disagree)|unverified|"
    r"needs? (?:verification|to be verified|confirming)|"
    r"treat (?:this|these|them) as (?:indicative|estimates?)", re.IGNORECASE)
# A currency sign must be followed by a DIGIT. "[\d,]+" alone let "caterers,"
# read as Rs followed by a comma, and counted a list of customers as a price.
FIGURE = re.compile(r"(?:₹|\$|€|£|\bRs\.?\s?)\s?\d[\d,]*(?:\.\d+)?"
                    r"|\b\d[\d,]*(?:\.\d+)?\s?(?:%|percent|crore|lakh|"
                    r"million|billion|bn|mn)\b", re.IGNORECASE)
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
LINK = re.compile(r"https?://\S+|www\.\S+")
ATTRIBUTION = re.compile(
    r"\([^)]*(?:19|20)\d{2}[^)]*\)|\bIS\s?\d{3,5}\b|\bISO\s?\d+\b|"
    r"\bEN\s?\d+\b|\baccording to\b|\bper\b\s+[A-Z]|\bsource\s*:|"
    r"\bcited\b|\breported by\b|https?://", re.IGNORECASE)
VAGUE = re.compile(r"industry reports?|various sources|studies show|"
                   r"it is (?:widely )?known|experts (?:say|agree)|"
                   r"research (?:shows|suggests)|market analysts",
                   re.IGNORECASE)
ESTIMATE = re.compile(r"\bestimate[ds]?\b|\bapprox|\brough(?:ly)?\b|"
                      r"\bour own\b|\bderived\b|\bassum|\bindicative\b|~",
                      re.IGNORECASE)
SOURCE_COLUMN = re.compile(r"\bsource\b", re.IGNORECASE)
# "Land & site development: ₹5.15 lakh" -- one row of a breakdown.
LABEL_VALUE = re.compile(r"^[^:]{2,60}:\s*(?:~|approx\.?\s*)?"
                         r"(?:₹|\$|€|£|Rs\.?\s?)?\s?\d", re.IGNORECASE)

LOOKAHEAD = 3           # a citation sits on one of the next few lines
TABLE_REACH = 15        # a 'Source' column header covers the rows below it
MAX_REPORTED = 6


def _cited_below(lines: list, i: int) -> bool:
    for j in range(i + 1, min(len(lines), i + 1 + LOOKAHEAD)):
        if SK.is_source_chip(lines[j]) or LINK.search(lines[j]):
            return True
    return False


def _under_a_source_column(lines: list, i: int) -> bool:
    for j in range(max(0, i - TABLE_REACH), i):
        head = lines[j]
        if (SOURCE_COLUMN.search(head) and len(head.split()) <= 12
                and not FIGURE.search(head) and not head.endswith(".")):
            return True
    return False


def _under_a_cited_total(lines: list, i: int) -> bool:
    """A breakdown under a cited total inherits its citation.

    Perplexity cites the head of a block -- "Total project cost: ₹107
    lakh", then "nhb.gov" -- and lists the parts beneath it with no
    citation of their own. On the owner's own reply that read as six
    unsourced figures. Only rows shaped "Label: value" qualify, so prose
    that merely follows a cited sentence still has to carry its own.
    """
    if not LABEL_VALUE.match(lines[i]):
        return False
    j = i - 1
    while j >= 0 and LABEL_VALUE.match(lines[j]) and not SK.is_source_chip(lines[j]):
        j -= 1
    return j >= 0 and SK.is_source_chip(lines[j])


def faults(text: str, context: dict) -> list:
    text = text or ""
    if len(text.strip()) < 200:
        return ["The answer is too short to be a research finding. It needs "
                "a summary, sourced findings, what is uncertain, and the "
                "sources used."]
    lines = SK.text_lines(text)
    out = []

    missing = []
    if not SK.has_section(text, SUMMARY):
        missing.append("summary")
    cited_lines = sum(1 for line in lines if SK.is_source_chip(line))
    if not (SK.has_section(text, SOURCES) or len(LINK.findall(text)) >= 3
            or cited_lines >= 3):
        missing.append("list of sources")
    if missing:
        out.append("No " + " and no ".join(missing) + " could be found. Open "
                   "with a short summary and end by listing every source "
                   "used, each with what it is and its date.")

    if not (SK.has_section(text, UNCERTAIN) or UNCERTAIN_SAID.search(text)):
        out.append("Nothing says what is uncertain or could not be found. Add "
                   "a short section on the gaps — a research answer with no "
                   "gaps is one that stopped looking.")

    naked = []
    for i, line in enumerate(lines):
        if not FIGURE.search(line) or SK.is_source_chip(line):
            continue
        if ATTRIBUTION.search(line) or ESTIMATE.search(line):
            continue
        if (_cited_below(lines, i) or _under_a_source_column(lines, i)
                or _under_a_cited_total(lines, i)):
            continue
        naked.append(line[:90] + ("…" if len(line) > 90 else ""))
    if naked:
        out.append(f"{len(naked)} figure(s) appear with no source and are not "
                   "marked as an estimate: " + " | ".join(naked[:MAX_REPORTED])
                   + ". Put the source and date beside each, or say it is your "
                     "own estimate and show the reasoning.")

    vague = sorted({m.group(0).lower() for m in VAGUE.finditer(text)})
    if vague:
        out.append("Vague attribution used instead of a source: "
                   + ", ".join(vague[:MAX_REPORTED])
                   + ". Name the organisation, publication or standard.")
    if not YEAR.search(text):
        out.append("No date appears anywhere. Every figure needs the year it "
                   "is from; an undated number cannot be relied on.")
    return out

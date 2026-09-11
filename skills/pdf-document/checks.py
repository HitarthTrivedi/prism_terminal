"""Faults a program can see in a document destined for print, PDF or Word.

Written for captured text, where a table arrives as rows of cells joined by
spaces and there are no pipes. The first version decided "figures given in
prose" by looking for pipe rows, so every rendered table read as prose.

A document cannot be corrected once it is forwarded, so these are the
things that make one indefensible later: no page structure, an undated
price, a promise with no exclusions, screen-only language, and the image
placeholder that went out to a customer — the owner's own "make a DOCX
document" run left eight of them in.
"""
from __future__ import annotations

import re

from core import skills as SK

PAGE = re.compile(r"^\W{0,6}(?:#+\s*)?(?:\*\*)?page\s+(\d{1,3})\b\s*"
                  r"(?:[—\-:–.|]\s*(.*?))?(?:\*\*)?\s*$", re.IGNORECASE)
DATE = re.compile(r"\b(?:19|20)\d{2}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
                  re.IGNORECASE)
MONEY = re.compile(r"(?:₹|\$|€|£|\bRs\.?\s?|\bINR\s?|\bUSD\s?)\s?\d[\d,]*",
                   re.IGNORECASE)
VALIDITY = re.compile(r"valid (?:for|until|till|up to)|validity|prices? "
                      r"(?:are |is )?(?:valid|firm|held|hold)|subject to "
                      r"(?:revision|change)|\bexpires?\b", re.IGNORECASE)
EXCLUSIONS = re.compile(r"exclusion|excluded|not included|assumption|out of "
                        r"scope|scope excludes|terms and conditions",
                        re.IGNORECASE)
PROMISE = re.compile(r"\bwe will\b|\bdelivery\b|\blead time\b|\bscope of "
                     r"(?:work|supply)\b|\bwarrant|\bguarantee", re.IGNORECASE)
SCREEN = re.compile(r"click here|\bclick the link\b|\bhover\b|scroll (?:down|up)|"
                    r"\btap\b|see (?:the )?(?:section )?above|\bthis link\b",
                    re.IGNORECASE)
CONTACT = re.compile(r"@[\w.-]+\.\w{2,}|\bcontact\b|\breach (?:us|out)\b|"
                     r"\+\d[\d\s-]{7,}|\bphone\b|\bemail\b", re.IGNORECASE)


def faults(text: str, context: dict) -> list:
    text = text or ""
    if len(text.strip()) < 200:
        return ["Too short to be a document. Lay it out page by page, "
                "starting with a cover page that names the sender, the "
                "subject, the recipient and the date."]
    lines = SK.text_lines(text)
    out = []

    pages = [i for i, line in enumerate(lines) if PAGE.match(line)]
    if not pages:
        out.append("No page structure. Mark every page — 'PAGE 1 — Cover', "
                   "'PAGE 2 — …' — so the document breaks where you intend "
                   "rather than wherever the text happens to run out.")
    else:
        # Everything before the second page is the cover, INCLUDING a header
        # block written above "PAGE 1". On the live ChatGPT run the date sat in
        # exactly such a block, and the old slice between the first two markers
        # faulted a dated cover and spent the stage's re-ask on it.
        cover = lines[:pages[1]] if len(pages) > 1 else lines[:pages[0] + 12]
        if not DATE.search("\n".join(cover)):
            out.append("The cover page carries no date. A forwarded document "
                       "with no date gets quoted back years later.")

    if MONEY.search(text) and not VALIDITY.search(text):
        out.append("Prices appear with no validity period. Say how long they "
                   "stand, or they stand forever.")
    if PROMISE.search(text) and not EXCLUSIONS.search(text):
        out.append("The document scopes or promises something but has no "
                   "exclusions or assumptions block. That block is what "
                   "prevents the argument later.")
    if (len(MONEY.findall(text)) >= 3 and not SK.item_rows(text)
            and not SK.table_like_lines(text)):
        out.append("Several prices are given in running prose. Anything "
                   "compared — specifications, options, prices — belongs in "
                   "a table with named columns and units.")

    screen = sorted({m.group(0).strip().lower() for m in SCREEN.finditer(text)})
    if screen:
        out.append("Screen-only language in a printed document: "
                   + ", ".join(screen[:6])
                   + ". Refer to pages by number and headings by name.")
    if not CONTACT.search(text):
        out.append("No contact details. The last page says who to reply to "
                   "and what happens next.")
    held = SK.placeholders(text)
    if held:
        out.append(f"{len(held)} placeholder(s) left in: " + ", ".join(held[:5])
                   + ". Put the real content in, or leave the space out.")
    return out

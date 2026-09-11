"""Faults a program can see in a written deck.

Written for the text Prism captures: the chat page as displayed, where a
bullet list arrives as plain lines with no bullet and bold arrives as plain
text. The first version counted bullets by their '•' and '-' markers, which
never survive capture, so the six-bullet and long-bullet rules could never
fire on a real answer.

Only what is unambiguous from the text. Taste is the doctrine's job; this
catches the failures that make a deck unusable whatever the taste -- a deck
that is really a document, a slide nobody can read from the back of a room,
and the bracket-name that gets sent to a customer.
"""
from __future__ import annotations

import re

from core import skills as SK

SLIDE = re.compile(r"^\W{0,6}(?:#+\s*)?(?:\*\*)?slide\s+(\d{1,3})\b"
                   r"\s*(?:[—\-:–.|]\s*(.*?))?(?:\*\*)?\s*$", re.IGNORECASE)
NOTES = re.compile(r"^\W{0,4}(?:\*\*)?(?:speaker\s+)?notes?(?:\*\*)?\s*:",
                   re.IGNORECASE)
MARKER = re.compile(r"^\s*(?:[•\-*▪◦]|\d{1,2}[.)])\s+")

MAX_BULLETS = 6
MAX_WORDS = 14          # doctrine says ~12; two words of slack before a fault
MIN_SLIDES = 4


def _slides(lines: list) -> list:
    """[(number, title, content lines, has notes)] in order."""
    marks = [(i, m) for i, line in enumerate(lines) for m in [SLIDE.match(line)] if m]
    out = []
    for k, (i, m) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(lines)
        title = (m.group(2) or "").strip()
        content, notes = [], False
        for line in lines[i + 1:end]:
            if NOTES.match(line):
                notes = True
                continue
            if notes:
                continue                  # the rest is the presenter's text
            if not title and not content:
                title = line              # "Slide 3" alone, title on the next line
                continue
            content.append(MARKER.sub("", line))
        out.append((m.group(1), title, content, notes))
    return out


def faults(text: str, context: dict) -> list:
    slides = _slides(SK.text_lines(text))
    if not slides:
        return ["The deck is not in the required shape. Every slide must "
                "start with a line like 'SLIDE 3 — Margins fell 4% on "
                "freight', followed by its points and a NOTES: line."]

    out = []
    if len(slides) < MIN_SLIDES:
        out.append(f"Only {len(slides)} slides. A deck needs at least "
                   f"{MIN_SLIDES}; say so in one line if the request really "
                   f"asked for fewer.")

    no_notes, topics, crowded, fat = [], [], [], []
    for num, title, content, notes in slides:
        if not notes:
            no_notes.append(num)
        if len(re.findall(r"[A-Za-z0-9₹%]+", title)) < 3 and not re.search(r"\d", title):
            topics.append(f"{num} ('{title}')")
        if len(content) > MAX_BULLETS:
            crowded.append(f"{num} ({len(content)} lines)")
        long_ = [c for c in content if len(c.split()) > MAX_WORDS]
        if long_:
            fat.append(f"{num} ({len(long_[0].split())} words)")

    if no_notes:
        out.append("These slides have no NOTES line: " + ", ".join(no_notes)
                   + ". Every slide needs two to four sentences of what the "
                     "presenter says.")
    if topics:
        out.append("These slide titles are topics, not claims: "
                   + ", ".join(topics) + ". Rewrite each as the point the "
                                          "slide makes.")
    if crowded:
        out.append("These slides carry more than " f"{MAX_BULLETS} points: "
                   + ", ".join(crowded) + ". Split them or move the rest to "
                                           "NOTES.")
    if fat:
        out.append(f"These slides have a point longer than {MAX_WORDS} "
                   "words: " + ", ".join(fat) + ". Cut to the claim and move "
                                                 "the detail to NOTES.")
    held = SK.placeholders(text)
    if held:
        out.append("Placeholder text left in the deck: " + ", ".join(held[:6])
                   + ". Replace it with the real content or drop the line.")
    return out

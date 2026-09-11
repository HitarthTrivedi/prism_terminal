"""Faults a program can see in documentation.

Written for captured text: a heading arrives as a bare short line, a
numbered list loses its numbers, and code fences are gone. The first
version looked for '#' headings and typed step numbers, and replayed over
the owner's saved replies it reported "no headings" on almost every one —
replies whose headings the chat had simply rendered.

Three failures make documentation useless and all three are visible in the
text: no prerequisites, no procedure, and the marketing register that tells
a stuck reader their problem is easy.
"""
from __future__ import annotations

import re

from core import skills as SK

BEFORE = (r"before you (?:start|begin)|prerequisit|requirements|"
          r"you(?:'ll| will) need|what you need|before starting")
STEPS = (r"\bsteps?\b|procedure|how to\b|instructions|set(?:ting)? (?:it )?up|"
         r"getting started|walkthrough")
TROUBLE = (r"when it goes wrong|troubleshoot|common (?:problems|issues|errors|"
           r"questions)|\bfaq\b|known issues|if (?:something|it|this) "
           r"(?:fails|goes wrong)")
NUMBERED = re.compile(r"^(?:step\s+)?(\d{1,2})[.):]\s+(.*)$", re.IGNORECASE)
BANNED = re.compile(r"\bsimply\b|\bjust\b\s+(?:click|run|open|type|add)|"
                    r"\beasy\b|\beasily\b|\bseamless(?:ly)?\b|\bpowerful\b|"
                    r"\bintuitive\b|\beffortless(?:ly)?\b|\bit'?s simple\b",
                    re.IGNORECASE)
FENCE = re.compile(r"^\s*```", re.MULTILINE)
ELLIPSIS_LINE = re.compile(r"^.*\.\.\..*$", re.MULTILINE)

MIN_HEADINGS = 2
MAX_STEP_WORDS = 40


def faults(text: str, context: dict) -> list:
    text = text or ""
    if len(text.strip()) < 150:
        return ["Too short to be documentation. It needs a title, "
                "prerequisites, a step-by-step procedure and a "
                "troubleshooting section."]
    lines = SK.text_lines(text)
    out = []

    if len(SK.headings(text)) < MIN_HEADINGS:
        out.append("There are almost no headings. Give every task and section "
                   "its own heading, so someone scanning for their problem "
                   "can find it.")
    if not (SK.has_section(text, BEFORE) or re.search(BEFORE, text, re.IGNORECASE)):
        out.append("No prerequisites. State what must already be installed, "
                   "licensed or true before the first step.")

    numbered = [m.group(2).strip() for line in lines
                for m in [NUMBERED.match(line)] if m]
    steps = numbered if len(numbered) >= 2 else SK.section_lines(text, STEPS)
    if len(steps) < 2:
        out.append("No step-by-step procedure was found. Put the task under a "
                   "Steps heading, one action per line, in order.")
    else:
        fat = [s for s in steps if len(s.split()) > MAX_STEP_WORDS]
        if fat:
            out.append(f"{len(fat)} step(s) run past {MAX_STEP_WORDS} words. "
                       "One action per step; move the explanation out of it.")
        joined = [s for s in steps
                  if re.search(r"\band then\b|, then\b", s, re.IGNORECASE)]
        if joined:
            out.append(f"{len(joined)} step(s) contain more than one action. "
                       "Split them.")

    if not SK.has_section(text, TROUBLE):
        out.append("No troubleshooting section. Add the three or four things "
                   "that actually go wrong, each starting with the symptom "
                   "the reader sees.")

    banned = sorted({m.group(0).strip().lower() for m in BANNED.finditer(text)})
    if banned:
        out.append("Marketing or belittling words used: " + ", ".join(banned[:6])
                   + ". A reader who is stuck is not helped by being told it "
                     "is easy.")
    held = SK.placeholders(text)
    if held:
        out.append("Placeholders left in: " + ", ".join(held[:6]) + ". Give the "
                   "real value, or say in a line where to find it.")
    if FENCE.search(text) and ELLIPSIS_LINE.search(text):
        out.append("A command or code block contains '...'. Every command must "
                   "be complete and runnable as written.")
    return out

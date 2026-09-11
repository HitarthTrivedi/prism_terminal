"""Faults a program can see in a storyboard.

The failures here are arithmetic and repetition, which is exactly what a
checker is good at: durations that do not add up, captions too long to
read in the time given, and the same entrance three scenes running — the
measured cause of Prism reels reading as slideshows.
"""
from __future__ import annotations

import re

SCENE = re.compile(r"^\s*(?:#+\s*)?(?:\*\*)?SCENE\s+(\d+)\b(.*)$",
                   re.IGNORECASE | re.MULTILINE)
TOTAL = re.compile(r"\bTOTAL\s*:?\s*(?:about\s*)?(\d+(?:\.\d+)?)\s*s(?:ec)?",
                   re.IGNORECASE)
DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*s(?:ec(?:onds?)?)?\b", re.IGNORECASE)
ON_SCREEN = re.compile(r"^\s*(?:[-*•]\s+)?(?:\*\*)?ON[\s-]?SCREEN\s*:?\s*(.*)$",
                       re.IGNORECASE | re.MULTILINE)
MOTION = re.compile(r"^\s*(?:[-*•]\s+)?(?:\*\*)?MOTION\s*:?\s*(.*)$",
                    re.IGNORECASE | re.MULTILINE)
QUOTED = re.compile(r"[\"“”']([^\"“”']{1,120})[\"“”']")
FEELING = re.compile(r"\bconvey(?:s|ing)?\b|\bevoke|\bfeel(?:s|ing)? (?:of|"
                     r"like)\b|\bpremium\b|\bdynamic\b|\bengaging\b|"
                     r"\bcinematic feel\b|\bmodern (?:and|,)|\bsleek\b|"
                     r"\bcaptivat|\bstunning\b|\beye-catching\b", re.IGNORECASE)
NARRATING = re.compile(r"\bwe see\b|\bthe camera reveals\b|\bthe video shows\b|"
                       r"\ba video (?:showing|of)\b|\bthe viewer (?:sees|is)\b",
                       re.IGNORECASE)
PERSON = re.compile(r"\ba (?:man|woman|person|worker|engineer|customer|"
                    r"presenter|model)\b|\bpeople\b|\bhands? (?:holding|"
                    r"reaching)\b|\bsmiling\b|\bactor\b", re.IGNORECASE)
CARRIES = re.compile(r"^\s*(?:[-*•]\s+)?(?:\*\*)?CARRIE?S?\b", re.IGNORECASE | re.MULTILINE)
# The entrance vocabulary a slideshow repeats.
ENTRANCE = ("fade", "rise", "slide", "wipe", "scale", "zoom", "push",
            "drift", "sweep", "blur", "mask", "flip", "type", "draw")
DIRECTION = ("left", "right", "up", "down", "in", "out", "centre", "center")

WORDS_PER_SECOND = 2.6      # readable on screen, not read-aloud pace
MIN_SCENES = 3


def _scene_blocks(text: str):
    marks = list(SCENE.finditer(text))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((m.group(1), m.group(2), text[m.end():end]))
    return out


def _entrance_key(block: str) -> str:
    low = block.lower()
    verb = next((e for e in ENTRANCE if e in low), "")
    way = next((d for d in DIRECTION if re.search(
        r"(?<![a-z])" + d + r"(?![a-z])", low)), "")
    return f"{verb}:{way}" if verb else ""


def faults(text: str, context: dict) -> list:
    text = text or ""
    scenes = _scene_blocks(text)
    if len(scenes) < MIN_SCENES:
        return ["The storyboard is not in the required shape. Every scene "
                "starts with a line like 'SCENE 1 — HOOK — 3.0s' and carries "
                "ON SCREEN, VISUAL and MOTION lines."]

    out = []
    durations = []
    for num, head, body in scenes:
        d = DURATION.search(head) or DURATION.search(body[:200])
        durations.append(float(d.group(1)) if d else None)

    missing = [n for (n, _, _), d in zip(scenes, durations) if d is None]
    if missing:
        out.append("Scene(s) " + ", ".join(missing[:8])
                   + " have no duration. Every scene needs one in seconds.")

    known = [d for d in durations if d is not None]
    if known:
        total = TOTAL.search(text)
        if total:
            want, got = float(total.group(1)), sum(known)
            if abs(want - got) > max(1.0, want * 0.1):
                out.append(f"The scene durations add to {got:g}s but the "
                           f"stated total is {want:g}s. Make them agree.")
        long_holds = [n for (n, _, _), d in zip(scenes, durations)
                      if d is not None and d > 8]
        if long_holds:
            out.append("Scene(s) " + ", ".join(long_holds[:6])
                       + " hold longer than 8s. Split them or give the shot "
                         "something that keeps moving.")

    # Captions nobody can read in the time given.
    unreadable, no_motion, no_carry = [], [], []
    for (num, head, body), d in zip(scenes, durations):
        on = ON_SCREEN.search(body)
        if on and d:
            for q in QUOTED.findall(on.group(1)) or [on.group(1)]:
                words = len(q.split())
                if words and words / WORDS_PER_SECOND > d:
                    unreadable.append(f"{num} ({words} words in {d:g}s)")
                    break
        if not MOTION.search(body) and not re.search(
                r"\b(?:" + "|".join(ENTRANCE) + r")\w*\b", body, re.I):
            no_motion.append(num)
        if not CARRIES.search(body):
            no_carry.append(num)

    if unreadable:
        out.append("On-screen text too long to read in its own duration: "
                   + ", ".join(unreadable[:6])
                   + ". Cut the words or lengthen the scene.")
    if no_motion:
        out.append("Scene(s) " + ", ".join(no_motion[:8])
                   + " do not say what moves. Name the entrance, the "
                     "direction and what keeps moving while the shot holds.")
    if len(no_carry) > max(1, len(scenes) // 2):
        out.append("Most scenes do not say what carries over to the next cut. "
                   "Name the element that survives each cut, or the piece "
                   "reads as unrelated cards.")

    keys = [_entrance_key(b) for _, _, b in scenes]
    for i in range(len(keys) - 2):
        if keys[i] and keys[i] == keys[i + 1] == keys[i + 2]:
            out.append("Scenes " + ", ".join(n for n, _, _ in scenes[i:i + 3])
                       + f" all enter the same way ({keys[i].replace(':', ' ')})."
                         " Vary the entrance, direction and speed between "
                         "consecutive scenes.")
            break

    felt = sorted({m.group(0).strip().lower() for m in FEELING.finditer(text)})
    if felt:
        out.append("Scenes describe a feeling instead of a picture: "
                   + ", ".join(felt[:6])
                   + ". Say what is actually on screen.")
    narr = sorted({m.group(0).strip().lower() for m in NARRATING.finditer(text)})
    if narr:
        out.append("Narrating the video instead of specifying it: "
                   + ", ".join(narr[:4]) + ".")
    if not context.get("has_footage") and PERSON.search(text):
        out.append("A scene puts a person on screen. Without supplied "
                   "footage, keep to type, product, shapes and fields.")
    return out

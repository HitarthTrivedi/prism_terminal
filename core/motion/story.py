"""
Prism Motion Graphics — one story grammar, for any business
────────────────────────────────────────────────────────────
`spine.py` is a single film — a SaaS ad's signal, hub and chat bubbles —
written down as seven mandatory beats with pixel coordinates, and every client
got that film. This is the grammar underneath a whole family of films, taken
from the reference the 11-12 Nov 2026 study measured (a product film that
alternates short bursts with long holds):

    hook     the name arrives on a quiet page; the camera does the work
    act      someone does the thing this business is for, typed or pressed
    promise  what happens for them, as work in progress, then one sentence
    proof    the result on screen, then a variation
    payoff   one decisive change, a "done", the name and one way to reach them

Each part says WHAT it needs and in what ENERGY (hold, build, burst) but not
where anything goes: the model supplies the business — the customer's action,
three things done for them, the demo object — and lays it out for the frame it
was given. `beat_faults()` checks facts (a prompt box or a cursor is present, a
checklist has rows) the way spine.beat_faults does, never taste. Stdlib only.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# share of the film's length, energy, what the part is, what it requires
BEATS: List[Dict[str, Any]] = [
    {"name": "hook", "share": 0.18, "energy": "build, then hold",
     "subject": "the name arrives on a quiet page and the camera does the work",
     "recipe": ("a mostly empty page; the company's name typed out or revealed in large type "
                "(text with type_on and a caret, or masked_reveal), perhaps one small descriptor "
                "above it and a small mark; a slow camera push toward the name. End on a HOLD of "
                "about a second — nothing drifting — so the name is read."),
     "requires": {"text": 1}},
    {"name": "act", "share": 0.20, "energy": "build",
     "subject": "someone does the thing this business is for, typed or pressed",
     "recipe": ("the customer's action, shown as interface: a ui_input whose text types itself "
                "with the request in the customer's own words (\"Send us the drawing\", \"Book a "
                "table for four\"), and a cursor that travels to the send button and clicks it at "
                "send_at. Keep the box large and the page empty around it. A moment of stillness "
                "while it types is the point."),
     "requires": {"any": ["ui_input", "cursor"]}},
    {"name": "promise", "share": 0.20, "energy": "build, then hold",
     "subject": "what happens for them, as work in progress, then one sentence",
     "recipe": ("a ui_checklist of three rows — the three things done for them, each with a short "
                "label, a quieter sub-line, and a staggered \"at\" so they arrive one by one — then "
                "a single sentence in large type that says what they get. HOLD on the sentence for "
                "1.5 seconds or more."),
     "requires": {"ui_checklist": 2}},
    {"name": "proof", "share": 0.27, "energy": "build, then burst",
     "subject": "the result on screen, then a variation",
     "recipe": ("a ui_window that rises into view holding THE DEMO OBJECT for this business — what "
                "the result actually looks like: a part drawing and a quote, a menu card, a "
                "dashboard tile, a listing card (use a supplied image if the artwork list names "
                "one, otherwise build it from text, numbers and shapes inside the window's "
                "children). Then offer a variation: ui_swatches popping in above it and the "
                "window changing palette."),
     "requires": {"ui_window": 1}},
    {"name": "payoff", "share": 0.15, "energy": "burst, then hold",
     "subject": "one decisive change, a done, the name and one way to reach them",
     "recipe": ("a ui_pill with check true (\"Quote ready\", \"Table booked\") arriving centred; then "
                "the name large and ONE contact line — a phone number or a web address, not both — "
                "that fits the frame with room. End on a HOLD."),
     "requires": {"ui_pill_check": 1}},
]

_NAMES = [b["name"] for b in BEATS]


def beat(name: str) -> Optional[Dict[str, Any]]:
    for b in BEATS:
        if b["name"] == name:
            return b
    return None


def storyboard_text(total_seconds: float = 22.0) -> str:
    """The beat list for the storyboard turn, with each part's share of the length."""
    lines = []
    for i, b in enumerate(BEATS, 1):
        lines.append(f'  {i}. "{b["name"]}" (~{b["share"] * total_seconds:.1f}s, {b["energy"]}) — {b["subject"]}')
    return ("THE STORY — every film is these five parts, in this order, ONE SCENE EACH; the business, "
            "the customer's words and the demo object are yours:\n" + "\n".join(lines)
            + '\n\nEach storyboard row carries its "beat" name. REST IS PART OF THE DESIGN: a film that '
              "is always moving reads as noise. Each part ends on a hold; one part spends a decisive "
              "burst. Do not add decoration to fill a hold.")


def recipe_text(name: str) -> str:
    b = beat(name)
    if not b:
        return ""
    return (f'THIS SCENE\'S PART: "{name}" ({b["energy"]}) — {b["subject"]}.\nBUILD IT LIKE THIS: '
            f"{b['recipe']}\nA scene without what this part needs is sent back.")


def _walk(scene: Dict[str, Any]):
    stack = [n for n in scene.get("nodes") or [] if isinstance(n, dict)]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(c for c in n.get("children") or [] if isinstance(c, dict))


def beat_faults(scene: Dict[str, Any], name: str) -> List[str]:
    """What the scene lacks of its part's requirements — facts, not taste."""
    b = beat(name)
    if not b:
        return []
    nodes = list(_walk(scene))
    types = [str(n.get("type")) for n in nodes]
    out: List[str] = []
    req = b["requires"]
    if req.get("text") and "text" not in types:
        out.append(f'part "{name}" needs the name as text and the scene has none')
    if req.get("any") and not any(t in types for t in req["any"]):
        out.append(f'part "{name}" needs one of {", ".join(req["any"])} — the customer\'s action shown as '
                   "interface — and the scene has none")
    if req.get("ui_checklist"):
        lists = [n for n in nodes if n.get("type") == "ui_checklist"]
        rows = max((len(n.get("items") or []) for n in lists), default=0)
        if rows < req["ui_checklist"]:
            out.append(f'part "{name}" needs a ui_checklist with at least {req["ui_checklist"]} rows; '
                       f"the scene has {'none' if not lists else str(rows) + ' row(s)'}")
    if req.get("ui_window") and "ui_window" not in types:
        out.append(f'part "{name}" needs a ui_window holding the demo object and the scene has none')
    if req.get("ui_pill_check") and not any(n.get("type") in ("ui_pill", "pill") and n.get("check") for n in nodes):
        out.append(f'part "{name}" needs a ui_pill with check true (the "done") and the scene has none')
    return [f"{f} — {recipe_text(name).split('BUILD IT LIKE THIS: ')[-1][:260]}" for f in out]
